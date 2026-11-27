"""Cloud broker market-data streaming. No broker order methods. TLS verification stays enabled.
Wire format: https://smartapi.angelone.in/docs/User (WebSocket Streaming 2.0).
"""
from __future__ import annotations
import asyncio
import json
import logging
import math
import struct
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

LOG = logging.getLogger(__name__)
EXCHANGE = {'NSE': 1, 'NFO': 2, 'BSE': 3, 'BFO': 4, 'MCX': 5}
REVERSE = {v:k for k,v in EXCHANGE.items()}
URL = 'wss://smartapisocket.angelone.in/smart-stream'


def decode_packet(raw: bytes):
    """Decode documented NSE/BSE/MCX quote/snapquote frames; all prices in paise."""
    if not isinstance(raw, bytes) or len(raw) < 51:
        raise ValueError('short packet')
    mode, exch = raw[0], raw[1]
    if mode not in (2,3) or exch not in REVERSE or len(raw) != {2:123,3:379}[mode]:
        raise ValueError('unsupported packet')
    token = raw[2:27].split(b'\0',1)[0].decode('ascii')
    if not token.isdigit(): raise ValueError('invalid token')
    q = lambda off: struct.unpack_from('<q', raw, off)[0]
    epoch = q(35)/1000
    if not 946684800 < epoch < 4102444800 or q(43) <= 0:
        raise ValueError('invalid price or timestamp')
    ltp, close = q(43)/100, q(115)/100
    item = {'symbolToken':token, 'exchange':REVERSE[exch], 'ltp':ltp,
            'exchFeedTime':datetime.fromtimestamp(epoch,timezone.utc).isoformat(),
            'open':q(91)/100,'high':q(99)/100,'low':q(107)/100,'close':close,
            'tradeVolume':max(0,q(67)), 'netChange':ltp-close if close>0 else 0,
            'percentChange':(ltp-close)/close*100 if close>0 else 0,
            '_feed_epoch':epoch,'_sequence':q(27),'_transport':'websocket'}
    if mode == 3:
        item['opnInterest'] = max(0,q(131))
        depth = {'buy':[], 'sell':[]}
        for off in range(147,347,20):
            flag,qty,price,orders = struct.unpack_from('<hqqh',raw,off)
            if flag in (0,1) and qty>0 and price>0:
                depth['buy' if off<247 else 'sell'].append({'price':price/100,'quantity':qty,'orders':orders})
        depth['buy'].sort(key=lambda x:-x['price'])
        depth['sell'].sort(key=lambda x:x['price'])
        if depth['buy'] and depth['sell'] and depth['buy'][0]['price'] > depth['sell'][0]['price']:
            depth={'buy':[], 'sell':[]}  # ambiguous/crossed depth is not executable
        item['depth']=depth
    return item


def fresh(item, now=None, max_age=10.):
    try:
        age=(time.time() if now is None else now)-float(item['_feed_epoch'])
        return math.isfinite(age) and -2 <= age <= max_age and math.isfinite(float(item['ltp'])) and float(item['ltp'])>0
    except (TypeError,ValueError,KeyError): return False


