import React, { useEffect, useRef, useState } from 'react';
import { createChart, CandlestickSeries } from 'lightweight-charts';
import api from '../api';
import McxDebatePanel, { McxHistory } from './McxDebatePanel';

const FRAMES = ['1m', '5m', '15m', '1h', '1d'];
const price = n => n == null || !Number.isFinite(Number(n)) ? '—' : Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const integer = n => n == null || !Number.isFinite(Number(n)) ? '—' : Number(n).toLocaleString('en-IN');
const stamp = s => { if (!s) return '—'; const dt = new Date(s); return Number.isNaN(dt.valueOf()) ? s : dt.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'medium' }) + ' IST'; };
const errorText = e => typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Market data request failed. Try again when the feed is available.';

function FutureChart({ rows }) {
  const element = useRef(null), chart = useRef(null), series = useRef(null), seen = useRef(false);
  useEffect(() => {
    if (!element.current) return;
    const c = createChart(element.current, {
      autoSize: true, height: 290,
      layout: { background: { color: '#ffffff' }, textColor: '#334155' },
      grid: { vertLines: { color: '#f1f5f9' }, horzLines: { color: '#f1f5f9' } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    chart.current = c;
    series.current = c.addSeries(CandlestickSeries, { upColor: '#059669', downColor: '#e11d48', borderVisible: false, wickUpColor: '#059669', wickDownColor: '#e11d48' });
    return () => { c.remove(); chart.current = null; series.current = null; seen.current = false; };
  }, []);
  useEffect(() => {
    if (!series.current) return;
    const byTime = new Map();
    for (const r of rows) {
      if (![r.time, r.open, r.high, r.low, r.close].every(Number.isFinite)) continue;
      if (r.low > Math.min(r.open, r.close) || r.high < Math.max(r.open, r.close)) continue;
      byTime.set(r.time, { time: r.time + 19800, open: r.open, high: r.high, low: r.low, close: r.close });
    }
    const data = [...byTime.values()].sort((a, b) => a.time - b.time);
    series.current.setData(data);
    if (data.length && !seen.current) { chart.current?.timeScale().fitContent(); seen.current = true; }
  }, [rows]);
  return <div ref={element} className="min-w-0 w-full" style={{ height: 290 }} aria-label="Historical Crude Oil futures candles in IST" />;
}

export default function McxResearch({ signedIn }) {
  const [future, setFuture] = useState('');
  const [expiry, setExpiry] = useState('');
  const [frame, setFrame] = useState('5m');
  const [market, setMarket] = useState(null);
  const [meta, setMeta] = useState(null);
  const [marketError, setMarketError] = useState('');
  const [chartError, setChartError] = useState('');
  const [tab,setTab] = useState('trade');
  const [mcxPaper, setMcxPaper] = useState(null);
  const [orderMsg, setOrderMsg] = useState('');

  const loadMcxPaper = async () => {
    if (!signedIn) return;
    try { const r = await api.get('/mcx/paper/state'); setMcxPaper(r.data); } catch { /* ignore */ }
  };
  useEffect(() => { if (!signedIn) return; let active=true,timer; async function refresh(){try{const r=await api.get('/mcx/paper/state');if(active)setMcxPaper(r.data);}catch{}finally{if(active)timer=setTimeout(refresh,10000);}}refresh();return()=>{active=false;clearTimeout(timer);}; }, [signedIn]);

  const handleMcxBuy = async (sym) => {
    setOrderMsg('');
    try {
      const r = await api.post('/mcx/paper/order', { symbol: sym, lots: 1 });
      setOrderMsg(`Filled MCX paper BUY 1 lot ${sym} @ ₹${r.data?.position?.entry_price}`);
      await loadMcxPaper();
    } catch (e) { setOrderMsg(errorText(e)); }
  };

  const handleMcxSquareoff = async () => {
    setOrderMsg('');
    try {
      const r = await api.post('/mcx/paper/squareoff');
      setOrderMsg(`Squared off ${r.data?.settled ?? 0} MCX position(s).`);
      await loadMcxPaper();
    } catch (e) { setOrderMsg(errorText(e)); }
  };
  useEffect(() => {
    if (!signedIn) return;
    setMarket(null); setMarketError('');
    let disposed = false, timer, controller;
    async function load() {
      controller = new AbortController();
      try {
        const r = await api.get('/mcx/market', { params: { ...(future ? { future } : {}), ...(expiry ? { expiry } : {}) }, signal: controller.signal, timeout: 35000 });
        if (!disposed) { setMarket(r.data); setMarketError(''); }
      } catch (e) { if (!disposed) { setMarket(null); setMarketError(errorText(e)); } }
      finally { if (!disposed) timer = setTimeout(load, 5000); }
    }
    load();
    return () => { disposed = true; clearTimeout(timer); controller?.abort(); };
  }, [signedIn, future, expiry]);
  const contract = market?.future?.symbol || '';
  useEffect(() => {
    setMeta(null); setChartError('');
    if (!signedIn || !contract) return;
    let disposed = false, timer, controller;
    async function load() {
      controller = new AbortController();
      try {
        const r = await api.get('/mcx/candles', { params: { future: contract, interval: frame }, signal: controller.signal, timeout: 60000 });
        if (!disposed) { setMeta(r.data); setChartError(''); }
      } catch (e) { if (!disposed) { setMeta(null); setChartError(errorText(e)); } }
      finally { if (!disposed) timer = setTimeout(load, 60000); }
    }
    load();
    return () => { disposed = true; clearTimeout(timer); controller?.abort(); };
  }, [signedIn, contract, frame]);
  if (!signedIn) return <div className="rounded-xl border bg-white p-5 text-ink">Sign in to view the MCX research market.</div>;
  const q = market?.future;
  return <section className="max-w-7xl mx-auto space-y-4 text-ink">
    <header className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-bold text-cyan-800 bg-cyan-50 rounded-full px-3 py-1">CLOUD V6.1 · MCX</span><span className="text-xs font-bold text-amber-900 bg-amber-100 rounded-full px-3 py-1">Isolated MCX Paper Wallet</span></div>
      </div>
      <h1 className="text-2xl font-bold mt-3 text-ink">Crude Oil (MCX)</h1>
      <p className="mt-1 text-sm text-slate-300">Live MCX CRUDEOIL futures & options (contract master lot sizes). Isolated from your NSE index wallet.</p>
      <div className="grid sm:grid-cols-3 gap-3 mt-4">
        <div className="border rounded-xl p-3"><div className="text-xs text-slate-400">Futures price</div><div className="text-2xl font-mono font-bold text-ink">{q?.ltp == null ? '—' : '₹' + price(q.ltp)}</div><div className="text-xs mt-1 break-words text-slate-300">{q?.symbol || 'Awaiting contract master'}</div></div>
        <div className="border rounded-xl p-3"><div className="text-xs text-slate-400">Session (IST)</div><div className="font-bold mt-1 text-ink">{market?.session_status?.replaceAll('_', ' ') || 'UNKNOWN'}</div><div className="text-xs mt-1 text-slate-300">{market?.session_open && `${market.session_open} – ${market.session_close}`}</div><div className="text-xs text-amber-800">{market && !market.calendar_holidays_configured ? 'Holiday overrides not configured' : ''}</div></div>
        <div className="border rounded-xl p-3"><div className="text-xs text-slate-400">Feed source</div><div className="font-bold mt-1 text-ink">{q?.transport === 'websocket' ? 'WebSocket' : q?.transport === 'rest' ? 'REST recovery' : 'Unavailable'}</div><div className="text-xs mt-1 break-words text-slate-300">{stamp(q?.exchange_timestamp)}</div></div>
      </div>
      {marketError && <p role="alert" className="mt-3 bg-amber-50 border border-amber-300 text-amber-900 p-3 rounded-lg text-sm">{marketError}</p>}
      {market && <div className="grid sm:grid-cols-2 gap-3 mt-4">
        <label className="text-xs font-semibold">Exact futures contract<select value={future || q?.symbol || ''} onChange={e => setFuture(e.target.value)} className="mt-1 block w-full rounded-lg border bg-white p-2 text-sm">{market.futures.map(c => <option key={c.symbol} value={c.symbol}>{c.symbol} · {c.expiry}</option>)}</select></label>
        <label className="text-xs font-semibold">Independent option expiry<select value={expiry || market.selected_expiry || ''} onChange={e => setExpiry(e.target.value)} className="mt-1 block w-full rounded-lg border bg-white p-2 text-sm">{!market.option_expiries.length && <option value="">Unavailable</option>}{market.option_expiries.map(d => <option key={d}>{d}</option>)}</select></label>
      </div>}
    </header>
    <nav className="grid grid-cols-3 gap-2 rounded-xl bg-white border p-2" aria-label="MCX terminal tabs">{[['trade','Option Buy/Sell'],['chat','Chat'],['history','History']].map(([key,label])=><button key={key} onClick={()=>setTab(key)} aria-pressed={tab===key} className={`rounded-lg px-2 py-3 text-xs sm:text-sm font-semibold ${tab===key?'bg-cyan-700 text-white':'text-slate-700 bg-slate-100'}`}>{label}</button>)}</nav>
    {tab==='chat' && <McxDebatePanel future={contract} expiry={market?.selected_expiry}/>}
    {tab==='history' && <McxHistory paper={mcxPaper}/>}
    <div hidden={tab!=='trade'} className="space-y-4">
    <div className="bg-white rounded-2xl border p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-bold">Futures candles · {contract || '—'}</h2><div className="flex flex-wrap gap-1">{FRAMES.map(f => <button key={f} onClick={() => setFrame(f)} aria-pressed={frame === f} className={`px-3 py-1.5 rounded-lg text-sm font-semibold ${frame === f ? 'bg-cyan-700 text-white' : 'bg-slate-100 text-slate-800'}`}>{f}</button>)}</div></div>
      <p className="text-xs text-slate-600">Historical REST candles · {meta?.source || 'unavailable'} · {meta?.last_candle_ist || 'No confirmed latest candle'}</p>
      {chartError && <p role="alert" className="text-sm text-amber-800">{chartError}</p>}
      <FutureChart key={`${contract}-${frame}`} rows={meta?.candles || []} />
      <div className="rounded-lg bg-slate-50 p-3 text-sm">{meta?.analysis ? <><strong>Research trend: {meta.analysis.direction}</strong><div className="text-xs mt-1">EMA20 {price(meta.analysis.ema20)} · EMA50 {price(meta.analysis.ema50)} · ATR {price(meta.analysis.atr_pct)}% · {meta.analysis.count} completed candles</div></> : <span className="text-slate-600">No validated trend: {meta?.analysis_reason || 'awaiting sufficient completed candles'}</span>}</div>
    </div>
    {mcxPaper && (
      <div className="bg-white rounded-2xl border p-4 space-y-2 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="font-bold text-sm text-ink">MCX Paper Wallet · Cash ₹{price(mcxPaper.cash_balance)} · Realized ₹{price(mcxPaper.realized_pnl)} · Open ({mcxPaper.positions?.length || 0})</div>
          {!!mcxPaper.positions?.length && <button type="button" onClick={handleMcxSquareoff} className="px-2.5 py-1 rounded bg-rose-600 text-white font-semibold">Square Off MCX</button>}
        </div>
        {mcxPaper.positions?.some(p=>p.exit_due) && <p role="alert" className="bg-amber-50 text-amber-900 rounded p-2">Square-off due. Open positions remain unresolved until a fresh executable bid is available. Check feed and contract expiry.</p>}
        {orderMsg && <div className="p-2 rounded bg-cyan-50 text-cyan-900 font-medium">{orderMsg}</div>}
        {!!mcxPaper.positions?.length && (
          <div className="overflow-x-auto"><table className="w-full text-left whitespace-nowrap"><thead><tr className="text-slate-400"><th className="p-1.5">Symbol</th><th className="p-1.5">Qty</th><th className="p-1.5">Entry</th><th className="p-1.5">LTP</th><th className="p-1.5">SL/Tgt</th><th className="p-1.5">P&amp;L</th></tr></thead><tbody>{mcxPaper.positions.map(p => <tr key={p.id} className="border-t"><td className="p-1.5 font-medium">{p.symbol}</td><td className="p-1.5">{p.quantity}</td><td className="p-1.5">₹{price(p.entry_price)}</td><td className="p-1.5">₹{price(p.ltp)}</td><td className="p-1.5">{price(p.stop_loss)} / {price(p.target)}</td><td className={`p-1.5 font-bold ${p.unrealized_pnl >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>₹{price(p.unrealized_pnl)}</td></tr>)}</tbody></table></div>
        )}
      </div>
    )}
    <div className="bg-white rounded-2xl border p-4">
      <h2 className="font-bold text-ink">MCX options · {market?.selected_expiry || '—'}</h2>
      <p className="text-xs text-amber-900 mt-2">{market?.warning || 'Contract mapping and settlement model are not yet verified.'} The displayed strike window is centered on the selected futures price.</p>
      <div className="overflow-x-auto mt-3"><table className="w-full text-xs text-left whitespace-nowrap"><thead className="bg-slate-900 text-slate-300"><tr>{['Contract','Type','Strike','LTP','Bid','Ask','OI','Lot','Tick','Feed','Trade'].map(v => <th className="p-2" key={v}>{v}</th>)}</tr></thead><tbody>{(market?.options || []).map(c => <tr key={c.symbol} className="border-t"><td className="p-2 font-medium text-ink">{c.symbol}</td><td className="p-2">{c.option_type}</td><td className="p-2">{price(c.strike)}</td><td className="p-2">{price(c.ltp)}</td><td className="p-2">{price(c.bid)}</td><td className="p-2">{price(c.ask)}</td><td className="p-2">{integer(c.oi)}</td><td className="p-2">{integer(c.lot_size)}</td><td className="p-2">{price(c.tick_size)}</td><td className="p-2">{c.transport || 'unavailable'}</td><td className="p-2"><button type="button" disabled={!c.ask} onClick={() => handleMcxBuy(c.symbol)} className="px-2 py-0.5 rounded bg-emerald-600 text-white font-semibold disabled:opacity-40">Buy 1</button></td></tr>)}</tbody></table></div>
      {!market?.options?.length && <p className="text-sm text-slate-300 mt-3">No current option quotes to display.</p>}
    </div>
    </div>
  </section>;
}
