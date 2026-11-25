import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  RefreshCw,
  SlidersHorizontal,
  ChevronDown,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  TrendingUp,
  Percent,
  BarChart2,
  ShoppingBag,
  Plus,
  Trash2,
  Zap,
} from 'lucide-react';
import { getOptionChain, getExpiries } from '../api';

export default function OptionChain({
  selectedIndex = 'NIFTY',
  onSelectIndex = () => {},
  spotPrice = 0,
  onOpenOrder = () => {},
  onSelectContract = () => {},
  onExecuteBasket = null,
}) {
  const [chain, setChain] = useState([]);
  const [advanced, setAdvanced] = useState(() => {
    try {
      return localStorage.getItem('tl_chain_advanced') === '1';
    } catch {
      return false;
    }
  });
  const toggleAdvanced = () =>
    setAdvanced((v) => {
      try {
        localStorage.setItem('tl_chain_advanced', v ? '0' : '1');
      } catch {}
      return !v;
    });
  const [chainMeta, setChainMeta] = useState({ data_source: null, lot_size: null, vix: null });
  const spotRef = useRef(spotPrice);
  spotRef.current = spotPrice;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [strikeCount, setStrikeCount] = useState(10);
  const [selectedExpiry, setSelectedExpiry] = useState('');
  const [expiries, setExpiries] = useState([]);
  const [viewFilter, setViewFilter] = useState('ALL'); // 'ALL' | 'CALLS' | 'PUTS'
  const [showTheta, setShowTheta] = useState(false);
  const [basketMode, setBasketMode] = useState(false);
  const [basketLegs, setBasketLegs] = useState([]);
  const [executingBasket, setExecutingBasket] = useState(false);

  const addBasketLeg = (strike, option_type, side, price) => {
    setBasketLegs((prev) => [
      ...prev,
      { strike, option_type, side, price, lots: 1 },
    ]);
  };

  const removeBasketLeg = (index) => {
    setBasketLegs((prev) => prev.filter((_, i) => i !== index));
  };

  const clearBasket = () => {
    setBasketLegs([]);
  };

  const handleExecuteBasket = async () => {
    if (basketLegs.length === 0) return;
    if (!window.confirm(`Execute all ${basketLegs.length} legs simultaneously in your virtual account?`)) return;
    setExecutingBasket(true);
    try {
      if (onExecuteBasket) {
        await onExecuteBasket(basketLegs.map((l) => ({ ...l, expiry: selectedExpiry })));
      }
      setBasketLegs([]);
      setBasketMode(false);
    } finally {
      setExecutingBasket(false);
    }
  };

  const lotSize =
    chainMeta.lot_size || (selectedIndex === 'BANKNIFTY' ? 30 : selectedIndex === 'SENSEX' ? 20 : 65);
  const strikeStep = selectedIndex === 'BANKNIFTY' || selectedIndex === 'SENSEX' ? 100 : 50;

  // Load available expiries
  useEffect(() => {
    let isSubscribed = true;
    async function loadExpiries() {
      try {
        const res = await getExpiries(selectedIndex);
        const raw = res.data?.expiries || res.data || [];
        const normalized = Array.isArray(raw)
          ? raw.map((item) => {
              if (typeof item === 'string') return { date: item, label: item };
              return {
                date: item.date || item.label || String(item),
                label: item.label || item.date || String(item),
              };
            })
          : [];

        if (isSubscribed && normalized.length > 0) {
          setExpiries(normalized);
          if (!selectedExpiry || !normalized.some((e) => e.date === selectedExpiry)) {
            setSelectedExpiry(normalized[0].date);
          }
        }
      } catch (e) {
        // Fallback default expiries if endpoint not ready
        const defaultExpiries = [
          { date: 'Current Week', label: 'Current Week' },
          { date: 'Next Week', label: 'Next Week' },
          { date: 'Monthly', label: 'Monthly' },
        ];
        if (isSubscribed) {
          setExpiries(defaultExpiries);
          setSelectedExpiry(defaultExpiries[0].date);
        }
      }
    }
    loadExpiries();
    return () => {
      isSubscribed = false;
    };
  }, [selectedIndex]);

  // Fetch option chain
  const chainBusy = useRef(false);
  const fetchChain = useCallback(async () => {
    if (chainBusy.current) return;
    chainBusy.current = true;
    setLoading(true);
    setError(null);
    try {
      const res = await getOptionChain(selectedIndex, strikeCount, selectedExpiry);
      const data = res.data?.chain || res.data?.data || res.data || [];
      if (Array.isArray(data)) {
        setChain(data);
        setChainMeta({
          data_source: res.data?.data_source || 'live',
          lot_size: res.data?.lot_size || null,
          vix: res.data?.vix ?? null,
        });
      }
    } catch (err) {
      console.warn('Failed to fetch option chain from backend:', err);
      // Never invent fake random option prices on feed failure; mark stale and show unavailability notice.
      setChainMeta((m) => ({ ...m, data_source: 'offline' }));
      setError('Option chain data unavailable. Check backend connection or Angel One market feed.');
    } finally {
      chainBusy.current = false;
      setLoading(false);
    }
  }, [selectedIndex, strikeCount, selectedExpiry]);

  useEffect(() => {
    fetchChain();
    const timer = setInterval(fetchChain, 5000);
    return () => clearInterval(timer);
  }, [fetchChain]);

  // Compute calculated ATM and max OI for bars
  const calculatedAtm = useMemo(() => {
    if (!spotPrice) return null;
    return Math.round(spotPrice / strikeStep) * strikeStep;
  }, [spotPrice, strikeStep]);

  const maxOi = useMemo(() => {
    let maxVal = 1;
    chain.forEach((row) => {
      const ceOi = Number(row.ce?.oi || 0);
      const peOi = Number(row.pe?.oi || 0);
      if (ceOi > maxVal) maxVal = ceOi;
      if (peOi > maxVal) maxVal = peOi;
    });
    return maxVal;
  }, [chain]);

  return (
    <div className="bg-[#ffffff] border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-full">
      {/* Controls Bar */}
      <div className="chain-controls p-3 bg-[#f4f6fa] border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        {/* Left: Index selector & Expiry & Strikes count */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Index Selector */}
          <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
            {[
              { id: 'NIFTY', label: 'NIFTY 50' },
              { id: 'BANKNIFTY', label: 'BANK NIFTY' },
              { id: 'FINNIFTY', label: 'FINNIFTY' },
              { id: 'SENSEX', label: 'SENSEX' },
            ].map((idx) => (
              <button
                key={idx.id}
                onClick={() => onSelectIndex(idx.id)}
                className={`px-2 py-1 rounded text-xs font-bold transition-all ${
                  selectedIndex === idx.id
                    ? 'bg-cyan-600 text-white shadow-md'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {idx.label}
              </button>
            ))}
          </div>

          {/* Expiry Dropdown */}
          <div className="flex items-center gap-1 bg-slate-900 border border-slate-800 px-2.5 py-1 rounded-lg text-xs">
            <span className="text-[10px] uppercase font-bold text-slate-500">Exp:</span>
            <select
              value={selectedExpiry}
              onChange={(e) => setSelectedExpiry(e.target.value)}
              className="bg-transparent text-slate-200 font-medium focus:outline-none cursor-pointer"
            >
              {expiries.map((exp) => (
                <option key={exp.date} value={exp.date} className="bg-slate-900 text-slate-200">
                  {exp.label}
                </option>
              ))}
            </select>
          </div>

          {/* Data source badge: tells you whether prices are real Angel One quotes */}
          {chainMeta.data_source && chainMeta.data_source !== 'live' && (
            <div
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wide bg-amber-950/70 border border-amber-600/60 text-amber-300"
              title="These prices are simulated, not real Angel One quotes. They will NOT match your broker."
            >
              ⚠ {chainMeta.data_source === 'offline' ? 'Offline demo data' : 'Simulated prices'}
            </div>
          )}
          {chainMeta.data_source === 'live' && (
            <div
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wide bg-emerald-950/60 border border-emerald-700/50 text-emerald-300"
              title="Real Angel One quotes"
            >
              ● Live{chainMeta.vix ? ` · VIX ${chainMeta.vix}` : ''}
            </div>
          )}

          {/* Simple / Advanced columns */}
          <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-xs">
            <button
              onClick={() => advanced && toggleAdvanced()}
              className={`px-2 py-1 rounded font-semibold transition-all ${!advanced ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
              title="Just prices and BUY / SELL buttons"
            >
              Simple
            </button>
            <button
              onClick={() => !advanced && toggleAdvanced()}
              className={`px-2 py-1 rounded font-semibold transition-all ${advanced ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
              title="Adds open interest, volume, IV, delta, bid and ask"
            >
              Advanced
            </button>
          </div>

          {/* Strike Count Selector */}
          <div className="flex items-center gap-1 bg-slate-900 border border-slate-800 px-2 py-1 rounded-lg text-xs">
            <span className="text-[10px] uppercase font-bold text-slate-500">Strikes:</span>
            <div className="flex gap-1">
              {[5, 7, 10, 15].map((cnt) => (
                <button
                  key={cnt}
                  onClick={() => setStrikeCount(cnt)}
                  className={`px-1.5 py-0.5 rounded text-[11px] font-mono font-bold transition-colors ${
                    strikeCount === cnt
                      ? 'bg-cyan-600 text-white'
                      : 'text-slate-400 hover:text-ink'
                  }`}
                >
                  ±{cnt}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right: View Toggle, Spot Display & Refresh */}
        <div className="flex items-center gap-2">
          {/* View Toggle */}
          <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-xs">
            <button
              onClick={() => setViewFilter('ALL')}
              className={`px-2 py-1 rounded font-semibold transition-all ${
                viewFilter === 'ALL' ? 'bg-slate-700 text-ink' : 'text-slate-400'
              }`}
            >
              All
            </button>
            <button
              onClick={() => setViewFilter('CALLS')}
              className={`px-2 py-1 rounded font-semibold transition-all ${
                viewFilter === 'CALLS' ? 'bg-emerald-600 text-white' : 'text-slate-400'
              }`}
            >
              Calls
            </button>
            <button
              onClick={() => setViewFilter('PUTS')}
              className={`px-2 py-1 rounded font-semibold transition-all ${
                viewFilter === 'PUTS' ? 'bg-rose-600 text-white' : 'text-slate-400'
              }`}
            >
              Puts
            </button>
            <button
              onClick={() => setShowTheta(!showTheta)}
              className={`px-2 py-1 rounded font-semibold transition-all border-l border-slate-800 ${
                showTheta ? 'bg-amber-600/80 text-white shadow' : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Toggle Option Theta (₹/day decay)"
            >
              θ Theta
            </button>
            <button
              onClick={() => setBasketMode(!basketMode)}
              className={`px-2 py-1 rounded font-semibold transition-all border-l border-slate-800 flex items-center gap-1 ${
                basketMode || basketLegs.length > 0
                  ? 'bg-purple-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Multi-Leg Strategy Basket Builder"
            >
              <ShoppingBag size={11} />
              <span>Basket{basketLegs.length > 0 ? ` (${basketLegs.length})` : ''}</span>
            </button>
          </div>

          {/* Spot price badge */}
          <div className="hidden sm:flex items-center gap-1.5 bg-slate-900 px-2.5 py-1 rounded-lg border border-slate-800 text-xs font-mono">
            <span className="text-slate-500 font-bold">SPOT:</span>
            <span className="text-cyan-400 font-bold num-tabular">
              ₹{Number(spotPrice || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </span>
          </div>

          {/* Refresh button */}
          <button
            onClick={fetchChain}
            disabled={loading}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700"
            title="Refresh Chain"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin text-cyan-400' : ''} />
          </button>
        </div>
        {error && (
          <div role="alert" className="w-full text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded px-2.5 py-1.5">
            {error}
          </div>
        )}
      </div>

      {/* Main Table */}
      <div className="chain-scroll flex-1 overflow-x-auto overflow-y-auto">
        <table data-advanced={advanced ? 'true' : 'false'} className="w-full border-collapse text-xs select-none">
          <thead className="sticky top-0 z-20 bg-[#f4f6fa] border-b border-slate-800 shadow-sm">
            {/* Top Super-headers */}
            <tr>
              {(viewFilter === 'ALL' || viewFilter === 'CALLS') && (
                <th
                  colSpan={showTheta ? 9 : 8}
                  className="py-1.5 px-3 text-center bg-emerald-950/40 text-emerald-400 font-bold uppercase tracking-wider text-[11px] border-r border-slate-800"
                >
                  CALLS (CE) • {selectedIndex}
                </th>
              )}

              <th className="py-1.5 px-3 text-center bg-slate-900 text-slate-200 font-bold uppercase tracking-wider text-[11px] border-r border-slate-800">
                STRIKE
              </th>

              {(viewFilter === 'ALL' || viewFilter === 'PUTS') && (
                <th
                  colSpan={showTheta ? 9 : 8}
                  className="py-1.5 px-3 text-center bg-rose-950/40 text-rose-400 font-bold uppercase tracking-wider text-[11px]"
                >
                  PUTS (PE) • {selectedIndex}
                </th>
              )}
            </tr>

            {/* Sub Column Headers */}
            <tr className="text-[10px] uppercase font-mono text-slate-400 bg-slate-950/80 border-b border-slate-800">
              {/* Calls Headers */}
              {(viewFilter === 'ALL' || viewFilter === 'CALLS') && (
                <>
                  <th title="Open interest: contracts still open. Bigger bar = more activity at that strike." className="adv-col py-2 px-2 text-right">OI (Bar)</th>
                  <th title="Contracts traded today" className="adv-col py-2 px-2 text-right">Vol</th>
                  <th title="Implied volatility: how much movement the market expects. Higher = pricier option." className="adv-col py-2 px-2 text-right">IV</th>
                  <th title="How much the option price moves for a 1-point move in the index." className="adv-col py-2 px-2 text-right">Delta</th>
                  {showTheta && <th className="py-2 px-2 text-right text-amber-400">θ Theta</th>}
                  <th title="Highest price a buyer is offering" className="adv-col py-2 px-2 text-right">Bid</th>
                  <th title="Lowest price a seller is asking" className="adv-col py-2 px-2 text-right">Ask</th>
                  <th className="py-2 px-2 text-right font-bold text-slate-200">LTP</th>
                  <th className="py-2 px-2 text-center border-r border-slate-800">Action</th>
                </>
              )}

              {/* Strike Header */}
              <th className="py-2 px-3 text-center font-bold text-ink bg-slate-900 border-r border-slate-800">
                Strike
              </th>

              {/* Puts Headers */}
              {(viewFilter === 'ALL' || viewFilter === 'PUTS') && (
                <>
                  <th className="py-2 px-2 text-center">Action</th>
                  <th className="py-2 px-2 text-left font-bold text-slate-200">LTP</th>
                  <th title="Highest price a buyer is offering" className="adv-col py-2 px-2 text-left">Bid</th>
                  <th title="Lowest price a seller is asking" className="adv-col py-2 px-2 text-left">Ask</th>
                  <th title="How much the option price moves for a 1-point move in the index." className="adv-col py-2 px-2 text-left">Delta</th>
                  {showTheta && <th className="py-2 px-2 text-left text-amber-400">θ Theta</th>}
                  <th title="Implied volatility: how much movement the market expects. Higher = pricier option." className="adv-col py-2 px-2 text-left">IV</th>
                  <th title="Contracts traded today" className="adv-col py-2 px-2 text-left">Vol</th>
                  <th title="Open interest: contracts still open. Bigger bar = more activity at that strike." className="adv-col py-2 px-2 text-left">OI (Bar)</th>
                </>
              )}
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
            {chain.length === 0 ? (
              <tr>
                <td
                  colSpan={viewFilter === 'ALL' ? (showTheta ? 19 : 17) : (showTheta ? 10 : 9)}
                  className="py-12 text-center text-slate-500 font-sans"
                >
                  {loading ? 'Fetching option chain...' : 'No option chain data available.'}
                </td>
              </tr>
            ) : (
              chain.map((row) => {
                const strike = row.strike;
                const isAtm = row.is_atm || strike === calculatedAtm;
                const currentSpot = spotPrice || (calculatedAtm ?? strike);
                const isCeItm = strike < currentSpot;
                const isPeItm = strike > currentSpot;

                const ce = row.ce || {};
                const pe = row.pe || {};

                const ceIv = ce.greeks?.iv ?? ce.iv;
                const ceDelta = ce.greeks?.delta ?? ce.delta;
                const peIv = pe.greeks?.iv ?? pe.iv;
                const peDelta = pe.greeks?.delta ?? pe.delta;

                const ceOi = Number(ce.oi || 0);
                const peOi = Number(pe.oi || 0);

                const ceOiPercent = Math.min(100, Math.round((ceOi / maxOi) * 100));
                const peOiPercent = Math.min(100, Math.round((peOi / maxOi) * 100));

                const ceLtp = Number(ce.ltp || 0);
                const peLtp = Number(pe.ltp || 0);

                return (
                  <tr
                    key={strike}
                    className={`transition-colors hover:bg-slate-800/50 ${
                      isAtm ? 'bg-cyan-950/30 border-y-2 border-cyan-500/80 font-semibold' : ''
                    }`}
                  >
                    {/* CALLS COLUMNS */}
                    {(viewFilter === 'ALL' || viewFilter === 'CALLS') && (
                      <>
                        {/* Call OI with visual mini bar */}
                        <td
                          className={`adv-col py-1.5 px-2 text-right relative overflow-hidden ${
                            isCeItm ? 'bg-amber-500/[0.07]' : ''
                          }`}
                        >
                          <div
                            className="absolute right-0 top-0 bottom-0 bg-emerald-500/20 pointer-events-none transition-all duration-300"
                            style={{ width: `${ceOiPercent}%` }}
                          />
                          <span className="relative z-10 text-slate-300">
                            {ceOi > 0 ? (ceOi / 1000).toFixed(1) + 'k' : '—'}
                          </span>
                        </td>

                        {/* Call Volume */}
                        <td className={`adv-col py-1.5 px-2 text-right text-slate-400 ${isCeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {ce.volume ? (ce.volume / 1000).toFixed(1) + 'k' : '—'}
                        </td>

                        {/* Call IV */}
                        <td className={`adv-col py-1.5 px-2 text-right text-slate-400 ${isCeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {ceIv > 5.1 ? ceIv : '—'}
                        </td>

                        {/* Call Delta */}
                        <td className={`adv-col py-1.5 px-2 text-right text-emerald-400 font-medium ${isCeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {ceDelta != null ? ceDelta : '—'}
                        </td>

                        {/* Call Theta */}
                        {showTheta && (
                          <td className={`py-1.5 px-2 text-right text-amber-400 font-mono text-[10px] ${isCeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                            {ce.greeks?.theta != null ? Number(ce.greeks.theta).toFixed(1) : '—'}
                          </td>
                        )}

                        {/* Call Bid */}
                        <td className={`adv-col py-1.5 px-2 text-right text-slate-400 ${isCeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {ce.bid != null ? Number(ce.bid).toFixed(2) : '—'}
                        </td>

                        {/* Call Ask */}
                        <td className={`adv-col py-1.5 px-2 text-right text-slate-400 ${isCeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {ce.ask != null ? Number(ce.ask).toFixed(2) : '—'}
                        </td>

                        {/* Call LTP */}
                        <td
                          className={`py-1.5 px-2 text-right font-bold text-emerald-400 num-tabular ${
                            isCeItm ? 'bg-amber-500/[0.07]' : ''
                          }`}
                        >
                          ₹{ceLtp.toFixed(2)}
                        </td>

                        {/* Call Action Buttons (Buy & Sell) */}
                        <td className={`py-1.5 px-2 text-center border-r border-slate-800 ${isCeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          <div className="flex items-center justify-center gap-1 font-sans">
                            <button
                              onClick={() => onSelectContract({ strike, option_type: 'CE', expiry: selectedExpiry })}
                              className="max-sm:hidden p-1 rounded text-cyan-400 hover:bg-cyan-950/80 hover:text-cyan-200 transition-colors"
                              title={`View ${selectedIndex} ${strike} CE Candlestick Chart`}
                            >
                              <BarChart2 size={12} />
                            </button>
                            {basketMode ? (
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={() => addBasketLeg(strike, 'CE', 'BUY', ceLtp)}
                                  className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-purple-600 hover:bg-purple-500 text-white shadow"
                                  title={`Add BUY ${strike} CE to Basket`}
                                >
                                  +B
                                </button>
                                <button
                                  onClick={() => addBasketLeg(strike, 'CE', 'SELL', ceLtp)}
                                  className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-600 hover:bg-amber-500 text-white shadow"
                                  title={`Add SELL ${strike} CE to Basket`}
                                >
                                  +S
                                </button>
                              </div>
                            ) : (
                              <>
                                <button
                                  onClick={() =>
                                    onOpenOrder({
                                      symbol: selectedIndex,
                                      strike,
                                      optionType: 'CE',
                                      side: 'BUY',
                                      ltp: ceLtp,
                                      bid: ce.bid || ceLtp,
                                      ask: ce.ask || ceLtp,
                                      lotSize,
                                      expiry: selectedExpiry,
                                    })
                                  }
                                  className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-600 hover:bg-emerald-500 text-white shadow transition-all active:scale-95"
                                  title={`Buy ${selectedIndex} ${strike} CE`}
                                >
                                  BUY
                                </button>
                                <button
                                  onClick={() =>
                                    onOpenOrder({
                                      symbol: selectedIndex,
                                      strike,
                                      optionType: 'CE',
                                      side: 'SELL',
                                      ltp: ceLtp,
                                      bid: ce.bid || ceLtp,
                                      ask: ce.ask || ceLtp,
                                      lotSize,
                                      expiry: selectedExpiry,
                                    })
                                  }
                                  className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-600/80 hover:bg-rose-500 text-white shadow transition-all active:scale-95"
                                  title={`Sell ${selectedIndex} ${strike} CE`}
                                >
                                  SELL
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </>
                    )}

                    {/* STRIKE PRICE COLUMN (CENTER) */}
                    <td
                      className={`py-2 px-3 text-center font-bold border-r border-slate-800 ${
                        isAtm
                          ? 'bg-cyan-600 text-white text-xs shadow-inner'
                          : 'bg-slate-900 text-slate-100'
                      }`}
                    >
                      <div className="flex items-center justify-center gap-1.5">
                        <span className="num-tabular">{strike}</span>
                        {isAtm && (
                          <span className="px-1.5 py-0.2 rounded text-[9px] bg-black/60 text-cyan-200 font-sans uppercase font-bold tracking-wider">
                            ATM
                          </span>
                        )}
                      </div>
                    </td>

                    {/* PUTS COLUMNS */}
                    {(viewFilter === 'ALL' || viewFilter === 'PUTS') && (
                      <>
                        {/* Put Action Buttons (Buy & Sell & Chart) */}
                        <td className={`py-1.5 px-2 text-center ${isPeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          <div className="flex items-center justify-center gap-1 font-sans">
                            {basketMode ? (
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={() => addBasketLeg(strike, 'PE', 'BUY', peLtp)}
                                  className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-purple-600 hover:bg-purple-500 text-white shadow"
                                  title={`Add BUY ${strike} PE to Basket`}
                                >
                                  +B
                                </button>
                                <button
                                  onClick={() => addBasketLeg(strike, 'PE', 'SELL', peLtp)}
                                  className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-600 hover:bg-amber-500 text-white shadow"
                                  title={`Add SELL ${strike} PE to Basket`}
                                >
                                  +S
                                </button>
                              </div>
                            ) : (
                              <>
                                <button
                                  onClick={() =>
                                    onOpenOrder({
                                      symbol: selectedIndex,
                                      strike,
                                      optionType: 'PE',
                                      side: 'BUY',
                                      ltp: peLtp,
                                      bid: pe.bid || peLtp,
                                      ask: pe.ask || peLtp,
                                      lotSize,
                                      expiry: selectedExpiry,
                                    })
                                  }
                                  className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-600 hover:bg-emerald-500 text-white shadow transition-all active:scale-95"
                                  title={`Buy ${selectedIndex} ${strike} PE`}
                                >
                                  BUY
                                </button>
                                <button
                                  onClick={() =>
                                    onOpenOrder({
                                      symbol: selectedIndex,
                                      strike,
                                      optionType: 'PE',
                                      side: 'SELL',
                                      ltp: peLtp,
                                      bid: pe.bid || peLtp,
                                      ask: pe.ask || peLtp,
                                      lotSize,
                                      expiry: selectedExpiry,
                                    })
                                  }
                                  className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-600/80 hover:bg-rose-500 text-white shadow transition-all active:scale-95"
                                  title={`Sell ${selectedIndex} ${strike} PE`}
                                >
                                  SELL
                                </button>
                              </>
                            )}
                            <button
                              onClick={() => onSelectContract({ strike, option_type: 'PE', expiry: selectedExpiry })}
                              className="max-sm:hidden p-1 rounded text-cyan-400 hover:bg-cyan-950/80 hover:text-cyan-200 transition-colors"
                              title={`View ${selectedIndex} ${strike} PE Candlestick Chart`}
                            >
                              <BarChart2 size={12} />
                            </button>
                          </div>
                        </td>

                        {/* Put LTP */}
                        <td
                          className={`py-1.5 px-2 text-left font-bold text-rose-400 num-tabular ${
                            isPeItm ? 'bg-amber-500/[0.07]' : ''
                          }`}
                        >
                          ₹{peLtp.toFixed(2)}
                        </td>

                        {/* Put Bid */}
                        <td className={`adv-col py-1.5 px-2 text-left text-slate-400 ${isPeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {pe.bid != null ? Number(pe.bid).toFixed(2) : '—'}
                        </td>

                        {/* Put Ask */}
                        <td className={`adv-col py-1.5 px-2 text-left text-slate-400 ${isPeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {pe.ask != null ? Number(pe.ask).toFixed(2) : '—'}
                        </td>

                        {/* Put Theta */}
                        {showTheta && (
                          <td className={`py-1.5 px-2 text-left text-amber-400 font-mono text-[10px] ${isPeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                            {pe.greeks?.theta != null ? Number(pe.greeks.theta).toFixed(1) : '—'}
                          </td>
                        )}

                        {/* Put Delta */}
                        <td className={`adv-col py-1.5 px-2 text-left text-rose-400 font-medium ${isPeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {peDelta != null ? peDelta : '—'}
                        </td>

                        {/* Put IV */}
                        <td className={`adv-col py-1.5 px-2 text-left text-slate-400 ${isPeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {peIv > 5.1 ? peIv : '—'}
                        </td>

                        {/* Put Volume */}
                        <td className={`adv-col py-1.5 px-2 text-left text-slate-400 ${isPeItm ? 'bg-amber-500/[0.07]' : ''}`}>
                          {pe.volume ? (pe.volume / 1000).toFixed(1) + 'k' : '—'}
                        </td>

                        {/* Put OI with visual mini bar */}
                        <td
                          className={`adv-col py-1.5 px-2 text-left relative overflow-hidden ${
                            isPeItm ? 'bg-amber-500/[0.07]' : ''
                          }`}
                        >
                          <div
                            className="absolute left-0 top-0 bottom-0 bg-rose-500/20 pointer-events-none transition-all duration-300"
                            style={{ width: `${peOiPercent}%` }}
                          />
                          <span className="relative z-10 text-slate-300">
                            {peOi > 0 ? (peOi / 1000).toFixed(1) + 'k' : '—'}
                          </span>
                        </td>
                      </>
                    )}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Floating Strategy Basket Dock */}
      {basketLegs.length > 0 && (
        <div className="p-2.5 bg-[#ffffff] border-t border-purple-800/60 flex flex-wrap items-center justify-between gap-2 shadow-2xl animate-fadeIn">
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 rounded bg-purple-600 text-white text-[11px] font-bold font-mono flex items-center gap-1">
              <ShoppingBag size={11} />
              Basket ({basketLegs.length})
            </span>
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              {basketLegs.map((leg, i) => (
                <span
                  key={i}
                  className={`px-2 py-0.5 rounded font-mono font-bold flex items-center gap-1 border ${
                    leg.side === 'BUY'
                      ? 'bg-emerald-950/80 border-emerald-700 text-emerald-300'
                      : 'bg-rose-950/80 border-rose-700 text-rose-300'
                  }`}
                >
                  {leg.side} {leg.strike} {leg.option_type} @ ₹{leg.price}
                  <button
                    onClick={() => removeBasketLeg(i)}
                    className="text-slate-400 hover:text-ink ml-0.5 text-xs"
                    title="Remove leg"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={clearBasket}
              className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-semibold"
            >
              Clear
            </button>
            <button
              onClick={handleExecuteBasket}
              disabled={executingBasket}
              className="px-3 py-1 rounded bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-bold shadow-lg shadow-emerald-950/50 flex items-center gap-1.5 active:scale-95 transition-all"
            >
              <Zap size={13} />
              <span>{executingBasket ? 'Placing Orders...' : `Execute All (${basketLegs.length} Legs)`}</span>
            </button>
          </div>
        </div>
      )}

      {/* Footer Info Ribbon */}
      <div className="px-3 py-1.5 bg-[#f4f6fa] border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-400">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1 text-amber-400">
            <span className="w-2.5 h-2.5 rounded-sm bg-amber-500/30 border border-amber-500/50 inline-block" />
            In-the-Money (ITM) Tint
          </span>
          <span className="flex items-center gap-1 text-cyan-400">
            <span className="w-2.5 h-2.5 rounded-sm bg-cyan-600 inline-block" />
            At-the-Money (ATM)
          </span>
        </div>
        <div className="font-mono text-slate-500">
          Lot Size: <span className="text-slate-300 font-bold">{lotSize}</span> units • Strike Interval: <span className="text-slate-300 font-bold">{strikeStep}</span> pts
        </div>
      </div>
    </div>
  );
}
