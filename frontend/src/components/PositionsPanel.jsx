import React, { useState } from 'react';
import {
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Shield,
  Save,
  LogOut,
  AlertOctagon,
  Check,
} from 'lucide-react';

export default function PositionsPanel({
  positions = [],
  closedPositions = [],
  portfolio = {},
  onExitPosition = () => {},
  onExitAllPositions = () => {},
  onUpdateStopLoss = () => {},
}) {
  const [editingSl, setEditingSl] = useState({});
  const [savingSl, setSavingSl] = useState({});
  const [exitingId, setExitingId] = useState(null);
  const [exitingAll, setExitingAll] = useState(false);
  const [showClosed, setShowClosed] = useState(false);

  const unrealizedPnl = portfolio?.unrealized_pnl ?? positions.reduce((acc, p) => acc + (p.pnl || p.unrealized_pnl || 0), 0);
  const marginUsed = portfolio?.margin_used ?? positions.reduce((acc, p) => acc + (p.invested_amount || p.margin || 0), 0);

  const handleSaveSl = async (id) => {
    const newSl = editingSl[id];
    if (newSl === undefined || newSl === '') return;
    setSavingSl((prev) => ({ ...prev, [id]: true }));
    try {
      await onUpdateStopLoss(id, newSl);
      setEditingSl((prev) => {
        const copy = { ...prev };
        delete copy[id];
        return copy;
      });
    } finally {
      setSavingSl((prev) => ({ ...prev, [id]: false }));
    }
  };

  const handleExit = async (id) => {
    setExitingId(id);
    try {
      await onExitPosition(id);
    } finally {
      setExitingId(null);
    }
  };

  const handleExitAll = async () => {
    if (positions.length === 0) return;
    if (!window.confirm('Are you sure you want to exit all open positions at market price?')) return;
    setExitingAll(true);
    try {
      await onExitAllPositions();
    } finally {
      setExitingAll(false);
    }
  };

  return (
    <div className="bg-[#ffffff] border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-full">
      {/* Header Bar */}
      <div className="p-3 bg-[#f4f6fa] border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-cyan-400" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-ink">
            {showClosed ? 'Recent Closed Positions' : `Active Positions (${positions.length})`}
          </h3>
        </div>

        <button
          type="button"
          onClick={() => setShowClosed((closed) => !closed)}
          className="px-2 py-1 text-xs font-semibold text-cyan-700 hover:underline"
        >
          {showClosed ? 'Show open positions' : 'Show closed positions'}
        </button>
        {!showClosed && positions.length > 0 && (
          <button
            onClick={handleExitAll}
            disabled={exitingAll}
            className="px-2.5 py-1 rounded bg-rose-600/80 hover:bg-rose-600 text-white text-xs font-semibold flex items-center gap-1 transition-all disabled:opacity-50"
          >
            <AlertOctagon size={13} />
            <span>{exitingAll ? 'Exiting All...' : 'Exit All'}</span>
          </button>
        )}
      </div>

      {showClosed ? (
        <div className="flex-1 overflow-auto">
          {closedPositions.length === 0 ? (
            <p className="p-4 text-sm text-slate-500">No closed positions yet.</p>
          ) : (
            <table className="w-full min-w-[520px] text-left text-xs">
              <thead className="bg-slate-100 text-slate-600">
                <tr>
                  <th className="p-2">Instrument</th>
                  <th className="p-2">Entry (₹)</th>
                  <th className="p-2">Exit (₹)</th>
                  <th className="p-2">Net P&amp;L (₹)</th>
                  <th className="p-2">Exit reason</th>
                  <th className="p-2">Closed at (IST)</th>
                </tr>
              </thead>
              <tbody>
                {closedPositions.map((trade) => (
                  <tr key={trade.id} className="border-b border-slate-200">
                    <td className="p-2 font-semibold">{trade.symbol}</td>
                    <td className="p-2">{trade.entry_price?.toFixed(2)}</td>
                    <td className="p-2">{trade.exit_price?.toFixed(2)}</td>
                    <td className={trade.realized_pnl < 0 ? 'p-2 text-rose-700' : 'p-2 text-emerald-700'}>
                      {trade.realized_pnl?.toFixed(2)}
                    </td>
                    <td className="p-2">{trade.exit_reason?.replaceAll('_', ' ') || '—'}</td>
                    <td className="p-2 whitespace-nowrap">{trade.closed_at?.replace('T', ' ').slice(0, 19)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
      <div className="flex-1 overflow-x-auto overflow-y-auto">
        <table className="w-full min-w-[560px] border-collapse text-xs select-none">
          <thead>
            <tr className="bg-slate-950/80 text-[10px] uppercase font-mono text-slate-400 border-b border-slate-800">
              <th className="py-2 px-3 text-left">Instrument</th>
              <th className="py-2 px-2 text-center">Type</th>
              <th className="py-2 px-2 text-right">Lots</th>
              <th className="py-2 px-2 text-right">Qty</th>
              <th className="py-2 px-2 text-right">Entry (₹)</th>
              <th className="py-2 px-2 text-right">LTP (₹)</th>
              <th className="py-2 px-3 text-right">P&L (₹)</th>
              <th className="py-2 px-3 text-center">Trailing SL</th>
              <th className="py-2 px-3 text-center">Action</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
            {positions.length === 0 ? (
              <tr>
                <td colSpan="9" className="py-10 text-center text-slate-500 font-sans">
                  <p className="font-semibold text-slate-300">No open positions yet</p>
                  <p className="text-xs mt-1">Tap BUY on a price in the option chain to open one. It will appear here with live profit/loss.</p>
                </td>
              </tr>
            ) : (
              positions.map((pos) => {
                const id = pos.id || pos.position_id;
                const pnl = pos.unrealized_pnl ?? pos.pnl ?? 0;
                const isProfit = Number(pnl) >= 0;
                const optType = pos.option_type || (pos.symbol?.includes('CE') ? 'CE' : 'PE');
                const isCe = optType === 'CE';
                const liveLtp = pos.live_price ?? pos.ltp ?? pos.entry_price;
                const currentSl = editingSl[id] !== undefined ? editingSl[id] : (pos.stop_loss || '');

                return (
                  <tr key={id} className="hover:bg-slate-800/40 transition-colors">
                    {/* Instrument */}
                    <td className="py-2 px-3 text-left">
                      <span className="font-bold text-ink">
                        {pos.option_symbol || pos.symbol || 'NIFTY Option'}
                      </span>
                      <div className="text-[10px] text-slate-500 font-sans">
                        Strike: {pos.strike || '—'}
                      </div>
                    </td>

                    {/* Type CE / PE */}
                    <td className="py-2 px-2 text-center">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          isCe
                            ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                            : 'bg-rose-950 text-rose-400 border border-rose-800'
                        }`}
                      >
                        {optType}
                      </span>
                    </td>

                    {/* Lots */}
                    <td className="py-2 px-2 text-right text-slate-300">
                      {pos.lots || Math.max(1, Math.round((pos.quantity || 25) / 25))}
                    </td>

                    {/* Qty */}
                    <td className="py-2 px-2 text-right text-slate-300">
                      {pos.quantity || pos.qty || 25}
                    </td>

                    {/* Entry Price */}
                    <td className="py-2 px-2 text-right text-slate-300 num-tabular">
                      ₹{Number(pos.entry_price || 0).toFixed(2)}
                    </td>

                    {/* Live LTP */}
                    <td className="py-2 px-2 text-right font-bold text-ink num-tabular">
                      ₹{Number(liveLtp).toFixed(2)}
                    </td>

                    {/* Current P&L */}
                    <td className="py-2 px-3 text-right num-tabular">
                      <span className={`font-bold ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {isProfit ? '+' : ''}₹{Number(pnl).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                      <div className={`text-[10px] ${isProfit ? 'text-emerald-500' : 'text-rose-500'}`}>
                        {pos.pnl_percent != null ? `${Number(pos.pnl_percent).toFixed(2)}%` : ''}
                      </div>
                    </td>

                    {/* Trailing Stop Loss Input */}
                    <td className="py-2 px-3 text-center">
                      <div className="flex items-center justify-center gap-1 font-sans">
                        <input
                          type="number"
                          step="0.5"
                          value={currentSl}
                          onChange={(e) =>
                            setEditingSl((prev) => ({ ...prev, [id]: e.target.value }))
                          }
                          placeholder="SL Price"
                          className="w-16 px-1.5 py-0.5 bg-slate-900 border border-slate-700 rounded text-slate-200 text-xs font-mono focus:outline-none focus:border-cyan-500"
                        />
                        {editingSl[id] !== undefined && (
                          <button
                            onClick={() => handleSaveSl(id)}
                            disabled={savingSl[id]}
                            className="p-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white transition-colors"
                            title="Save Stop-Loss"
                          >
                            <Check size={12} />
                          </button>
                        )}
                      </div>
                    </td>

                    {/* Exit Button */}
                    <td className="py-2 px-3 text-center font-sans">
                      <button
                        onClick={() => handleExit(id)}
                        disabled={exitingId === id}
                        className="px-2 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center gap-1 mx-auto transition-colors disabled:opacity-50"
                      >
                        <LogOut size={11} />
                        <span>{exitingId === id ? 'Exiting...' : 'Exit'}</span>
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      )}

      {/* Bottom Summary Bar */}
      <div className="p-2.5 bg-[#f4f6fa] border-t border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-4 font-mono">
          <div>
            <span className="text-slate-500 font-sans uppercase text-[10px] mr-1">Total Margin Used:</span>
            <span className="font-bold text-slate-200 num-tabular">
              ₹{Number(marginUsed).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>

          <div>
            <span className="text-slate-500 font-sans uppercase text-[10px] mr-1">Unrealized P&L:</span>
            <span
              className={`font-bold num-tabular ${
                unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {unrealizedPnl >= 0 ? '+' : ''}₹{Number(unrealizedPnl).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>

        {!showClosed && positions.length > 0 && (
          <button
            onClick={handleExitAll}
            disabled={exitingAll}
            className="px-3 py-1 rounded bg-rose-600/80 hover:bg-rose-600 text-white font-semibold transition-all text-xs"
          >
            Exit All Positions
          </button>
        )}
      </div>
    </div>
  );
}
