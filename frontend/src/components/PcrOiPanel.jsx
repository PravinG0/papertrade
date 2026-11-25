import React, { useState, useEffect, useMemo } from 'react';
import { getPcrOi, getOptionChain } from '../api';
import { Layers, TrendingUp, TrendingDown, Target, Shield, RefreshCw } from 'lucide-react';

export default function PcrOiPanel({
  selectedIndex = 'NIFTY',
  spotPrice = 23500,
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await getPcrOi(selectedIndex);
      if (res.data && Object.hasOwn(res.data, 'pcr')) {
        const d = res.data;
        setData(d.data_source !== 'live' ? null : {
          ...d, call_wall: d.call_oi_wall, put_wall: d.put_oi_wall,
          total_call_oi: d.total_ce_oi, total_put_oi: d.total_pe_oi,
          strikes: (d.strikes || []).map((strike, i) => ({ strike, ceOi: Number(d.ce_oi?.[i] || 0), peOi: Number(d.pe_oi?.[i] || 0) })),
        });
      } else {
        // Fallback to fetch option chain and compute
        const chainRes = await getOptionChain(selectedIndex, 12);
        const chain = chainRes.data?.chain || chainRes.data || [];
        if (chainRes.data?.data_source === 'simulated') setData(null);
        else processChainData(chain);
      }
    } catch (e) {
      // Fallback: compute from chain or generate realistic stats
      fetchChainFallback();
    } finally {
      setLoading(false);
    }
  };

  const processChainData = (chain) => {
    let totalCeOi = 0;
    let totalPeOi = 0;
    let maxCeOi = -1;
    let maxPeOi = -1;
    let callWall = null;
    let putWall = null;
    const strikes = [];

    chain.forEach((row) => {
      const c = Number(row.ce?.oi || 0);
      const p = Number(row.pe?.oi || 0);
      totalCeOi += c;
      totalPeOi += p;
      if (c > maxCeOi) {
        maxCeOi = c;
        callWall = row.strike;
      }
      if (p > maxPeOi) {
        maxPeOi = p;
        putWall = row.strike;
      }
      strikes.push({
        strike: row.strike,
        ceOi: c,
        peOi: p,
      });
    });

    let minLoss = Infinity;
    let maxPain = null;
    chain.forEach((cand) => {
      let loss = 0;
      chain.forEach((r) => {
        if (cand.strike > r.strike) loss += (cand.strike - r.strike) * Number(r.ce?.oi || 0);
        else if (cand.strike < r.strike) loss += (r.strike - cand.strike) * Number(r.pe?.oi || 0);
      });
      if (loss < minLoss) {
        minLoss = loss;
        maxPain = cand.strike;
      }
    });

    const pcr = totalCeOi > 0 ? Number((totalPeOi / totalCeOi).toFixed(2)) : null;

    setData({
      symbol: selectedIndex,
      pcr,
      total_call_oi: totalCeOi,
      total_put_oi: totalPeOi,
      call_wall: callWall,
      put_wall: putWall,
      max_pain: maxPain,
      strikes,
    });
  };

  const fetchChainFallback = async () => {
    try {
      const res = await getOptionChain(selectedIndex, 10);
      const chain = res.data?.chain || res.data || [];
      if (chain.length > 0) {
        if (res.data?.data_source === 'simulated') setData(null);
        else processChainData(chain);
      } else {
        // mock data
        generateMockPcr();
      }
    } catch (e) {
      generateMockPcr();
    }
  };

  const generateMockPcr = () => setData(null); // no fabricated OI

  useEffect(() => {
    fetchData();
  }, [selectedIndex]);

  const pcrSentiment = useMemo(() => {
    if (!data || data.pcr == null) return { text: 'Unavailable', color: 'text-amber-400' };
    if (data.pcr >= 1.25) return { text: 'Bullish (High Put Writing)', color: 'text-emerald-400' };
    if (data.pcr >= 1.0) return { text: 'Mildly Bullish', color: 'text-emerald-300' };
    if (data.pcr <= 0.75) return { text: 'Bearish (Heavy Call Writing)', color: 'text-rose-400' };
    if (data.pcr < 1.0) return { text: 'Mildly Bearish', color: 'text-rose-300' };
    return { text: 'Neutral', color: 'text-amber-400' };
  }, [data]);

  const maxStrikeOi = useMemo(() => {
    if (!data?.strikes) return 1;
    let m = 1;
    data.strikes.forEach((s) => {
      if (s.ceOi > m) m = s.ceOi;
      if (s.peOi > m) m = s.peOi;
    });
    return m;
  }, [data]);

  return (
    <div className="bg-[#ffffff] border border-slate-800 rounded-xl p-4 shadow-xl space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-cyan-600/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
            <Layers size={18} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-ink uppercase tracking-wider">
              {selectedIndex} • Institutional OI & PCR Analysis
            </h2>
            <p className="text-xs text-slate-400">
              Derivatives Open Interest positioning, Max Pain, and Call/Put walls
            </p>
          </div>
        </div>

        <button
          onClick={fetchData}
          disabled={loading}
          className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700"
          title="Refresh OI Stats"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin text-cyan-400' : ''} />
        </button>
      </div>

      {/* Top 4 KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* PCR Metric Card */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs text-slate-400 uppercase font-semibold">
            <span>Put-Call Ratio (PCR)</span>
            <Target size={14} className="text-cyan-400" />
          </div>
          <div className="my-2">
            <div className="text-2xl font-black font-mono text-cyan-400">
              {data?.pcr != null ? data.pcr.toFixed(2) : '—'}
            </div>
            <div className={`text-xs font-semibold ${pcrSentiment.color}`}>
              {pcrSentiment.text}
            </div>
          </div>
          <div className="text-[10px] text-slate-500">
            Ratio of Put OI to Call OI
          </div>
        </div>

        {/* Max Pain Card */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs text-slate-400 uppercase font-semibold">
            <span>Max Pain Strike</span>
            <Target size={14} className="text-purple-400" />
          </div>
          <div className="my-2">
            <div className="text-2xl font-black font-mono text-purple-400">
              {data?.max_pain || '—'}
            </div>
            <div className="text-xs text-slate-400">
              Option Sellers Minimum Payout
            </div>
          </div>
          <div className="text-[10px] text-slate-500">
            Strike where option writers lose least
          </div>
        </div>

        {/* Call Wall (Resistance) */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs text-rose-400 uppercase font-semibold">
            <span>Call Wall (Resistance)</span>
            <Shield size={14} className="text-rose-400" />
          </div>
          <div className="my-2">
            <div className="text-2xl font-black font-mono text-rose-400">
              {data?.call_wall ? `${data.call_wall} CE` : '—'}
            </div>
            <div className="text-xs text-slate-400">
              Max Call Open Interest Strike
            </div>
          </div>
          <div className="text-[10px] text-slate-500">
            Major ceiling level for upside
          </div>
        </div>

        {/* Put Wall (Support) */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs text-emerald-400 uppercase font-semibold">
            <span>Put Wall (Support)</span>
            <Shield size={14} className="text-emerald-400" />
          </div>
          <div className="my-2">
            <div className="text-2xl font-black font-mono text-emerald-400">
              {data?.put_wall ? `${data.put_wall} PE` : '—'}
            </div>
            <div className="text-xs text-slate-400">
              Max Put Open Interest Strike
            </div>
          </div>
          <div className="text-[10px] text-slate-500">
            Major floor level for downside
          </div>
        </div>
      </div>

      {/* Dual OI Bar Chart by Strike */}
      <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
            Strike-wise Call OI vs Put OI Distribution
          </h3>
          <div className="flex items-center gap-4 text-xs font-semibold">
            <span className="flex items-center gap-1.5 text-rose-400">
              <span className="w-3 h-3 rounded-sm bg-rose-500 inline-block" />
              Call OI (Resistance)
            </span>
            <span className="flex items-center gap-1.5 text-emerald-400">
              <span className="w-3 h-3 rounded-sm bg-emerald-500 inline-block" />
              Put OI (Support)
            </span>
          </div>
        </div>

        <div className="space-y-2">
          {(!data?.strikes || data.strikes.length === 0) ? (
            <div className="py-8 text-center text-slate-500 text-xs">
              Loading strike-wise OI statistics...
            </div>
          ) : (
            data.strikes.map((s) => {
              const cePct = Math.round((s.ceOi / maxStrikeOi) * 100);
              const pePct = Math.round((s.peOi / maxStrikeOi) * 100);
              const isMaxPain = s.strike === data.max_pain;

              return (
                <div key={s.strike} className="flex items-center gap-2 text-xs font-mono">
                  {/* Left: Call OI Bar (aligned right towards strike) */}
                  <div className="min-w-0 flex-1 flex items-center justify-end gap-1.5">
                    <span className="text-[10px] text-slate-400 num-tabular">
                      {(s.ceOi / 1000).toFixed(0)}k
                    </span>
                    <div className="min-w-0 flex-1 max-w-[12rem] bg-slate-800 rounded-sm h-3.5 flex justify-end overflow-hidden">
                      <div
                        className="bg-rose-500 h-full rounded-sm transition-all duration-300"
                        style={{ width: `${cePct}%` }}
                      />
                    </div>
                  </div>

                  {/* Center: Strike badge */}
                  <div
                    className={`w-16 sm:w-20 py-0.5 rounded text-center font-bold text-[11px] ${
                      isMaxPain
                        ? 'bg-purple-600 text-white'
                        : 'bg-slate-800 text-slate-200 border border-slate-700'
                    }`}
                  >
                    {s.strike}
                  </div>

                  {/* Right: Put OI Bar (aligned left away from strike) */}
                  <div className="min-w-0 flex-1 flex items-center justify-start gap-1.5">
                    <div className="min-w-0 flex-1 max-w-[12rem] bg-slate-800 rounded-sm h-3.5 flex justify-start overflow-hidden">
                      <div
                        className="bg-emerald-500 h-full rounded-sm transition-all duration-300"
                        style={{ width: `${pePct}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-slate-400 num-tabular">
                      {(s.peOi / 1000).toFixed(0)}k
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
