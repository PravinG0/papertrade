"""Offline candidate evaluation and champion/challenger comparison.

Consumes real historical *option contract* OHLC and point-in-time proposals supplied by
an operator. Never fetches credentials, invokes live execution, or writes to a DB.
One non-overlapping long-option position per strategy, conservative stop-first tie rule.
This is a bar-based research simulator, not exchange execution or an AI replay engine.
"""
from __future__ import annotations
import argparse
import json
from datetime import timedelta
from pathlib import Path
from adaptive_memory import parse_time, number


def finite_positive(value, label):
    v=number(value)
    if v is None or v<=0: raise ValueError(f'Invalid {label}')
    return v


def historical_bars(rows):
    result=[]; seen=set()
    for r in rows:
        t=parse_time(r.get('timestamp'))
        if not t or t in seen: raise ValueError('Invalid or duplicate historical candle time')
        o,h,l,c=(finite_positive(r.get(k),k) for k in ('open','high','low','close'))
        if l>min(o,c) or h<max(o,c): raise ValueError('Invalid historical OHLC')
        result.append((t,o,h,l,c)); seen.add(t)
    return sorted(result)


def simulate_candidate(candidate, bars, *, interval_minutes=5, slippage_bps=10., fixed_fee=40., turnover_fee_bps=5.):
    """A proposed BUY must enter on a subsequent bar, after proposal availability.
    Exact contract prices only. No overlap with next day or expired contract.
    Stop wins if both levels touched in the same bar; gap through stop uses open.
    """
    decision=parse_time(candidate.get('decision_at')); ready=parse_time(candidate.get('available_at'))
    expiry=parse_time(candidate.get('expiry_at'))
    if not decision or not ready or ready<decision or not expiry or expiry<=ready:
        return {'status':'unresolved','reason':'Invalid or absent point-in-time metadata'}
    if candidate.get('verdict') not in ('BUY CE','BUY PE') or not candidate.get('contract'):
        return {'status':'unresolved','reason':'No exact long-option candidate'}
    try:
        qty=finite_positive(candidate.get('quantity'),'quantity')
        if not qty.is_integer(): raise ValueError('Quantity must be integer')
        entry0,stop0,target0=(finite_positive(candidate.get(k),k) for k in ('reference_entry','stop','target'))
        if not stop0<entry0<target0: raise ValueError('Invalid risk geometry')
        if type(interval_minutes) is not int or interval_minutes<=0: raise ValueError('Invalid interval')
        if not all(number(v) is not None and v>=0 for v in (slippage_bps,fixed_fee,turnover_fee_bps)) or slippage_bps>=10000: raise ValueError('Invalid cost assumptions')
        horizon=int(candidate.get('max_bars',12))
        if not 1<=horizon<=75: raise ValueError('Invalid holding horizon')
        all_rows=historical_bars(bars)
    except (ValueError,TypeError,OverflowError) as exc:
        return {'status':'unresolved','reason':str(exc)}
    interval=timedelta(minutes=interval_minutes)
    rows=[r for r in all_rows if r[0]>ready and r[0].date()==ready.date() and r[0]+interval<=expiry]
    if not rows or rows[0][0]-ready>interval:
        return {'status':'unresolved','reason':'Next eligible contract candle unavailable'}
    entry_time=rows[0][0]; entry=rows[0][1]*(1+slippage_bps/10000)
    sl=entry*stop0/entry0; target=entry*target0/entry0
    chosen=None; exit_reason=None; raw_exit=None
    for i,row in enumerate(rows[:horizon]):
        t,o,h,l,c=row
        if i and t-rows[i-1][0]!=interval:
            return {'status':'unresolved','reason':'Gap in historical contract candles'}
        if l<=sl:
            raw_exit=min(o,sl); exit_reason='STOP'; chosen=row; break
        if h>=target:
            raw_exit=target; exit_reason='TARGET'; chosen=row; break
        if i==horizon-1:
            raw_exit=c; exit_reason='TIME'; chosen=row; break
    if chosen is None:
        return {'status':'unresolved','reason':'Full outcome horizon unavailable'}
    exit_price=max(.01,raw_exit*(1-slippage_bps/10000))
    charges=fixed_fee+(entry+exit_price)*qty*turnover_fee_bps/10000
    return {'status':'resolved','entry_at':entry_time.isoformat(),'outcome_at':(chosen[0]+interval).isoformat(),
            'entry_price':entry,'exit_price':exit_price,'exit_reason':exit_reason,'cost':entry*qty,
            'fees':charges,'net_pnl':round((exit_price-entry)*qty-charges,2),'quantity':int(qty)}


