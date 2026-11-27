"""Commodity-only debate, research and scheduling. No NSE wallet or broker order calls."""
from __future__ import annotations
import asyncio
import json
import logging
import math
import uuid
from datetime import datetime, timedelta
from collections import Counter
from adaptive_memory import number, parse_time, prompt_with_memory
from mcx_market import (IST, configured_mcx_bounds, historical_mcx_bounds, select_contracts,
    get_mcx_paper_state, place_mcx_paper_order, settle_mcx_positions, calculate_mcx_charges,
    ledger_key, _empty_mcx_ledger)
from quant_engine import validated_bars, frame_features, market_regime, validate_direction, option_validation
from verdict_validation import validated_verdict
from mcx_storage import read, edit, keys

logger = logging.getLogger(__name__)
FRAMES = {'1m':'5d','5m':'5d','15m':'15d','1h':'30d','1d':'1y'}


def session_active(now):
    bounds = configured_mcx_bounds(now)
    return bool(bounds and bounds[0] <= now.astimezone(IST).time() < bounds[1])


def near_close(now):
    bounds = configured_mcx_bounds(now)
    return not bounds or now >= datetime.combine(now.date(), bounds[1], IST) - timedelta(minutes=5)


def memory_summary(trades, now):
    """Measured outcomes only; preserve legacy fills and label their provenance."""
    valid = [(parse_time(t.get('closed_at')),t) for t in trades if number(t.get('net_pnl')) is not None]
    valid = [(d,t) for d,t in valid if d and d <= now]
    days = sorted({d.date() for d,t in valid}, reverse=True)
    result = {}
    for label,n in [('intraday',0),('5_days',5),('30_days',30),('90_days',90)]:
        selected = {now.date()} if n == 0 else set(days[:n])
        rows = [t for d,t in valid if d.date() in selected]
        result[label] = {'sample_size':len(rows),'wins':sum(float(t['net_pnl'])>0 for t in rows),
            'net_pnl':round(sum(float(t['net_pnl']) for t in rows),2),
            'loss_reasons':dict(Counter(str(t.get('exit_reason','UNKNOWN')) for t in rows if float(t['net_pnl'])<0)),
            'ai_fills':sum(t.get('source')=='AI' for t in rows)}
    return result


def daily_summaries(trades):
    """Separate measured realized reports; preserve original records, no causal claims."""
    reports={}
    for t in trades:
        dt=parse_time(t.get('closed_at')); pnl=number(t.get('net_pnl'))
        if not dt or pnl is None: continue
        day=dt.date().isoformat()
        r=reports.setdefault(day,{'date':day,'trades':0,'wins':0,'losses':0,'net_pnl':0.,'estimated_charges':0.,'exit_reasons':{}})
        r['trades']+=1;r['wins']+=int(pnl>0);r['losses']+=int(pnl<0);r['net_pnl']+=pnl
        r['estimated_charges']+=number(t.get('charges')) or 0.
        reason=str(t.get('exit_reason') or 'UNKNOWN');r['exit_reasons'][reason]=r['exit_reasons'].get(reason,0)+1
    for r in reports.values():
        r['net_pnl']=round(r['net_pnl'],2);r['estimated_charges']=round(r['estimated_charges'],2)
    return sorted(reports.values(),key=lambda r:r['date'],reverse=True)


def session_reference(rows, now):
    bounds = configured_mcx_bounds(now)
    if not bounds:
        return None, 'UNKNOWN'
    today = [r for r in rows if datetime.fromtimestamp(r['time'], IST).date()==now.date()]
    if not today or datetime.fromtimestamp(today[0]['time'], IST).time()!=bounds[0]:
        return None, 'UNKNOWN'
    prices=[(r['high']+r['low']+r['close'])/3 for r in today]
    volume=[r['volume'] for r in today]
    if all(v>0 for v in volume):
        return sum(p*v for p,v in zip(prices,volume))/sum(volume),'VWAP'
    return sum(prices)/len(prices),'TYPICAL_PRICE_PROXY'


