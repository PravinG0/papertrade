import React, { useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  RotateCcw,
  Radio,
  PlayCircle,
  Wallet,
  Activity,
  Layers,
  Calendar,
  Sparkles,
  Calculator,
  Keyboard,
  Volume2,
  VolumeX,
} from 'lucide-react';
import sound from '../utils/audio';

export default function Header({
  indices = {},
  portfolio = {},
  replayState = {},
  activeTab = 'terminal',
  setActiveTab = () => {},
  onResetPortfolio = () => {},
  onOpenReplay = () => {},
  onOpenCalculator = () => {},
  onOpenShortcuts = () => {},
}) {
  const [isMuted, setIsMuted] = useState(sound.isMuted());
  const toggleSound = () => setIsMuted(sound.toggleMute());
  const isReplay = replayState?.is_active || false;
  const initialCapital = portfolio?.initial_capital || 1000000;
  const capital = portfolio?.capital ?? initialCapital;
  const realizedPnl = portfolio?.realized_pnl || 0;
  const unrealizedPnl = portfolio?.unrealized_pnl || 0;
  const netPnl = realizedPnl + unrealizedPnl;

  const renderTicker = (symbol, label, defaultLtp) => {
    const item = indices[symbol] || {
      ltp: defaultLtp,
      change: 0,
      change_pct: 0,
    };
    const ltp = item.ltp ?? defaultLtp;
    const change = item.change ?? 0;
    const changePct = item.change_pct ?? (item.percent_change ?? 0);
    const isUp = change >= 0;

    return (
      <div className="flex items-center gap-2 px-3 py-1 bg-slate-900/80 rounded-lg border border-slate-800/80 text-xs">
        <span className="font-semibold text-slate-300 tracking-wide">{label}</span>
        <span className="font-mono font-bold text-slate-100 num-tabular">
          ₹{Number(ltp).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
        <span
          className={`flex items-center gap-0.5 text-[11px] font-mono font-medium px-1.5 py-0.2 rounded ${
            isUp ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800/50' : 'bg-rose-950/80 text-rose-400 border border-rose-800/50'
          }`}
        >
          {isUp ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
          <span>{isUp ? '+' : ''}{Number(change).toFixed(2)}</span>
          <span>({isUp ? '+' : ''}{Number(changePct).toFixed(2)}%)</span>
        </span>
      </div>
    );
  };

  return (
    <header className="bg-[#080c14] border-b border-slate-800 sticky top-0 z-40 select-none">
      {/* Top Main Bar */}
      <div className="px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        {/* Brand & Mode */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-cyan-600 via-blue-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-900/30">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-black text-sm tracking-wider text-white uppercase font-sans">
                  The TradeLab
                </span>
                <span className="text-[10px] uppercase font-bold tracking-widest px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800/60">
                  Paper Sim
                </span>
              </div>
              <p className="text-[10px] text-slate-400 tracking-tight font-medium">
                Institutional Paper Trading Engine
              </p>
            </div>
          </div>

          {/* Mode Pill */}
          <div className="hidden sm:flex items-center">
            {isReplay ? (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-950/70 border border-amber-500/50 text-amber-300 text-xs font-semibold animate-pulse">
                <PlayCircle size={14} className="text-amber-400" />
                <span>REPLAY MODE ({replayState.current_date || 'Historical'})</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 text-xs font-semibold">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                <span>LIVE FEED</span>
              </div>
            )}
          </div>
        </div>

        {/* Center Live Indices Ribbon */}
        <div className="hidden lg:flex items-center gap-2.5">
          {renderTicker('NIFTY', 'NIFTY 50', 23500)}
          {renderTicker('BANKNIFTY', 'BANK NIFTY', 50200)}
          {renderTicker('SENSEX', 'SENSEX', 77500)}
        </div>

        {/* Right Wallet & Actions */}
        <div className="flex items-center gap-3">
          {/* Virtual Wallet */}
          <div className="flex items-center gap-3 px-3 py-1.5 bg-slate-900/90 rounded-xl border border-slate-800 shadow-inner">
            <div className="flex items-center gap-1.5 text-slate-400 text-xs">
              <Wallet size={14} className="text-cyan-400" />
              <div className="flex flex-col">
                <span className="text-[9px] uppercase tracking-wider text-slate-400 font-semibold">Virtual Capital</span>
                <span className="font-mono font-bold text-white text-xs num-tabular">
                  ₹{Number(capital).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>
            </div>

            <div className="h-6 w-px bg-slate-800" />

            <div className="flex flex-col text-right">
              <span className="text-[9px] uppercase tracking-wider text-slate-400 font-semibold">Net P&L</span>
              <span
                className={`font-mono font-bold text-xs num-tabular ${
                  netPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {netPnl >= 0 ? '+' : ''}₹{Number(netPnl).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          {/* Calculator Tool Button */}
          <button
            onClick={onOpenCalculator}
            className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors border border-slate-700 flex items-center gap-1.5 text-xs font-medium"
            title="Position Size & Risk Calculator"
          >
            <Calculator size={13} className="text-cyan-400" />
            <span className="hidden sm:inline">Calc</span>
          </button>

          {/* Shortcuts Guide Button */}
          <button
            onClick={onOpenShortcuts}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors border border-slate-700 flex items-center justify-center text-xs"
            title="Keyboard Shortcuts (?)"
          >
            <Keyboard size={14} />
          </button>

          {/* Sound Mute/Unmute Toggle Button */}
          <button
            onClick={toggleSound}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors border border-slate-700 flex items-center justify-center text-xs"
            title={isMuted ? "Unmute Audio Feedback" : "Mute Audio Feedback"}
          >
            {isMuted ? <VolumeX size={14} className="text-slate-500" /> : <Volume2 size={14} className="text-cyan-400" />}
          </button>

          {/* Reset Portfolio Button */}
          <button
            onClick={onResetPortfolio}
            className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors border border-slate-700 flex items-center gap-1.5 text-xs font-medium"
            title="Reset Portfolio to ₹10,00,000"
          >
            <RotateCcw size={13} className="text-amber-400" />
            <span className="hidden sm:inline">Reset</span>
          </button>
        </div>
      </div>

      {/* Sub-bar: Navigation Tabs & Mobile Ticker */}
      <div className="px-4 py-1.5 bg-slate-950/90 border-t border-slate-800/80 flex items-center justify-between gap-2 overflow-x-auto">
        <div className="flex items-center gap-1 text-xs">
          <button
            onClick={() => setActiveTab('terminal')}
            className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
              activeTab === 'terminal'
                ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-900/40'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <Activity size={14} />
            <span>Terminal</span>
          </button>

          <button
            onClick={() => setActiveTab('oi')}
            className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
              activeTab === 'oi'
                ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-900/40'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <Layers size={14} />
            <span>OI & Greeks</span>
          </button>

          <button
            onClick={() => setActiveTab('pnl')}
            className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
              activeTab === 'pnl'
                ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-900/40'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <Calendar size={14} />
            <span>P&L Journal</span>
          </button>

          <button
            onClick={() => setActiveTab('payoff')}
            className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
              activeTab === 'payoff'
                ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-900/40'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <Layers size={14} />
            <span>Strategy Payoff</span>
          </button>
        </div>

        {/* Mobile / Compact Mode Replay Toggle */}
        <div className="flex items-center gap-2">
          {!isReplay ? (
            <button
              onClick={onOpenReplay}
              className="px-2.5 py-1 rounded bg-amber-950/70 hover:bg-amber-900/80 border border-amber-600/50 text-amber-300 text-xs font-semibold flex items-center gap-1.5 transition-colors"
            >
              <PlayCircle size={13} />
              <span>Historical Replay</span>
            </button>
          ) : (
            <span className="text-[11px] font-mono text-amber-400 bg-amber-950/50 px-2 py-0.5 rounded border border-amber-800">
              Replay Active: {replayState.current_time || '09:15:00'}
            </span>
          )}
        </div>
      </div>
    </header>
  );
}
