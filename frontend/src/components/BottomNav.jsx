import React from 'react';
import { Activity, Layers, Calendar, LineChart } from 'lucide-react';

const ITEMS = [
  { id: 'terminal', label: 'Terminal', icon: Activity },
  { id: 'oi', label: 'Analysis', icon: Layers },
  { id: 'pnl', label: 'Journal', icon: Calendar },
  { id: 'payoff', label: 'Strategy', icon: LineChart },
];

/** Phone-only tab bar fixed to the bottom of the screen (thumb reach). */
export default function BottomNav({ activeTab, setActiveTab, positionsCount = 0 }) {
  return (
    <nav
      className="md:hidden fixed bottom-0 inset-x-0 z-40 bg-white/95 backdrop-blur border-t border-slate-200 shadow-[0_-4px_16px_-8px_rgba(15,23,42,0.25)]"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      aria-label="Main navigation"
    >
      <ul className="grid grid-cols-4">
        {ITEMS.map(({ id, label, icon: Icon }) => {
          const active = activeTab === id;
          return (
            <li key={id}>
              <button
                onClick={() => {
                  setActiveTab(id);
                  window.scrollTo({ top: 0, behavior: 'smooth' });
                }}
                className={`w-full flex flex-col items-center justify-center gap-0.5 py-2 min-h-[56px] text-[10px] font-semibold transition-colors ${
                  active ? 'text-cyan-700' : 'text-slate-400'
                }`}
                aria-current={active ? 'page' : undefined}
              >
                <span className="relative">
                  <Icon size={20} />
                  {id === 'terminal' && positionsCount > 0 && (
                    <span className="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 px-1 rounded-full bg-cyan-600 text-white text-[9px] font-bold flex items-center justify-center">
                      {positionsCount}
                    </span>
                  )}
                </span>
                <span>{label}</span>
                {active && <span className="absolute top-0 h-0.5 w-8 rounded-full bg-cyan-600" />}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