def risk_guard(data, contract, now, risk, *, max_trades, max_risk_pct, max_loss_pct, generation):
    cfg=data.get('ai_config',{})
    if not cfg.get('enabled') or not cfg.get('auto_execute') or cfg.get('generation')!=generation:
        raise ValueError('MCX automatic execution stopped or configuration changed')
    if not session_active(now) or near_close(now):
        raise ValueError('MCX entry window closed')
    if data.get('positions'):
        raise ValueError('MCX already has an open primary position')
    trades=data.get('trades',[])
    today=[t for t in trades if (d:=parse_time(t.get('entered_at'))) and d.date()==now.date() and t.get('source')=='AI']
    if max_trades and len(today)>=max_trades:
        raise ValueError('MCX daily automatic trade cap reached')
    closed=[t for t in trades if (d:=parse_time(t.get('closed_at'))) and d.date()==now.date()]
    pnl=sum(float(t.get('net_pnl',0)) for t in closed)
    start=float(data['cash_balance'])-pnl
    if start<=0 or pnl<=-start*max_loss_pct/100 or -min(pnl,0)+risk>start*max_loss_pct/100:
        raise ValueError('MCX daily loss budget exceeded')
    if risk>float(data['cash_balance'])*max_risk_pct/100:
        raise ValueError('MCX per-trade risk budget exceeded')
    for t in trades:
        stamp=parse_time(t.get('closed_at'))
        if stamp and t.get('symbol')==contract.symbol and t.get('exit_reason')=='STOP_LOSS_HIT' and 0<=(now-stamp).total_seconds()<1800:
            raise ValueError('MCX repeat-contract stop-loss cooldown active')
    recent=sorted(closed,key=lambda t:parse_time(t['closed_at']),reverse=True)[:3]
    if len(recent)==3 and all(t.get('exit_reason')=='STOP_LOSS_HIT' for t in recent) and now-parse_time(recent[0]['closed_at'])<timedelta(hours=1):
        raise ValueError('MCX consecutive-loss cooldown active')


async def gemini_json(role, context, memory):
    """Use commodity prompts, not NSE's index-specific risk clamp or VIX assumptions."""
    from config import settings, gemini_candidate_models
    from google import genai
    from google.genai import types
    if not settings.GEMINI_API_KEY:
        raise ValueError('Gemini not configured')
    base = ('You are the '+role+' agent for MCX standard CRUDEOIL futures options. '
        'Only use provided data. Unknown data is unknown; no India VIX, NIFTY, inventory or news assumptions. '
        'Historical outcomes are not guarantees. Return JSON only. ')
    if role=='Judge':
        base += ('Return verdict (BUY CE, BUY PE, or NO_TRADE), integer confidence 1..10, '
            'recommended_strike, entry_price, stop_loss, target, reasoning, key_risks. '
            'Choose an exact listed option in the selected expiry; entry/stop/target are OPTION PREMIUMS, not futures prices. '
            'If mapping or data is insufficient return NO_TRADE.')
    else:
        base += ('Present the '+('bullish CE' if role=='Bull' else 'bearish PE')+' case. '
            'Return integer confidence 1..10, thesis, arguments (nonempty array of strings). Acknowledge conflicting evidence.')
    client=genai.Client(api_key=settings.GEMINI_API_KEY)
    try:
        for model in gemini_candidate_models()[:3]:
            try:
                response=await asyncio.wait_for(client.aio.models.generate_content(model=model,
                    contents=json.dumps(context,allow_nan=False),config=types.GenerateContentConfig(
                        system_instruction=prompt_with_memory(base,memory),response_mime_type='application/json',temperature=.2)),20)
                raw_txt = (response.text or '').strip()
                if raw_txt.startswith('```'):
                    raw_txt = raw_txt.strip('`')
                    if raw_txt.startswith('json'):
                        raw_txt = raw_txt[4:].strip()
                result=json.loads(raw_txt)
                if not isinstance(result,dict):
                    raise ValueError('Invalid JSON object')
                if role!='Judge':
                    if type(result.get('confidence')) is not int or not 1<=result['confidence']<=10 or not isinstance(result.get('thesis'),str) or not isinstance(result.get('arguments'),list) or not result['arguments'] or not all(isinstance(x,str) for x in result['arguments']):
                        raise ValueError('Invalid agent response')
                if role!='Judge':
                    result={'confidence':result['confidence'],'thesis':result['thesis'][:4000],'arguments':[a[:2000] for a in result['arguments'][:10]]}
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning('MCX %s Gemini attempt (%s) failed: %s: %s', role, model, type(exc).__name__, str(exc)[:180])
        raise ValueError(f'MCX {role} agent unavailable; no fallback trade')
    finally:
        await client.aio.aclose()


