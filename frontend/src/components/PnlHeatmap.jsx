import React, { useState, useEffect, useMemo } from 'react';
import {
  Calendar as CalendarIcon,
  TrendingUp,
  TrendingDown,
  Award,
  DollarSign,
  Download,
  Activity,
  ShieldAlert,
  Percent,
  Receipt,
  FileSpreadsheet,
  RotateCcw,
} from 'lucide-react';
import { getPnlCalendar, getTradeHistory, getTradingState } from '../api';

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

export default function PnlHeatmap() {
  const [calendarData, setCalendarData] = useState({});
  const [tradeLogs, setTradeLogs] = useState([]);
  const [tradingState, setTradingState] = useState(null);
  const [loading, setLoading] = useState(false);
  const [currentDate, setCurrentDate] = useState(new Date());
  const [selectedDay, setSelectedDay] = useState(null);

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();

  const loadData = async () => {
    setLoading(true);
    try {
      const [calRes, histRes, stateRes] = await Promise.allSettled([
        getPnlCalendar(),
        getTradeHistory(),
        getTradingState(),
      ]);

      if (calRes.status === 'fulfilled' && calRes.value.data) {
        const raw = calRes.value.data?.days || calRes.value.data || {};
        if (Array.isArray(raw)) {
          const map = {};
          raw.forEach((d) => {
            if (d.date) {
              map[d.date] = {
                net_pnl: d.pnl,
                trades: d.trades_count,
                win_rate: d.trades_count > 0 ? (d.wins / d.trades_count) * 100 : 0,
              };
            }
          });
          setCalendarData(map);
        } else {
          setCalendarData(raw);
        }
      }

      if (histRes.status === 'fulfilled' && histRes.value.data) {
        setTradeLogs(histRes.value.data?.trades || histRes.value.data || []);
      }

      if (stateRes.status === 'fulfilled' && stateRes.value.data) {
        setTradingState(stateRes.value.data);
      }
    } catch (err) {
      console.warn('Error loading journal analytics:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [year, month]);

  // Days in month calculation for grid
  const calendarGrid = useMemo(() => {
    const firstDayIndex = new Date(year, month, 1).getDay(); // 0 is Sun
    const totalDays = new Date(year, month + 1, 0).getDate();
    const cells = [];

    for (let i = 0; i < firstDayIndex; i++) {
      cells.push(null);
    }

    for (let day = 1; day <= totalDays; day++) {
      const dateKey = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const dayData = calendarData[dateKey] || null;
      cells.push({ day, dateKey, data: dayData });
    }

    return cells;
  }, [year, month, calendarData]);

  // Advanced Performance Metrics
  const metrics = useMemo(() => {
    const backendStats = tradingState?.statistics || {};
    const wallet = tradingState?.wallet || {};

    let totalGrossProfit = 0;
    let totalGrossLoss = 0;
    let totalCharges = wallet.total_charges || 0;
    let totalNetPnl = wallet.realized_pnl || 0;

    tradeLogs.forEach((t) => {
      const net = Number(t.realized_pnl || 0);
      if (net > 0) totalGrossProfit += net;
      else if (net < 0) totalGrossLoss += Math.abs(net);
      if (t.total_charges) totalCharges += Number(t.total_charges);
    });

    const totalTrades = tradeLogs.length || backendStats.total_trades || 0;
    const wins = tradeLogs.filter((t) => Number(t.realized_pnl) > 0).length || backendStats.winning_trades || 0;
    const losses = totalTrades - wins;
    const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : 0;
    const profitFactor = totalGrossLoss > 0 ? (totalGrossProfit / totalGrossLoss).toFixed(2) : (totalGrossProfit > 0 ? '∞' : '1.00');
    const avgWin = wins > 0 ? (totalGrossProfit / wins).toFixed(0) : 0;
    const avgLoss = losses > 0 ? (totalGrossLoss / losses).toFixed(0) : 0;

    return {
      netPnl: totalNetPnl,
      grossProfit: totalGrossProfit,
      grossLoss: totalGrossLoss,
      totalCharges,
      totalTrades,
      wins,
      losses,
      winRate,
      profitFactor,
      avgWin,
      avgLoss,
      maxDrawdown: backendStats.max_drawdown || 0,
      maxDrawdownPct: backendStats.max_drawdown_pct || 0,
    };
  }, [tradeLogs, tradingState]);

  // Cumulative Equity Curve Points
  const equityCurve = useMemo(() => {
    const initial = 1000000;
    if (tradeLogs.length === 0) {
      return [{ x: 0, y: initial, label: 'Start' }, { x: 1, y: initial, label: 'Now' }];
    }
    const sorted = [...tradeLogs].sort((a, b) => new Date(a.exit_time || 0) - new Date(b.exit_time || 0));
    let running = initial;
    const pts = [{ x: 0, y: initial, label: 'Start' }];

    sorted.forEach((t, i) => {
      running += Number(t.realized_pnl || 0);
      pts.push({
        x: i + 1,
        y: running,
        label: t.symbol || `T${i + 1}`,
      });
    });

    return pts;
  }, [tradeLogs]);

  // Filtered trades for selected day or all
  const displayedTrades = useMemo(() => {
    if (!selectedDay) return tradeLogs;
    return tradeLogs.filter((t) => t.exit_time && t.exit_time.startsWith(selectedDay));
  }, [tradeLogs, selectedDay]);

  return (
    <div className="space-y-4">
      {/* 1. Header Toolbar */}
      <div className="bg-[#0f172a] border border-slate-800 rounded-xl p-4 shadow-xl flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-600 to-teal-800 flex items-center justify-center text-white shadow-lg">
            <CalendarIcon size={20} />
          </div>
          <div>
            <h1 className="text-base font-extrabold text-white tracking-wide flex items-center gap-2">
              <span>Performance Analytics & Trade Journal</span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-950 text-cyan-300 border border-cyan-800">
                PRO JOURNAL
              </span>
            </h1>
            <p className="text-xs text-slate-400">
              Track consistency, equity curve trajectory, statutory charges, and daily win rates
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={loadData}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700"
            title="Refresh Journal"
          >
            <RotateCcw size={14} className={loading ? 'animate-spin text-cyan-400' : ''} />
          </button>

          <a
            href="/api/trading/export"
            download="tradelab_trade_journal.csv"
            className="px-3.5 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold flex items-center gap-1.5 transition-colors shadow-md"
            title="Download full CSV Journal"
          >
            <Download size={14} />
            <span>Export CSV</span>
          </a>

          <div className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs font-bold text-slate-200 font-mono">
            {MONTH_NAMES[month]} {year}
          </div>
        </div>
      </div>

      {/* 2. Key Performance Indicators */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* Net Realized P&L */}
        <div className="p-3.5 rounded-xl bg-[#0f172a] border border-slate-800 shadow">
          <div className="text-[11px] text-slate-400 uppercase font-semibold flex items-center justify-between">
            <span>Net Realized P&L</span>
            <DollarSign size={13} className="text-emerald-400" />
          </div>
          <div
            className={`text-xl font-black font-mono my-1 num-tabular ${
              metrics.netPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
            }`}
          >
            {metrics.netPnl >= 0 ? '+' : ''}₹{metrics.netPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
          <div className="text-[10px] text-slate-500">After charges & taxes</div>
        </div>

        {/* Trade Win Rate */}
        <div className="p-3.5 rounded-xl bg-[#0f172a] border border-slate-800 shadow">
          <div className="text-[11px] text-slate-400 uppercase font-semibold flex items-center justify-between">
            <span>Win Rate</span>
            <Award size={13} className="text-cyan-400" />
          </div>
          <div className="text-xl font-black font-mono my-1 text-cyan-400">
            {metrics.winRate}%
          </div>
          <div className="text-[10px] text-slate-500">
            {metrics.wins} Wins / {metrics.losses} Losses
          </div>
        </div>

        {/* Profit Factor */}
        <div className="p-3.5 rounded-xl bg-[#0f172a] border border-slate-800 shadow">
          <div className="text-[11px] text-slate-400 uppercase font-semibold flex items-center justify-between">
            <span>Profit Factor</span>
            <TrendingUp size={13} className="text-amber-400" />
          </div>
          <div className="text-xl font-black font-mono my-1 text-amber-400">
            {metrics.profitFactor}
          </div>
          <div className="text-[10px] text-slate-500">Gross Wins / Gross Losses</div>
        </div>

        {/* Avg Win vs Avg Loss */}
        <div className="p-3.5 rounded-xl bg-[#0f172a] border border-slate-800 shadow">
          <div className="text-[11px] text-slate-400 uppercase font-semibold flex items-center justify-between">
            <span>Avg Win / Loss</span>
            <Percent size={13} className="text-violet-400" />
          </div>
          <div className="text-sm font-bold font-mono my-1 text-slate-200">
            <span className="text-emerald-400">+₹{metrics.avgWin}</span> / <span className="text-rose-400">-₹{metrics.avgLoss}</span>
          </div>
          <div className="text-[10px] text-slate-500">Average per trade</div>
        </div>

        {/* Max Drawdown */}
        <div className="p-3.5 rounded-xl bg-[#0f172a] border border-slate-800 shadow">
          <div className="text-[11px] text-slate-400 uppercase font-semibold flex items-center justify-between">
            <span>Max Drawdown</span>
            <ShieldAlert size={13} className="text-rose-400" />
          </div>
          <div className="text-xl font-black font-mono my-1 text-rose-400">
            -₹{Number(metrics.maxDrawdown).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </div>
          <div className="text-[10px] text-slate-500">Peak drop: {metrics.maxDrawdownPct}%</div>
        </div>

        {/* Charges & Taxes */}
        <div className="p-3.5 rounded-xl bg-[#0f172a] border border-slate-800 shadow">
          <div className="text-[11px] text-slate-400 uppercase font-semibold flex items-center justify-between">
            <span>Total Charges</span>
            <Receipt size={13} className="text-slate-400" />
          </div>
          <div className="text-xl font-black font-mono my-1 text-slate-300">
            ₹{Number(metrics.totalCharges).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
          <div className="text-[10px] text-slate-500">STT, Brokerage & GST</div>
        </div>
      </div>

      {/* 3. Cumulative Equity Curve & Calendar Heatmap Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
        {/* Left 7 cols: Calendar Heatmap */}
        <div className="lg:col-span-7 bg-[#0f172a] border border-slate-800 rounded-xl p-4 shadow-xl">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
              <CalendarIcon size={14} className="text-cyan-400" />
              <span>Daily Consistency Heatmap</span>
            </div>
            {selectedDay && (
              <button
                onClick={() => setSelectedDay(null)}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 text-[11px] font-semibold transition-colors"
              >
                Clear Day Filter ({selectedDay})
              </button>
            )}
          </div>

          <div className="grid grid-cols-7 gap-1.5 mb-1.5 text-center text-[10px] font-bold text-slate-500 uppercase tracking-wider">
            <span>Sun</span>
            <span>Mon</span>
            <span>Tue</span>
            <span>Wed</span>
            <span>Thu</span>
            <span>Fri</span>
            <span>Sat</span>
          </div>

          <div className="grid grid-cols-7 gap-1.5">
            {calendarGrid.map((cell, idx) => {
              if (!cell) {
                return (
                  <div
                    key={`empty-${idx}`}
                    className="h-16 rounded-lg bg-slate-950/20 border border-slate-850/20 opacity-30"
                  />
                );
              }

              const { day, dateKey, data } = cell;
              const hasData = data && data.net_pnl != null;
              const pnl = hasData ? Number(data.net_pnl) : 0;
              const isProfit = pnl > 0;
              const isLoss = pnl < 0;
              const isSelected = selectedDay === dateKey;

              let bgClass = 'bg-[#080c14] border-slate-800 text-slate-300';
              if (isProfit) bgClass = 'bg-emerald-950/40 border-emerald-600/60 text-emerald-200';
              else if (isLoss) bgClass = 'bg-rose-950/40 border-rose-600/60 text-rose-200';

              if (isSelected) bgClass += ' ring-2 ring-cyan-400';

              return (
                <div
                  key={dateKey}
                  onClick={() => setSelectedDay(isSelected ? null : dateKey)}
                  className={`h-16 p-1.5 rounded-lg border flex flex-col justify-between transition-all cursor-pointer hover:border-cyan-400 ${bgClass}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold font-mono">{day}</span>
                    {hasData && (
                      <span className="text-[8px] font-sans px-1 py-0.2 rounded bg-slate-900/90 text-slate-400">
                        {data.trades || 1}t
                      </span>
                    )}
                  </div>

                  {hasData ? (
                    <div className="text-right">
                      <div
                        className={`text-[11px] font-black font-mono num-tabular ${
                          isProfit ? 'text-emerald-400' : isLoss ? 'text-rose-400' : 'text-slate-400'
                        }`}
                      >
                        {isProfit ? '+' : ''}₹{Math.abs(pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                      </div>
                    </div>
                  ) : (
                    <div className="text-[9px] text-slate-600 text-right font-mono">-</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right 5 cols: Cumulative Equity Curve */}
        <div className="lg:col-span-5 bg-[#0f172a] border border-slate-800 rounded-xl p-4 shadow-xl flex flex-col">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
              <TrendingUp size={14} className="text-emerald-400" />
              <span>Cumulative Equity Curve</span>
            </div>
            <div className="text-[11px] font-mono text-cyan-300 font-bold">
              ₹{(equityCurve[equityCurve.length - 1]?.y || 1000000).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </div>
          </div>

          <div className="flex-1 w-full min-h-[190px] flex items-center justify-center relative">
            {/* Responsive SVG Curve */}
            <svg viewBox="0 0 400 160" className="w-full h-full overflow-visible">
              <defs>
                <linearGradient id="equityGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.4" />
                  <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Grid Lines */}
              <line x1="30" y1="20" x2="390" y2="20" stroke="#1e293b" strokeDasharray="3,3" />
              <line x1="30" y1="80" x2="390" y2="80" stroke="#1e293b" strokeDasharray="3,3" />
              <line x1="30" y1="140" x2="390" y2="140" stroke="#1e293b" strokeDasharray="3,3" />

              {/* Path generation */}
              {(() => {
                const minY = Math.min(...equityCurve.map((p) => p.y)) * 0.995;
                const maxY = Math.max(...equityCurve.map((p) => p.y)) * 1.005;
                const rangeY = Math.max(1, maxY - minY);
                const count = equityCurve.length;

                const points = equityCurve.map((pt, idx) => {
                  const x = 35 + (idx / Math.max(1, count - 1)) * 350;
                  const y = 140 - ((pt.y - minY) / rangeY) * 115;
                  return `${x.toFixed(1)},${y.toFixed(1)}`;
                });

                const polylineStr = points.join(' ');
                const firstX = points[0].split(',')[0];
                const lastX = points[points.length - 1].split(',')[0];
                const areaStr = `${firstX},140 ${polylineStr} ${lastX},140`;

                return (
                  <>
                    <polygon points={areaStr} fill="url(#equityGrad)" />
                    <polyline
                      fill="none"
                      stroke="#06b6d4"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      points={polylineStr}
                    />
                    {points.map((pt, i) => {
                      const [cx, cy] = pt.split(',');
                      return (
                        <circle
                          key={i}
                          cx={cx}
                          cy={cy}
                          r="3"
                          fill="#38bdf8"
                          stroke="#080c14"
                          strokeWidth="1.5"
                        />
                      );
                    })}
                  </>
                );
              })()}
            </svg>
          </div>

          <div className="flex items-center justify-between text-[10px] text-slate-500 font-mono pt-2 border-t border-slate-800">
            <span>Base: ₹10,00,000</span>
            <span>Total Trades: {tradeLogs.length}</span>
            <span className={metrics.netPnl >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
              {metrics.netPnl >= 0 ? '+' : ''}{((metrics.netPnl / 1000000) * 100).toFixed(2)}% ROI
            </span>
          </div>
        </div>
      </div>

      {/* 4. Closed Trades Log Table */}
      <div className="bg-[#0f172a] border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <div className="p-3 bg-[#080c14] border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileSpreadsheet size={15} className="text-cyan-400" />
            <h2 className="text-xs font-bold text-slate-200 uppercase tracking-wider">
              Executed Trade Journal ({displayedTrades.length})
            </h2>
            {selectedDay && (
              <span className="px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 text-[10px] font-mono">
                Filtered: {selectedDay}
              </span>
            )}
          </div>
        </div>

        <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
          {displayedTrades.length === 0 ? (
            <div className="p-8 text-center text-slate-500 text-xs">
              No executed trades recorded yet. Place orders on the Option Chain or Terminal to populate your journal.
            </div>
          ) : (
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-slate-900/90 text-slate-400 uppercase text-[10px] sticky top-0 border-b border-slate-800 select-none">
                <tr>
                  <th className="py-2.5 px-3">Contract</th>
                  <th className="py-2.5 px-3">Side</th>
                  <th className="py-2.5 px-3 text-right">Qty (Lots)</th>
                  <th className="py-2.5 px-3 text-right">Entry</th>
                  <th className="py-2.5 px-3 text-right">Exit</th>
                  <th className="py-2.5 px-3 text-right">Gross P&L</th>
                  <th className="py-2.5 px-3 text-right">Charges</th>
                  <th className="py-2.5 px-3 text-right">Net P&L</th>
                  <th className="py-2.5 px-3 text-right">Return</th>
                  <th className="py-2.5 px-3">Times (IST)</th>
                  <th className="py-2.5 px-3">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-850">
                {displayedTrades.map((t, idx) => {
                  const net = Number(t.realized_pnl || 0);
                  const gross = Number(t.gross_pnl || net);
                  const isProfit = net >= 0;

                  return (
                    <tr key={t.pos_id || idx} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-2 px-3 font-bold text-slate-200">
                        {t.symbol || `${t.underlying} ${t.strike} ${t.option_type}`}
                      </td>
                      <td className="py-2 px-3">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                            t.side === 'BUY'
                              ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                              : 'bg-rose-950 text-rose-300 border border-rose-800'
                          }`}
                        >
                          {t.side}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-right text-slate-300">
                        {t.quantity} ({t.lots}L)
                      </td>
                      <td className="py-2 px-3 text-right text-slate-300 font-semibold">
                        ₹{Number(t.entry_price).toFixed(2)}
                      </td>
                      <td className="py-2 px-3 text-right text-slate-300 font-semibold">
                        ₹{Number(t.exit_price).toFixed(2)}
                      </td>
                      <td
                        className={`py-2 px-3 text-right font-semibold ${
                          gross >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {gross >= 0 ? '+' : ''}₹{gross.toFixed(2)}
                      </td>
                      <td className="py-2 px-3 text-right text-slate-400">
                        -₹{Number(t.total_charges || t.charges?.total_charges || 0).toFixed(2)}
                      </td>
                      <td
                        className={`py-2 px-3 text-right font-bold ${
                          isProfit ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {isProfit ? '+' : ''}₹{net.toFixed(2)}
                      </td>
                      <td
                        className={`py-2 px-3 text-right font-semibold ${
                          isProfit ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {isProfit ? '+' : ''}{Number(t.pnl_pct || 0).toFixed(2)}%
                      </td>
                      <td className="py-2 px-3 text-[10px] text-slate-400">
                        <div>In: {t.entry_time?.split(' ')[1] || t.entry_time}</div>
                        <div>Out: {t.exit_time?.split(' ')[1] || t.exit_time}</div>
                      </td>
                      <td className="py-2 px-3 text-[10px]">
                        <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                          {t.exit_reason || 'MANUAL_EXIT'}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
