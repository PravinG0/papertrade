import React, { useEffect, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts';
import { getCandles } from '../api';
import { RefreshCw, Columns, X } from 'lucide-react';

const TIMEFRAMES = [
  { label: '1m', interval: '1m', range: '1d' },
  { label: '5m', interval: '5m', range: '5d' },
  { label: '15m', interval: '15m', range: '5d' },
  { label: '1D', interval: '1d', range: '1mo' },
];

function calculateEMA(candles, period) {
  if (!candles || candles.length === 0) return [];
  const k = 2 / (period + 1);
  const ema = [];
  let prev = candles[0].close;

  for (let i = 0; i < candles.length; i++) {
    const c = candles[i].close;
    if (i < period) {
      prev = (prev * i + c) / (i + 1);
    } else {
      prev = c * k + prev * (1 - k);
    }
    ema.push({
      time: candles[i].time,
      value: Number(prev.toFixed(2)),
    });
  }
  return ema;
}

function calculateVWAP(candles) {
  if (!candles || candles.length === 0) return [];
  let cumVol = 0;
  let cumVolPrice = 0;
  const vwap = [];

  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    const typicalPrice = ((c.high || c.close) + (c.low || c.close) + c.close) / 3;
    const vol = Math.max(1, Number(c.volume || 1));
    cumVolPrice += typicalPrice * vol;
    cumVol += vol;
    vwap.push({
      time: c.time,
      value: Number((cumVolPrice / cumVol).toFixed(2)),
    });
  }
  return vwap;
}