def wallet_metrics(evaluations, predicate, initial_capital):
    capital=finite_positive(initial_capital,'initial_capital'); initial=capital; high=capital; drawdown=0.; selected=[]; busy_until=None
    for row in evaluations:
        out=row['outcome']; candidate=row['candidate']
        if out.get('status')!='resolved' or not predicate(candidate): continue
        entry=parse_time(out['entry_at']); end=parse_time(out['outcome_at'])
        if busy_until and entry<busy_until: continue
        if out['cost']>capital: continue
        capital+=out['net_pnl']; high=max(high,capital); drawdown=max(drawdown,high-capital)
        selected.append(out); busy_until=end
    pnl=[r['net_pnl'] for r in selected]; wins=[p for p in pnl if p>0]; losses=[p for p in pnl if p<0]
    return {'trades':len(pnl),'initial_capital':initial,'ending_capital':round(capital,2),'net_pnl':round(sum(pnl),2),
            'win_rate':len(wins)/len(pnl) if pnl else None,'profit_factor':sum(wins)/-sum(losses) if losses else None,
            'realized_equity_max_drawdown':round(drawdown,2),'fees':round(sum(r['fees'] for r in selected),2),
            'expectancy':sum(pnl)/len(pnl) if pnl else None}


def run_research(dataset):
    if dataset.get('provenance')!='historical_contract_ohlc': raise ValueError('Explicit real historical contract data provenance required; index/simulated data not accepted')
    candidates=dataset['candidates']; bars=dataset['bars_by_contract']; costs=dataset.get('assumptions',{})
    if len({r.get('id') for r in candidates})!=len(candidates) or any(not r.get('id') for r in candidates): raise ValueError('Candidate IDs must be unique and nonempty')
    out=[]
    for c in candidates:
        result=simulate_candidate(c,bars.get(c.get('contract'),[]),**costs)
        out.append({'candidate':c,'outcome':result})
    out.sort(key=lambda r: (r['outcome'].get('entry_at','9999'),str(r['candidate']['id'])))
    capital=dataset.get('initial_capital',1_000_000)
    # Champion = original point-in-time AI proposal; Challenger = stricter gate passed.
    # Both consume exactly the same candidate dataset with independent simulated wallets.
    champion=wallet_metrics(out,lambda c:c.get('verdict') in ('BUY CE','BUY PE'),capital)
    challenger=wallet_metrics(out,lambda c:c.get('quant_eligible') is True,capital)
    return {'mode':'offline_bar_research_only','assumptions':{'interval_minutes':5,'slippage_bps':10.,'fixed_fee':40.,'turnover_fee_bps':5.,**costs},
            'champion':champion,'challenger':challenger,'resolved_candidates':sum(r['outcome']['status']=='resolved' for r in out),
            'unresolved_candidates':sum(r['outcome']['status']!='resolved' for r in out),'evaluations':out,
            'limitations':['Candidate features/quant_eligible must have been recorded at decision time; no automatic historical signal reconstruction.',
                           'Costs are explicit research assumptions, not a broker margin/fee calculator. No spread depth, actual fills or mark-to-market drawdown.',
                           'Rejected outcomes are hypothetical and must never enter live trade history or wallet. No strategy is automatically promoted.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('dataset',type=Path); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); result=run_research(json.loads(args.dataset.read_text())); args.output.write_text(json.dumps(result,indent=2,allow_nan=False))

if __name__=='__main__': main()
