import React, { useState, useMemo } from 'react';
import { Calculator, X, ShieldAlert, CheckCircle, ArrowRight, DollarSign, Percent } from 'lucide-react';

export default function PositionSizeModal({
  availableCapital = 1000000,
  selectedIndex = 'NIFTY',
  onClose = () => {},
  onApplyToOrder = () => {},
}) {
  const [indexSymbol, setIndexSymbol] = useState(selectedIndex);
  const [riskPercent, setRiskPercent] = useState(1.0); // 1%
  const [entryPrice, setEntryPrice] = useState(120.0);
  const [stopLossPrice, setStopLossPrice] = useState(100.0);
  const [targetPrice, setTargetPrice] = useState(160.0);

  const lotSize = indexSymbol === 'BANKNIFTY' ? 15 : indexSymbol === 'SENSEX' ? 10 : 25;

  const calculations = useMemo(() => {
    const maxRiskInr = (availableCapital * riskPercent) / 100;
    const pointRisk = Math.max(0.1, entryPrice - stopLossPrice);
    const pointReward = Math.max(0, targetPrice - entryPrice);

    const riskPerLot = pointRisk * lotSize;
    const maxLotsAllowed = Math.max(1, Math.floor(maxRiskInr / riskPerLot));
    const totalQuantity = maxLotsAllowed * lotSize;

    const actualRiskInr = pointRisk * totalQuantity;
    const actualRewardInr = pointReward * totalQuantity;
    const totalCapitalRequired = entryPrice * totalQuantity;

    const rrRatio = pointRisk > 0 ? (pointReward / pointRisk).toFixed(2) : 'N/A';

    return {
      maxRiskInr,
      pointRisk,
      pointReward,
      riskPerLot,
      maxLotsAllowed,
      totalQuantity,
      actualRiskInr,
      actualRewardInr,
      totalCapitalRequired,
      rrRatio,
      lotSize,
    };
  }, [availableCapital, riskPercent, entryPrice, stopLossPrice, targetPrice, lotSize]);

  const handleApply = () => {
    onApplyToOrder({
      symbol: indexSymbol,
      lots: calculations.maxLotsAllowed,
      price: entryPrice,
      stopLoss: stopLossPrice,
      target: targetPrice,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-xs p-4 animate-fade-in select-none">
      <div className="bg-[#0f172a] border border-slate-800 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col font-sans">
        {/* Header */}
        <div className="p-4 bg-[#080c14] border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-cyan-600/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
              <Calculator size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">Position Size & Risk Calculator</h3>
              <p className="text-[11px] text-slate-400">TradeLab Capital Protection Tool</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Form Inputs */}
        <div className="p-5 space-y-4 text-xs font-medium text-slate-300">
          {/* Index & Capital */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Underlying Index</label>
              <select
                value={indexSymbol}
                onChange={(e) => setIndexSymbol(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-white font-bold focus:outline-none focus:border-cyan-500"
              >
                <option value="NIFTY">NIFTY 50 (Lot 25)</option>
                <option value="BANKNIFTY">BANK NIFTY (Lot 15)</option>
                <option value="FINNIFTY">FINNIFTY (Lot 25)</option>
                <option value="SENSEX">SENSEX (Lot 10)</option>
              </select>
            </div>

            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Available Capital (₹)</label>
              <input
                type="text"
                disabled
                value={`₹${availableCapital.toLocaleString('en-IN')}`}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-slate-400 font-mono font-bold cursor-not-allowed"
              />
            </div>
          </div>

          {/* Risk % Slider */}
          <div className="bg-slate-900/60 p-3 rounded-xl border border-slate-800 space-y-2">
            <div className="flex justify-between items-center text-xs">
              <span className="text-slate-400">Max Risk per Trade</span>
              <span className="text-cyan-400 font-mono font-bold">{riskPercent}% (₹{calculations.maxRiskInr.toLocaleString('en-IN')})</span>
            </div>
            <input
              type="range"
              min="0.5"
              max="5.0"
              step="0.5"
              value={riskPercent}
              onChange={(e) => setRiskPercent(parseFloat(e.target.value))}
              className="w-full accent-cyan-500 cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-slate-500 font-mono">
              <span>0.5% (Safe)</span>
              <span>1.0% (Standard)</span>
              <span>2.0% (Aggressive)</span>
              <span>5.0% (High Risk)</span>
            </div>
          </div>

          {/* Price Levels: Entry, SL, Target */}
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Entry Premium (₹)</label>
              <input
                type="number"
                step="0.5"
                value={entryPrice}
                onChange={(e) => setEntryPrice(Math.max(1, parseFloat(e.target.value) || 0))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-white font-mono font-bold focus:outline-none focus:border-cyan-500"
              />
            </div>

            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Stop Loss (₹)</label>
              <input
                type="number"
                step="0.5"
                value={stopLossPrice}
                onChange={(e) => setStopLossPrice(Math.max(0, parseFloat(e.target.value) || 0))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-rose-400 font-mono font-bold focus:outline-none focus:border-rose-500"
              />
            </div>

            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Target Price (₹)</label>
              <input
                type="number"
                step="0.5"
                value={targetPrice}
                onChange={(e) => setTargetPrice(Math.max(0, parseFloat(e.target.value) || 0))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-emerald-400 font-mono font-bold focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          {/* Result Card */}
          <div className="bg-gradient-to-br from-slate-900 to-cyan-950/40 p-4 rounded-xl border border-cyan-800/50 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-[10px] uppercase font-bold text-slate-400 block">Recommended Position Size</span>
                <span className="text-xl font-bold font-mono text-cyan-300">
                  {calculations.maxLotsAllowed} Lots <span className="text-xs text-slate-400">({calculations.totalQuantity} Units)</span>
                </span>
              </div>
              <div className="text-right">
                <span className="text-[10px] uppercase font-bold text-slate-400 block">Capital Required</span>
                <span className="text-sm font-bold font-mono text-white">
                  ₹{calculations.totalCapitalRequired.toLocaleString('en-IN')}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-800 text-[11px] font-mono">
              <div>
                <span className="text-slate-500 block">Total Risk</span>
                <span className="text-rose-400 font-bold">₹{calculations.actualRiskInr.toLocaleString('en-IN')}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Total Target</span>
                <span className="text-emerald-400 font-bold">₹{calculations.actualRewardInr.toLocaleString('en-IN')}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Risk : Reward</span>
                <span className="text-cyan-300 font-bold">1 : {calculations.rrRatio}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="p-4 bg-[#080c14] border-t border-slate-800 flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleApply}
            className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold flex items-center gap-1.5 shadow-lg shadow-cyan-900/40 transition-all"
          >
            <span>Apply {calculations.maxLotsAllowed} Lots to Ticket</span>
            <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
