import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  Brain,
  TrendingUp,
  TrendingDown,
  Scale,
  Target,
  Shield,
  Zap,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Timer,
  Layers,
  History,
  Activity,
  ArrowUpCircle,
  ArrowDownCircle,
  MinusCircle,
  Sparkles,
  ChevronRight,
  ShoppingCart,
  Percent,
} from 'lucide-react';
import {
  runDebate,
  getLatestDebate,
  getDebateHistory,
  executeDebateVerdict,
  startScheduler,
  stopScheduler,
  getSchedulerStatus,
} from '../api';

function ConvictionTugOfWar({ bullScore = 0, bearScore = 0 }) {
  const bull = Number(bullScore) || 0;
  const bear = Number(bearScore) || 0;
  const total = bull + bear;

  const bullPct = total > 0 ? Math.round((bull / total) * 100) : 50;
  const bearPct = total > 0 ? 100 - bullPct : 50;

  const diff = bull - bear;
  let edgeText = 'Neutral Conviction Balance';
  let edgeColor = 'text-amber-400';

  if (diff >= 2) {
    edgeText = `Bull Dominance (+${diff.toFixed(1)} pts)`;
    edgeColor = 'text-emerald-400';
  } else if (diff <= -2) {
    edgeText = `Bear Dominance (+${Math.abs(diff).toFixed(1)} pts)`;
    edgeColor = 'text-rose-400';
  } else if (diff > 0) {
    edgeText = `Slight Bullish Tilt (${bull}/10)`;
    edgeColor = 'text-emerald-300';
  } else if (diff < 0) {
    edgeText = `Slight Bearish Tilt (${bear}/10)`;
    edgeColor = 'text-rose-300';
  }

  return (
    <div className="bg-[#ffffff]/90 backdrop-blur-md border border-slate-800/80 rounded-2xl p-4 sm:p-5 shadow-lg space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
            <Scale size={16} />
          </div>
          <div>
            <h3 className="text-xs sm:text-sm font-bold text-ink tracking-wide">
              Conviction Tug-of-War
            </h3>
            <p className="text-[10px] text-slate-400">
              Adversarial conviction balance between Bull & Bear quantitative models
            </p>
          </div>
        </div>

        <span className={`text-xs font-bold font-mono px-2.5 py-1 rounded-md bg-slate-900 border border-slate-800 ${edgeColor}`}>
          {edgeText}
        </span>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs font-mono font-bold tabular-nums">
          <div className="flex items-center gap-1.5 text-emerald-400">
            <span>🐂 Bull Agent</span>
            <span className="px-1.5 py-0.5 rounded bg-emerald-950/80 border border-emerald-800/60 text-[11px]">
              {bull.toFixed(1)}/10 ({bullPct}%)
            </span>
          </div>

          <div className="flex items-center gap-1.5 text-rose-400">
            <span className="px-1.5 py-0.5 rounded bg-rose-950/80 border border-rose-800/60 text-[11px]">
              ({bearPct}%) {bear.toFixed(1)}/10
            </span>
            <span>Bear Agent 🐻</span>
          </div>
        </div>

        <div className="relative h-3.5 bg-slate-950 rounded-full overflow-hidden p-0.5 border border-slate-800 flex shadow-inner">
          <div
            className="h-full bg-gradient-to-r from-emerald-600 to-emerald-400 rounded-l-full transition-all duration-700 ease-out"
            style={{ width: `${bullPct}%` }}
          />
          <div className="w-1 h-full bg-white/50 shadow-sm z-10 -ml-0.5" />
          <div
            className="h-full bg-gradient-to-l from-rose-600 to-rose-400 rounded-r-full transition-all duration-700 ease-out"
            style={{ width: `${bearPct}%` }}
          />
        </div>
      </div>
    </div>
  );
}