// Sub-component for each independent chart pane
function ChartPane({
  title,
  symbol,
  contract = null,
  initialTfIndex = 1,
  onPriceUpdate = null,
  badgeColor = 'cyan',
  enabled = true,
}) {
  const [selectedTf, setSelectedTf] = useState(TIMEFRAMES[initialTfIndex]);
  const [loading, setLoading] = useState(true);
  const [candleError, setCandleError] = useState('');
  const [legendData, setLegendData] = useState(null);
  const [showEma20, setShowEma20] = useState(true);
  const [showEma50, setShowEma50] = useState(true);
  const [showVwap, setShowVwap] = useState(true);

  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const ema20SeriesRef = useRef(null);
  const ema50SeriesRef = useRef(null);
  const vwapSeriesRef = useRef(null);

  const refreshRef = useRef(null);
  const priceCallbackRef = useRef(onPriceUpdate);
  priceCallbackRef.current = onPriceUpdate;
  const strike = contract?.strike;
  const optionType = contract?.option_type;
  const expiry = contract?.expiry;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let chart = null;
    let ro = null;
    {
      if (!containerRef.current) return;
      const initialWidth = containerRef.current.clientWidth || 400;
      const initialHeight = containerRef.current.clientHeight || 260;

      chart = createChart(container, {
        width: initialWidth,
        height: initialHeight,
        layout: {
          background: { type: ColorType.Solid, color: '#f4f6fa' },
          textColor: '#64748b',
          fontSize: 10,
        },
        grid: {
          vertLines: { color: 'rgba(148, 163, 184, 0.25)' },
          horzLines: { color: 'rgba(148, 163, 184, 0.25)' },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: { color: '#06b6d4', width: 1, style: 3, labelBackgroundColor: '#0891b2' },
          horzLine: { color: '#06b6d4', width: 1, style: 3, labelBackgroundColor: '#0891b2' },
        },
        timeScale: {
          borderColor: '#e2e8f0',
          timeVisible: true,
          secondsVisible: false,
        },
        rightPriceScale: {
          borderColor: '#e2e8f0',
          scaleMargins: { top: 0.1, bottom: 0.25 },
        },
      });

      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#10b981',
        downColor: '#f43f5e',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#f43f5e',
      });

      let volumeSeries = null;
      try {
        volumeSeries = chart.addSeries(HistogramSeries, {
          priceFormat: { type: 'volume' },
          priceScaleId: 'volume',
        });
        if (chart.priceScale && typeof chart.priceScale === 'function') {
          try {
            chart.priceScale('volume')?.applyOptions({
              scaleMargins: { top: 0.8, bottom: 0.01 },
            });
          } catch {
            volumeSeries.priceScale()?.applyOptions({
              scaleMargins: { top: 0.8, bottom: 0.01 },
            });
          }
        }
      } catch (e) {
        // safe fallback
      }

      const ema20Series = chart.addSeries(LineSeries, {
        color: '#f59e0b',
        lineWidth: 1.5,
        priceLineVisible: false,
        title: 'EMA 20',
      });

      const ema50Series = chart.addSeries(LineSeries, {
        color: '#06b6d4',
        lineWidth: 1.5,
        priceLineVisible: false,
        title: 'EMA 50',
      });

      const vwapSeries = chart.addSeries(LineSeries, {
        color: '#c084fc',
        lineWidth: 1.5,
        priceLineVisible: false,
        title: 'VWAP',
      });

      chartRef.current = chart;
      candleSeriesRef.current = candleSeries;
      volumeSeriesRef.current = volumeSeries;
      ema20SeriesRef.current = ema20Series;
      ema50SeriesRef.current = ema50Series;
      vwapSeriesRef.current = vwapSeries;

      chart.subscribeCrosshairMove((param) => {
        if (param.time && candleSeriesRef.current) {
          const data = param.seriesData.get(candleSeriesRef.current);
          const volData = param.seriesData.get(volumeSeriesRef.current);
          if (data) {
            const change = data.close != null && data.open != null ? data.close - data.open : 0;
            const changePct = data.open && data.open > 0 ? (change / data.open) * 100 : 0;
            setLegendData({
              open: data.open,
              high: data.high,
              low: data.low,
              close: data.close,
              volume: volData?.value || 0,
              change,
              changePct,
            });
          }
        }
      });

      // ResizeObserver for container resizing
      ro = new ResizeObserver((entries) => {
        for (const entry of entries) {
          if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
            chart.applyOptions({
              width: entry.contentRect.width,
              height: entry.contentRect.height,
            });
          }
        }
      });
      ro.observe(container);
    }

    return () => {
      if (ro) ro.disconnect();
      if (chart) chart.remove();
    };
  }, []);

  useEffect(() => {
    if (ema20SeriesRef.current) {
      ema20SeriesRef.current.applyOptions({ visible: showEma20 });
    }
  }, [showEma20]);

  useEffect(() => {
    if (ema50SeriesRef.current) {
      ema50SeriesRef.current.applyOptions({ visible: showEma50 });
    }
  }, [showEma50]);

  useEffect(() => {
    if (!enabled || !candleSeriesRef.current) return;
    const controller = new AbortController();
    let timer;
    let busy = false;
    let previous = '';
    for (const series of [candleSeriesRef, volumeSeriesRef, ema20SeriesRef, ema50SeriesRef, vwapSeriesRef]) {
      series.current?.setData([]);
    }
    setLegendData(null);
    setCandleError('');

    async function load(showLoading = false) {
      if (busy || controller.signal.aborted) return;
      clearTimeout(timer);
      busy = true;
      if (showLoading) setLoading(true);
      try {
        const res = await getCandles(symbol, selectedTf.interval, selectedTf.range, strike, optionType, expiry, controller.signal);
        if (controller.signal.aborted) return;
        const raw = res.data?.candles || res.data?.data || res.data;
        const byTime = new Map();
        for (const candle of Array.isArray(raw) ? raw : []) {
          const utcTime = typeof candle.time === 'number'
            ? candle.time
            : Math.floor(Date.parse(candle.time || candle.timestamp || candle.date) / 1000);
          const [open, high, low, close] = [candle.open, candle.high, candle.low, candle.close].map(Number);
          if ([utcTime, open, high, low, close].every(Number.isFinite)) {
            const time = utcTime + 19800; // Display candle times in IST.
            byTime.set(time, {
              time, open, high: Math.max(high, open, close), low: Math.min(low, open, close), close,
              volume: Number(candle.volume) || 0,
            });
          }
        }
        const candles = [...byTime.values()].sort((a, b) => a.time - b.time);
        if (!candles.length) {
          setCandleError(previous ? 'New candles unavailable. Showing last received data.' : 'Candle data unavailable.');
          return;
        }
        setCandleError('');
        const snapshot = JSON.stringify(candles);
        if (snapshot === previous) return;

        candleSeriesRef.current.setData(candles);
        volumeSeriesRef.current?.setData(candles.map(({ time, volume, open, close }) => ({
          time,
          value: volume,
          color: close >= open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(244, 63, 94, 0.4)',
        })));
        ema20SeriesRef.current?.setData(calculateEMA(candles, 20));
        ema50SeriesRef.current?.setData(calculateEMA(candles, 50));
        vwapSeriesRef.current?.setData(calculateVWAP(candles));
        if (!previous) chartRef.current.timeScale().fitContent();
        previous = snapshot;

        const latest = candles.at(-1);
        const prior = candles.at(-2) || latest;
        const change = latest.close - prior.close;
        setLegendData({ ...latest, change, changePct: prior.close > 0 ? (change / prior.close) * 100 : 0 });
        priceCallbackRef.current?.(latest.close);
      } catch {
        if (!controller.signal.aborted) {
          setCandleError(previous ? 'New candles unavailable. Showing last received data.' : 'Candle data unavailable.');
        }
      } finally {
        busy = false;
        if (!controller.signal.aborted) {
          setLoading(false);
          timer = setTimeout(load, 6000);
        }
      }
    }

    refreshRef.current = () => load(true);
    load(true);
    return () => {
      controller.abort();
      clearTimeout(timer);
      refreshRef.current = null;
    };
  }, [symbol, selectedTf, strike, optionType, expiry, enabled]);

  return (
    <div className="flex flex-col h-full bg-[#f4f6fa] border border-slate-800 rounded-lg overflow-hidden">
      {/* Pane Top Bar */}
      <div className="chart-pane-controls p-2 bg-[#ffffff] border-b border-slate-800 flex flex-wrap items-center justify-between gap-1.5 text-[11px]">
        <div className="flex items-center gap-1.5">
          <span
            className={`px-2 py-0.5 rounded font-mono font-bold text-[11px] ${
              badgeColor === 'amber'
                ? 'bg-amber-950/70 border border-amber-600/50 text-amber-300'
                : 'bg-cyan-950/70 border border-cyan-600/50 text-cyan-300'
            }`}
          >
            {title}
          </span>

          {/* Timeframes */}
          <div className="flex items-center bg-slate-900 p-0.5 rounded border border-slate-800">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.label}
                onClick={() => setSelectedTf(tf)}
                className={`px-1.5 py-0.5 rounded text-[10px] font-semibold transition-all ${
                  selectedTf.interval === tf.interval
                    ? 'bg-slate-700 text-ink'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {tf.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          {/* Indicator Quick Toggles */}
          <div className="flex items-center gap-1 font-mono text-[10px]">
            <button
              onClick={() => {
                const next = !showEma20;
                setShowEma20(next);
                ema20SeriesRef.current?.applyOptions({ visible: next });
              }}
              className={`px-1.5 py-0.5 rounded transition-all font-bold ${
                showEma20
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                  : 'bg-slate-900 text-slate-500 border border-slate-800'
              }`}
              title="Toggle EMA 20 (Orange)"
            >
              EMA20
            </button>
            <button
              onClick={() => {
                const next = !showEma50;
                setShowEma50(next);
                ema50SeriesRef.current?.applyOptions({ visible: next });
              }}
              className={`px-1.5 py-0.5 rounded transition-all font-bold ${
                showEma50
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                  : 'bg-slate-900 text-slate-500 border border-slate-800'
              }`}
              title="Toggle EMA 50 (Cyan)"
            >
              EMA50
            </button>
            <button
              onClick={() => {
                const next = !showVwap;
                setShowVwap(next);
                vwapSeriesRef.current?.applyOptions({ visible: next });
              }}
              className={`px-1.5 py-0.5 rounded transition-all font-bold ${
                showVwap
                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40'
                  : 'bg-slate-900 text-slate-500 border border-slate-800'
              }`}
              title="Toggle VWAP (Purple)"
            >
              VWAP
            </button>
          </div>

          {/* Refresh */}
          <button
            onClick={() => refreshRef.current?.()}
            disabled={loading}
            className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700"
            title="Refresh"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin text-cyan-400' : ''} />
          </button>
        </div>
      </div>

      {/* Pane Legend */}
      {legendData && (
        <div className="px-2.5 py-1 bg-slate-950/90 border-b border-slate-800 flex flex-wrap items-center gap-2 text-[10px] font-mono select-none">
          <span className="text-slate-400">O: <b className="text-slate-200">{legendData.open?.toFixed(2)}</b></span>
          <span className="text-slate-400">H: <b className="text-slate-200">{legendData.high?.toFixed(2)}</b></span>
          <span className="text-slate-400">L: <b className="text-slate-200">{legendData.low?.toFixed(2)}</b></span>
          <span className="text-slate-400">C: <b className="text-slate-100">{legendData.close?.toFixed(2)}</b></span>
          <span
            className={`font-semibold ml-auto ${
              legendData.change >= 0 ? 'text-emerald-400' : 'text-rose-400'
            }`}
          >
            {legendData.change >= 0 ? '+' : ''}{legendData.change?.toFixed(2)} ({legendData.changePct?.toFixed(2)}%)
          </span>
        </div>
      )}

      {/* Canvas */}
      <div className="flex-1 w-full min-h-[180px] relative overflow-hidden">
        <div ref={containerRef} className="absolute inset-0" />
        {candleError && (
          <div role="status" className="absolute top-2 left-2 bg-white/95 px-2 py-1 text-xs text-slate-700">
            {candleError}
          </div>
        )}
      </div>
    </div>
  );
}

export default function TradingChart({
  selectedIndex = 'NIFTY',
  contract = null,
  onClearContract = () => {},
  onSelectIndex = () => {},
}) {
  const [dualSplit, setDualSplit] = useState(false);
  const [lastSpot, setLastSpot] = useState(null);
  const [atmSide, setAtmSide] = useState('CE');

  const step = { NIFTY: 50, FINNIFTY: 50, BANKNIFTY: 100, SENSEX: 100 }[selectedIndex] || 50;
  const atmStrike = lastSpot?.symbol === selectedIndex ? Math.round(lastSpot.price / step) * step : null;
  const compareContract = contract || (atmStrike ? { strike: atmStrike, option_type: atmSide } : null);

  function captureSpot(price) {
    setLastSpot((previous) => {
      if (dualSplit && previous?.symbol === selectedIndex) return previous;
      return { symbol: selectedIndex, price };
    });
  }

  // Close the compare view with Escape
  useEffect(() => {
    if (!dualSplit) return undefined;
    const onKey = (e) => e.key === 'Escape' && setDualSplit(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dualSplit]);

  return (
    <div className="bg-[#ffffff] border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-full">
      {/* Chart Global Header Controls */}
      <div className="chart-controls px-3 py-2 bg-[#f4f6fa] border-b border-slate-800 flex items-center justify-between gap-2 text-xs">
        {/* Left: Index Selector */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
            {['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX'].map((idx) => (
              <button
                key={idx}
                onClick={() => {
                  onSelectIndex(idx);
                }}
                className={`px-2.5 py-1 rounded text-xs font-bold transition-all ${
                  selectedIndex === idx ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {idx}
              </button>
            ))}
          </div>

          {contract && !dualSplit && (
            <div className="flex items-center gap-1.5 px-2 py-0.5 bg-amber-950/70 border border-amber-600/50 rounded text-amber-300 font-mono text-[11px]">
              <span>{contract.strike} {contract.option_type}</span>
              <button
                onClick={onClearContract}
                className="text-slate-400 hover:text-ink text-[10px]"
                title="Return to Spot Index"
              >
                ✕
              </button>
            </div>
          )}
        </div>

        {/* Right: Dual Split Toggle */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setDualSplit(!dualSplit)}
            className={`px-2.5 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition-colors ${
              dualSplit
                ? 'bg-cyan-600 text-white border-cyan-500 shadow-sm'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700'
            }`}
            title="Compare the index chart with the ATM option chart, side by side"
          >
            <Columns size={12} />
            <span>Compare</span>
          </button>
        </div>
      </div>

      {/* Charts Area */}
      <div className="flex-1 p-1.5 flex overflow-hidden min-h-[260px]">
        <div className="flex-1 h-full min-w-0">
          <ChartPane
            title={
              contract
                ? `${selectedIndex} ${contract.strike} ${contract.option_type}`
                : `${selectedIndex} Spot`
            }
            symbol={selectedIndex}
            contract={contract}
            initialTfIndex={2} // 15m default
            enabled={!dualSplit}
            onPriceUpdate={contract ? null : captureSpot}
            badgeColor={contract ? 'amber' : 'cyan'}
          />
        </div>
      </div>

      {/* Compare view: full-screen sheet, side by side on wide screens, stacked on phones */}
      {dualSplit && (
        <div
          className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-end sm:items-center justify-center sm:p-4"
          role="dialog"
          aria-label="Compare index and ATM option charts"
          onClick={(e) => e.target === e.currentTarget && setDualSplit(false)}
        >
          <div className="mobile-dialog chart-compare bg-white w-full h-[94vh] sm:h-[88vh] sm:max-w-6xl rounded-t-2xl sm:rounded-2xl shadow-2xl flex flex-col overflow-hidden">
            <div className="px-3 sm:px-4 py-2.5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2 flex-1 min-w-0">
                <h3 className="text-sm font-bold text-ink">Compare charts</h3>
                <span className="text-xs text-slate-400">{selectedIndex} index vs option</span>
                {!contract && (
                  <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-xs">
                    {['CE', 'PE'].map((t) => (
                      <button
                        key={t}
                        onClick={() => setAtmSide(t)}
                        className={`px-3 py-1.5 rounded font-bold ${atmSide === t ? 'bg-cyan-600 text-white' : 'text-slate-400'}`}
                      >
                        ATM {t}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={() => setDualSplit(false)}
                aria-label="Close compare view"
                className="shrink-0 p-2 rounded-lg text-slate-400 hover:text-ink hover:bg-slate-800"
              >
                <X size={18} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-2 flex flex-col md:flex-row gap-2">
              <div className="flex-none h-[340px] md:h-auto md:flex-1 min-w-0">
                <ChartPane
                  title={`${selectedIndex} Spot`}
                  symbol={selectedIndex}
                  contract={null}
                  initialTfIndex={1}
                  onPriceUpdate={captureSpot}
                  badgeColor="cyan"
                />
              </div>
              <div className="flex-none h-[340px] md:h-auto md:flex-1 min-w-0">
                {compareContract ? (
                  <ChartPane
                      title={`${selectedIndex} ${compareContract.strike} ${compareContract.option_type}`}
                    symbol={selectedIndex}
                    contract={compareContract}
                    initialTfIndex={0}
                    badgeColor="amber"
                  />
                ) : (
                  <div className="h-full flex items-center justify-center text-xs text-slate-400 border border-dashed border-slate-300 rounded-xl">
                    Waiting for the live index price to pick the ATM strike...
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