async def build_debate(user_id, future, expiry, *, agent=gemini_json):
    from config import settings
    from angel_service import angel_service as service
    from scrip_master import scrip_master
    from mcx_market import quote_view
    now=datetime.now(IST)
    if not session_active(now):
        raise ValueError('MCX market session is closed or calendar unverified')
    await service.ensure_contracts()
    _, fut, _, expiry, opts=select_contracts(scrip_master.mcx_contracts(),now.date(),future,expiry)
    if not fut:
        raise ValueError('MCX future unavailable')
    frames={}; missing={}; five=[]
    for frame,span in FRAMES.items():
        meta=await service.get_candles_with_meta('CRUDEOIL',frame,span,contract=fut)
        try:
            if meta.get('source') not in ('live','cached'):
                raise ValueError(meta.get('reason') or 'Historical candles unavailable')
            rows=validated_bars(meta['candles'],datetime.now(IST),frame,historical_mcx_bounds)
            frames[frame]=frame_features(rows)
            if frame=='5m': five=rows
        except ValueError as exc:
            frames[frame]={'direction':'UNKNOWN'};missing[frame]=str(exc)
    if not five:
        raise ValueError('MCX 5m data: '+missing.get('5m','Unavailable'))
    fq=(await service.get_token_quotes([('MCX',fut.token)])).get(fut.token)
    if not fq or not service._quote_is_current(fq,settings.BROKER_QUOTE_MAX_AGE_SECONDS):
        raise ValueError('Fresh MCX futures quote unavailable')
    spot=float(fq['ltp']); now=datetime.now(IST)
    strikes=sorted({c.strike for c in opts},key=lambda s:abs(s-spot))[:5]
    choices=[c for c in opts if c.strike in strikes]
    quotes=await service.get_token_quotes([('MCX',c.token) for c in choices])
    mapped=json.loads(settings.MCX_OPTION_FUTURE_MAP).get(expiry)==fut.symbol
    ref,kind=session_reference(five,now)
    snap={'future':fut.symbol,'expiry':expiry,'spot_price':spot,'timeframes':frames,'market_regime':market_regime(frames),
        'data_status':'live','spot_fresh':True,'session_active':session_active(now),'vwap':ref,'session_reference':kind,
        'supertrend_direction':frames['5m'].get('supertrend'),'external_macro':'UNAVAILABLE','option_mapping_verified':mapped,
        'options':[quote_view(c,quotes.get(c.token)) for c in choices if quotes.get(c.token)],'missing_frames':missing}
    primary=await read(ledger_key(user_id,'paper'),_empty_mcx_ledger)
    memory={'primary':memory_summary(primary.get('trades',[]),now)}
    for ledger in ('champion','challenger'):
        research=await read(ledger_key(user_id,ledger),_empty_mcx_ledger)
        memory[ledger+'_hypothetical']=memory_summary(research.get('trades',[]),now)
    mem='### MCX EPISODIC MEMORY — measured paper and separately labelled research outcomes\n'+json.dumps(memory)
    bull,bear=await asyncio.gather(agent('Bull',snap,mem),agent('Bear',snap,mem))
    judge=await agent('Judge',{'market':snap,'bull':bull,'bear':bear},mem)
    verdict,confidence,strike,entry,sl,target=validated_verdict(judge)
    quant=validate_direction(snap,verdict,confidence)
    if not mapped:
        quant['reasons'].append('Option expiry to exact futures mapping has not been verified.')
    if missing:
        quant['reasons'].append('One or more timeframes unavailable.')
    quant['eligible']=not quant['reasons']
    return {'id':uuid.uuid4().hex,'timestamp':now.isoformat(),'future':fut.symbol,'expiry':expiry,
        'spot_price':spot,'technical':frames['5m'],'bull':bull,'bear':bear,'judge':{'verdict':verdict,'confidence':confidence,
        'recommended_strike':strike,'entry_price':entry,'stop_loss':sl,'target':target,'reasoning':str(judge.get('reasoning',''))[:4000]},
        'verdict':verdict if quant['eligible'] else 'NO_TRADE','recommended_strike':strike,
        'quantitative_validation':quant,'market_snapshot':snap,'memory':memory,'auto_execution_enabled':settings.MCX_AUTO_EXECUTION_ENABLED}