function MarketMatrixBar({ snapshot }) {
  if (!snapshot) return null;

  return (
    <div className="bg-[#f4f6fa]/90 border border-slate-800/90 rounded-xl p-3 text-xs overflow-x-auto">
      <div className="flex items-center justify-between gap-4 min-w-[760px]">
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 uppercase text-[10px] font-semibold">Spot</span>
          <span className="font-mono font-bold text-ink text-xs">₹{snapshot.spot_price?.toFixed(2)}</span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 uppercase text-[10px] font-semibold">EMA 20/50</span>
          <span className="font-mono font-medium text-cyan-300 text-xs">
            {snapshot.ema_20?.toFixed(1)} / {snapshot.ema_50?.toFixed(1)}
          </span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 uppercase text-[10px] font-semibold">VWAP</span>
          <span className="font-mono font-medium text-indigo-300 text-xs">₹{snapshot.vwap?.toFixed(1)}</span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 uppercase text-[10px] font-semibold">RSI (14)</span>
          <span className={`font-mono font-bold text-xs ${snapshot.rsi > 60 ? 'text-emerald-400' : snapshot.rsi < 40 ? 'text-rose-400' : 'text-slate-300'}`}>
            {snapshot.rsi?.toFixed(1)}
          </span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 uppercase text-[10px] font-semibold">PCR</span>
          <span className={`font-mono font-bold text-xs ${snapshot.pcr >= 1.0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {snapshot.pcr?.toFixed(2)}
          </span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 uppercase text-[10px] font-semibold">CPR</span>
          <span className="font-mono text-amber-400 text-[11px] font-bold">
            {snapshot.cpr_width_type === 'NARROW_TRENDING' ? '⚡ NARROW' : '↔ WIDE'}
          </span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 uppercase text-[10px] font-semibold">OI Walls</span>
          <span className="font-mono text-slate-300 text-[11px]">
            <span className="text-rose-400">C:{snapshot.call_oi_wall || '—'}</span> | <span className="text-emerald-400">P:{snapshot.put_oi_wall || '—'}</span>
          </span>
        </div>
      </div>
    </div>
  );
}

/** Shows what happened to a debate's trade: skipped, open, target hit, stop-loss hit ... */
function OutcomeBadge({ sess }) {
  const o = sess.outcome;
  if (!sess.executed) {
    return sess.skip_reason ? (
      <span className="text-[10px] text-amber-400 font-medium">⏭ Not traded: {sess.skip_reason}</span>
    ) : null;
  }
  const tag = sess.auto_executed ? 'auto' : 'manual';
  if (!o) {
    return <span className="text-[10px] text-cyan-400 font-medium">⚡ Trade executed ({tag})</span>;
  }
  const pnl = Number(o.pnl || 0);
  const isOpen = o.status === 'OPEN' || o.status === 'ACTIVE';
  const reason = isOpen
    ? 'OPEN'
    : o.exit_reason === 'TARGET_HIT'
    ? '🎯 TARGET HIT'
    : o.exit_reason === 'STOP_LOSS_HIT'
    ? '🛑 STOP-LOSS HIT'
    : (o.exit_reason || 'CLOSED').replace(/_/g, ' ');
  const fmt = (v) => (v === null || v === undefined ? '-' : Number(v).toFixed(2));
  return (
    <div className="mt-1 pt-1.5 border-t border-slate-800 space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-bold text-slate-200 truncate">{sess.exec_symbol || 'Trade'}</span>
        <span className="text-[10px] font-bold text-slate-300">{reason}</span>
      </div>
      <div className="flex items-center justify-between text-[10px] font-mono text-slate-400">
        <span>
          {fmt(o.entry_price)} → {isOpen ? fmt(o.ltp) : fmt(o.exit_price)}
        </span>
        <span className={`font-bold ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
          {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(0)}
        </span>
      </div>
      <div className="text-[9px] text-slate-500 font-mono">
        SL {fmt(o.stop_loss)} · TGT {fmt(o.target)} · {tag}
      </div>
    </div>
  );
}

export default function DebateArena({
  selectedIndex = 'NIFTY',
  onSelectIndex = () => {},
  onExecuteTrade = null,
  onTradeChanged = () => {},
}) {
  const { isAuthenticated } = useAuth();
  const [currentSymbol, setCurrentSymbol] = useState(selectedIndex || 'NIFTY');
  const [debate, setDebate] = useState(null);
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  // Auto-Debate Scheduler State
  const [schedulerRunning, setSchedulerRunning] = useState(false);
  const [schedulerInterval, setSchedulerInterval] = useState(5);
  const [autoExecute, setAutoExecute] = useState(false);
  const [nextRunTime, setNextRunTime] = useState(null);
  const [runCount, setRunCount] = useState(0);
  const [countdownText, setCountdownText] = useState('');
  const [schedulerLoading, setSchedulerLoading] = useState(false);

  const lastSessionRef = useRef(undefined);
  const [marketHoursOnly, setMarketHoursOnly] = useState(true);
  const [schedulerInfo, setSchedulerInfo] = useState({});

  // Sync internal symbol if parent prop changes
  useEffect(() => {
    if (selectedIndex && selectedIndex !== currentSymbol) {
      setCurrentSymbol(selectedIndex);
    }
  }, [selectedIndex]);

  // Load latest debate on mount or symbol change
  const fetchLatest = useCallback(async (sym) => {
    try {
      setLoading(true);
      setErrorMsg(null);
      const res = await getLatestDebate(sym);
      if (res.data) {
        setDebate(res.data);
      }
    } catch (err) {
      console.warn('No active debate found:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchHistoryList = useCallback(async () => {
    try {
      const res = await getDebateHistory(20);
      if (Array.isArray(res.data)) {
        setHistory(res.data);
      }
    } catch (err) {
      console.warn('Failed to fetch debate history:', err);
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) setDebate(null);
    fetchLatest(currentSymbol);
    fetchHistoryList();
  }, [currentSymbol, fetchLatest, fetchHistoryList, isAuthenticated]);

  // Sync scheduler status from backend
  const checkSchedulerStatus = useCallback(async () => {
    try {
      const res = await getSchedulerStatus();
      if (res.data) {
        const s = res.data;
        const isRun = Boolean(s.is_running);
        setSchedulerRunning(isRun);
        if (s.interval_minutes) setSchedulerInterval(s.interval_minutes);
        if (s.auto_execute !== undefined) setAutoExecute(Boolean(s.auto_execute));
        setNextRunTime(s.next_run || null);
        setRunCount(s.run_count || 0);
        if (s.market_hours_only !== undefined) setMarketHoursOnly(Boolean(s.market_hours_only));
        setSchedulerInfo({
          status_text: s.status_text,
          last_error: s.last_error,
          is_debating: s.is_debating,
          market_open: s.market_open,
        });

        // Refresh the debate view + history whenever the scheduler produced a NEW session
        // (also covers the very first run, which the old run-count check skipped)
        if (lastSessionRef.current !== undefined && s.last_session_id && s.last_session_id !== lastSessionRef.current) {
          fetchLatest(s.symbol || currentSymbol);
          fetchHistoryList();
        }
        lastSessionRef.current = s.last_session_id || null;
        return s;
      }
    } catch (err) {
      console.warn('Could not fetch scheduler status:', err);
    }
    return null;
  }, [currentSymbol, fetchLatest, fetchHistoryList]);

  // Initial scheduler query on mount
  useEffect(() => {
    checkSchedulerStatus();
  }, [checkSchedulerStatus]);

  // Periodic polling for scheduler heartbeat when active
  useEffect(() => {
    if (!schedulerRunning) return;
    const pollInterval = setInterval(() => {
      checkSchedulerStatus();
    }, 3500);
    return () => clearInterval(pollInterval);
  }, [schedulerRunning, checkSchedulerStatus]);

  // Keep history/outcomes fresh while the scheduler is on or the history panel is open
  useEffect(() => {
    if (!schedulerRunning && !showHistory) return;
    const t = setInterval(fetchHistoryList, 10000);
    return () => clearInterval(t);
  }, [schedulerRunning, showHistory, fetchHistoryList]);

  // 1-second Countdown Ticker
  useEffect(() => {
    if (!schedulerRunning || !nextRunTime) {
      setCountdownText('--:--');
      return;
    }

    const updateTicker = () => {
      const targetMs = new Date(nextRunTime).getTime();
      const nowMs = Date.now();
      const diffSec = Math.floor((targetMs - nowMs) / 1000);

      if (diffSec <= 0) {
        if (diffSec < -15) checkSchedulerStatus();
        setCountdownText(schedulerInfo.is_debating ? 'Debating...' : 'Starting...');
        return;
      }

      const mins = Math.floor(diffSec / 60);
      const secs = diffSec % 60;
      setCountdownText(`${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`);
    };

    updateTicker();
    const ticker = setInterval(updateTicker, 1000);
    return () => clearInterval(ticker);
  }, [schedulerRunning, nextRunTime, schedulerInfo.is_debating]);

  // Toggle Auto-Debate ON/OFF
  const handleToggleScheduler = async () => {
    setSchedulerLoading(true);
    setErrorMsg(null);
    try {
      if (schedulerRunning) {
        const res = await stopScheduler();
        if (res.data?.scheduler) {
          setSchedulerRunning(false);
          setNextRunTime(null);
        }
      } else {
        const res = await startScheduler({
          interval_minutes: Number(schedulerInterval),
          symbol: currentSymbol,
          auto_execute: Boolean(autoExecute),
          market_hours_only: marketHoursOnly,
        });
        if (res.data?.scheduler) {
          const s = res.data.scheduler;
          setSchedulerRunning(true);
          setNextRunTime(s.next_run);
          setRunCount(s.run_count || 0);
          lastSessionRef.current = s.last_session_id || null;
        }
      }
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || 'Failed to toggle scheduler';
      setErrorMsg(msg);
    } finally {
      setSchedulerLoading(false);
    }
  };

  // Change interval
  const handleIntervalChange = async (newVal) => {
    const val = Number(newVal);
    setSchedulerInterval(val);
    if (schedulerRunning) {
      setSchedulerLoading(true);
      try {
        const res = await startScheduler({
          interval_minutes: val,
          symbol: currentSymbol,
          auto_execute: Boolean(autoExecute),
          market_hours_only: marketHoursOnly,
        });
        if (res.data?.scheduler) {
          setNextRunTime(res.data.scheduler.next_run);
        }
      } catch (err) {
        console.warn('Failed to update scheduler interval:', err);
      } finally {
        setSchedulerLoading(false);
      }
    }
  };

  // Toggle auto execution of trades
  const handleAutoExecuteToggle = async () => {
    const nextVal = !autoExecute;
    setAutoExecute(nextVal);
    if (schedulerRunning) {
      setSchedulerLoading(true);
      try {
        const res = await startScheduler({
          interval_minutes: Number(schedulerInterval),
          symbol: currentSymbol,
          auto_execute: nextVal,
          market_hours_only: marketHoursOnly,
        });
        if (res.data?.scheduler) {
          setNextRunTime(res.data.scheduler.next_run);
        }
      } catch (err) {
        console.warn('Failed to update scheduler auto-execute mode:', err);
      } finally {
        setSchedulerLoading(false);
      }
    }
  };

  // Trigger Live AI Debate
  const handleTriggerDebate = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const res = await runDebate(currentSymbol);
      if (res.data) {
        setDebate(res.data);
        await fetchHistoryList();
      }
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || 'Failed to trigger debate';
      setErrorMsg(msg);
    } finally {
      setLoading(false);
    }
  };

  // 1-Click Judge Trade Execution
  const handleExecuteJudge = async () => {
    if (!debate) return;
    setExecuting(true);
    setErrorMsg(null);
    try {
      const res = await executeDebateVerdict(debate.id, { lots: 1 });
      if (res.data?.status === 'success') {
        setDebate((prev) =>
          prev
            ? { ...prev, executed: true, position_id: res.data.order?.position_id, exec_symbol: res.data.symbol }
            : prev
        );
        onTradeChanged(
          `Judge trade executed: ${res.data.symbol} @ ${res.data.entry_price} (SL ${res.data.stop_loss} / TGT ${res.data.target})`
        );
        await fetchHistoryList();
      }
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || 'Trade execution failed';
      setErrorMsg(msg);
    } finally {
      setExecuting(false);
    }
  };

  // Backing quick trade for Bull or Bear
  const handleBackThesis = async (optionType, strikeVal) => {
    if (!onExecuteTrade) return;
    const strikeNum = Number(strikeVal) || (currentSymbol === 'BANKNIFTY' ? 52000 : 24500);
    const entryP = optionType === 'CE' ? 125 : 120;
    const slP = entryP - 25;
    const tgtP = entryP + 38;

    try {
      await onExecuteTrade({
        symbol: `${currentSymbol}${Math.round(strikeNum)}${optionType}`,
        underlying: currentSymbol,
        strike: strikeNum,
        option_type: optionType,
        lots: 1,
        side: 'BUY',
        order_type: 'MARKET',
        price: 0,
        stop_loss_pct: 20,
        target_pct: 30,
      });
    } catch (err) {
      console.error('Quick trade failed:', err);
    }
  };

  const bull = debate?.bull || {};
  const bear = debate?.bear || {};
  const judge = debate?.judge || {};
  const snapshot = debate?.market_snapshot;
  const isBank = currentSymbol === 'BANKNIFTY';
  const lotSize = isBank ? 30 : currentSymbol === 'SENSEX' ? 20 : 65;

  const judgeVerdict = (judge.verdict || 'NO_TRADE').toUpperCase();
  const isBuyCE = judgeVerdict.includes('CE');
  const isBuyPE = judgeVerdict.includes('PE');
  const isNoTrade = !isBuyCE && !isBuyPE;

  return (
    <div className="space-y-4 max-w-7xl mx-auto pb-12">
      {/* ── AUTO-DEBATE SCHEDULER CONTROL BAR ── */}
      <div className="bg-[#ffffff]/90 backdrop-blur-md border border-slate-800 rounded-2xl p-3.5 sm:p-4 shadow-xl">
        <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-3 sm:gap-4">
          {/* Left: Auto-Debate Toggle, Active Badge & Interval Selector */}
          <div className="flex flex-wrap items-center gap-2.5 sm:gap-3">
            <button
              onClick={handleToggleScheduler}
              disabled={schedulerLoading}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl font-bold text-xs transition-all duration-200 shadow-md ${
                schedulerRunning
                  ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-950/50 ring-1 ring-emerald-400/40'
                  : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700/80'
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  schedulerRunning ? 'bg-emerald-300 animate-pulse' : 'bg-slate-500'
                }`}
              />
              <span>
                {schedulerLoading
                  ? 'Updating...'
                  : schedulerRunning
                  ? 'Auto-Debate: ON'
                  : 'Auto-Debate: OFF'}
              </span>
            </button>

            {/* Active / Standby Status Badge */}
            <div
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold ${
                schedulerRunning
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                  : 'bg-slate-900 text-slate-500 border border-slate-800'
              }`}
            >
              <Activity size={13} className={schedulerRunning ? 'animate-pulse' : ''} />
              <span>{schedulerRunning ? 'Active Schedule' : 'Standby'}</span>
            </div>

            {/* Interval Selector */}
            <div className="flex items-center gap-1.5 bg-slate-950 border border-slate-800 rounded-xl px-2.5 py-1 text-xs">
              <Clock size={13} className="text-cyan-400" />
              <span className="text-[11px] text-slate-400 font-medium">Interval:</span>
              <select
                value={schedulerInterval}
                onChange={(e) => handleIntervalChange(e.target.value)}
                disabled={schedulerLoading}
                className="bg-transparent text-ink font-mono font-bold text-xs focus:outline-none cursor-pointer"
              >
                <option value={3} className="bg-slate-900 text-ink">3m</option>
                <option value={5} className="bg-slate-900 text-ink">5m</option>
                <option value={10} className="bg-slate-900 text-ink">10m</option>
                <option value={15} className="bg-slate-900 text-ink">15m</option>
              </select>
            </div>
          </div>

          {/* Right: Countdown, Auto-Execute toggle & Stats Pill */}
          <div className="flex flex-wrap items-center gap-2.5 sm:gap-3">
            {/* Next Run Countdown Display */}
            {schedulerRunning && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-cyan-950/40 border border-cyan-800/60 font-mono text-xs">
                <Timer size={14} className="text-cyan-400" />
                <span className="text-slate-300">Next run in:</span>
                <span className="font-bold text-cyan-300 tracking-wider">
                  {countdownText || '--:--'}
                </span>
              </div>
            )}

            {/* Auto-Execute Toggle */}
            <label className="flex items-center gap-2 cursor-pointer select-none bg-slate-950 border border-slate-800 hover:border-slate-700 rounded-xl px-3 py-1.5 transition-colors">
              <input
                type="checkbox"
                checked={autoExecute}
                onChange={handleAutoExecuteToggle}
                disabled={schedulerLoading}
                className="w-3.5 h-3.5 rounded text-amber-500 focus:ring-0 focus:ring-offset-0 bg-slate-900 border-slate-700 cursor-pointer accent-amber-500"
              />
              <span className="text-xs text-slate-300 font-medium whitespace-nowrap">
                Auto-Execute Judge Trades
              </span>
              <span className="px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 text-[10px] font-bold font-mono">
                Confidence ≥ 70%
              </span>
            </label>

            {/* Market-hours-only toggle */}
            <label className="flex items-center gap-2 cursor-pointer select-none bg-slate-950 border border-slate-800 hover:border-slate-700 rounded-xl px-3 py-1.5 transition-colors">
              <input
                type="checkbox"
                checked={marketHoursOnly}
                onChange={() => {
                  const v = !marketHoursOnly;
                  setMarketHoursOnly(v);
                  if (schedulerRunning) {
                    startScheduler({
                      interval_minutes: Number(schedulerInterval),
                      symbol: currentSymbol,
                      auto_execute: Boolean(autoExecute),
                      market_hours_only: v,
                    })
                      .then((r) => r.data?.scheduler && setNextRunTime(r.data.scheduler.next_run))
                      .catch(() => {});
                  }
                }}
                className="w-3.5 h-3.5 rounded focus:ring-0 focus:ring-offset-0 bg-slate-900 border-slate-700 cursor-pointer accent-cyan-500"
              />
              <span className="text-xs text-slate-300 font-medium whitespace-nowrap">Market hours only</span>
            </label>

            {/* Stats Pill */}
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-xs font-mono">
              <Zap size={13} className="text-purple-400" />
              <span className="text-slate-400">Debates Run:</span>
              <span className="font-bold text-ink">{runCount}</span>
            </div>
          </div>
        </div>

        {schedulerRunning && (
          <div className="mt-3 pt-3 border-t border-slate-800/80 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
            <span className="text-slate-300">
              <span className="text-slate-500">Status: </span>
              {schedulerInfo.status_text || '—'}
            </span>
            {!schedulerInfo.market_open && marketHoursOnly && (
              <span className="text-amber-400">Market closed (09:15–15:30 IST, Mon–Fri) - debates resume at open</span>
            )}
            {schedulerInfo.last_error && (
              <span className="text-rose-400">Last error: {schedulerInfo.last_error}</span>
            )}
          </div>
        )}
      </div>

      {/* Top Studio Control Bar */}
      <div className="bg-[#ffffff]/90 backdrop-blur-md border border-slate-800 rounded-2xl p-4 sm:p-5 shadow-xl flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-gradient-to-tr from-purple-600 via-indigo-600 to-cyan-500 flex items-center justify-center shadow-lg shadow-purple-900/40 text-white">
            <Brain size={24} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base sm:text-lg font-black text-ink uppercase tracking-wider">
                AI Debate Studio
              </h2>
              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-purple-950/80 text-purple-300 border border-purple-800/60">
                GEMINI 3-AGENT SYSTEM
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Adversarial quantitative deliberation: Bull vs Bear judged by Institutional CRO
            </p>
          </div>
        </div>

        {/* Index Selector & Run Button */}
        <div className="flex flex-wrap items-center gap-2.5 w-full md:w-auto">
          {/* Symbol Toggle */}
          <div className="flex items-center bg-slate-950 border border-slate-800 rounded-xl p-1 text-xs">
            <button
              onClick={() => {
                setCurrentSymbol('NIFTY');
                onSelectIndex('NIFTY');
              }}
              className={`px-3 py-1.5 rounded-lg font-bold font-mono transition-all ${
                currentSymbol === 'NIFTY'
                  ? 'bg-cyan-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              NIFTY 50
            </button>
            <button
              onClick={() => {
                setCurrentSymbol('BANKNIFTY');
                onSelectIndex('BANKNIFTY');
              }}
              className={`px-3 py-1.5 rounded-lg font-bold font-mono transition-all ${
                currentSymbol === 'BANKNIFTY'
                  ? 'bg-cyan-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              BANK NIFTY
            </button>
          </div>

          {/* History Button */}
          <button
            onClick={() => setShowHistory((prev) => !prev)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-ink text-xs font-semibold transition-colors"
            title="Debate history"
          >
            <History size={14} className="text-cyan-400" />
            <span>History ({history.length})</span>
          </button>

          {/* Run AI Debate Button */}
          <button
            onClick={handleTriggerDebate}
            disabled={loading}
            className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl font-bold text-xs bg-gradient-to-r from-purple-600 hover:from-purple-500 to-indigo-600 hover:to-indigo-500 text-white shadow-lg shadow-purple-900/30 transition-all disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            <span>{loading ? 'Agents Deliberating...' : 'Run AI Debate'}</span>
          </button>
        </div>
      </div>

      {/* Error Message */}
      {errorMsg && (
        <div className="flex items-center gap-2 p-3 bg-rose-950/50 border border-rose-800/80 rounded-xl text-xs text-rose-200">
          <AlertTriangle size={15} className="text-rose-400 flex-shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* History Drawer / Panel */}
      {showHistory && (
        <div className="bg-[#ffffff]/95 border border-slate-800 rounded-2xl p-4 shadow-xl space-y-3">
          <div className="flex items-center justify-between border-b border-slate-800 pb-2">
            <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
              <History size={14} className="text-cyan-400" />
              <span>Debate Audit Trail</span>
            </h3>
            <button
              onClick={() => setShowHistory(false)}
              className="text-xs text-slate-400 hover:text-ink"
            >
              Close
            </button>
          </div>

          {history.length === 0 ? (
            <p className="text-xs text-slate-500 py-3 text-center">
              {isAuthenticated
                ? 'No past debates recorded yet.'
                : 'Sign in to keep a personal debate history. Debates you run while signed out are not saved.'}
            </p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 max-h-[32rem] overflow-y-auto pr-1">
              {history.map((sess) => {
                const isCE = sess.judge?.verdict?.includes('CE');
                const isPE = sess.judge?.verdict?.includes('PE');
                return (
                  <div
                    key={sess.id}
                    onClick={() => {
                      setDebate(sess);
                      setCurrentSymbol(sess.symbol);
                      setShowHistory(false);
                    }}
                    className="p-3 bg-slate-950/80 hover:bg-slate-900 border border-slate-800 hover:border-cyan-500/50 rounded-xl cursor-pointer transition-all space-y-1.5 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-bold text-slate-200">{sess.symbol}</span>
                      <span
                        className={`font-mono font-bold text-[10px] px-1.5 py-0.2 rounded ${
                          isCE
                            ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                            : isPE
                            ? 'bg-rose-950 text-rose-400 border border-rose-800'
                            : 'bg-amber-950 text-amber-400 border border-amber-800'
                        }`}
                      >
                        {sess.judge?.verdict || 'NO_TRADE'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-slate-400">
                      <span>Spot: ₹{sess.spot_price?.toFixed(1)}</span>
                      <span>{sess.timestamp}</span>
                    </div>
                    <OutcomeBadge sess={sess} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Main Debate Display */}
      {loading && !debate ? (
        <div className="flex flex-col items-center justify-center py-24 space-y-3 bg-[#ffffff]/60 rounded-2xl border border-slate-800/80">
          <div className="w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-xs text-slate-300 font-semibold tracking-wide">
            Ingesting live ticks & launching multi-agent debate...
          </p>
        </div>
      ) : !debate ? (
        <div className="bg-[#ffffff]/90 backdrop-blur-md border border-slate-800 rounded-2xl p-12 text-center shadow-xl space-y-4">
          <div className="w-16 h-16 rounded-2xl bg-purple-600/10 border border-purple-500/20 flex items-center justify-center text-purple-400 mx-auto">
            <Brain size={32} />
          </div>
          <div>
            <h3 className="text-base font-bold text-ink">No Active AI Debate Session</h3>
            <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
              Click <span className="text-purple-400 font-semibold">"Run AI Debate"</span> to initiate an adversarial evaluation between Bull, Bear, and Judge agents using live Angel One SmartAPI exchange candles.
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* Market Matrix Strip */}
          <MarketMatrixBar snapshot={snapshot} />

          {/* Conviction Tug-of-War Bar */}
          <ConvictionTugOfWar
            bullScore={bull.confidence || 0}
            bearScore={bear.confidence || 0}
          />

          {/* Three-Column Arena Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* ── BULL AGENT CARD ── */}
            <div className="bg-[#ffffff]/90 backdrop-blur-md border border-slate-800/80 hover:border-emerald-500/40 rounded-2xl overflow-hidden shadow-xl transition-all duration-300 flex flex-col justify-between">
              <div>
                <div className="h-1.5 bg-gradient-to-r from-emerald-500 to-teal-400" />
                <div className="p-4 sm:p-5 space-y-3.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-2xl">🐂</span>
                      <div>
                        <h3 className="font-bold text-ink text-sm sm:text-base">Bull Agent</h3>
                        <p className="text-[11px] text-emerald-400 font-medium">CE Call Option Strategist</p>
                      </div>
                    </div>
                    <div className="px-2.5 py-1 rounded-lg bg-emerald-950/80 border border-emerald-800/60 font-mono font-bold text-emerald-300 text-xs">
                      {bull.confidence || 0}/10
                    </div>
                  </div>

                  {/* Thesis Box */}
                  <div className="p-3 rounded-xl bg-slate-950 border border-slate-800/90 text-xs text-slate-200 italic leading-relaxed border-l-2 border-l-emerald-500">
                    "{bull.thesis || 'Bullish accumulation pattern supported by moving average demand.'}"
                  </div>

                  {/* Recommended Contract & Back Thesis */}
                  <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-950 border border-slate-800">
                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-semibold">Advocated Strike</span>
                      <div className="font-mono font-bold text-emerald-400 text-xs">
                        {bull.strike ? `${Math.round(bull.strike)} CE` : 'ATM CE'}
                      </div>
                    </div>
                    {onExecuteTrade && (
                      <button
                        onClick={() => handleBackThesis('CE', bull.strike)}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition-colors"
                      >
                        <ShoppingCart size={12} />
                        <span>Trade CE</span>
                      </button>
                    )}
                  </div>

                  {/* Arguments List */}
                  <div className="space-y-1.5">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Bullish Arguments
                    </span>
                    <ul className="space-y-1.5">
                      {(bull.arguments || []).map((arg, idx) => (
                        <li
                          key={idx}
                          className="flex items-start gap-2 p-2 rounded-lg bg-slate-950/60 border border-slate-800/60 text-xs text-slate-300 leading-relaxed"
                        >
                          <CheckCircle2 size={13} className="text-emerald-400 mt-0.5 flex-shrink-0" />
                          <span>{arg}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>

              {/* Bull Key Levels Footer */}
              {bull.key_levels && (
                <div className="p-3 bg-slate-950/90 border-t border-slate-800 text-[11px] grid grid-cols-2 gap-2 text-slate-400">
                  <div>Sup 1: <span className="font-mono text-slate-200">₹{bull.key_levels.support_1}</span></div>
                  <div>Breakout: <span className="font-mono text-emerald-400">₹{bull.key_levels.breakout_target}</span></div>
                </div>
              )}
            </div>

            {/* ── BEAR AGENT CARD ── */}
            <div className="bg-[#ffffff]/90 backdrop-blur-md border border-slate-800/80 hover:border-rose-500/40 rounded-2xl overflow-hidden shadow-xl transition-all duration-300 flex flex-col justify-between">
              <div>
                <div className="h-1.5 bg-gradient-to-r from-rose-500 to-pink-500" />
                <div className="p-4 sm:p-5 space-y-3.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-2xl">🐻</span>
                      <div>
                        <h3 className="font-bold text-ink text-sm sm:text-base">Bear Agent</h3>
                        <p className="text-[11px] text-rose-400 font-medium">PE Put Option Strategist</p>
                      </div>
                    </div>
                    <div className="px-2.5 py-1 rounded-lg bg-rose-950/80 border border-rose-800/60 font-mono font-bold text-rose-300 text-xs">
                      {bear.confidence || 0}/10
                    </div>
                  </div>

                  {/* Thesis Box */}
                  <div className="p-3 rounded-xl bg-slate-950 border border-slate-800/90 text-xs text-slate-200 italic leading-relaxed border-l-2 border-l-rose-500">
                    "{bear.thesis || 'Overhead resistance ceiling indicates high probability downward rejection.'}"
                  </div>

                  {/* Recommended Contract & Back Thesis */}
                  <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-950 border border-slate-800">
                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-semibold">Advocated Strike</span>
                      <div className="font-mono font-bold text-rose-400 text-xs">
                        {bear.strike ? `${Math.round(bear.strike)} PE` : 'ATM PE'}
                      </div>
                    </div>
                    {onExecuteTrade && (
                      <button
                        onClick={() => handleBackThesis('PE', bear.strike)}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs transition-colors"
                      >
                        <ShoppingCart size={12} />
                        <span>Trade PE</span>
                      </button>
                    )}
                  </div>

                  {/* Arguments List */}
                  <div className="space-y-1.5">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Bearish Arguments
                    </span>
                    <ul className="space-y-1.5">
                      {(bear.arguments || []).map((arg, idx) => (
                        <li
                          key={idx}
                          className="flex items-start gap-2 p-2 rounded-lg bg-slate-950/60 border border-slate-800/60 text-xs text-slate-300 leading-relaxed"
                        >
                          <CheckCircle2 size={13} className="text-rose-400 mt-0.5 flex-shrink-0" />
                          <span>{arg}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>

              {/* Bear Key Levels Footer */}
              {bear.key_levels && (
                <div className="p-3 bg-slate-950/90 border-t border-slate-800 text-[11px] grid grid-cols-2 gap-2 text-slate-400">
                  <div>Res 1: <span className="font-mono text-slate-200">₹{bear.key_levels.resistance_1}</span></div>
                  <div>Breakdown: <span className="font-mono text-rose-400">₹{bear.key_levels.breakdown_target}</span></div>
                </div>
              )}
            </div>

            {/* ── JUDGE / CRO CARD (PROMINENT) ── */}
            <div className="bg-[#ffffff]/90 backdrop-blur-md border-2 border-amber-500/50 hover:border-amber-400 rounded-2xl overflow-hidden shadow-2xl transition-all duration-300 flex flex-col justify-between">
              <div>
                <div className="h-2 bg-gradient-to-r from-amber-500 via-yellow-400 to-amber-600" />
                <div className="p-4 sm:p-5 space-y-3.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-2xl">⚖️</span>
                      <div>
                        <h3 className="font-black text-ink text-base">Judge & Risk Manager</h3>
                        <p className="text-[11px] text-amber-400 font-medium">Chief Risk Officer Final Verdict</p>
                      </div>
                    </div>
                    <div className="p-2 rounded-lg bg-amber-950/60 border border-amber-800/50">
                      <Scale size={18} className="text-amber-400" />
                    </div>
                  </div>

                  {/* Prominent Action Badge */}
                  <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 flex flex-col items-center justify-center text-center">
                    {isBuyCE ? (
                      <div className="flex items-center gap-2 text-emerald-400 font-mono font-black text-lg">
                        <ArrowUpCircle size={22} />
                        <span>BUY CALL (CE)</span>
                      </div>
                    ) : isBuyPE ? (
                      <div className="flex items-center gap-2 text-rose-400 font-mono font-black text-lg">
                        <ArrowDownCircle size={22} />
                        <span>BUY PUT (PE)</span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 text-amber-400 font-mono font-black text-lg">
                        <MinusCircle size={22} />
                        <span>NO TRADE</span>
                      </div>
                    )}

                    {!isNoTrade && judge.recommended_strike > 0 && (
                      <div className="mt-1 text-xs text-slate-300 font-mono font-bold">
                        Strike: <span className="text-ink px-2 py-0.5 rounded bg-slate-800 border border-slate-700">{Math.round(judge.recommended_strike)} {isBuyCE ? 'CE' : 'PE'}</span>
                      </div>
                    )}
                  </div>

                  {/* Trade Parameters Table */}
                  {!isNoTrade && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between text-[11px] font-semibold text-slate-400">
                        <span>INSTITUTIONAL RISK BOUNDS</span>
                        <span className="text-emerald-400 font-mono">Lot: {lotSize} (Max SL ₹700)</span>
                      </div>

                      <div className="grid grid-cols-2 gap-1.5 text-xs font-mono">
                        <div className="p-2 rounded-lg bg-slate-950 border border-slate-800 flex flex-col">
                          <span className="text-[10px] text-slate-400 uppercase font-sans">Entry LTP</span>
                          <span className="font-bold text-blue-300">₹{judge.entry_price?.toFixed(2) || '—'}</span>
                        </div>
                        <div className="p-2 rounded-lg bg-slate-950 border border-slate-800 flex flex-col">
                          <span className="text-[10px] text-slate-400 uppercase font-sans">Stop Loss</span>
                          <span className="font-bold text-rose-400">₹{judge.stop_loss?.toFixed(2) || '—'}</span>
                        </div>
                        <div className="p-2 rounded-lg bg-slate-950 border border-slate-800 flex flex-col">
                          <span className="text-[10px] text-slate-400 uppercase font-sans">Target</span>
                          <span className="font-bold text-emerald-400">₹{judge.target?.toFixed(2) || '—'}</span>
                        </div>
                        <div className="p-2 rounded-lg bg-slate-950 border border-slate-800 flex flex-col">
                          <span className="text-[10px] text-slate-400 uppercase font-sans">Risk : Reward</span>
                          <span className="font-bold text-amber-400">{judge.risk_reward_ratio || '1:1.5'}</span>
                        </div>
                      </div>

                      {/* 1-Click Execution Button */}
                      <button
                        onClick={handleExecuteJudge}
                        disabled={executing || debate.executed}
                        className={`w-full mt-2 py-3 px-4 rounded-xl font-black text-xs flex items-center justify-center gap-2 shadow-lg transition-all ${
                          debate.executed
                            ? 'bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700'
                            : 'bg-gradient-to-r from-amber-500 hover:from-amber-400 to-yellow-500 hover:to-yellow-400 text-slate-950 shadow-amber-900/40 hover:scale-[1.01]'
                        }`}
                      >
                        <Zap size={15} />
                        <span>
                          {debate.executed
                            ? '✓ Judge Trade Executed'
                            : executing
                            ? 'Placing Order...'
                            : `⚡ Execute Judge Trade (1 Lot ${currentSymbol})`}
                        </span>
                      </button>
                    </div>
                  )}

                  {/* Verdict Rationale */}
                  <div className="space-y-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      CRO Decision Rationale
                    </span>
                    <blockquote className="border-l-2 border-amber-500 pl-3 py-1.5 text-xs text-slate-300 leading-relaxed italic bg-slate-950/70 rounded-r-lg">
                      {judge.reasoning || judge.winning_argument_summary || 'Evaluating market condition for trade approval.'}
                    </blockquote>
                  </div>

                  {/* Risk Alert */}
                  {judge.key_risks && judge.key_risks.length > 0 && (
                    <div className="flex items-start gap-2 p-2.5 rounded-xl bg-amber-950/30 border border-amber-600/30 text-xs text-amber-200">
                      <AlertTriangle size={15} className="text-amber-400 mt-0.5 flex-shrink-0" />
                      <div>
                        <span className="font-bold block text-[10px] uppercase text-amber-400">Desk Warnings:</span>
                        <span>{judge.key_risks.join(' • ')}</span>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Debate Footer Metadata */}
              <div className="p-3 bg-slate-950/90 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-400 font-mono">
                <span className="flex items-center gap-1">
                  <Clock size={12} className="text-cyan-400" />
                  {debate.timestamp || 'Just now'}
                </span>
                <span>Session #{debate.id?.slice(-6) || 'LIVE'}</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
