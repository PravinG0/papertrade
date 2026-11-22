import React, { useState, useEffect } from 'react';
import {
  Play,
  Pause,
  SkipForward,
  FastForward,
  Calendar,
  X,
  Clock,
  Gauge,
  Sliders,
  RotateCcw,
} from 'lucide-react';
import { getReplayDates, startReplay, controlReplay } from '../api';

const SPEEDS = [1, 2, 5, 10];

export default function ReplayControls({
  replayState = {},
  onClose = () => {},
  onStateChange = () => {},
}) {
  const [dates, setDates] = useState([]);
  const [selectedDate, setSelectedDate] = useState('');
  const [speed, setSpeed] = useState(replayState?.speed || 1);
  const [isPlaying, setIsPlaying] = useState(replayState?.is_playing || false);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const isActive = replayState?.is_active || false;
  const currentTime = replayState?.current_time || '09:15 AM';
  const progressPercent = replayState?.progress_percent ?? 15;

  useEffect(() => {
    async function loadDates() {
      try {
        const res = await getReplayDates();
        const raw = res.data?.dates || res.data || [];
        const normalized = Array.isArray(raw)
          ? raw.map((item) => {
              if (typeof item === 'string') return { date: item, label: item };
              return {
                date: item.date || item.label || String(item),
                label: item.label || item.date || String(item),
              };
            })
          : [];

        if (normalized.length > 0) {
          setDates(normalized);
          setSelectedDate(normalized[0].date);
        } else {
          // Provide default recent trading dates
          const defaultDates = [
            { date: '2026-11-17', label: '17 Nov 2026' },
            { date: '2026-11-16', label: '16 Nov 2026' },
            { date: '2026-11-13', label: '13 Nov 2026' },
          ];
          setDates(defaultDates);
          setSelectedDate(defaultDates[0].date);
        }
      } catch (err) {
        const defaultDates = [
          { date: '2026-11-17', label: '17 Nov 2026' },
          { date: '2026-11-16', label: '16 Nov 2026' },
        ];
        setDates(defaultDates);
        setSelectedDate(defaultDates[0].date);
      }
    }
    loadDates();
  }, []);

  useEffect(() => {
    setIsPlaying(replayState?.is_playing || false);
    if (replayState?.speed) setSpeed(replayState.speed);
  }, [replayState]);

  const handleStartReplay = async () => {
    if (!selectedDate) return;
    setLoading(true);
    setErrorMsg('');
    try {
      await startReplay(selectedDate);
      onStateChange();
    } catch (err) {
      console.warn('Replay start call error:', err);
      const detail = err?.response?.data?.detail;
      setErrorMsg(
        typeof detail === 'string' ? detail : 'Could not start the replay. Please try again.'
      );
    } finally {
      setLoading(false);
    }
  };

  const handleTogglePlay = async () => {
    const nextPlay = !isPlaying;
    setIsPlaying(nextPlay);
    try {
      await controlReplay(nextPlay ? 'play' : 'pause', speed);
      onStateChange();
    } catch (err) {
      console.warn('Control replay play/pause error:', err);
    }
  };

  const handleStepForward = async () => {
    try {
      await controlReplay('step', speed);
      onStateChange();
    } catch (err) {
      console.warn('Step forward error:', err);
    }
  };

  const handleSpeedChange = async (s) => {
    setSpeed(s);
    try {
      await controlReplay('speed', s);
      onStateChange();
    } catch (err) {
      console.warn('Change speed error:', err);
    }
  };

  const handleExitReplay = async () => {
    try {
      await controlReplay('stop', 1);
      onStateChange();
      onClose();
    } catch (err) {
      console.warn('Stop replay error:', err);
      onClose();
    }
  };

  return (
    <div className="bg-[#ffffff]/95 backdrop-blur-md border border-amber-500/50 rounded-xl p-3 shadow-2xl flex flex-wrap items-center justify-between gap-3 text-xs select-none">
      {/* Date Selector & Mode Label */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-amber-950/80 border border-amber-600/50 text-amber-300 font-bold uppercase tracking-wider text-[11px]">
          <Calendar size={13} />
          <span>Historical Replay</span>
        </div>

        {!isActive ? (
          <div className="flex items-center gap-2">
            <select
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="bg-slate-900 border border-slate-700 text-slate-200 px-2 py-1 rounded-lg text-xs font-mono focus:outline-none focus:border-amber-500"
            >
              {dates.map((d) => (
                <option key={d.date} value={d.date}>
                  {d.label}
                </option>
              ))}
            </select>
            <button
              onClick={handleStartReplay}
              disabled={loading}
              className="px-3 py-1 bg-amber-600 hover:bg-amber-500 text-slate-950 font-bold rounded-lg transition-colors shadow-md disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'Launch Replay'}
            </button>
            {errorMsg && (
              <span role="alert" className="text-[11px] text-rose-600 font-sans max-w-xs leading-snug">
                {errorMsg}
              </span>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2 font-mono">
            <span className="text-slate-400">Date:</span>
            <span className="text-amber-300 font-bold">{replayState.current_date || selectedDate}</span>
          </div>
        )}
      </div>

      {/* Progress & Time Indicator */}
      {isActive && (
        <div className="flex-1 min-w-[200px] max-w-md mx-2 flex flex-col gap-1">
          <div className="flex items-center justify-between text-[11px] font-mono">
            <div className="flex items-center gap-1 text-amber-300 font-bold">
              <Clock size={12} />
              <span>{currentTime}</span>
            </div>
            <div className="text-slate-400">09:15 AM — 03:30 PM</div>
          </div>

          <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden border border-slate-800">
            <div
              className="bg-amber-500 h-1.5 rounded-full transition-all duration-300"
              style={{ width: `${Math.min(100, Math.max(0, progressPercent))}%` }}
            />
          </div>
        </div>
      )}

      {/* Action Controls & Speeds */}
      {isActive && (
        <div className="flex items-center gap-2">
          {/* Play / Pause */}
          <button
            onClick={handleTogglePlay}
            className={`p-2 rounded-lg font-bold flex items-center justify-center transition-all shadow-md ${
              isPlaying
                ? 'bg-amber-600 text-slate-950 hover:bg-amber-500'
                : 'bg-emerald-600 text-white hover:bg-emerald-500'
            }`}
            title={isPlaying ? 'Pause Replay' : 'Play Replay'}
          >
            {isPlaying ? <Pause size={14} /> : <Play size={14} className="fill-current" />}
          </button>

          {/* Step Forward */}
          <button
            onClick={handleStepForward}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors border border-slate-700"
            title="Step Forward (+1 Candle)"
          >
            <SkipForward size={14} />
          </button>

          {/* Speed Presets */}
          <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => handleSpeedChange(s)}
                className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold transition-all ${
                  speed === s
                    ? 'bg-amber-600 text-slate-950 shadow-sm'
                    : 'text-slate-400 hover:text-ink'
                }`}
              >
                {s}x
              </button>
            ))}
          </div>

          {/* Exit Replay Button */}
          <button
            onClick={handleExitReplay}
            className="px-2.5 py-1 rounded-lg bg-rose-950 hover:bg-rose-900 text-rose-300 border border-rose-800 font-semibold transition-colors flex items-center gap-1"
            title="Exit Replay and return to live feed"
          >
            <X size={13} />
            <span>Exit</span>
          </button>
        </div>
      )}

      {!isActive && (
        <button
          onClick={onClose}
          className="p-1 rounded-lg text-slate-500 hover:text-ink hover:bg-slate-800 transition-colors"
        >
          <X size={15} />
        </button>
      )}
    </div>
  );
}