def default_config():
    return {'enabled':False,'auto_execute':False,'interval':5,'lots':1,'max_trades':5,'future':None,'expiry':None,
        'generation':uuid.uuid4().hex,'next_run':None,'lease_until':None,'last_error':None}


async def status(uid):
    from config import settings
    data=await read(ledger_key(uid,'paper'),_empty_mcx_ledger)
    cfg=data.get('ai_config') or {**default_config(),'generation':'not-configured'}
    history=data.get('debates',[])
    return {**cfg,'execution_available':bool(settings.MCX_AUTO_EXECUTION_ENABLED and settings.MCX_SPECIFICATIONS_VERIFIED and settings.MCX_CALENDAR_VERIFIED),
        'shadow_enabled':settings.MCX_SHADOW_ENABLED,'session_active':session_active(datetime.now(IST)),
        'last_debate':history[0] if history else None}


async def configure(uid, payload):
    from config import settings
    if not settings.MCX_RESEARCH_ENABLED:
        raise ValueError('MCX disabled')
    for k in ('enabled','auto_execute'):
        if k in payload and type(payload[k]) is not bool: raise ValueError(f'Invalid {k}')
    for k,lo,hi in [('interval',3,30),('lots',1,20),('max_trades',0,100)]:
        if k in payload and (type(payload[k]) is not int or not lo<=payload[k]<=hi): raise ValueError(f'Invalid {k}')
    for k in ('future','expiry'):
        if k in payload and payload[k] is not None and (not isinstance(payload[k],str) or len(payload[k])>64): raise ValueError(f'Invalid {k}')
    async with edit(ledger_key(uid,'paper'),_empty_mcx_ledger) as data:
        cfg=data.setdefault('ai_config',default_config())
        cfg.update({k:payload[k] for k in ('enabled','auto_execute','interval','lots','max_trades','future','expiry') if k in payload})
        if cfg['enabled'] and (not cfg['future'] or not cfg['expiry']): raise ValueError('Choose an exact MCX future and expiry')
        if cfg['auto_execute'] and not (settings.MCX_AUTO_EXECUTION_ENABLED and settings.MCX_SPECIFICATIONS_VERIFIED and settings.MCX_CALENDAR_VERIFIED):
            raise ValueError('MCX automatic execution disabled pending commodity verification')
        cfg.update(generation=uuid.uuid4().hex,next_run=datetime.now(IST).isoformat(),last_error=None)
        # Keep an in-flight lease; its generation will no longer authorize a fill.
    return await status(uid)


async def claim(uid, scheduled):
    now=datetime.now(IST)
    async with edit(ledger_key(uid,'paper'),_empty_mcx_ledger) as data:
        cfg=data.setdefault('ai_config',default_config())
        lease=parse_time(cfg.get('lease_until'))
        if lease and lease>now: return None
        due=parse_time(cfg.get('next_run'))
        if scheduled and (not cfg['enabled'] or not session_active(now) or (due and due>now)): return None
        token=uuid.uuid4().hex
        cfg.update(lease_until=(now+timedelta(minutes=5)).isoformat(),lease_token=token)
        if scheduled: cfg['next_run']=(now+timedelta(minutes=cfg['interval'])).isoformat()
        return dict(cfg)


