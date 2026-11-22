import React, { useState } from 'react';
import { X, MousePointerClick, Wallet, Brain, Eye } from 'lucide-react';

const KEY = 'tl_guide_dismissed_v1';

function readDismissed() {
  try {
    return localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
}

/** First-visit "how it works" card. Dismiss once and it stays away. */
export default function WelcomeGuide({ onOpenDebate = () => {}, marketOpen = true }) {
  const [hidden, setHidden] = useState(readDismissed);
  if (hidden) return null;

  const close = () => {
    try {
      localStorage.setItem(KEY, '1');
    } catch {}
    setHidden(true);
  };

  const steps = [
    { icon: MousePointerClick, title: '1. Pick a contract', text: 'Choose an index and expiry, then tap BUY next to a price in the option chain.' },
    { icon: Wallet, title: '2. Place the order', text: 'Set lots, and optionally a stop-loss and target. You trade with ₹10,00,000 of virtual money.' },
    { icon: Eye, title: '3. Watch it', text: 'Your trade appears under Positions with live profit/loss and closes itself at stop-loss or target.' },
  ];

  return (
    <div className="mb-3 rounded-2xl border border-cyan-900/60 bg-gradient-to-r from-cyan-950/50 via-slate-900/70 to-indigo-950/40 p-4 relative">
      <button
        onClick={close}
        aria-label="Dismiss guide"
        className="absolute top-3 right-3 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800"
      >
        <X size={16} />
      </button>

      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pr-8">
        <h2 className="text-sm font-bold text-white">Welcome to The TradeLab</h2>
        <p className="text-xs text-slate-400">
          Practice index-options trading with live Angel One prices. No real money involved.
        </p>
      </div>

      {!marketOpen && (
        <p className="mt-2 text-xs text-amber-300 bg-amber-950/40 border border-amber-800/50 rounded-lg px-3 py-1.5 inline-block">
          The market is closed right now. Trades can be opened Mon–Fri, 09:15–15:15 IST. Prices shown are the last traded ones.
        </p>
      )}

      <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2.5">
        {steps.map(({ icon: Icon, title, text }) => (
          <div key={title} className="flex gap-3 rounded-xl bg-slate-950/60 border border-slate-800 p-3">
            <div className="w-8 h-8 shrink-0 rounded-lg bg-cyan-600/15 text-cyan-300 flex items-center justify-center">
              <Icon size={16} />
            </div>
            <div>
              <p className="text-xs font-bold text-slate-100">{title}</p>
              <p className="text-[11px] leading-relaxed text-slate-400 mt-0.5">{text}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          onClick={() => {
            onOpenDebate();
            close();
          }}
          className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 text-white text-xs font-bold flex items-center gap-1.5 hover:from-purple-500 hover:to-indigo-500"
        >
          <Brain size={13} />
          Try the AI Debate (auto-trading)
        </button>
        <button onClick={close} className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold">
          Got it, hide this
        </button>
      </div>
    </div>
  );
}
