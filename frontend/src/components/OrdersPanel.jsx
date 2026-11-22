import React, { useState } from 'react';
import { Clock, XCircle, ArrowUpRight, ArrowDownRight, Layers } from 'lucide-react';

export default function OrdersPanel({
  orders = [],
  onCancelOrder = () => {},
}) {
  const [cancellingId, setCancellingId] = useState(null);

  const handleCancel = async (id) => {
    setCancellingId(id);
    try {
      await onCancelOrder(id);
    } finally {
      setCancellingId(null);
    }
  };

  return (
    <div className="bg-[#0f172a] border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-full">
      {/* Header Bar */}
      <div className="p-3 bg-[#080c14] border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock size={16} className="text-cyan-400" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-white">
            Pending Orders ({orders.length})
          </h3>
        </div>
      </div>

      {/* Orders Table */}
      <div className="flex-1 overflow-x-auto overflow-y-auto">
        <table className="w-full min-w-[560px] border-collapse text-xs select-none">
          <thead>
            <tr className="bg-slate-950/80 text-[10px] uppercase font-mono text-slate-400 border-b border-slate-800">
              <th className="py-2 px-3 text-left">Order ID</th>
              <th className="py-2 px-2 text-left">Time</th>
              <th className="py-2 px-2 text-center">Side</th>
              <th className="py-2 px-3 text-left">Instrument</th>
              <th className="py-2 px-2 text-right">Lots</th>
              <th className="py-2 px-2 text-right">Limit Price</th>
              <th className="py-2 px-2 text-right">Trigger SL</th>
              <th className="py-2 px-2 text-center">Status</th>
              <th className="py-2 px-3 text-center">Action</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
            {orders.length === 0 ? (
              <tr>
                <td colSpan="9" className="py-10 text-center text-slate-500 font-sans">
                  <p className="font-semibold text-slate-300">No pending orders</p>
                  <p className="text-xs mt-1">Limit and stop orders waiting for their price show up here.</p>
                </td>
              </tr>
            ) : (
              orders.map((ord) => {
                const id = ord.id || ord.order_id;
                const isBuy = (ord.side || ord.trade_type || 'BUY').toUpperCase() === 'BUY';
                const timeStr = ord.created_at || ord.timestamp || '—';

                return (
                  <tr key={id} className="hover:bg-slate-800/40 transition-colors">
                    {/* Order ID */}
                    <td className="py-2 px-3 text-left text-slate-400 font-mono">
                      #{String(id).slice(-6)}
                    </td>

                    {/* Time */}
                    <td className="py-2 px-2 text-left text-slate-400">
                      {typeof timeStr === 'string' && timeStr.includes('T')
                        ? timeStr.split('T')[1].slice(0, 8)
                        : timeStr}
                    </td>

                    {/* Side BUY / SELL */}
                    <td className="py-2 px-2 text-center font-sans">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          isBuy
                            ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                            : 'bg-rose-950 text-rose-400 border border-rose-800'
                        }`}
                      >
                        {isBuy ? 'BUY' : 'SELL'}
                      </span>
                    </td>

                    {/* Instrument */}
                    <td className="py-2 px-3 text-left">
                      <span className="font-bold text-white">
                        {ord.symbol || ord.option_symbol || 'Option'}
                      </span>
                      {ord.order_type && (
                        <span className="ml-1.5 text-[9px] uppercase px-1 py-0.2 rounded bg-slate-800 text-slate-400 font-sans">
                          {ord.order_type}
                        </span>
                      )}
                    </td>

                    {/* Lots */}
                    <td className="py-2 px-2 text-right text-slate-300">
                      {ord.lots || Math.max(1, Math.round((ord.quantity || 25) / 25))}
                    </td>

                    {/* Limit Price */}
                    <td className="py-2 px-2 text-right text-slate-300 num-tabular">
                      {ord.price != null && Number(ord.price) > 0 ? `₹${Number(ord.price).toFixed(2)}` : 'MKT'}
                    </td>

                    {/* Trigger SL */}
                    <td className="py-2 px-2 text-right text-amber-400 num-tabular">
                      {ord.stop_loss ? `₹${Number(ord.stop_loss).toFixed(2)}` : '—'}
                    </td>

                    {/* Status */}
                    <td className="py-2 px-2 text-center">
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-950/80 text-amber-300 border border-amber-800 font-sans">
                        {ord.status || 'PENDING'}
                      </span>
                    </td>

                    {/* Cancel Action */}
                    <td className="py-2 px-3 text-center font-sans">
                      <button
                        onClick={() => handleCancel(id)}
                        disabled={cancellingId === id}
                        className="px-2 py-1 rounded bg-slate-800 hover:bg-rose-900/60 text-slate-300 hover:text-rose-200 text-[10px] font-bold flex items-center justify-center gap-1 mx-auto transition-colors disabled:opacity-50 border border-slate-700 hover:border-rose-700"
                      >
                        <XCircle size={11} />
                        <span>{cancellingId === id ? 'Cancelling...' : 'Cancel'}</span>
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