async def execution_candidate(result,lots):
    from config import settings
    from angel_service import angel_service as service
    from scrip_master import scrip_master
    from quant_engine import expected_starts
    now=datetime.now(IST); j=result['judge']; verdict=j['verdict']
    if verdict not in ('BUY CE','BUY PE'): raise ValueError('No eligible AI proposal')
    if not settings.MCX_SPECIFICATIONS_VERIFIED or not settings.MCX_CALENDAR_VERIFIED: raise ValueError('Commodity specifications and official calendar not verified')
    if not session_active(now) or near_close(now): raise ValueError('MCX entry window closed')
    if not 0 <= (now-parse_time(result['timestamp'])).total_seconds() <= 180: raise ValueError('MCX debate expired')
    if json.loads(settings.MCX_OPTION_FUTURE_MAP).get(result['expiry'])!=result['future']: raise ValueError('Verified option mapping required')
    contracts=scrip_master.mcx_contracts()
    matches=[c for c in contracts if c.expiry==result['expiry'] and c.strike==j['recommended_strike'] and c.option_type==verdict[-2:]]
    if len(matches)!=1: raise ValueError('Exact MCX option contract unavailable or ambiguous')
    c=matches[0]
    if not any(o.get('symbol')==c.symbol and o.get('token')==c.token for o in result['market_snapshot']['options']): raise ValueError('Option was not in observed debate snapshot')
    if c.expiry<=now.date().isoformat(): raise ValueError('MCX expiry-day auto-entry disabled')
    fut=next((f for f in contracts if f.symbol==result['future'] and f.option_type=='FUT'),None)
    if not fut: raise ValueError('Exact futures contract unavailable')
    quotes=await service.get_token_quotes([('MCX',c.token),('MCX',fut.token)])
    q=quotes.get(c.token); fq=quotes.get(fut.token)
    if not fq or not service._quote_is_current(fq,settings.BROKER_QUOTE_MAX_AGE_SECONDS): raise ValueError('Fresh futures quote required before execution')
    result['rechecked_direction']=validate_direction({**result['market_snapshot'],'spot_price':float(fq['ltp'])},verdict,j['confidence'])
    if not result['rechecked_direction']['eligible']: result['quantitative_validation']['eligible']=False
    expected=expected_starts(datetime.now(IST),'5m',historical_mcx_bounds,1)
    if not expected or result['market_snapshot']['timeframes']['5m'].get('last_start')!=expected[-1]: raise ValueError('A new 5m bar completed since debate; run a new debate')
    if abs(float(fq['ltp'])/result['spot_price']-1)>.0025: raise ValueError('Futures moved materially since debate; run a new debate')
    if not q or not service._quote_is_current(q,settings.BROKER_QUOTE_MAX_AGE_SECONDS): raise ValueError('Fresh MCX option quote required')
    book=q.get('depth') or {}; bid=number((book.get('buy') or [{}])[0].get('price'));ask=number((book.get('sell') or [{}])[0].get('price'))
    if not ask or not bid or not 0<bid<=ask: raise ValueError('MCX two-sided quote required')
    # Prices snapped conservatively to contract tick; no inferred lot size.
    tick=c.tick_size; sl=round(math.floor(j['stop_loss']/tick)*tick,2);target=round(math.ceil(j['target']/tick)*tick,2)
    stamp=service._parse_exchange_quote_time(q)
    validation=option_validation({'bid':bid,'ask':ask,'ltp':q['ltp'],'exchange_timestamp':stamp.isoformat() if stamp else None},ask,sl,target,c.lot_size*lots,datetime.now(IST),lambda b,s:calculate_mcx_charges(b,s)['total_charges'],max_age=settings.BROKER_QUOTE_MAX_AGE_SECONDS)
    return c,ask,sl,target,validation


async def run(uid, *, future=None, expiry=None, scheduled=False, claimed=None):
    from config import settings
    cfg=claimed or await claim(uid,scheduled)
    if not cfg: raise ValueError('MCX debate already in progress or not due')
    result=None;error=None
    try:
        result=await asyncio.wait_for(build_debate(uid,future or cfg['future'],expiry or cfg['expiry']),150)
        result['execution']={'status':'NOT_EXECUTED'}
        if settings.MCX_SHADOW_ENABLED or (scheduled and cfg['auto_execute'] and settings.MCX_AUTO_EXECUTION_ENABLED):
            try:
                c,entry,sl,target,validation=await execution_candidate(result,cfg['lots'])
                result['option_validation']=validation
                if not validation['eligible'] or not result['quantitative_validation']['eligible']:
                    result['verdict']='NO_TRADE'
                    result['execution']={'status':'BLOCKED','reason':'Independent validation rejected the proposal'}
                live_cfg=(await read(ledger_key(uid,'paper'),_empty_mcx_ledger)).get('ai_config',{})
                if settings.MCX_SHADOW_ENABLED and 0 < sl < entry < target and (not scheduled or live_cfg.get('generation')==cfg['generation']):
                    for ledger in ('champion','challenger'):
                        if ledger=='challenger' and not (result['quantitative_validation']['eligible'] and validation['eligible']): continue
                        try:
                            def shadow_guard(data):
                                if len(data.get('positions',[]))>=20: raise ValueError('Research concurrency cap')
                            await place_mcx_paper_order(uid,c,cfg['lots'],entry,sl,target,datetime.now(IST),ledger=ledger,debate_id=result['id'],guard=shadow_guard)
                        except ValueError as exc: result.setdefault('shadow_rejections',{})[ledger]=str(exc)
                if scheduled and cfg['auto_execute'] and settings.MCX_AUTO_EXECUTION_ENABLED and result['quantitative_validation']['eligible'] and validation['eligible']:
                    result['execution']=await place_mcx_paper_order(uid,c,cfg['lots'],entry,sl,target,datetime.now(IST),debate_id=result['id'],guard=lambda data:risk_guard(data,c,datetime.now(IST),validation['metrics']['net_risk'],max_trades=cfg['max_trades'],max_risk_pct=settings.MCX_MAX_RISK_PCT,max_loss_pct=settings.MCX_MAX_DAILY_LOSS_PCT,generation=cfg['generation']))
            except ValueError as exc:
                result['verdict']='NO_TRADE';result['execution']={'status':'BLOCKED','reason':str(exc)}
        return result
    except asyncio.TimeoutError as exc:
        error='MCX debate timed out';raise ValueError(error) from exc
    except Exception as exc:
        error=str(exc) if isinstance(exc,ValueError) else 'MCX debate failed; inspect backend logs';raise
    finally:
        async with edit(ledger_key(uid,'paper'),_empty_mcx_ledger) as data:
            live=data.setdefault('ai_config',default_config())
            if result: data.setdefault('debates',[]).insert(0,result)
            if live.get('lease_token')==cfg['lease_token']:
                live.update(lease_until=None,last_error=error)


