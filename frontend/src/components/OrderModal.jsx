import React, { useState } from 'react';
import {
  X,
  ArrowUpRight,
  ArrowDownRight,
  Shield,
  Target,
  Plus,
  Minus,
  CheckCircle,
  AlertCircle,
} from 'lucide-react';

export default function OrderModal({
  orderData = null,
  availableCash = 1000000,
  onClose = () => {},
  onSubmitOrder = () => {},
}) {
  if (!orderData) return null;

  const {
    symbol = 'NIFTY',
    strike = 23500,
    optionType = 'CE',
    side = 'BUY',
    ltp = 100,
    bid = 99.5,
    ask = 100.5,
    lotSize = symbol === 'BANKNIFTY' ? 15 : 25,
  } = orderData;

  const [orderType, setOrderType] = useState('MARKET'); // MARKET | LIMIT | SL
  const [lots, setLots] = useState(1);
  const [limitPrice, setLimitPrice] = useState(side === 'BUY' ? ask : bid);
  const [targetPrice, setTargetPrice] = useState('');
  const [stopLossPrice, setStopLossPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const totalQty = lots * lotSize;
  const executionPrice = orderType === 'MARKET' ? ltp : (Number(limitPrice) || ltp);
  const estimatedMargin = Math.round(totalQty * executionPrice * 100) / 100;
  const hasSufficientMargin = availableCash >= estimatedMargin;

  const handleLotsChange = (delta) => {
    setLots((prev) => Math.max(1, Math.min(50, prev + delta)));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    if (orderType !== 'MARKET' && (!limitPrice || Number(limitPrice) <= 0)) {
      setError('Please provide a valid limit price.');
      return;
    }

    if (!hasSufficientMargin) {
      setError('Insufficient virtual capital margin available.');
      return;
    }

    setSubmitting(true);
    try {
      await onSubmitOrder({
        symbol: `${symbol} ${strike} ${optionType}`,
        index_symbol: symbol,
        strike,
        option_type: optionType,
        side,
        order_type: orderType,
        lots,
        quantity: totalQty,
        price: orderType === 'MARKET' ? ltp : Number(limitPrice),
        target: targetPrice ? Number(targetPrice) : null,
        stop_loss: stopLossPrice ? Number(stopLossPrice) : null,
      });
      onClose();
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to place order');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fadeIn">
      <div className="bg-[#0f172a] border border-slate-700 w-full max-w-md max-h-[92vh] flex flex-col rounded-2xl overflow-hidden shadow-2xl">
        {/* Top Header */}
        <div
          className={`p-4 flex items-center justify-between border-b ${
            side === 'BUY'
              ? 'bg-emerald-950/60 border-emerald-800 text-emerald-300'
              : 'bg-rose-950/60 border-rose-800 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-2.5">
            <div
              className={`w-7 h-7 rounded-lg flex items-center justify-center text-white ${
                side === 'BUY' ? 'bg-emerald-600' : 'bg-rose-600'
              }`}
            >
              {side === 'BUY' ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-bold text-sm text-white">
                  {side} {symbol} {strike} {optionType}
                </span>
                <span className="text-[10px] uppercase font-bold px-1.5 py-0.2 rounded bg-black/40 text-slate-300">
                  {lotSize} Qty / Lot
                </span>
              </div>
              <div className="text-xs font-mono text-slate-300">
                LTP: <strong className="text-white">₹{Number(ltp).toFixed(2)}</strong>
              </div>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-slate-800/80 text-slate-400 hover:text-white transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal Body Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4 overflow-y-auto flex-1">
          {error && (
            <div className="p-2.5 rounded-lg bg-rose-950/80 border border-rose-700 text-rose-300 text-xs flex items-center gap-2">
              <AlertCircle size={14} className="flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Order Type Tabs */}
          <div>
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block mb-1.5">
              Order Execution Type
            </label>
            <div className="grid grid-cols-3 gap-2">
              {['MARKET', 'LIMIT', 'SL'].map((type) => (
                <button
                  type="button"
                  key={type}
                  onClick={() => setOrderType(type)}
                  className={`py-1.5 text-xs font-bold rounded-lg border transition-all ${
                    orderType === type
                      ? 'bg-cyan-600 border-cyan-500 text-white shadow-md'
                      : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>

          {/* Lot Stepper */}
          <div>
            <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1.5">
              <span>Lot Size</span>
              <span className="text-cyan-400 font-mono">Total: {totalQty} Units</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleLotsChange(-1)}
                className="w-10 h-10 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 flex items-center justify-center text-slate-200 font-bold text-lg active:scale-95 transition-all"
              >
                <Minus size={16} />
              </button>

              <input
                type="number"
                min="1"
                max="50"
                value={lots}
                onChange={(e) => setLots(Math.max(1, parseInt(e.target.value) || 1))}
                className="flex-1 h-10 bg-slate-900 border border-slate-700 rounded-xl text-center font-mono font-bold text-white text-sm focus:outline-none focus:border-cyan-500"
              />

              <button
                type="button"
                onClick={() => handleLotsChange(1)}
                className="w-10 h-10 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 flex items-center justify-center text-slate-200 font-bold text-lg active:scale-95 transition-all"
              >
                <Plus size={16} />
              </button>
            </div>
          </div>

          {/* Price Input (if not MARKET) */}
          {orderType !== 'MARKET' && (
            <div>
              <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block mb-1.5">
                {orderType === 'LIMIT' ? 'Limit Price (₹)' : 'Trigger / SL Limit Price (₹)'}
              </label>
              <input
                type="number"
                step="0.05"
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)}
                className="w-full h-10 px-3 bg-slate-900 border border-slate-700 rounded-xl font-mono text-sm text-white focus:outline-none focus:border-cyan-500"
                placeholder="Enter price..."
                required
              />
            </div>
          )}

          {/* Target & Stop Loss Inputs */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-emerald-400 block mb-1">
                Target Price (₹)
              </label>
              <input
                type="number"
                step="0.5"
                value={targetPrice}
                onChange={(e) => setTargetPrice(e.target.value)}
                placeholder="Optional Target"
                className="w-full h-9 px-2.5 bg-slate-900 border border-slate-700 rounded-lg font-mono text-xs text-white focus:outline-none focus:border-emerald-500"
              />
            </div>

            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-rose-400 block mb-1">
                Stop Loss (₹)
              </label>
              <input
                type="number"
                step="0.5"
                value={stopLossPrice}
                onChange={(e) => setStopLossPrice(e.target.value)}
                placeholder="Optional SL"
                className="w-full h-9 px-2.5 bg-slate-900 border border-slate-700 rounded-lg font-mono text-xs text-white focus:outline-none focus:border-rose-500"
              />
            </div>
          </div>

          {/* Margin Summary */}
          <div className="p-3 rounded-xl bg-slate-900/90 border border-slate-800 space-y-1.5 text-xs">
            <div className="flex items-center justify-between text-slate-400">
              <span>Required Margin:</span>
              <span className="font-mono font-bold text-white num-tabular">
                ₹{estimatedMargin.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>
            </div>

            <div className="flex items-center justify-between text-slate-400">
              <span>Available Margin:</span>
              <span className={`font-mono font-bold num-tabular ${hasSufficientMargin ? 'text-slate-300' : 'text-rose-400'}`}>
                ₹{Number(availableCash).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          {/* Confirm Button */}
          <button
            type="submit"
            disabled={submitting || !hasSufficientMargin}
            className={`w-full py-3 rounded-xl font-bold text-sm flex items-center justify-center gap-2 shadow-lg transition-all active:scale-[0.99] disabled:opacity-50 ${
              side === 'BUY'
                ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/40'
                : 'bg-rose-600 hover:bg-rose-500 text-white shadow-rose-900/40'
            }`}
          >
            <CheckCircle size={16} />
            <span>
              {submitting
                ? 'Placing Order...'
                : `Place ${side} Order • ₹${estimatedMargin.toLocaleString('en-IN')}`}
            </span>
          </button>
        </form>
      </div>
    </div>
  );
}
