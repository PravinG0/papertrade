import React, { useState } from 'react';
import { Zap, Shield, ArrowUpRight, ArrowDownRight, Flame } from 'lucide-react';
import sound from '../utils/audio';

export default function QuickScalperBar({
  selectedIndex = 'NIFTY',
  spotPrice = 25000,
  onPlaceOrder = () => {},
}) {
  const lotSize = selectedIndex === 'BANKNIFTY' ? 15 : selectedIndex === 'SENSEX' ? 10 : 25;
  const strikeStep = selectedIndex === 'BANKNIFTY' || selectedIndex === 'SENSEX' ? 100 : 50;
  const atmStrike = Math.round(spotPrice / strikeStep) * strikeStep;

  const [slPoints, setSlPoints] = useState(15);
  const [targetPoints, setTargetPoints] = useState(30);
  const [loadingAction, setLoadingAction] = useState(null);

  // Approximate ATM premiums for rapid scalp display
  const ceEstLtp = Math.round(Math.max(40, 110 + (spotPrice - atmStrike) * 0.5) * 10) / 10;
  const peEstLtp = Math.round(Math.max(40, 110 - (spotPrice - atmStrike) * 0.5) * 10) / 10;

  const handleQuickScalp = async (optionType, lots, actionKey) => {
    setLoadingAction(actionKey);
    const estLtp = optionType === 'CE' ? ceEstLtp : peEstLtp;
    const sl = slPoints > 0 ? Math.max(1, Math.round((estLtp - slPoints) * 10) / 10) : null;
    const tgt = targetPoints > 0 ? Math.round((estLtp + targetPoints) * 10) / 10 : null;

    try {
      await onPlaceOrder({
        symbol: `${selectedIndex}${atmStrike}${optionType}`,
        underlying: selectedIndex,
        strike: atmStrike,
        option_type: optionType,
        side: 'BUY',
        order_type: 'MARKET',
        lots,
        quantity: lots * lotSize,
        current_ltp: estLtp,
        price: estLtp,
        stop_loss: sl,
        target: tgt,
      });
      sound.playOrderFill();
    } finally {
      setLoadingAction(null);
    }
  };

  return (
    <div className="bg-[#ffffff] border border-slate-800/90 rounded-xl p-2.5 shadow-lg select-none">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2 pb-2 border-b border-slate-800/60">
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-5 rounded bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400">
            <Flame size={12} />
          </div>
          <span className="text-[11px] font-bold text-ink uppercase tracking-wider">
            1-Click Scalper Dock
          </span>
          <span className="px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 text-[10px] font-mono">
            ATM {atmStrike}
          </span>
        </div>

        {/* SL & Target Presets */}
        <div className="flex flex-wrap items-center gap-2 text-[10px]">
          <div className="flex items-center gap-1 bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
            <Shield size={10} className="text-rose-400" />
            <span className="text-slate-400">SL:</span>
            {[10, 15, 20].map((pts) => (
              <button
                key={pts}
                onClick={() => setSlPoints(pts)}
                className={`px-1 py-0.2 rounded font-mono font-bold transition-colors ${
                  slPoints === pts
                    ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                    : 'text-slate-400 hover:text-ink'
                }`}
              >
                {pts}p
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1 bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
            <span className="text-emerald-400 font-bold">🎯</span>
            <span className="text-slate-400">TGT:</span>
            {[20, 30, 50].map((pts) => (
              <button
                key={pts}
                onClick={() => setTargetPoints(pts)}
                className={`px-1 py-0.2 rounded font-mono font-bold transition-colors ${
                  targetPoints === pts
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                    : 'text-slate-400 hover:text-ink'
                }`}
              >
                {pts}p
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Scalp Triggers (ATM Call on Left, ATM Put on Right) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {/* ATM CALL SCALPER */}
        <div className="bg-emerald-950/20 border border-emerald-900/40 rounded-lg p-2 flex items-center justify-between gap-2">
          <div className="flex flex-col">
            <div className="flex items-center gap-1 text-[11px] font-bold text-emerald-400">
              <ArrowUpRight size={13} />
              <span>{atmStrike} CE</span>
            </div>
            <span className="text-[10px] font-mono text-slate-300 num-tabular">
              ₹{ceEstLtp.toFixed(1)}
            </span>
          </div>

          <div className="flex items-center gap-1">
            {[1, 2, 5].map((lots) => (
              <button
                key={lots}
                onClick={() => handleQuickScalp('CE', lots, `CE_${lots}`)}
                disabled={loadingAction !== null}
                className="min-h-[40px] sm:min-h-0 px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 active:scale-95 text-white font-mono font-bold text-[10px] shadow transition-all disabled:opacity-50"
                title={`Buy ${lots} Lot (${lots * lotSize} Qty) of ${atmStrike} CE with SL ${slPoints}pts`}
              >
                {loadingAction === `CE_${lots}` ? '...' : `+${lots}L`}
              </button>
            ))}
          </div>
        </div>

        {/* ATM PUT SCALPER */}
        <div className="bg-rose-950/20 border border-rose-900/40 rounded-lg p-2 flex items-center justify-between gap-2">
          <div className="flex flex-col">
            <div className="flex items-center gap-1 text-[11px] font-bold text-rose-400">
              <ArrowDownRight size={13} />
              <span>{atmStrike} PE</span>
            </div>
            <span className="text-[10px] font-mono text-slate-300 num-tabular">
              ₹{peEstLtp.toFixed(1)}
            </span>
          </div>

          <div className="flex items-center gap-1">
            {[1, 2, 5].map((lots) => (
              <button
                key={lots}
                onClick={() => handleQuickScalp('PE', lots, `PE_${lots}`)}
                disabled={loadingAction !== null}
                className="min-h-[40px] sm:min-h-0 px-2 py-1 rounded bg-rose-600 hover:bg-rose-500 active:scale-95 text-white font-mono font-bold text-[10px] shadow transition-all disabled:opacity-50"
                title={`Buy ${lots} Lot (${lots * lotSize} Qty) of ${atmStrike} PE with SL ${slPoints}pts`}
              >
                {loadingAction === `PE_${lots}` ? '...' : `+${lots}L`}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
