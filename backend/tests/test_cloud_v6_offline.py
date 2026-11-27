"""Cloud V6 unit tests using synthetic broker frames; no login, no DB writes."""
import asyncio
import json
import struct
import time
from datetime import date, datetime, time as clock, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo
import pytest
from broker_stream import BrokerStream, decode_packet, fresh, EXCHANGE
from mcx_market import mcx_session_bounds, parse_contract, select_contracts, quote_view
from config import Settings, normalize_index_symbol
from scrip_master import ScripMaster

IST = ZoneInfo('Asia/Kolkata')
TODAY = date(2026,11,27)


def packet(ex=5, mode=3, token='1234', epoch=None, seq=1, price=700000, crossed=False):
    raw=bytearray({2:123,3:379}[mode]);raw[0]=mode;raw[1]=ex
    t=token.encode();raw[2:2+len(t)]=t
    stamp=int((time.time() if epoch is None else epoch)*1000)
    for offset,value in [(27,seq),(35,stamp),(43,price),(67,1234),(91,690000),(99,710000),(107,680000),(115,695000)]:
        struct.pack_into('<q',raw,offset,value)
    if mode==3:
        struct.pack_into('<q',raw,131,987)
        for i in range(10):
            buy=i<5; off=147+20*i
            px=(price+100 if crossed else price-100) if buy else price+50
            struct.pack_into('<hqqh',raw,off,1 if buy else 0,5,px,2)
    return bytes(raw)


@pytest.mark.parametrize('exchange', list(EXCHANGE))
@pytest.mark.parametrize('mode',[2,3])
def test_stream_decoder_all_segments(exchange,mode):
    row=decode_packet(packet(ex=EXCHANGE[exchange],mode=mode))
    assert row['exchange']==exchange and row['ltp']==7000 and row['tradeVolume']==1234
    assert row['_transport']=='websocket'
    if mode==3:
        assert row['depth']['buy'][0]['price']==6999
        assert row['depth']['sell'][0]['price']==7000.5
        assert row['opnInterest']==987


@pytest.mark.parametrize('raw',[b'',b'\x03'*50,b'\x03'*51,packet(ex=99),packet(token='abc'),packet(price=0),packet(epoch=10)])
def test_invalid_packet_rejected(raw):
    with pytest.raises(ValueError):decode_packet(raw)


def test_crossed_book_not_usable():
    assert decode_packet(packet(crossed=True))['depth']=={'buy':[],'sell':[]}


@pytest.mark.parametrize('age,valid',[(-3,False),(-1,True),(0,True),(10,True),(10.01,False),(60,False)])
def test_exchange_freshness(age,valid):
    assert fresh({'ltp':100,'_feed_epoch':1000-age},now=1000,max_age=10)==valid


def test_cross_exchange_token_isolation_and_duplicate_ticks():
    stream=BrokerStream(SimpleNamespace(is_configured=lambda:False),False)
    stream.connected=True;stream.active={('MCX','1234'),('NFO','1234')}
    stamp=time.time()
    assert stream.ingest(packet(ex=5,epoch=stamp,seq=2))
    assert stream.ingest(packet(ex=2,epoch=stamp,seq=1,price=20000))
    assert not stream.ingest(packet(ex=5,epoch=stamp,seq=2))
    assert not stream.ingest(packet(ex=5,epoch=stamp-1,seq=3))
    assert stream.get('MCX','1234')['ltp']==7000
    assert stream.get('NFO','1234')['ltp']==200
    stream.connected=False
    assert stream.get('MCX','1234') is None


def test_subscription_limit_and_expiry():
    stream=BrokerStream(SimpleNamespace(is_configured=lambda:False),False,limit=2)
    stream.watch([('NSE','1')],persistent=True)
    stream.watch([('MCX','2'),('MCX','3')]);stream.wanted[('MCX','2')]=time.time()-61
    assert stream.desired()=={('NSE','1'),('MCX','3')}