class BrokerStream:
    def __init__(self, service, enabled, limit=300):
        self.service=service
        self.enabled=enabled
        self.limit=limit
        self.task=None
        self.connected=False
        self.error=None
        self.last_frame=0.
        self.ticks=0
        self.reconnects=0
        self.quotes={}
        self.wanted={}
        self.active=set()
        self.changed=asyncio.Event()
        self.priorities=set()
        self.last_pong=0.
        self.latency_samples=[]
        self.bars={}  # provisional observed OHLC only, never supplied to AI historical validation

    def watch(self, pairs, persistent=False):
        now=time.time()
        for exchange,token in pairs:
            if exchange in EXCHANGE:
                key=(exchange,str(token)); self.wanted[key]=now
                if persistent: self.priorities.add(key)
        self.ensure_running()

    def ensure_running(self):
        if self.enabled and self.service.is_configured() and (self.task is None or self.task.done()):
            self.task=asyncio.create_task(self.run())

    def desired(self):
        now=time.time()
        self.wanted={k:v for k,v in self.wanted.items() if k in self.priorities or now-v<60}
        ordered=sorted(self.wanted,key=lambda k:(k not in self.priorities,-self.wanted[k]))
        return set(ordered[:self.limit])

    def get(self, exchange, token, max_age=3.):
        q=self.quotes.get((exchange,str(token)))
        if self.connected and q and fresh(q,max_age=max_age): return q.copy()
        return None

    def ingest(self, raw):
        q=decode_packet(raw)
        key=(q['exchange'],q['symbolToken'])
        if key not in self.active or not fresh(q,max_age=10): return False
        previous=self.quotes.get(key)
        if previous and (q['_feed_epoch']<previous['_feed_epoch'] or (q['_feed_epoch']==previous['_feed_epoch'] and q['_sequence']<=previous['_sequence'])): return False
        self.quotes[key]=q
        self._observe_bars(key,q)
        self.ticks+=1; self.last_frame=time.time()
        self.latency_samples.append(max(0,self.last_frame-q['_feed_epoch']))
        self.latency_samples=self.latency_samples[-500:]
        self.changed.set()
        return True

    def _observe_bars(self,key,q):
        # Use the exchange session anchor, including operator-configured special sessions.
        from config import get_session_bounds
        from mcx_market import configured_mcx_bounds
        dt=datetime.fromtimestamp(q['_feed_epoch'],ZoneInfo('Asia/Kolkata'))
        bounds=configured_mcx_bounds(dt) if key[0]=='MCX' else get_session_bounds(dt)
        if not bounds or not bounds[0]<=dt.time()<bounds[1]: return
        start=datetime.combine(dt.date(),bounds[0],dt.tzinfo)
        for frame,minutes in (('1m',1),('5m',5),('15m',15),('1h',60),('1d',1440)):
            bucket=start+timedelta(minutes=(int((dt-start).total_seconds())//(minutes*60))*minutes)
            epoch=int(bucket.timestamp()); p=q['ltp']; key2=(key,frame)
            b=self.bars.get(key2)
            if not b or b['time']!=epoch:
                self.bars[key2]={'time':epoch,'open':p,'high':p,'low':p,'close':p,'volume':0,'provisional':True}
            else:
                b['high']=max(b['high'],p); b['low']=min(b['low'],p); b['close']=p

    def current_bar(self,exchange,token,frame):
        if not self.get(exchange,token): return None
        b=self.bars.get(((exchange,str(token)),frame.lower()))
        return b.copy() if b else None

    def status(self):
        samples=sorted(self.latency_samples)
        return {'enabled':self.enabled,'connected':self.connected,'subscribed':len(self.active),'ticks':self.ticks,
                'last_tick_age_seconds':round(time.time()-self.last_frame,2) if self.last_frame else None,
                'p95_transport_seconds':round(samples[int((len(samples)-1)*.95)],3) if samples else None,
                'reconnects':self.reconnects,'error':self.error}

    async def _subscription(self, ws, keys, action):
        groups=defaultdict(lambda:defaultdict(list))
        for exch,tok in sorted(keys): groups[3 if exch in ('NFO','BFO','MCX') else 2][EXCHANGE[exch]].append(tok)
        for mode, exchanges in groups.items():
            await ws.send(json.dumps({'correlationID':f'cloud{action}{mode}','action':action,'params':{'mode':mode,'tokenList':[{'exchangeType':e,'tokens':t} for e,t in exchanges.items()]}}))

    async def run(self):
        from websockets.asyncio.client import connect
        delay=2
        while True:
            try:
                if not await self.service.authenticate(): raise RuntimeError('authentication unavailable')
                if not self.service._feed_token: raise RuntimeError('feed token missing')
                headers={'Authorization':self.service._jwt_token,'x-api-key':self.service.api_key,
                         'x-client-code':self.service.client_code,'x-feed-token':self.service._feed_token}
                async with connect(URL,additional_headers=headers,open_timeout=15,close_timeout=3,ping_interval=None,max_size=65536) as ws:
                    self.connected=True; self.error=None; self.quotes.clear(); self.active.clear(); self.bars.clear()
                    self.last_pong=time.monotonic(); last_ping=0.; last_sync=0.; last_rx=time.monotonic()
                    while True:
                        now=time.monotonic()
                        if now-last_sync>=1:
                            desired=self.desired(); removed=self.active-desired; added=desired-self.active
                            if removed: await self._subscription(ws,removed,0); self.active-=removed
                            for key in removed:
                                self.quotes.pop(key,None)
                                for k in list(self.bars):
                                    if k[0]==key: self.bars.pop(k,None)
                            if added: await self._subscription(ws,added,1); self.active|=added
                            last_sync=now
                        if now-last_ping>=25: await ws.send('ping'); last_ping=now
                        if now-self.last_pong>65: raise TimeoutError('heartbeat expired')
                        # reconnect after REST authentication renews the shared credentials
                        if headers['Authorization']!=self.service._jwt_token: raise RuntimeError('session renewed')
                        try: frame=await asyncio.wait_for(ws.recv(),timeout=.5)
                        except asyncio.TimeoutError: continue
                        if isinstance(frame,str):
                            if frame.strip().lower()=='pong': self.last_pong=time.monotonic(); delay=2
                            else:
                                try: error=json.loads(frame)
                                except ValueError: continue
                                if error.get('errorCode'): self.error='Broker subscription rejected: '+str(error['errorCode']); raise RuntimeError('subscription rejected')
                            continue
                        if frame==b'pong': self.last_pong=time.monotonic(); delay=2; continue
                        try:
                            if self.ingest(frame): delay=2
                        except (ValueError,UnicodeError,struct.error): continue
            except asyncio.CancelledError: raise
            except Exception as exc:
                # Never log handshake headers or authentication credentials.
                status=getattr(getattr(exc,'response',None),'status_code',None)
                if status==401: self.service._token_expiry_epoch=0
                self.error=f'{type(exc).__name__}' + (f' HTTP {status}' if status else '')
                self.reconnects+=1; LOG.warning('Broker feed reconnect: %s',self.error)
            finally:
                self.connected=False; self.active.clear(); self.quotes.clear(); self.changed.set()
            await asyncio.sleep(delay); delay=min(delay*2,60)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
        self.connected=False; self.quotes.clear(); self.active.clear()
