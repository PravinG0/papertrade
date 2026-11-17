import React from 'react';
import { Keyboard, X, Command } from 'lucide-react';

export default function ShortcutsModal({ onClose = () => {} }) {
  const shortcuts = [
    { key: 'Space', desc: 'Toggle Market Replay Play / Pause' },
    { key: '→', desc: 'Step Forward (+1 minute candle) in Replay' },
    { key: '←', desc: 'Step Backward (-1 minute candle) in Replay' },
    { key: '1 / 2 / 3 / 4', desc: 'Switch view tabs (Terminal, OI & Greeks, P&L, Strategy)' },
    { key: 'Shift + X', desc: 'Exit All Open Positions immediately' },
    { key: 'Esc', desc: 'Close any open modal or order ticket' },
    { key: '?', desc: 'Open this Keyboard Shortcuts cheat-sheet' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-xs p-4 animate-fade-in select-none">
      <div className="bg-[#0f172a] border border-slate-800 rounded-2xl w-full max-w-md shadow-2xl overflow-hidden flex flex-col font-sans">
        {/* Header */}
        <div className="p-4 bg-[#080c14] border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-cyan-600/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
              <Keyboard size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">Keyboard Shortcuts</h3>
              <p className="text-[11px] text-slate-400">TradeLab Pro Speed Navigation</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Shortcuts List */}
        <div className="p-4 divide-y divide-slate-800 text-xs">
          {shortcuts.map((item, idx) => (
            <div key={idx} className="py-2.5 flex items-center justify-between">
              <span className="text-slate-300 font-medium">{item.desc}</span>
              <kbd className="px-2 py-1 rounded bg-slate-900 border border-slate-700 text-cyan-300 font-mono font-bold text-[11px] shadow-sm">
                {item.key}
              </kbd>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="p-3 bg-[#080c14] border-t border-slate-800 text-center text-[11px] text-slate-500">
          Press <kbd className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-700 text-slate-300 font-mono">Esc</kbd> anytime to dismiss
        </div>
      </div>
    </div>
  );
}
