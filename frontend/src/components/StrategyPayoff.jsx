import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Layers,
  Plus,
  Trash2,
  Play,
  RotateCcw,
  ShieldAlert,
  ArrowRight,
  Info,
  DollarSign,
} from 'lucide-react';
import { getStrategyPayoff, placeOrder } from '../api';

export default function StrategyPayoff({
  selectedIndex = 'NIFTY',
  spotPrice = 25400,
  onExecuteSuccess = () => {},
}) {
  const lotSize = selectedIndex === 'BANKNIFTY' ? 15 : 25;
  const strikeStep = selectedIndex === 'BANKNIFTY' ? 100 : 50;
  const atm = Math.round(spotPrice / strikeStep) * strikeStep;

  // Pre-configured strategy templates
  const STRATEGY_TEMPLATES = {
    BULL_CALL_SPREAD: {
      name: 'Bull Call Spread',
      desc: 'Moderately bullish; caps upside to reduce entry debit.',
      legs: [
        { strike: atm, option_type: 'CE', side: 'BUY', lots: 1, price: 130 },
        { strike: atm + strikeStep * 2, option_type: 'CE', side: 'SELL', lots: 1, price: 55 },
      ],
    },
    BEAR_PUT_SPREAD: {
      name: 'Bear Put Spread',
      desc: 'Moderately bearish; benefits from downward movement with capped risk.',
      legs: [
        { strike: atm, option_type: 'PE', side: 'BUY', lots: 1, price: 125 },
        { strike: atm - strikeStep * 2, option_type: 'PE', side: 'SELL', lots: 1, price: 50 },
      ],
    },
    LONG_STRADDLE: {
      name: 'Long Straddle',
      desc: 'Volatility breakout; profits from large price movement in either direction.',
      legs: [
        { strike: atm, option_type: 'CE', side: 'BUY', lots: 1, price: 130 },
        { strike: atm, option_type: 'PE', side: 'BUY', lots: 1, price: 125 },
      ],
    },
    SHORT_STRANGLE: {
      name: 'Short Strangle',
      desc: 'Range-bound theta decay; profits if market stays between strikes.',
      legs: [
        { strike: atm - strikeStep * 2, option_type: 'PE', side: 'SELL', lots: 1, price: 50 },
        { strike: atm + strikeStep * 2, option_type: 'CE', side: 'SELL', lots: 1, price: 55 },
      ],
    },
    IRON_CONDOR: {
      name: 'Iron Condor',
      desc: 'Defined-risk neutral strategy collecting net credit.',
      legs: [
        { strike: atm - strikeStep * 3, option_type: 'PE', side: 'BUY', lots: 1, price: 25 },
        { strike: atm - strikeStep, option_type: 'PE', side: 'SELL', lots: 1, price: 75 },
        { strike: atm + strikeStep, option_type: 'CE', side: 'SELL', lots: 1, price: 80 },
        { strike: atm + strikeStep * 3, option_type: 'CE', side: 'BUY', lots: 1, price: 28 },
      ],
    },
  };

  const [selectedTemplate, setSelectedTemplate] = useState('BULL_CALL_SPREAD');
  const [legs, setLegs] = useState(STRATEGY_TEMPLATES.BULL_CALL_SPREAD.legs);
  const [payoffData, setPayoffData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [hoverIndex, setHoverIndex] = useState(null);

  // Apply template
  const applyTemplate = (key) => {
    setSelectedTemplate(key);
    if (STRATEGY_TEMPLATES[key]) {
      // re-anchor to current ATM
      const t = STRATEGY_TEMPLATES[key];
      const reAnchored = t.legs.map((leg) => ({
        ...leg,
        quantity: (leg.lots || 1) * lotSize,
      }));
      setLegs(reAnchored);
    }
  };

  // Re-fetch payoff curve whenever legs change
  const fetchPayoff = useCallback(async () => {
    if (legs.length === 0) {
      setPayoffData(null);
      return;
    }
    setLoading(true);
    try {
      const payloadLegs = legs.map((l) => ({
        strike: Number(l.strike),
        option_type: l.option_type,
        side: l.side,
        quantity: Number(l.lots || 1) * lotSize,
        price: Number(l.price || 0),
      }));

      const res = await getStrategyPayoff({
        symbol: selectedIndex,
        spot: spotPrice,
        legs: payloadLegs,
      });
      setPayoffData(res.data);
    } catch (err) {
      console.warn('Payoff fetch failed:', err);
    } finally {
      setLoading(false);
    }
  }, [legs, selectedIndex, spotPrice, lotSize]);

  useEffect(() => {
    fetchPayoff();
  }, [fetchPayoff]);

  // Update leg
  const updateLeg = (index, field, value) => {
    setSelectedTemplate('CUSTOM');
    setLegs((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], [field]: value };
      return copy;
    });
  };

  // Add new leg
  const addLeg = () => {
    setSelectedTemplate('CUSTOM');
    setLegs((prev) => [
      ...prev,
      {
        strike: atm,
        option_type: 'CE',
        side: 'BUY',
        lots: 1,
        price: 100,
        quantity: lotSize,
      },
    ]);
  };

  // Remove leg
  const removeLeg = (index) => {
    setSelectedTemplate('CUSTOM');
    setLegs((prev) => prev.filter((_, i) => i !== index));
  };

  // Execute all legs simultaneously
  const executeStrategy = async () => {
    if (legs.length === 0) return;
    if (!window.confirm(`Execute all ${legs.length} strategy legs simultaneously in your paper trading account?`)) return;

    setExecuting(true);
    try {
      for (const leg of legs) {
        await placeOrder({
          symbol: `${selectedIndex}${leg.strike}${leg.option_type}`,
          underlying: selectedIndex,
          strike: Number(leg.strike),
          option_type: leg.option_type,
          side: leg.side,
          order_type: 'MARKET',
          lots: Number(leg.lots || 1),
          current_ltp: Number(leg.price || 100),
          price: Number(leg.price || 100),
        });
      }
      alert('Strategy successfully placed into active paper positions!');
      onExecuteSuccess();
    } catch (e) {
      alert('Failed to execute strategy: ' + (e.response?.data?.detail || e.message));
    } finally {
      setExecuting(false);
    }
  };

  // SVG Chart Scaling
  const chartPoints = payoffData?.curve || [];
  const svgMetrics = useMemo(() => {
    if (chartPoints.length === 0) return null;
    const width = 800;
    const height = 300;
    const padding = { top: 30, right: 40, bottom: 40, left: 60 };

    const spots = chartPoints.map((p) => p.spot);
    const pnls = chartPoints.map((p) => p.pnl);

    const minSpot = Math.min(...spots);
    const maxSpot = Math.max(...spots);
    const minPnl = Math.min(...pnls, 0);
    const maxPnl = Math.max(...pnls, 0);

    const pnlRange = Math.max(maxPnl - minPnl, 1000);
    const spotRange = Math.max(maxSpot - minSpot, 100);

    const getX = (spot) => padding.left + ((spot - minSpot) / spotRange) * (width - padding.left - padding.right);
    const getY = (pnl) => height - padding.bottom - ((pnl - minPnl) / pnlRange) * (height - padding.top - padding.bottom);

    const zeroY = getY(0);
    const spotX = getX(spotPrice);

    const pathData = chartPoints
      .map((pt, i) => `${i === 0 ? 'M' : 'L'} ${getX(pt.spot).toFixed(1)} ${getY(pt.pnl).toFixed(1)}`)
      .join(' ');

    return { width, height, padding, minSpot, maxSpot, minPnl, maxPnl, getX, getY, zeroY, spotX, pathData };
  }, [chartPoints, spotPrice]);

  return (
    <div className="bg-[#0f172a] border border-slate-800 rounded-xl overflow-hidden shadow-2xl flex flex-col p-4 gap-4">
      {/* Top Header & Strategy Selector */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <Layers size={18} className="text-cyan-400" />
          <h2 className="text-sm font-bold uppercase tracking-wider text-white">Options Strategy Payoff Analyzer</h2>
          <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-cyan-950 border border-cyan-800 text-cyan-300">
            {selectedIndex} • Spot ₹{Number(spotPrice).toLocaleString('en-IN')}
          </span>
        </div>

        {/* Template Quick Switcher */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400 font-semibold">Template:</span>
          <select
            value={selectedTemplate}
            onChange={(e) => applyTemplate(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1 text-xs text-slate-200 font-medium focus:outline-none focus:border-cyan-500 cursor-pointer"
          >
            <option value="BULL_CALL_SPREAD">Bull Call Spread</option>
            <option value="BEAR_PUT_SPREAD">Bear Put Spread</option>
            <option value="LONG_STRADDLE">Long Straddle</option>
            <option value="SHORT_STRANGLE">Short Strangle</option>
            <option value="IRON_CONDOR">Iron Condor</option>
            <option value="CUSTOM">Custom Multi-Leg</option>
          </select>

          <button
            onClick={addLeg}
            className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center gap-1 border border-slate-700 transition-colors"
          >
            <Plus size={13} />
            <span>Add Leg</span>
          </button>

          <button
            onClick={executeStrategy}
            disabled={executing || legs.length === 0}
            className="px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center gap-1 shadow-lg transition-all disabled:opacity-50"
          >
            <Play size={13} />
            <span>{executing ? 'Executing...' : 'Execute Strategy'}</span>
          </button>
        </div>
      </div>

      {/* Strategy Summary Metric Cards */}
      {payoffData && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
          {/* Max Profit */}
          <div className="bg-slate-900/90 border border-slate-800/80 p-2.5 rounded-lg flex flex-col">
            <span className="text-[10px] uppercase font-bold text-slate-500">Max Profit</span>
            <span className="text-sm font-mono font-bold text-emerald-400 mt-0.5">
              {typeof payoffData.max_profit === 'number'
                ? `₹${payoffData.max_profit.toLocaleString('en-IN')}`
                : payoffData.max_profit}
            </span>
          </div>

          {/* Max Loss */}
          <div className="bg-slate-900/90 border border-slate-800/80 p-2.5 rounded-lg flex flex-col">
            <span className="text-[10px] uppercase font-bold text-slate-500">Max Loss</span>
            <span className="text-sm font-mono font-bold text-rose-400 mt-0.5">
              {typeof payoffData.max_loss === 'number'
                ? `₹${payoffData.max_loss.toLocaleString('en-IN')}`
                : payoffData.max_loss}
            </span>
          </div>

          {/* Breakeven Points */}
          <div className="bg-slate-900/90 border border-slate-800/80 p-2.5 rounded-lg flex flex-col">
            <span className="text-[10px] uppercase font-bold text-slate-500">Breakevens</span>
            <span className="text-sm font-mono font-bold text-cyan-300 mt-0.5">
              {payoffData.breakevens?.length > 0 ? payoffData.breakevens.join(', ') : 'None'}
            </span>
          </div>

          {/* Net Premium */}
          <div className="bg-slate-900/90 border border-slate-800/80 p-2.5 rounded-lg flex flex-col">
            <span className="text-[10px] uppercase font-bold text-slate-500">Net Premium</span>
            <span
              className={`text-sm font-mono font-bold mt-0.5 ${
                payoffData.net_premium >= 0 ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              ₹{Math.abs(payoffData.net_premium).toLocaleString('en-IN')} (
              {payoffData.is_credit ? 'Credit' : 'Debit'})
            </span>
          </div>

          {/* Risk to Reward */}
          <div className="bg-slate-900/90 border border-slate-800/80 p-2.5 rounded-lg flex flex-col">
            <span className="text-[10px] uppercase font-bold text-slate-500">Risk : Reward</span>
            <span className="text-sm font-mono font-bold text-slate-100 mt-0.5">
              {payoffData.risk_reward}
            </span>
          </div>
        </div>
      )}

      {/* SVG Payoff Curve Diagram */}
      <div className="bg-[#080c14] border border-slate-800 rounded-xl p-3 relative flex flex-col items-center">
        {loading && (
          <div className="absolute inset-0 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center z-10 text-xs text-cyan-400 font-mono">
            Calculating payoff matrix...
          </div>
        )}

        {svgMetrics ? (
          <div className="w-full overflow-x-auto flex justify-center">
            <svg
              viewBox={`0 0 ${svgMetrics.width} ${svgMetrics.height}`}
              className="w-full max-w-4xl h-64 select-none"
            >
              {/* Zero P&L horizontal reference line */}
              <line
                x1={svgMetrics.padding.left}
                y1={svgMetrics.zeroY}
                x2={svgMetrics.width - svgMetrics.padding.right}
                y2={svgMetrics.zeroY}
                stroke="#475569"
                strokeDasharray="4 4"
                strokeWidth="1.5"
              />
              <text
                x={svgMetrics.padding.left - 8}
                y={svgMetrics.zeroY + 4}
                fill="#64748b"
                fontSize="10"
                textAnchor="end"
                fontFamily="monospace"
              >
                ₹0
              </text>

              {/* Spot price vertical line */}
              <line
                x1={svgMetrics.spotX}
                y1={svgMetrics.padding.top}
                x2={svgMetrics.spotX}
                y2={svgMetrics.height - svgMetrics.padding.bottom}
                stroke="#06b6d4"
                strokeDasharray="3 3"
                strokeWidth="1.5"
              />
              <text
                x={svgMetrics.spotX}
                y={svgMetrics.padding.top - 8}
                fill="#22d3ee"
                fontSize="10"
                textAnchor="middle"
                fontFamily="monospace"
                fontWeight="bold"
              >
                Spot ₹{Math.round(spotPrice)}
              </text>

              {/* Payoff Curve Line */}
              <path
                d={svgMetrics.pathData}
                fill="none"
                stroke="#10b981"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              {/* Data points and hover interaction */}
              {chartPoints.map((pt, idx) => {
                const cx = svgMetrics.getX(pt.spot);
                const cy = svgMetrics.getY(pt.pnl);
                const isHovered = hoverIndex === idx;

                return (
                  <g key={idx} onMouseEnter={() => setHoverIndex(idx)} onMouseLeave={() => setHoverIndex(null)}>
                    <circle
                      cx={cx}
                      cy={cy}
                      r={isHovered ? 6 : 3}
                      fill={pt.is_profit ? '#10b981' : '#f43f5e'}
                      stroke="#0f172a"
                      strokeWidth="1.5"
                      className="cursor-pointer transition-all"
                    />
                  </g>
                );
              })}

              {/* Hover tooltip */}
              {hoverIndex !== null && chartPoints[hoverIndex] && (
                <g>
                  <rect
                    x={Math.min(svgMetrics.width - 150, Math.max(10, svgMetrics.getX(chartPoints[hoverIndex].spot) - 70))}
                    y={10}
                    width={140}
                    height={40}
                    rx="6"
                    fill="#1e293b"
                    stroke="#334155"
                  />
                  <text
                    x={Math.min(svgMetrics.width - 80, Math.max(80, svgMetrics.getX(chartPoints[hoverIndex].spot)))}
                    y={26}
                    fill="#94a3b8"
                    fontSize="10"
                    textAnchor="middle"
                    fontFamily="monospace"
                  >
                    Spot: ₹{chartPoints[hoverIndex].spot.toFixed(0)}
                  </text>
                  <text
                    x={Math.min(svgMetrics.width - 80, Math.max(80, svgMetrics.getX(chartPoints[hoverIndex].spot)))}
                    y={42}
                    fill={chartPoints[hoverIndex].is_profit ? '#34d399' : '#f87171'}
                    fontSize="11"
                    fontWeight="bold"
                    textAnchor="middle"
                    fontFamily="monospace"
                  >
                    P&L: ₹{chartPoints[hoverIndex].pnl.toFixed(0)}
                  </text>
                </g>
              )}
            </svg>
          </div>
        ) : (
          <div className="h-48 flex items-center justify-center text-xs text-slate-500 font-mono">
            Add legs to visualize payoff curve
          </div>
        )}
      </div>

      {/* Editable Legs Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-left border-collapse font-mono">
          <thead>
            <tr className="bg-slate-900/80 text-[10px] uppercase text-slate-400 border-b border-slate-800">
              <th className="py-2 px-3">Side</th>
              <th className="py-2 px-3">Lots (Qty)</th>
              <th className="py-2 px-3">Strike</th>
              <th className="py-2 px-3">Type</th>
              <th className="py-2 px-3">Premium (₹)</th>
              <th className="py-2 px-3">Total Value</th>
              <th className="py-2 px-2 text-center">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {legs.map((leg, index) => {
              const qty = (leg.lots || 1) * lotSize;
              const totalVal = (leg.price || 0) * qty;

              return (
                <tr key={index} className="hover:bg-slate-800/40 transition-colors">
                  {/* Side (BUY / SELL) */}
                  <td className="py-2 px-3">
                    <select
                      value={leg.side}
                      onChange={(e) => updateLeg(index, 'side', e.target.value)}
                      className={`px-2 py-1 rounded font-bold text-xs ${
                        leg.side === 'BUY'
                          ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          : 'bg-rose-950 text-rose-400 border border-rose-800'
                      }`}
                    >
                      <option value="BUY">BUY</option>
                      <option value="SELL">SELL</option>
                    </select>
                  </td>

                  {/* Lots & Qty */}
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-1.5">
                      <input
                        type="number"
                        min="1"
                        max="50"
                        value={leg.lots || 1}
                        onChange={(e) => updateLeg(index, 'lots', Math.max(1, parseInt(e.target.value) || 1))}
                        className="w-14 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-100 font-bold focus:outline-none"
                      />
                      <span className="text-slate-500 text-[11px]">({qty})</span>
                    </div>
                  </td>

                  {/* Strike Price */}
                  <td className="py-2 px-3">
                    <input
                      type="number"
                      step={strikeStep}
                      value={leg.strike}
                      onChange={(e) => updateLeg(index, 'strike', parseFloat(e.target.value) || atm)}
                      className="w-24 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-100 font-bold focus:outline-none"
                    />
                  </td>

                  {/* Option Type (CE / PE) */}
                  <td className="py-2 px-3">
                    <select
                      value={leg.option_type}
                      onChange={(e) => updateLeg(index, 'option_type', e.target.value)}
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-200 font-bold focus:outline-none"
                    >
                      <option value="CE">CALL (CE)</option>
                      <option value="PE">PUT (PE)</option>
                    </select>
                  </td>

                  {/* Premium Price */}
                  <td className="py-2 px-3">
                    <input
                      type="number"
                      step="0.5"
                      value={leg.price}
                      onChange={(e) => updateLeg(index, 'price', parseFloat(e.target.value) || 0)}
                      className="w-20 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-100 font-bold focus:outline-none"
                    />
                  </td>

                  {/* Total Leg Outlay */}
                  <td className="py-2 px-3 text-slate-300 font-bold">
                    ₹{totalVal.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </td>

                  {/* Delete Leg */}
                  <td className="py-2 px-2 text-center">
                    <button
                      onClick={() => removeLeg(index)}
                      className="p-1 rounded text-rose-400 hover:bg-rose-950/60 transition-colors"
                      title="Remove Leg"
                    >
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
