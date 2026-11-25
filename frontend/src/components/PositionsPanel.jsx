import React, { useState, useMemo } from 'react';
import { dateTimeIST, dateInRange, todayIST } from '../utils/tradeDates';
import {
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Shield,
  Target,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Check,
  LogOut,
  AlertOctagon,
  Sparkles,
  FileText,
  Search,
  Filter,
  TrendingUp,
  TrendingDown,
  Layers,
} from 'lucide-react';

export default function PositionsPanel({
  positions = [],
  closedPositions = [],
  allTrades = [],
  portfolio = {},
  onExitPosition = () => {},
  onExitAllPositions = () => {},
  onUpdateStopLoss = () => {},
  onOpenReport = () => {},
  openOnly = false,
  historyMode = false,
}) {
  const [activeFilter, setActiveFilter] = useState('ALL'); // 'ALL' | 'OPEN' | 'TARGET_HIT' | 'STOP_LOSS_HIT' | 'CLOSED'
  const [searchQuery, setSearchQuery] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [dateField, setDateField] = useState('entry');
  const [indexFilter, setIndexFilter] = useState('');
  const [editingSl, setEditingSl] = useState({});
  const [savingSl, setSavingSl] = useState({});
  const [exitingId, setExitingId] = useState(null);
  const [exitingAll, setExitingAll] = useState(false);

  // Normalize and combine all executed trades
  const unifiedTrades = useMemo(() => {
    // If allTrades prop is provided and has items, use that as the primary source
    const list = [];
    const seenIds = new Set();

    // 1. Process active open positions
    positions.forEach((pos) => {
      const id = pos.id || pos.pos_id || pos.position_id;
      if (id && !seenIds.has(id)) {
        seenIds.add(id);
        const ltp = Number(pos.live_price ?? pos.current_ltp ?? pos.ltp ?? pos.entry_price ?? 0);
        const entry = Number(pos.entry_price || 0);
        const qty = Number(pos.quantity || pos.qty || 25);
        const isBuy = (pos.side || 'BUY').toUpperCase() === 'BUY';
        const pnl = isBuy ? (ltp - entry) * qty : (entry - ltp) * qty;
        const pnlPct = entry > 0 ? (pnl / (entry * qty)) * 100 : 0;

        list.push({
          ...pos,
          id,
          pos_id: id,
          trade_status: 'OPEN',
          status: 'OPEN',
          entry_price: entry,
          exit_price: null,
          current_ltp: ltp,
          live_price: ltp,
          pnl,
          unrealized_pnl: pnl,
          realized_pnl: 0,
          pnl_pct: pnlPct,
          execution_time: pos.entry_time || pos.created_at || '—',
          entry_time: pos.entry_time || pos.created_at || '—',
          exit_time: null,
          closed_at: null,
          exit_reason: null,
          is_open: true,
        });
      }
    });

    // 2. Process closed positions
    const rawClosed = openOnly ? [] : allTrades.length > 0
      ? allTrades.filter((t) => t.status !== 'ACTIVE' && t.status !== 'OPEN' && !seenIds.has(t.id || t.pos_id))
      : closedPositions;

    rawClosed.forEach((trade) => {
      const id = trade.id || trade.pos_id;
      if (id && !seenIds.has(id)) {
        seenIds.add(id);
        const reason = (trade.exit_reason || trade.reason || '').toUpperCase();
        const rawStatus = (trade.status || trade.trade_status || '').toUpperCase();

        let tradeStatus = 'CLOSED';
        if (reason === 'TARGET_HIT' || rawStatus === 'TARGET_HIT' || reason.includes('TARGET')) {
          tradeStatus = 'TARGET_HIT';
        } else if (reason === 'STOP_LOSS_HIT' || rawStatus === 'STOP_LOSS_HIT' || reason.includes('STOP_LOSS') || reason.includes('SL')) {
          tradeStatus = 'STOP_LOSS_HIT';
        }

        const entry = Number(trade.entry_price || 0);
        const exit = Number(trade.exit_price ?? trade.current_ltp ?? entry);
        const pnl = Number(trade.realized_pnl ?? trade.pnl ?? 0);
        const pnlPct = Number(trade.pnl_pct ?? (entry > 0 ? (pnl / (entry * (trade.quantity || 25))) * 100 : 0));

        list.push({
          ...trade,
          id,
          pos_id: id,
          trade_status: tradeStatus,
          status: tradeStatus,
          entry_price: entry,
          exit_price: exit,
          current_ltp: exit,
          pnl,
          realized_pnl: pnl,
          unrealized_pnl: 0,
          pnl_pct: pnlPct,
          execution_time: trade.entry_time || trade.created_at || '—',
          entry_time: trade.entry_time || trade.created_at || '—',
          exit_time: trade.exit_time || trade.closed_at || '—',
          closed_at: trade.closed_at || trade.exit_time || '—',
          exit_reason: trade.exit_reason || trade.reason || 'SQUARED_OFF',
          is_open: false,
        });
      }
    });

    return list.sort((a, b) => String(b.entry_time).localeCompare(String(a.entry_time)));
  }, [positions, closedPositions, allTrades, openOnly]);

  // Counts for tabs
  const counts = useMemo(() => {
    return {
      ALL: unifiedTrades.length,
      OPEN: unifiedTrades.filter((t) => t.trade_status === 'OPEN').length,
      TARGET_HIT: unifiedTrades.filter((t) => t.trade_status === 'TARGET_HIT').length,
      STOP_LOSS_HIT: unifiedTrades.filter((t) => t.trade_status === 'STOP_LOSS_HIT').length,
      CLOSED: unifiedTrades.filter((t) => t.trade_status === 'CLOSED').length,
    };
  }, [unifiedTrades]);

  // Filtered trades by tab and search
  const filteredTrades = useMemo(() => {
    return unifiedTrades.filter((t) => {
      if (!dateInRange(dateField === 'exit' ? t.exit_time : t.entry_time, fromDate, toDate)) return false;
      if (indexFilter && (t.underlying || "").toUpperCase() !== indexFilter) return false;
      // Tab filter
      if (activeFilter === 'OPEN' && t.trade_status !== 'OPEN') return false;
      if (activeFilter === 'TARGET_HIT' && t.trade_status !== 'TARGET_HIT') return false;
      if (activeFilter === 'STOP_LOSS_HIT' && t.trade_status !== 'STOP_LOSS_HIT') return false;
      if (activeFilter === 'CLOSED' && t.trade_status !== 'CLOSED') return false;

      // Search filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const symbolMatch = (t.symbol || '').toLowerCase().includes(q);
        const strikeMatch = String(t.strike || '').includes(q);
        const optTypeMatch = (t.option_type || '').toLowerCase().includes(q);
        const statusMatch = (t.trade_status || '').toLowerCase().includes(q);
        if (!symbolMatch && !strikeMatch && !optTypeMatch && !statusMatch) return false;
      }

      return true;
    });
  }, [unifiedTrades, activeFilter, searchQuery, fromDate, toDate, dateField, indexFilter]);

  const unrealizedPnl = portfolio?.unrealized_pnl ?? positions.reduce((acc, p) => acc + (p.pnl || p.unrealized_pnl || 0), 0);
  const realizedPnl = historyMode ? filteredTrades.filter(t => !t.is_open).reduce((acc, t) => acc + Number(t.realized_pnl ?? 0), 0) : (portfolio?.realized_pnl ?? closedPositions.reduce((acc, p) => acc + (p.realized_pnl || 0), 0));
  const marginUsed = portfolio?.used_margin ?? portfolio?.margin_used ?? positions.reduce((acc, p) => acc + (p.invested_amount || p.margin || (p.entry_price * (p.quantity || 25)) || 0), 0);

  const handleSaveSl = async (id) => {
    const newSl = editingSl[id];
    if (newSl === undefined || newSl === '') return;
    setSavingSl((prev) => ({ ...prev, [id]: true }));
    try {
      await onUpdateStopLoss(id, newSl);
      setEditingSl((prev) => {
        const copy = { ...prev };
        delete copy[id];
        return copy;
      });
    } finally {
      setSavingSl((prev) => ({ ...prev, [id]: false }));
    }
  };

  const handleExit = async (id) => {
    setExitingId(id);
    try {
      await onExitPosition(id);
    } finally {
      setExitingId(null);
    }
  };

  const handleExitAll = async () => {
    if (positions.length === 0) return;
    if (!window.confirm('Are you sure you want to exit all open positions at market price?')) return;
    setExitingAll(true);
    try {
      await onExitAllPositions();
    } finally {
      setExitingAll(false);
    }
  };

  // Render Status Badge
  const renderStatusBadge = (tradeStatus) => {
    switch (tradeStatus) {
      case 'OPEN':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-cyan-950/80 text-cyan-300 border border-cyan-600/70 shadow-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping"></span>
            OPEN
          </span>
        );
      case 'TARGET_HIT':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-950/90 text-emerald-300 border border-emerald-500/70 shadow-sm">
            <Target size={11} className="text-emerald-400" />
            TARGET HIT
          </span>
        );
      case 'STOP_LOSS_HIT':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-950/90 text-rose-300 border border-rose-500/70 shadow-sm">
            <AlertTriangle size={11} className="text-rose-400" />
            SL HIT
          </span>
        );
      case 'CLOSED':
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-600 shadow-sm">
            <CheckCircle2 size={11} className="text-slate-400" />
            CLOSED
          </span>
        );
    }
  };

  return (
    <div className="trade-ledger bg-[#ffffff] border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-full select-none">
      {/* Header Bar */}
      <div className="p-2.5 bg-[#f4f6fa] border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-cyan-500" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-ink flex items-center gap-1.5">
            <span>{openOnly ? 'Open Positions' : historyMode ? 'Executed Trade History' : 'Terminal Positions & Executed Trades'}</span>
            <span className="px-1.5 py-0.2 rounded bg-cyan-100 text-cyan-800 text-[10px] font-mono">
              {historyMode ? `${filteredTrades.length}/${unifiedTrades.length}` : unifiedTrades.length}
            </span>
          </h3>
        </div>

        <div className="flex items-center gap-2">
          {/* AI Daily Report Trigger Button */}
          <button
            onClick={onOpenReport}
            className="px-2.5 py-1 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow-md shadow-indigo-900/30 transition-all hover:scale-[1.02]"
            title="Open AI Daily Trading Report & Performance Audit"
          >
            <Sparkles size={12} className="text-amber-300" />
            <span>Daily Report</span>
          </button>

          {/* Exit All Open Trades Button */}
          {positions.length > 0 && (
            <button
              onClick={handleExitAll}
              disabled={exitingAll}
              className="px-2.5 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold flex items-center gap-1 transition-all disabled:opacity-50 shadow-sm"
              title="Close all open positions at market price"
            >
              <AlertOctagon size={13} />
              <span>{exitingAll ? 'Exiting All...' : `Exit All (${positions.length})`}</span>
            </button>
          )}
        </div>
      </div>

      {/* Filter Tabs & Quick Search Ribbon */}
      <div className="trade-filters px-3 py-1.5 bg-slate-900 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2 text-xs">
        {/* Status Filter Buttons */}
        {!openOnly && <div className="trade-status-filters flex items-center gap-1 overflow-x-auto scrollbar-none">
          <button
            onClick={() => setActiveFilter('ALL')}
            className={`px-2.5 py-1 rounded-md font-medium text-[11px] flex items-center gap-1 transition-all ${
              activeFilter === 'ALL'
                ? 'bg-cyan-600 text-white font-bold shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            <span>All Trades</span>
            <span className="px-1 py-0.2 rounded text-[10px] bg-slate-800/80 text-slate-300 font-mono">
              {counts.ALL}
            </span>
          </button>

          <button
            onClick={() => setActiveFilter('OPEN')}
            className={`px-2.5 py-1 rounded-md font-medium text-[11px] flex items-center gap-1 transition-all ${
              activeFilter === 'OPEN'
                ? 'bg-cyan-500 text-slate-950 font-bold shadow-sm'
                : 'text-cyan-400 hover:bg-cyan-950/40'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse"></span>
            <span>Open</span>
            <span className="px-1 py-0.2 rounded text-[10px] bg-cyan-950 text-cyan-300 font-mono">
              {counts.OPEN}
            </span>
          </button>

          <button
            onClick={() => setActiveFilter('TARGET_HIT')}
            className={`px-2.5 py-1 rounded-md font-medium text-[11px] flex items-center gap-1 transition-all ${
              activeFilter === 'TARGET_HIT'
                ? 'bg-emerald-600 text-white font-bold shadow-sm'
                : 'text-emerald-400 hover:bg-emerald-950/40'
            }`}
          >
            <Target size={11} />
            <span>Target Hit</span>
            <span className="px-1 py-0.2 rounded text-[10px] bg-emerald-950 text-emerald-300 font-mono">
              {counts.TARGET_HIT}
            </span>
          </button>

          <button
            onClick={() => setActiveFilter('STOP_LOSS_HIT')}
            className={`px-2.5 py-1 rounded-md font-medium text-[11px] flex items-center gap-1 transition-all ${
              activeFilter === 'STOP_LOSS_HIT'
                ? 'bg-rose-600 text-white font-bold shadow-sm'
                : 'text-rose-400 hover:bg-rose-950/40'
            }`}
          >
            <AlertTriangle size={11} />
            <span>SL Hit</span>
            <span className="px-1 py-0.2 rounded text-[10px] bg-rose-950 text-rose-300 font-mono">
              {counts.STOP_LOSS_HIT}
            </span>
          </button>

          <button
            onClick={() => setActiveFilter('CLOSED')}
            className={`px-2.5 py-1 rounded-md font-medium text-[11px] flex items-center gap-1 transition-all ${
              activeFilter === 'CLOSED'
                ? 'bg-slate-700 text-white font-bold shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            <CheckCircle2 size={11} />
            <span>Closed</span>
            <span className="px-1 py-0.2 rounded text-[10px] bg-slate-800 text-slate-300 font-mono">
              {counts.CLOSED}
            </span>
          </button>
        </div>}
        {historyMode && <div className="trade-date-filters flex flex-wrap gap-2 items-center">
          <label className="text-[11px] text-slate-300 flex items-center gap-1">Date by <select value={dateField} onChange={e => setDateField(e.target.value)} className="bg-white border border-slate-700 text-ink rounded px-1 py-0.5"><option value="entry">Entry</option><option value="exit">Exit</option></select></label>
          <label className="text-[11px] text-slate-300 flex items-center gap-1">From <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} className="bg-white border border-slate-700 text-ink rounded px-1 py-0.5" /></label>
          <label className="text-[11px] text-slate-300 flex items-center gap-1">To <input type="date" value={toDate} onChange={e => setToDate(e.target.value)} className="bg-white border border-slate-700 text-ink rounded px-1 py-0.5" /></label>
          <button onClick={() => { const today = todayIST(); setFromDate(today); setToDate(today); }} className="text-cyan-700 font-semibold text-xs">Today</button>
          <label className="text-[11px] text-slate-300 flex items-center gap-1">Index <select value={indexFilter} onChange={(e) => setIndexFilter(e.target.value)} className="bg-white border border-slate-700 text-ink rounded px-1 py-0.5"><option value="">All</option>{[...new Set(unifiedTrades.map((t) => t.underlying).filter(Boolean))].sort().map((idx) => <option key={idx}>{idx}</option>)}</select></label>
          <button onClick={() => { setFromDate(''); setToDate(''); setDateField('entry'); setIndexFilter(''); setSearchQuery(''); setActiveFilter('ALL'); }} className="text-cyan-700 font-semibold text-xs">Clear filters</button>
          {fromDate && toDate && fromDate > toDate && <span role="alert" className="text-rose-600 text-xs">From date must be on or before To date.</span>}
        </div>}

        {/* Quick Search Box */}
        <div className="trade-search relative flex items-center">
          <Search size={12} className="absolute left-2 text-slate-500 pointer-events-none" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search symbol / strike..."
            className="pl-6 pr-2 py-0.5 bg-slate-800 border border-slate-700 rounded-md text-[11px] text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 w-36 sm:w-44"
          />
        </div>
      </div>

      {/* Main Executed Trades Table */}
      <div className="trade-scroll flex-1 overflow-x-auto overflow-y-auto min-h-[220px]">
        <table role="table" className="trade-table w-full min-w-[760px] border-collapse text-xs">
          <thead role="rowgroup">
            <tr role="row" className="bg-slate-950 text-[10px] uppercase font-mono text-slate-400 border-b border-slate-800 sticky top-0 z-10">
              <th role="columnheader" className="py-2.5 px-3 text-left">Trade Status</th>
              <th role="columnheader" className="py-2.5 px-3 text-left">Instrument</th>
              <th role="columnheader" className="py-2.5 px-2 text-center">Side / Qty</th>
              <th role="columnheader" className="py-2.5 px-2 text-right">Entry (₹)</th>
              <th role="columnheader" className="py-2.5 px-2 text-right">Exit / LTP (₹)</th>
              <th role="columnheader" className="py-2.5 px-2 text-center">Stop-Loss (₹)</th>
              <th role="columnheader" className="py-2.5 px-2 text-center">Target (₹)</th>
              <th role="columnheader" className="py-2.5 px-3 text-right">P&amp;L (₹)</th>
              <th role="columnheader" className="py-2.5 px-2 text-left">Entry / Exit Date &amp; Time (IST)</th>
              <th role="columnheader" className="py-2.5 px-3 text-center">Action / Reason</th>
            </tr>
          </thead>

          <tbody role="rowgroup" className="divide-y divide-slate-800/60 font-mono text-[11px]">
            {filteredTrades.length === 0 ? (
              <tr role="row" className="trade-empty">
                <td role="cell" colSpan="10" className="py-12 text-center text-slate-500 font-sans">
                  <Activity size={24} className="mx-auto mb-2 text-slate-600" />
                  <p className="font-semibold text-slate-300">No trades matching filter</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {(openOnly || activeFilter === 'OPEN')
                      ? 'No open positions currently active. Tap BUY on the option chain to execute a trade.'
                      : activeFilter === 'TARGET_HIT'
                      ? 'No target hit trades recorded yet today.'
                      : activeFilter === 'STOP_LOSS_HIT'
                      ? 'No stop-loss hit trades recorded yet today.'
                      : 'Executed trades will appear here with full execution and P&L details.'}
                  </p>
                </td>
              </tr>
            ) : (
              filteredTrades.map((trade) => {
                const id = trade.id || trade.pos_id;
                const isOpen = trade.is_open || trade.trade_status === 'OPEN';
                const pnl = Number(trade.pnl ?? trade.realized_pnl ?? 0);
                const isProfit = pnl >= 0;
                const optType = trade.option_type || (trade.symbol?.includes('CE') ? 'CE' : 'PE');
                const isCe = optType === 'CE';
                const isBuy = (trade.side || 'BUY').toUpperCase() === 'BUY';
                const currentSl = editingSl[id] !== undefined ? editingSl[id] : (trade.stop_loss || '');

                return (
                  <tr
                    key={id} role="row"
                    className={`transition-colors ${
                      isOpen
                        ? 'bg-slate-900/60 hover:bg-slate-800/60'
                        : trade.trade_status === 'TARGET_HIT'
                        ? 'bg-emerald-950/20 hover:bg-emerald-950/40'
                        : trade.trade_status === 'STOP_LOSS_HIT'
                        ? 'bg-rose-950/20 hover:bg-rose-950/40'
                        : 'hover:bg-slate-900/40'
                    }`}
                  >
                    {/* 1. Trade Status Badge */}
                    <td role="cell" data-label="Status" className="py-2.5 px-3 text-left whitespace-nowrap">
                      {renderStatusBadge(trade.trade_status)}
                    </td>

                    {/* 2. Instrument & Type */}
                    <td role="cell" data-label="Instrument" className="py-2.5 px-3 text-left">
                      <div className="flex items-center gap-1.5 font-bold text-ink font-sans">
                        <span>{trade.symbol || `${trade.underlying || 'NIFTY'} ${trade.strike} ${optType}`}</span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                            isCe
                              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                              : 'bg-rose-950 text-rose-400 border border-rose-800'
                          }`}
                        >
                          {optType}
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-500 font-sans">
                        Strike: {trade.strike ? `₹${trade.strike}` : 'ATM'}
                      </div>
                    </td>

                    {/* 3. Side & Qty */}
                    <td role="cell" data-label="Side / Qty" className="py-2.5 px-2 text-center">
                      <span
                        className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                          isBuy
                            ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40'
                            : 'bg-rose-950/60 text-rose-400 border border-rose-800/40'
                        }`}
                      >
                        {trade.side || 'BUY'}
                      </span>
                      <div className="text-[10px] text-slate-400 mt-0.5">
                        {trade.lots || Math.max(1, Math.round((trade.quantity || 25) / 25))} Lot ({trade.quantity || 25} qty)
                      </div>
                    </td>

                    {/* 4. Entry Price */}
                    <td role="cell" data-label="Entry (₹)" className="py-2.5 px-2 text-right text-slate-300 num-tabular">
                      ₹{Number(trade.entry_price || 0).toFixed(2)}
                    </td>

                    {/* 5. Exit / LTP Price */}
                    <td role="cell" data-label="Exit / LTP (₹)" className="py-2.5 px-2 text-right num-tabular">
                      {isOpen ? (
                        <div>
                          <span className="font-bold text-ink">
                            ₹{Number(trade.current_ltp || trade.live_price || trade.entry_price).toFixed(2)}
                          </span>
                          <div className={`text-[9px] font-sans uppercase ${trade.stale_prior_day || trade.quote_stale ? 'text-amber-600 font-bold' : 'text-cyan-600'}`}>
                            {trade.stale_prior_day ? 'Prior Session' : trade.quote_stale ? 'Stale Quote' : 'Live LTP'}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <span className="font-bold text-ink">
                            ₹{Number(trade.exit_price ?? trade.current_ltp ?? trade.entry_price).toFixed(2)}
                          </span>
                          <div className="text-[9px] text-slate-500 font-sans uppercase">Exit Price</div>
                        </div>
                      )}
                    </td>

                    {/* 6. Stop-Loss Price (Editable if open) */}
                    <td role="cell" data-label="Stop-loss (₹)" className="py-2.5 px-2 text-center">
                      {isOpen ? (
                        <div className="flex items-center justify-center gap-1 font-sans">
                          <input
                            type="number"
                            step="0.5"
                            value={currentSl}
                            onChange={(e) =>
                              setEditingSl((prev) => ({ ...prev, [id]: e.target.value }))
                            }
                            placeholder="Set SL"
                            className="w-16 px-1.5 py-0.5 bg-slate-900 border border-slate-700 rounded text-slate-200 text-xs font-mono focus:outline-none focus:border-cyan-500 text-center"
                          />
                          {editingSl[id] !== undefined && (
                            <button
                              onClick={() => handleSaveSl(id)}
                              disabled={savingSl[id]}
                              className="p-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white transition-colors"
                              title="Save Trailing Stop-Loss"
                            >
                              <Check size={12} />
                            </button>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-400 font-mono">
                          {trade.stop_loss ? `₹${Number(trade.stop_loss).toFixed(2)}` : '—'}
                        </span>
                      )}
                    </td>

                    {/* 7. Target Price */}
                    <td role="cell" data-label="Target (₹)" className="py-2.5 px-2 text-center text-slate-300 font-mono">
                      {trade.target ? (
                        <span className="text-emerald-400 font-bold">₹{Number(trade.target).toFixed(2)}</span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>

                    {/* 8. P&L (Unrealized or Realized) */}
                    <td role="cell" data-label="P&L (₹)" className="py-2.5 px-3 text-right num-tabular whitespace-nowrap">
                      <div className={`font-bold ${isProfit ? 'text-emerald-600' : 'text-rose-600'}`}>
                        {isProfit ? '+' : ''}₹{Number(pnl).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                      <div className={`text-[10px] ${isProfit ? 'text-emerald-500' : 'text-rose-500'}`}>
                        {trade.pnl_pct != null
                          ? `${Number(trade.pnl_pct) >= 0 ? '+' : ''}${Number(trade.pnl_pct).toFixed(2)}%`
                          : ''}
                      </div>
                    </td>

                    {/* 9. Execution Time */}
                    <td role="cell" data-label="Date & time (IST)" className="py-2.5 px-2 text-left font-sans whitespace-nowrap">
                      <div className="flex items-center gap-1 text-[11px] text-slate-300">
                        <Clock size={11} className="text-slate-500 shrink-0" />
                        <span>Entry: {dateTimeIST(trade.execution_time)}</span>
                      </div>
                      {!isOpen && trade.exit_time && (
                        <div className="text-[10px] text-slate-500">
                          Exit: {dateTimeIST(trade.exit_time)}
                        </div>
                      )}
                    </td>

                    {/* 10. Action / Exit Reason */}
                    <td role="cell" data-label="Action / Reason" className="py-2.5 px-3 text-center font-sans">
                      {isOpen ? (
                        <button
                          onClick={() => handleExit(id)}
                          disabled={exitingId === id}
                          className="px-2.5 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center gap-1 mx-auto transition-colors disabled:opacity-50 shadow-sm"
                          title="Square off position at current market price"
                        >
                          <LogOut size={11} />
                          <span>{exitingId === id ? 'Exiting...' : 'Exit'}</span>
                        </button>
                      ) : (
                        <span
                          className={`inline-block px-2 py-0.5 rounded text-[10px] font-medium uppercase tracking-tight ${
                            trade.trade_status === 'TARGET_HIT'
                              ? 'bg-emerald-950/70 text-emerald-300 border border-emerald-800'
                              : trade.trade_status === 'STOP_LOSS_HIT'
                              ? 'bg-rose-950/70 text-rose-300 border border-rose-800'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          {trade.exit_reason?.replaceAll('_', ' ') || 'Closed'}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Bottom Summary Bar */}
      <div className="p-2.5 bg-[#f4f6fa] border-t border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex flex-wrap items-center gap-4 font-mono">
          <div>
            <span className="text-slate-500 font-sans uppercase text-[10px] mr-1">Open Margin Used:</span>
            <span className="font-bold text-ink num-tabular">
              ₹{Number(marginUsed).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>

          <div>
            <span className="text-slate-500 font-sans uppercase text-[10px] mr-1">Unrealized MTM:</span>
            <span
              className={`font-bold num-tabular ${
                unrealizedPnl >= 0 ? 'text-emerald-600' : 'text-rose-600'
              }`}
            >
              {unrealizedPnl >= 0 ? '+' : ''}₹{Number(unrealizedPnl).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>

          <div>
            <span className="text-slate-500 font-sans uppercase text-[10px] mr-1">{historyMode ? 'Filtered realized P&L:' : 'Realized Net P&L:'}</span>
            <span
              className={`font-bold num-tabular ${
                realizedPnl >= 0 ? 'text-emerald-600' : 'text-rose-600'
              }`}
            >
              {realizedPnl >= 0 ? '+' : ''}₹{Number(realizedPnl).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onOpenReport}
            className="px-2.5 py-1 rounded bg-indigo-900/60 hover:bg-indigo-900 text-indigo-300 border border-indigo-700/60 font-semibold text-xs flex items-center gap-1.5 transition-colors"
          >
            <Sparkles size={12} className="text-indigo-400" />
            <span>View Daily AI Report</span>
          </button>

          {positions.length > 0 && (
            <button
              onClick={handleExitAll}
              disabled={exitingAll}
              className="px-3 py-1 rounded bg-rose-600/90 hover:bg-rose-600 text-white font-semibold transition-all text-xs"
            >
              Exit All Positions
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
