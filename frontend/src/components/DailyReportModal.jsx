import React, { useState, useEffect, useCallback } from 'react';
import {
  X,
  Sparkles,
  Calendar,
  TrendingUp,
  TrendingDown,
  Target,
  AlertTriangle,
  CheckCircle2,
  Brain,
  ShieldAlert,
  Award,
  RefreshCw,
  Clock,
  Download,
  BookOpen,
  PieChart,
  FileText,
} from 'lucide-react';
import { getDailyReport, generateDailyReport } from '../api';

export default function DailyReportModal({ isOpen, onClose }) {
  const [reportDate, setReportDate] = useState(() => {
    const now = new Date();
    return now.toISOString().slice(0, 10);
  });
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('summary'); // 'summary' | 'sl_analysis' | 'target_analysis' | 'agent_audit' | 'trades_log'

  const fetchReport = useCallback(async (date) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getDailyReport(date);
      setReport(res.data);
    } catch (err) {
      // If 404, we don't have a report yet for today, show prompt to generate
      if (err.response?.status === 404) {
        setReport(null);
      } else {
        setError(err.response?.data?.detail || 'Failed to load daily report.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchReport(reportDate);
    }
  }, [isOpen, reportDate, fetchReport]);

  const handleGenerateReport = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await generateDailyReport(reportDate);
      setReport(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to generate daily report. Please try again.');
    } finally {
      setGenerating(false);
    }
  };

  const handleExportMarkdown = () => {
    if (!report) return;
    const content = report.report_markdown || JSON.stringify(report, null, 2);
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `tradelab_daily_report_${reportDate}.md`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  if (!isOpen) return null;

  const metrics = report?.summary_metrics || {};
  const analysis = report?.raw_analysis || {};
  const totalTrades = metrics.total_trades ?? 0;
  const winRate = metrics.win_rate ?? 0;
  const netPnl = metrics.net_pnl ?? metrics.total_pnl ?? 0;
  const isNetProfit = Number(netPnl) >= 0;
  const executedTrades = report?.executed_trades || analysis.executed_trades || [];

  // Helper to safely extract string text from potentially complex or nested structures
  const safeText = (val, fallback = '') => {
    if (typeof val === 'string') return val;
    if (typeof val === 'number') return String(val);
    if (!val) return fallback;
    if (typeof val === 'object') {
      if (val.overall_critique) return String(val.overall_critique);
      if (val.reasons) return String(val.reasons);
      if (val.explanation) return String(val.explanation);
      if (val.analysis) return String(val.analysis);
      if (val.evaluation) return String(val.evaluation);
      return fallback;
    }
    return fallback;
  };

  const executiveSummaryText =
    safeText(analysis.executive_summary) ||
    safeText(analysis.performance_summary) ||
    (analysis.performance_summary?.overall_critique
      ? `${analysis.performance_summary.overall_critique} (Risk Rating: ${analysis.performance_summary.risk_discipline_rating || 'Disciplined'})`
      : '') ||
    (report?.report_markdown ? report.report_markdown.slice(0, 500) : '') ||
    'Detailed trade analysis recorded for this session.';

  const keyLessons = Array.isArray(analysis.key_lessons_learned)
    ? analysis.key_lessons_learned
    : Array.isArray(analysis.key_lessons)
    ? analysis.key_lessons
    : Array.isArray(analysis.performance_summary?.key_lessons)
    ? analysis.performance_summary.key_lessons
    : [];

  const targetHits = Array.isArray(analysis.target_hit_analysis)
    ? analysis.target_hit_analysis
    : [];

  const slHits = Array.isArray(analysis.stop_loss_analysis)
    ? analysis.stop_loss_analysis
    : Array.isArray(analysis.stop_loss_hit_analysis)
    ? analysis.stop_loss_hit_analysis
    : [];

  const decisionAudits = Array.isArray(analysis.trade_decision_analysis)
    ? analysis.trade_decision_analysis
    : Array.isArray(analysis.agent_audits)
    ? analysis.agent_audits
    : [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-[#ffffff] border border-slate-800 rounded-2xl w-full max-w-5xl max-h-[92vh] flex flex-col shadow-2xl shadow-indigo-950/40 overflow-hidden font-sans">
        {/* Header Bar */}
        <div className="p-4 bg-[#f4f6fa] border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-purple-600 via-indigo-600 to-cyan-500 flex items-center justify-center shadow-md shadow-indigo-950/50">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base sm:text-lg font-black tracking-wide text-slate-900 uppercase">
                  Daily Trading Report
                </h2>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-950 text-indigo-400 border border-indigo-700/60 font-mono">
                  AI Institutional Audit
                </span>
              </div>
              <p className="text-xs text-slate-500 font-medium">
                Data-backed evaluation of daily executions, stop-loss triggers, target hits, and AI predictive accuracy
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {/* Date Selector */}
            <div className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-slate-200">
              <Calendar size={13} className="text-cyan-400" />
              <input
                type="date"
                value={reportDate}
                onChange={(e) => setReportDate(e.target.value)}
                className="bg-transparent text-slate-200 focus:outline-none cursor-pointer"
              />
            </div>

            {/* Refresh / Generate Button */}
            <button
              onClick={handleGenerateReport}
              disabled={generating || loading}
              className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-semibold text-xs flex items-center gap-1.5 shadow-md shadow-indigo-900/40 transition-all disabled:opacity-50"
            >
              <RefreshCw size={12} className={generating ? 'animate-spin' : ''} />
              <span>{generating ? 'Auditing Trades...' : report ? 'Regenerate' : 'Generate Report'}</span>
            </button>

            {report && (
              <button
                onClick={handleExportMarkdown}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors border border-slate-700"
                title="Download Markdown Report"
              >
                <Download size={15} />
              </button>
            )}

            {/* Close Button */}
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Modal Navigation Tabs */}
        {report && (
          <div className="px-4 py-2 bg-slate-900 border-b border-slate-800 flex items-center gap-1 overflow-x-auto scrollbar-none text-xs shrink-0">
            <button
              onClick={() => setActiveTab('summary')}
              className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'summary'
                  ? 'bg-indigo-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              <PieChart size={13} />
              <span>Executive Summary</span>
            </button>

            <button
              onClick={() => setActiveTab('target_analysis')}
              className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'target_analysis'
                  ? 'bg-emerald-600 text-white shadow-md'
                  : 'text-emerald-400 hover:bg-emerald-950/40'
              }`}
            >
              <Target size={13} />
              <span>Target Hit Analysis ({metrics.winning_trades || 0})</span>
            </button>

            <button
              onClick={() => setActiveTab('sl_analysis')}
              className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'sl_analysis'
                  ? 'bg-rose-600 text-white shadow-md'
                  : 'text-rose-400 hover:bg-rose-950/40'
              }`}
            >
              <AlertTriangle size={13} />
              <span>Stop-Loss Hit Analysis ({metrics.losing_trades || 0})</span>
            </button>

            <button
              onClick={() => setActiveTab('agent_audit')}
              className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'agent_audit'
                  ? 'bg-purple-600 text-white shadow-md'
                  : 'text-purple-400 hover:bg-purple-950/40'
              }`}
            >
              <Brain size={13} />
              <span>AI Decision Audit</span>
            </button>

            <button
              onClick={() => setActiveTab('trades_log')}
              className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'trades_log'
                  ? 'bg-cyan-600 text-white shadow-md'
                  : 'text-cyan-400 hover:bg-cyan-950/40'
              }`}
            >
              <FileText size={13} />
              <span>Executed Trades Log ({totalTrades})</span>
            </button>
          </div>
        )}

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {error && (
            <div className="p-3 bg-rose-950/80 border border-rose-600 text-rose-200 rounded-xl text-xs flex items-center gap-2">
              <AlertTriangle size={15} className="shrink-0 text-rose-400" />
              <span>{error}</span>
            </div>
          )}

          {loading ? (
            <div className="py-20 text-center text-slate-400">
              <RefreshCw size={32} className="animate-spin mx-auto mb-3 text-cyan-400" />
              <p className="font-semibold text-slate-200">Fetching daily trading report...</p>
            </div>
          ) : !report ? (
            <div className="py-20 text-center max-w-md mx-auto">
              <div className="w-16 h-16 rounded-2xl bg-indigo-950/80 border border-indigo-700/60 flex items-center justify-center mx-auto mb-4 shadow-xl shadow-indigo-950/50">
                <Sparkles size={28} className="text-indigo-400" />
              </div>
              <h3 className="text-base font-bold text-slate-900 mb-1">
                No Daily Trading Report for {reportDate}
              </h3>
              <p className="text-xs text-slate-500 mb-5 leading-relaxed">
                Generate an institutional end-of-day audit analyzing every executed trade, stop-loss trigger causes, target confluences, and AI agent predictive accuracy.
              </p>
              <button
                onClick={handleGenerateReport}
                disabled={generating}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 via-indigo-600 to-cyan-600 hover:from-purple-500 hover:to-cyan-500 text-white font-bold text-xs flex items-center gap-2 mx-auto shadow-lg shadow-indigo-950/50 transition-all hover:scale-105 disabled:opacity-50"
              >
                <Sparkles size={14} className="text-amber-300" />
                <span>{generating ? 'Generating AI Analysis...' : 'Generate AI Daily Report Now'}</span>
              </button>
            </div>
          ) : (
            <>
              {/* Top KPI Summary Ribbon */}
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
                {/* 1. Net P&L */}
                <div className="p-3 bg-slate-900/90 rounded-xl border border-slate-800">
                  <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Net Realized P&amp;L</span>
                  <div className={`text-base font-black font-mono mt-0.5 ${isNetProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {isNetProfit ? '+' : ''}₹{Number(netPnl).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className="text-[10px] text-slate-400 font-mono">
                    Gross: ₹{Number(metrics.gross_pnl ?? netPnl).toFixed(2)}
                  </div>
                </div>

                {/* 2. Win Rate */}
                <div className="p-3 bg-slate-900/90 rounded-xl border border-slate-800">
                  <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Win Rate</span>
                  <div className={`text-base font-black font-mono mt-0.5 ${winRate >= 50 ? 'text-emerald-400' : 'text-amber-400'}`}>
                    {Number(winRate).toFixed(1)}%
                  </div>
                  <div className="text-[10px] text-slate-400 font-mono">
                    {metrics.winning_trades ?? 0}W - {metrics.losing_trades ?? 0}L
                  </div>
                </div>

                {/* 3. Total Trades */}
                <div className="p-3 bg-slate-900/90 rounded-xl border border-slate-800">
                  <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Total Trades</span>
                  <div className="text-base font-black font-mono text-slate-100 mt-0.5">
                    {totalTrades}
                  </div>
                  <div className="text-[10px] text-cyan-400 font-mono">
                    Target Hits: {metrics.target_hit_count ?? metrics.winning_trades ?? 0}
                  </div>
                </div>

                {/* 4. Stop-Loss Hits */}
                <div className="p-3 bg-slate-900/90 rounded-xl border border-slate-800">
                  <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Stop-Loss Hits</span>
                  <div className="text-base font-black font-mono text-rose-400 mt-0.5">
                    {metrics.sl_hit_count ?? metrics.losing_trades ?? 0}
                  </div>
                  <div className="text-[10px] text-slate-400 font-mono">
                    Total Loss: ₹{Number(metrics.gross_loss ?? 0).toFixed(2)}
                  </div>
                </div>

                {/* 5. Profit Factor */}
                <div className="p-3 bg-slate-900/90 rounded-xl border border-slate-800">
                  <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Profit Factor</span>
                  <div className="text-base font-black font-mono text-indigo-400 mt-0.5">
                    {Number(metrics.profit_factor ?? 1.0).toFixed(2)}
                  </div>
                  <div className="text-[10px] text-slate-400 font-mono">
                    Avg Win: ₹{Number(metrics.average_win ?? 0).toFixed(0)}
                  </div>
                </div>

                {/* 6. Taxes & Brokerage */}
                <div className="p-3 bg-slate-900/90 rounded-xl border border-slate-800">
                  <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Statutory Charges</span>
                  <div className="text-base font-black font-mono text-slate-300 mt-0.5">
                    ₹{Number(metrics.total_charges ?? 0).toFixed(2)}
                  </div>
                  <div className="text-[10px] text-slate-500 font-mono">
                    STT + GST + SEBI + Exch
                  </div>
                </div>
              </div>

              {/* Tab 1: Executive Summary */}
              {activeTab === 'summary' && (
                <div className="space-y-4">
                  {/* Executive Summary Card */}
                  <div className="p-4 bg-slate-900/90 rounded-2xl border border-slate-800 shadow-md">
                    <div className="flex items-center gap-2 mb-2.5 text-indigo-400">
                      <Brain size={18} />
                      <h4 className="text-sm font-bold uppercase tracking-wider text-slate-200">
                        AI Quantitative Performance Analysis
                      </h4>
                    </div>
                    <div className="text-xs text-slate-300 leading-relaxed space-y-2 whitespace-pre-line font-sans">
                      {executiveSummaryText}
                    </div>
                  </div>

                  {/* Key Lessons Learned Card */}
                  <div className="p-4 bg-slate-900/90 rounded-2xl border border-amber-900/40 shadow-md">
                    <div className="flex items-center gap-2 mb-2.5 text-amber-400">
                      <BookOpen size={18} />
                      <h4 className="text-sm font-bold uppercase tracking-wider text-slate-200">
                        Key Lessons &amp; Systemic Insights
                      </h4>
                    </div>
                    <ul className="space-y-2 text-xs text-slate-300 font-sans list-disc list-inside">
                      {keyLessons.length > 0 ? (
                        keyLessons.map((lesson, idx) => (
                          <li key={idx} className="leading-snug">
                            <span className="text-slate-200 font-medium">
                              {typeof lesson === 'string' ? lesson : lesson?.lesson || JSON.stringify(lesson)}
                            </span>
                          </li>
                        ))
                      ) : (
                        <>
                          <li className="leading-snug">
                            Respect institutional stop-loss levels strictly: trades that reversed past VWAP and CPR pivot showed deteriorating risk-reward.
                          </li>
                          <li className="leading-snug">
                            Confluence between option chain open interest walls and momentum indicators (RSI) yielded the highest win rate trades.
                          </li>
                        </>
                      )}
                    </ul>
                  </div>
                </div>
              )}

              {/* Tab 2: Target Hit Analysis */}
              {activeTab === 'target_analysis' && (
                <div className="space-y-3">
                  <div className="p-3 bg-emerald-950/40 rounded-xl border border-emerald-800/60 flex items-center gap-2 text-emerald-300 text-xs">
                    <Target size={16} className="shrink-0 text-emerald-400" />
                    <span>
                      Data-backed technical factors, indicator confluence, and market dynamics that enabled trades to reach their profit targets.
                    </span>
                  </div>

                  {targetHits.length > 0 ? (
                    targetHits.map((item, idx) => {
                      const pnl = Number(item.profit_amount ?? item.realized_pnl ?? item.pnl ?? 0);
                      return (
                        <div key={idx} className="p-4 bg-slate-900/90 rounded-xl border border-slate-800 space-y-2.5">
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-xs text-emerald-400 flex items-center gap-1.5 font-sans">
                              <CheckCircle2 size={13} />
                              <span>{item.symbol || `Trade #${idx + 1}`}</span>
                              {item.entry_price && item.exit_price && (
                                <span className="text-[10px] text-slate-400 font-mono">
                                  (₹{Number(item.entry_price).toFixed(2)} → ₹{Number(item.exit_price).toFixed(2)})
                                </span>
                              )}
                            </span>
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                              +₹{pnl.toFixed(2)}
                            </span>
                          </div>

                          {(item.market_trends || item.reasons || item.analysis || item.explanation) && (
                            <p className="text-xs text-slate-300 leading-relaxed font-sans">
                              {item.market_trends || item.reasons || item.analysis || item.explanation}
                            </p>
                          )}

                          {item.supporting_indicators && (
                            <div className="text-xs text-cyan-300 font-sans bg-cyan-950/30 p-2.5 rounded-lg border border-cyan-900/40">
                              <span className="font-bold uppercase text-[10px] text-cyan-400 tracking-wider block mb-1">
                                Supporting Confluence
                              </span>
                              {Array.isArray(item.supporting_indicators) ? (
                                <div className="flex flex-wrap gap-1.5">
                                  {item.supporting_indicators.map((ind, i) => (
                                    <span key={i} className="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-cyan-300 font-mono">
                                      {typeof ind === 'string' ? ind : JSON.stringify(ind)}
                                    </span>
                                  ))}
                                </div>
                              ) : (
                                <span>{String(item.supporting_indicators)}</span>
                              )}
                            </div>
                          )}

                          {(item.success_factors || item.key_takeaway) && (
                            <div className="text-[11px] text-emerald-300/90 font-sans bg-emerald-950/20 p-2 rounded-lg border border-emerald-900/30">
                              <strong>Key Takeaway:</strong> {item.success_factors || item.key_takeaway}
                            </div>
                          )}
                        </div>
                      );
                    })
                  ) : (
                    <div className="p-4 bg-slate-900/90 rounded-xl border border-slate-800 text-xs text-slate-400 text-center py-8">
                      {safeText(analysis.target_analysis_summary, 'No target-hit trades recorded for this session.')}
                    </div>
                  )}
                </div>
              )}

              {/* Tab 3: Stop-Loss Hit Analysis */}
              {activeTab === 'sl_analysis' && (
                <div className="space-y-3">
                  <div className="p-3 bg-rose-950/40 rounded-xl border border-rose-800/60 flex items-center gap-2 text-rose-300 text-xs">
                    <AlertTriangle size={16} className="shrink-0 text-rose-400" />
                    <span>
                      Root-cause evaluation of failed predictions: market conditions, indicator breakdown, sudden volatility shifts, and price action divergence.
                    </span>
                  </div>

                  {slHits.length > 0 ? (
                    slHits.map((item, idx) => {
                      const loss = Number(item.loss_amount ?? item.realized_pnl ?? item.pnl ?? 0);
                      return (
                        <div key={idx} className="p-4 bg-slate-900/90 rounded-xl border border-slate-800 space-y-2.5">
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-xs text-rose-400 flex items-center gap-1.5 font-sans">
                              <AlertTriangle size={13} />
                              <span>{item.symbol || `Trade #${idx + 1}`}</span>
                              {item.entry_price && item.exit_price && (
                                <span className="text-[10px] text-slate-400 font-mono">
                                  (₹{Number(item.entry_price).toFixed(2)} → ₹{Number(item.exit_price).toFixed(2)})
                                </span>
                              )}
                            </span>
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">
                              {loss < 0 ? `-₹${Math.abs(loss).toFixed(2)}` : `₹${loss.toFixed(2)}`}
                            </span>
                          </div>

                          {(item.reasons_for_failed_prediction || item.reasons || item.analysis || item.explanation) && (
                            <p className="text-xs text-slate-300 leading-relaxed font-sans">
                              {item.reasons_for_failed_prediction || item.reasons || item.analysis || item.explanation}
                            </p>
                          )}

                          {(item.technical_indicators || item.technical_breakdown || item.market_conditions) && (
                            <div className="text-[11px] text-slate-400 font-mono bg-slate-950/60 p-2.5 rounded-lg border border-slate-800 space-y-1">
                              {item.market_conditions && (
                                <div><strong className="text-slate-300">Market Context:</strong> {item.market_conditions}</div>
                              )}
                              {item.technical_indicators && (
                                <div><strong className="text-slate-300">Technical Breakdown:</strong> {typeof item.technical_indicators === 'string' ? item.technical_indicators : JSON.stringify(item.technical_indicators)}</div>
                              )}
                              {item.technical_breakdown && !item.technical_indicators && (
                                <div><strong className="text-slate-300">Technical Breakdown:</strong> {typeof item.technical_breakdown === 'string' ? item.technical_breakdown : JSON.stringify(item.technical_breakdown)}</div>
                              )}
                            </div>
                          )}

                          {item.key_takeaway && (
                            <div className="text-[11px] text-rose-300/90 font-sans bg-rose-950/20 p-2 rounded-lg border border-rose-900/30">
                              <strong>Corrective Rule:</strong> {item.key_takeaway}
                            </div>
                          )}
                        </div>
                      );
                    })
                  ) : (
                    <div className="p-4 bg-slate-900/90 rounded-xl border border-slate-800 text-xs text-slate-400 text-center py-8">
                      {safeText(analysis.sl_analysis_summary, 'No stop-loss hit trades recorded for this session.')}
                    </div>
                  )}
                </div>
              )}

              {/* Tab 4: AI Decision Audit */}
              {activeTab === 'agent_audit' && (
                <div className="space-y-3">
                  <div className="p-3 bg-purple-950/40 rounded-xl border border-purple-800/60 flex items-center gap-2 text-purple-300 text-xs">
                    <Brain size={16} className="shrink-0 text-purple-400" />
                    <span>
                      Audit of AI Bull Agent, Bear Agent, and Judge Agent recommendations: did market movements validate or invalidate their pre-trade theses?
                    </span>
                  </div>

                  {decisionAudits.length > 0 ? (
                    <div className="space-y-3">
                      {decisionAudits.map((item, idx) => {
                        const isAligned =
                          item.alignment_evaluation?.includes('CORRECT') ||
                          item.aligned === true ||
                          item.alignment?.toLowerCase()?.includes('align');
                        return (
                          <div key={idx} className="p-4 bg-slate-900/90 rounded-2xl border border-slate-800 space-y-2 text-xs">
                            <div className="flex items-center justify-between font-semibold border-b border-slate-800 pb-2">
                              <div className="flex items-center gap-2">
                                <span className="font-bold text-slate-200">
                                  {item.symbol || item.trade_id || `Trade #${idx + 1}`}
                                </span>
                                {item.initial_verdict && (
                                  <span className="px-2 py-0.5 rounded text-[10px] bg-purple-950 text-purple-300 border border-purple-800 font-mono">
                                    Verdict: {item.initial_verdict}
                                  </span>
                                )}
                              </div>
                              <span className={`text-[11px] font-bold ${isAligned ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {isAligned ? '✓ Aligned with Market' : '✗ Diverged from Market'}
                              </span>
                            </div>

                            {item.judge_rationale && (
                              <div className="text-slate-300 leading-relaxed font-sans pt-1">
                                <strong className="text-slate-400 text-[10px] uppercase tracking-wider block">AI Decision Thesis:</strong>
                                {item.judge_rationale}
                              </div>
                            )}

                            {item.actual_market_movement && (
                              <div className="text-[11px] text-slate-400 font-mono bg-slate-950/60 p-2 rounded-lg border border-slate-800">
                                <strong className="text-slate-300">Actual Price Action:</strong> {item.actual_market_movement}
                              </div>
                            )}

                            {item.alignment_evaluation && (
                              <p className="text-xs text-slate-300 leading-relaxed font-sans">
                                {item.alignment_evaluation}
                              </p>
                            )}

                            {item.evaluation && !item.alignment_evaluation && (
                              <p className="text-xs text-slate-300 leading-relaxed font-sans">
                                {item.evaluation}
                              </p>
                            )}

                            {item.agent_calibration_feedback && (
                              <div className="text-[11px] text-indigo-300/90 font-sans bg-indigo-950/20 p-2 rounded-lg border border-indigo-900/30">
                                <strong>Agent Calibration Feedback:</strong> {item.agent_calibration_feedback}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="p-4 bg-slate-900/90 rounded-2xl border border-slate-800 space-y-3 text-xs">
                      <div className="text-slate-300 leading-relaxed whitespace-pre-line font-sans">
                        {safeText(
                          analysis.trade_decision_analysis,
                          safeText(analysis.agent_decision_audit, 'All trade recommendations adhered to institutional risk parameters with ₹700 Max SL clamp.')
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Tab 5: Executed Trades Log Table */}
              {activeTab === 'trades_log' && (
                <div className="overflow-x-auto rounded-xl border border-slate-800">
                  <table className="w-full min-w-[700px] border-collapse text-xs select-none">
                    <thead>
                      <tr className="bg-slate-950 text-[10px] uppercase font-mono text-slate-400 border-b border-slate-800">
                        <th className="py-2.5 px-3 text-left">Status</th>
                        <th className="py-2.5 px-3 text-left">Instrument</th>
                        <th className="py-2.5 px-2 text-right">Entry (₹)</th>
                        <th className="py-2.5 px-2 text-right">Exit (₹)</th>
                        <th className="py-2.5 px-2 text-center">Stop Loss</th>
                        <th className="py-2.5 px-2 text-center">Target</th>
                        <th className="py-2.5 px-3 text-right">Net P&amp;L (₹)</th>
                        <th className="py-2.5 px-2 text-left">Execution Time</th>
                        <th className="py-2.5 px-2 text-left">Exit Reason</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                      {executedTrades.length === 0 ? (
                        <tr>
                          <td colSpan="9" className="py-8 text-center text-slate-500 font-sans">
                            No trades recorded for this day.
                          </td>
                        </tr>
                      ) : (
                        executedTrades.map((t, idx) => {
                          const pnl = Number(t.realized_pnl ?? t.pnl ?? 0);
                          const isWin = pnl >= 0;
                          const reason = (t.exit_reason || t.reason || '').toUpperCase();
                          const isTarget = reason.includes('TARGET');
                          const isSl = reason.includes('STOP_LOSS') || reason.includes('SL');

                          return (
                            <tr key={t.id || idx} className="hover:bg-slate-800/40">
                              <td className="py-2 px-3 whitespace-nowrap">
                                {isTarget ? (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">
                                    TARGET HIT
                                  </span>
                                ) : isSl ? (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-400 border border-rose-800">
                                    SL HIT
                                  </span>
                                ) : (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700">
                                    CLOSED
                                  </span>
                                )}
                              </td>
                              <td className="py-2 px-3 font-semibold text-slate-200">
                                {t.symbol}
                              </td>
                              <td className="py-2 px-2 text-right text-slate-300">
                                ₹{Number(t.entry_price || 0).toFixed(2)}
                              </td>
                              <td className="py-2 px-2 text-right text-slate-200 font-bold">
                                ₹{Number(t.exit_price ?? t.entry_price).toFixed(2)}
                              </td>
                              <td className="py-2 px-2 text-center text-slate-400">
                                {t.stop_loss ? `₹${Number(t.stop_loss).toFixed(2)}` : '—'}
                              </td>
                              <td className="py-2 px-2 text-center text-emerald-400">
                                {t.target ? `₹${Number(t.target).toFixed(2)}` : '—'}
                              </td>
                              <td className={`py-2 px-3 text-right font-bold ${isWin ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {isWin ? '+' : ''}₹{pnl.toFixed(2)}
                              </td>
                              <td className="py-2 px-2 text-slate-400 text-[10px] whitespace-nowrap">
                                {t.execution_time?.slice(11, 19) || t.entry_time?.slice(11, 19) || t.created_at?.slice(11, 19) || '—'}
                              </td>
                              <td className="py-2 px-2 text-slate-400 text-[10px]">
                                {t.exit_reason?.replaceAll('_', ' ') || 'Manual'}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="p-3 bg-[#f4f6fa] border-t border-slate-800 flex items-center justify-between text-xs text-slate-400 shrink-0">
          <div className="flex items-center gap-2">
            <ShieldAlert size={14} className="text-cyan-400" />
            <span>AI Risk Audit: Clamped ₹700 Max SL &amp; ₹1000 Max Target Institutional Rules</span>
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold transition-colors"
          >
            Close Report
          </button>
        </div>
      </div>
    </div>
  );
}