async def history(uid, limit=30, offset=0):
    data=await read(ledger_key(uid,'paper'),_empty_mcx_ledger)
    debates=data.get('debates',[])
    return {'debates':debates[offset:offset+limit],'total':len(debates)}


async def monitor_once():
    from angel_service import angel_service as service
    from config import settings
    now=datetime.now(IST)
    if not session_active(now): return
    work=[]; tokens=set()
    for ledger in ('paper','champion','challenger'):
        for key in await keys(f'mcx-{ledger}:'):
            uid=int(key.split(':')[1]); state=await get_mcx_paper_state(uid,ledger=ledger)
            positions=state['positions']
            if not positions: continue
            work.append((uid,ledger,positions))
            tokens.update(str(p['token']) for p in positions)
    # Bounded broker requests. Each position uses a fresh executable bid, not stale LTP.
    quotes={}
    for start in range(0,len(tokens),50):
        quotes.update(await service.get_token_quotes([('MCX',t) for t in sorted(tokens)[start:start+50]]))
    for uid,ledger,positions in work:
        bids={}; ids=set()
        for p in positions:
            q=quotes.get(str(p['token']))
            if q and service._quote_is_current(q,settings.BROKER_QUOTE_MAX_AGE_SECONDS):
                bid=number(((q.get('depth') or {}).get('buy') or [{}])[0].get('price'))
                stamp=service._parse_exchange_quote_time(q); entered=parse_time(p.get('entered_at'))
                if bid and bid>0 and stamp and entered and stamp>=entered:
                    bids[str(p['token'])]=bid; ids.add(p['id'])
        if bids: await settle_mcx_positions(uid,bids,ledger=ledger,eligible_ids=ids,due_only=True)


async def monitor_loop():
    while True:
        try: await monitor_once()
        except asyncio.CancelledError: raise
        except Exception: logger.exception('MCX position monitor failed; no fabricated exits')
        await asyncio.sleep(3)


async def scheduler_loop():
    from config import settings
    tasks={}
    async def worker(uid,cfg):
        try: await run(uid,scheduled=True,claimed=cfg)
        except Exception: logger.warning('Scheduled MCX debate failed for account %s',uid)
    try:
        while True:
            try:
                tasks={u:t for u,t in tasks.items() if not t.done()}
                if settings.MCX_RESEARCH_ENABLED and session_active(datetime.now(IST)):
                    for key in await keys('mcx-paper:'):
                        if len(tasks)>=2: break
                        uid=int(key.split(':')[1])
                        if uid in tasks: continue
                        state=await read(key,_empty_mcx_ledger)
                        if not state.get('ai_config',{}).get('enabled'): continue
                        cfg=await claim(uid,True)
                        if cfg: tasks[uid]=asyncio.create_task(worker(uid,cfg))
            except asyncio.CancelledError: raise
            except Exception: logger.exception('MCX scheduler scan failed')
            await asyncio.sleep(5)
    finally:
        for task in tasks.values(): task.cancel()
        await asyncio.gather(*tasks.values(),return_exceptions=True)