@pytest.mark.asyncio
async def test_subscription_protocol_groups_mcx_snapquote():
    stream=BrokerStream(SimpleNamespace(is_configured=lambda:False),False)
    ws=SimpleNamespace(send=AsyncMock())
    await stream._subscription(ws,{('NSE','1'),('NFO','2'),('MCX','3')},1)
    messages=[json.loads(c.args[0]) for c in ws.send.await_args_list]
    assert {m['params']['mode'] for m in messages}=={2,3}
    snap=next(m for m in messages if m['params']['mode']==3)
    assert {'exchangeType':5,'tokens':['3']} in snap['params']['tokenList']
    await stream._subscription(ws,{('MCX','3')},0)
    assert json.loads(ws.send.await_args.args[0])['action']==0


@pytest.mark.parametrize('day,expected',[(date(2026,11,1),None),(date(2026,11,2),(clock(9),clock(23,55))),(date(2026,11,27),(clock(9),clock(23,55))),(date(2026,11,28),None),(date(2027,3,12),(clock(9),clock(23,55))),(date(2027,3,15),None)])
def test_mcx_session_season_bounds(day,expected):
    assert mcx_session_bounds(day)==expected


def test_mcx_holiday_and_special_session():
    assert mcx_session_bounds(TODAY,holidays='2026-11-27') is None
    assert mcx_session_bounds(TODAY,special_sessions='2026-11-27=17:00-23:55')==(clock(17),clock(23,55))
    assert mcx_session_bounds(datetime(2026,11,27,22,0,tzinfo=IST))[1]==clock(23,55)


def row(**kw):
    return dict(name='CRUDEOIL',exch_seg='MCX',instrumenttype='OPTFUT',symbol='CRUDEOIL18DEC266500CE',expiry='18DEC2026',strike='650000',lotsize='100',tick_size='10',token='123')|kw


@pytest.mark.parametrize('changes',[{'name':'CRUDEOILM'},{'exch_seg':'NCO'},{'instrumenttype':'OPTIDX'},{'expiry':'01JAN2026'},{'lotsize':'0'},{'lotsize':'1.5'},{'tick_size':'nan'},{'strike':'0'},{'token':'x'},{'symbol':'WRONGCE'}])
def test_reject_wrong_or_corrupt_mcx_contract(changes):
    assert parse_contract(row(**changes),TODAY) is None


def test_contract_selection_never_rolls_explicit_future_or_expiry():
    opt=parse_contract(row(),TODAY)
    fut=parse_contract(row(instrumenttype='FUTCOM',symbol='CRUDEOIL21DECFUT',strike='-1',token='456'),TODAY)
    assert opt.strike==6500 and opt.tick_size==.1 and opt.lot_size==100 and fut.option_type=='FUT'
    futures,selected,expiries,expiry,options=select_contracts([opt,fut],TODAY)
    assert selected==fut and options==[opt]
    with pytest.raises(ValueError):select_contracts([opt,fut],TODAY,'CRUDEOIL_OTHER')
    with pytest.raises(ValueError):select_contracts([opt,fut],TODAY,expiry='2026-12-17')
    assert quote_view(opt,None)['ltp'] is None


def test_scrip_master_keeps_mcx_out_of_index_order_resolver():
    s=ScripMaster(); c=parse_contract(row(),TODAY)
    s._index([['NIFTY','2099-12-31',25000,'CE','NFO','123','NIFTY31DEC9925000CE',65],
              [c.name,c.expiry,c.strike,c.option_type,c.exchange,c.token,c.symbol,c.lot_size,c.tick_size]])
    s._loaded_on=s._today()
    assert s.mcx_contracts()==[c] and s.by_symbol(c.symbol) is None
    assert s.resolve(c.symbol,'NIFTY',25000,'CE') is None
    with pytest.raises(ValueError):normalize_index_symbol('CRUDEOIL')


def test_default_auto_execution_safe_and_ws_settings_bounded():
    assert Settings(_env_file=None,V6_AUTO_EXECUTION_ENABLED=False).V6_AUTO_EXECUTION_ENABLED is False
    with pytest.raises(ValueError):Settings(BROKER_STREAM_MAX_SUBSCRIPTIONS=1001)
