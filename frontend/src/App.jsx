import React, { useState, useEffect, useCallback, useRef, lazy, Suspense } from 'react';
import Header from './components/Header';
import OptionChain from './components/OptionChain';
import TradingChart from './components/TradingChart';
import PositionsPanel from './components/PositionsPanel';
import OrdersPanel from './components/OrdersPanel';
import ReplayControls from './components/ReplayControls';
import OrderModal from './components/OrderModal';
import PositionSizeModal from './components/PositionSizeModal';
import ShortcutsModal from './components/ShortcutsModal';
import AuthModal from './components/AuthModal';
import DebateArena from './components/DebateArena';
import QuickScalperBar from './components/QuickScalperBar';
import WelcomeGuide from './components/WelcomeGuide';
import BottomNav from './components/BottomNav';
import { useAuth } from './context/AuthContext';
import sound from './utils/audio';
import {
  getStatus,
  getIndices,
  getTradingState,
  placeOrder,
  cancelOrder,
  exitPosition,
  exitAllPositions,
  updateStopLoss,
  resetPortfolio,
  getReplayState,
  getTradeHistory,
  exportTradeHistory,
} from './api';
import { Activity, Clock, Zap, ChevronDown, ChevronUp, CheckCircle2, AlertTriangle, Info, MessageSquare, History, Download, FileText } from 'lucide-react';

const PcrOiPanel = lazy(() => import('./components/PcrOiPanel'));

const PnlHeatmap = lazy(() => import('./components/PnlHeatmap'));

const StrategyPayoff = lazy(() => import('./components/StrategyPayoff'));

const DailyReportModal = lazy(() => import('./components/DailyReportModal'));

export default function App() {
  const [activeTab, setActiveTab] = useState('terminal'); // 'terminal' | 'oi' | 'pnl'
  const [terminalTab, setTerminalTab] = useState('trade');
  const [historyView, setHistoryView] = useState('trades');
  const [exporting, setExporting] = useState(false);
  const openTerminal = (tab = 'trade') => {
    setActiveTab('terminal'); setTerminalTab(tab);
    // When switching a sticky mobile tab deep in the ledger, return to the start of the content.
    if (window.matchMedia('(max-width: 767px)').matches) {
      const main = document.querySelector('.app-main');
      if (main && main.getBoundingClientRect().top < 0) {
        window.scrollTo({ top: Math.max(0, main.getBoundingClientRect().top + window.scrollY), behavior: 'auto' });
      }
    }
  };
  const openDebateHistory = () => { setHistoryView('debates'); openTerminal('history'); };
  const [rightBottomTab, setRightBottomTab] = useState('positions'); // 'positions' | 'orders'
  const [selectedIndex, setSelectedIndex] = useState('NIFTY');
  const [spotPrice, setSpotPrice] = useState(23500);

  // Market indices
  const [indices, setIndices] = useState({});

  // Portfolio & Trading State
  const [portfolio, setPortfolio] = useState({
    capital: 1000000,
    initial_capital: 1000000,
    realized_pnl: 0,
    unrealized_pnl: 0,
    margin_used: 0,
    available_margin: 1000000,
  });
  const [positions, setPositions] = useState([]);
  const [closedPositions, setClosedPositions] = useState([]);
  const [allTrades, setAllTrades] = useState([]);
  const [orders, setOrders] = useState([]);
  const [showDailyReportModal, setShowDailyReportModal] = useState(false);

  // Replay State
  const [replayState, setReplayState] = useState({
    is_active: false,
    current_date: '',
    current_time: '09:15:00',
    is_playing: false,
    speed: 1,
    progress_percent: 0,
  });
  const [showReplayBar, setShowReplayBar] = useState(false);
  const [showScalper, setShowScalper] = useState(false);
  const positionsRef = useRef(null);
  const [feedInfo, setFeedInfo] = useState({ source: 'stale', marketOpen: false });

  // Auth state & context
  const { user, token, loading: authLoading } = useAuth();
  const userRef = useRef(user);
  userRef.current = user;
  const selectedIndexRef = useRef(selectedIndex);
  selectedIndexRef.current = selectedIndex;
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authModalTab, setAuthModalTab] = useState('login');

  // Modals state
  const [orderModalData, setOrderModalData] = useState(null);
  const [selectedContract, setSelectedContract] = useState(null);
  const [showCalculator, setShowCalculator] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const handleOpenOrder = useCallback(
    (data) => {
      if (!user) { setAuthModalTab("login"); setShowAuthModal(true); return; }
      setOrderModalData({ ...data, marketOpen: feedInfo.marketOpen });
    },
    [feedInfo.marketOpen, user]
  );
  // Toast feedback
  const [toast, setToast] = useState(null);

  const showToast = (message, type = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3500);
  };

  // Sound and Toast detection on automated SL, Target or Square-Off triggers
  const prevPositionsCountRef = useRef(0);
  useEffect(() => {
    if (prevPositionsCountRef.current > positions.length) {
      getTradeHistory()
        .then((res) => {
          const trades = res.data?.trades || res.data || [];
          if (trades.length > 0) {
            const latest = trades[0];
            const reason = latest.exit_reason || latest.reason;
            if (reason === 'TARGET_HIT') {
              sound.playTargetHit();
              showToast(`🎉 Target Achieved on ${latest.symbol}! Net P&L: +₹${latest.realized_pnl}`, 'success');
            } else if (reason === 'STOP_LOSS_HIT') {
              sound.playStopLoss();
              showToast(`⚠️ Stop Loss Hit on ${latest.symbol}: ₹${latest.realized_pnl}`, 'error');
            } else if (reason === 'AUTO_SQUAREOFF_315PM') {
              sound.playCancel();
              showToast(`⏰ 3:15 PM Auto Square-off: ${latest.symbol} closed`, 'info');
            }
          }
        })
        .catch(() => {});
    }
    prevPositionsCountRef.current = positions.length;
  }, [positions.length]);

  // Sync market indices
  const syncMarketIndices = useCallback(async () => {
    try {
      const res = await getIndices();
      const raw = res.data?.indices || res.data || [];
      const map = {};
      if (Array.isArray(raw)) {
        raw.forEach((item) => {
          if (item && item.symbol) {
            map[item.symbol] = {
              ltp: item.ltp,
              change: item.net_change ?? item.change ?? 0,
              change_pct: item.percent_change ?? item.change_pct ?? 0,
            };
          }
        });
      } else if (raw && typeof raw === 'object') {
        Object.assign(map, raw);
      }

      if (Array.isArray(raw) && raw.length > 0) {
        const sources = raw.map((i) => i?.source).filter(Boolean);
        const source = sources.includes('simulated') ? 'simulated' : sources.includes('stale') || sources.length !== raw.length || !sources.every(v => v === 'live') ? 'stale' : 'live';
        setFeedInfo((f) => (f.source === source ? f : { ...f, source }));
      }

      if (!Object.keys(map).length) setFeedInfo(f => ({ ...f, source: 'stale' }));
      if (Object.keys(map).length > 0) {
        setIndices((prev) => ({ ...prev, ...map }));
        if (map[selectedIndex]?.ltp) {
          setSpotPrice(map[selectedIndex].ltp);
        }
      }
    } catch (e) {
      // Preserve last known prices; never present random ticks as market data.
      setFeedInfo(f => ({ ...f, source: 'stale' }));
    }
  }, [selectedIndex]);

  // Sync portfolio and trading state
  const tradingSyncRequest = useRef(null);
  const tradingToken = useRef(token);
  tradingToken.current = token;
  const syncTradingState = useCallback(async ({ lightweight = false } = {}) => {
    if (!token || tradingSyncRequest.current?.token === token) return;
    const request = { token };
    tradingSyncRequest.current = request;
    try {
      const res = await getTradingState(lightweight);
      if (tradingToken.current !== token) return;
      const data = res.data || {};
      if (data.portfolio) {
        setPortfolio(data.portfolio);
      }
      if (Array.isArray(data.positions)) {
        setPositions(data.positions);
      }
      if (!data.history_omitted) {
        if (Array.isArray(data.recent_closed_positions)) {
          setClosedPositions(data.recent_closed_positions);
        }
        if (Array.isArray(data.all_trades)) {
          setAllTrades(data.all_trades);
        }
      }
      if (Array.isArray(data.orders)) {
        setOrders(data.orders);
      }
    } catch (e) {
      // Keep existing state on error
    } finally {
      if (tradingSyncRequest.current === request) tradingSyncRequest.current = null;
    }
  }, [token]);

  // Re-sync portfolio & trade history when user logs in or out
  useEffect(() => {
    setPortfolio({ capital: 1000000, initial_capital: 1000000, realized_pnl: 0, unrealized_pnl: 0, margin_used: 0, available_margin: 1000000 });
    setPositions([]);
    setClosedPositions([]);
    setAllTrades([]);
    setOrders([]);
    prevPositionsCountRef.current = 0;
    syncTradingState();
  }, [syncTradingState]);

  // Sync replay state
  const syncReplayState = useCallback(async () => {
    try {
      const res = await getReplayState();
      const data = res.data || {};
      setReplayState(data);
      if (data.is_replaying || data.is_active) {
        setShowReplayBar(true);
      }
    } catch (e) {
      // Replay endpoint not yet active or disabled
    }
  }, []);

  // Global WebSocket Live Streaming Feed
  useEffect(() => {
    // Wait until auth verification settles to avoid aborting handshake midway
    if (authLoading) return;

    let ws = null;
    let reconnectTimer = null;
    let isMounted = true;

    function connectWs() {
      if (!isMounted) return;
      const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
      let wsUrl = '';

      if (import.meta.env.VITE_WS_URL) {
        const base = import.meta.env.VITE_WS_URL.replace(/\/$/, '');
        wsUrl = `${base}/ws/terminal${tokenParam}`;
      } else if (import.meta.env.VITE_API_URL) {
        const wsBase = import.meta.env.VITE_API_URL.replace(/^http/, 'ws').replace(/\/$/, '');
        wsUrl = `${wsBase}/ws/terminal${tokenParam}`;
      } else if (typeof window !== 'undefined' && window.location.hostname.includes('vercel.app')) {
        wsUrl = `wss://papertrade-1-uv24.onrender.com/ws/terminal${tokenParam}`;
      } else {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsHost = window.location.hostname || 'localhost';
        wsUrl = `${wsProtocol}//${wsHost}:8000/ws/terminal${tokenParam}`;
      }

      try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          // Connected cleanly to streaming feed
        };

        ws.onmessage = (event) => {
          if (!isMounted) return;
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'INIT') {
              if (data.trading_state?.portfolio) setPortfolio(data.trading_state.portfolio);
              if (Array.isArray(data.trading_state?.positions)) setPositions(data.trading_state.positions);
              if (Array.isArray(data.trading_state?.recent_closed_positions)) setClosedPositions(data.trading_state.recent_closed_positions);
              if (Array.isArray(data.trading_state?.all_trades)) setAllTrades(data.trading_state.all_trades);
              if (Array.isArray(data.trading_state?.orders)) setOrders(data.trading_state.orders);
              if (data.replay_state) setReplayState(data.replay_state);
            } else if (data.type === 'TICK') {
              // Only overwrite portfolio and positions if user is NOT logged in
              if (!token) {
                if (data.portfolio) setPortfolio(data.portfolio);
                if (Array.isArray(data.positions)) setPositions(data.positions);
              }
              if (Array.isArray(data.indices)) {
                const map = {};
                data.indices.forEach((item) => {
                  if (item && item.symbol) {
                    map[item.symbol] = {
                      ltp: item.ltp,
                      change: item.net_change ?? item.change ?? 0,
                      change_pct: item.percent_change ?? item.change_pct ?? 0,
                    };
                  }
                });
                const sources = data.indices.map(item => item?.source);
                setFeedInfo(f => ({ ...f, source: sources.includes('simulated') ? 'simulated' : sources.length && sources.every(v => v === 'live') ? 'live' : 'stale' }));
                if (Object.keys(map).length > 0) {
                  setIndices((prev) => ({ ...prev, ...map }));
                  const currentSymbol = selectedIndexRef.current;
                  if (map[currentSymbol]?.ltp) {
                    setSpotPrice(map[currentSymbol].ltp);
                  }
                }
              }
            } else if (data.type === 'ORDER_UPDATE') {
              const curUser = userRef.current;
              const matchesUser =
                data.user_id === undefined ||
                (curUser && curUser.id === data.user_id) ||
                (!curUser && !data.user_id);
              if (matchesUser) {
                if (data.trading_state?.portfolio) setPortfolio(data.trading_state.portfolio);
                if (Array.isArray(data.trading_state?.positions)) setPositions(data.trading_state.positions);
                if (Array.isArray(data.trading_state?.recent_closed_positions)) setClosedPositions(data.trading_state.recent_closed_positions);
                if (Array.isArray(data.trading_state?.all_trades)) setAllTrades(data.trading_state.all_trades);
                if (Array.isArray(data.trading_state?.orders)) setOrders(data.trading_state.orders);
              }
            }
          } catch (e) {
            // Ignore parse errors
          }
        };

        ws.onclose = () => {
          if (isMounted) {
            reconnectTimer = setTimeout(connectWs, 3000);
          }
        };

        ws.onerror = () => {
          // Allow graceful reconnect via onclose or timer
        };
      } catch (err) {
        if (isMounted) {
          reconnectTimer = setTimeout(connectWs, 5000);
        }
      }
    }

    connectWs();

    return () => {
      isMounted = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) {
        // Disarm handlers so aborted connections don't log error in Firefox
        ws.onerror = null;
        ws.onclose = null;
        if (ws.readyState === WebSocket.CONNECTING) {
          ws.onopen = () => {
            try { ws.close(1000, 'Normal unmount'); } catch (e) {}
          };
        } else if (ws.readyState === WebSocket.OPEN) {
          try { ws.close(1000, 'Normal unmount'); } catch (e) {}
        }
      }
    };
  }, [authLoading, token]);

  // Resilient REST fallback polling (independent of WS lifecycle)
  useEffect(() => {
    syncMarketIndices();
    syncTradingState();
    syncReplayState();
    const refreshStatus = () =>
      getStatus()
        .then((r) => setFeedInfo((f) => ({ ...f, marketOpen: Boolean(r.data?.market_open) })))
        .catch(() => {});
    refreshStatus();
    const statusTimer = setInterval(refreshStatus, 30000);

    const interval = setInterval(() => {
      syncMarketIndices();
      syncTradingState({ lightweight: true });
      syncReplayState();
    }, 4000);

    return () => {
      clearInterval(interval);
      clearInterval(statusTimer);
    };
  }, [syncMarketIndices, syncTradingState, syncReplayState]);

  // Order Placement Handler
  const handlePlaceOrder = async (orderPayload) => {
    try {
      const res = await placeOrder(orderPayload);
      sound.playOrderFill();
      const filled = res?.data;
      showToast(
        filled?.status === 'PENDING'
          ? 'Order placed and waiting for its price. See Pending Orders.'
          : `Bought ${filled?.symbol || orderPayload.symbol} at ₹${filled?.filled_price ?? ''}. See it under Positions.`,
        'success'
      );
      setRightBottomTab(filled?.status === 'PENDING' ? 'orders' : 'positions');
      setTimeout(() => { if (positionsRef.current?.getClientRects().length) positionsRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 150);
      await syncTradingState();
      return res;
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || 'Failed to place order';
      showToast(`Error: ${msg}`, 'error');
      throw err;
    }
  };

  // Cancel Order Handler
  const handleCancelOrder = async (id) => {
    try {
      await cancelOrder(id);
      sound.playCancel();
      showToast(`Order #${id} cancelled`, 'info');
      await syncTradingState();
    } catch (err) {
      showToast('Failed to cancel order', 'error');
    }
  };

  // Exit Position Handler
  const handleExitPosition = async (id) => {
    try {
      await exitPosition(id);
      sound.playOrderFill();
      showToast(`Position squared off successfully`, 'success');
      await syncTradingState();
    } catch (err) {
      showToast('Failed to exit position', 'error');
    }
  };

  // Exit All Positions Handler
  const handleExitAllPositions = async () => {
    try {
      await exitAllPositions();
      sound.playOrderFill();
      showToast('All open positions squared off', 'success');
      await syncTradingState();
    } catch (err) {
      showToast('Failed to square off all positions', 'error');
    }
  };

  // Execute AI Debate Judge Trade Handler
  const handleExecuteDebateTrade = async (orderPayload) => {
    try {
      const res = await handlePlaceOrder(orderPayload);
      showToast(
        `Judge trade executed: ${orderPayload.side} ${orderPayload.underlying} ${orderPayload.strike} ${orderPayload.option_type} (1 Lot)`,
        'success'
      );
      await syncTradingState();
      return res;
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || 'Failed to execute judge trade';
      showToast(`Judge trade failed: ${msg}`, 'error');
      throw err;
    }
  };

  // Update Trailing Stop Loss
  const handleUpdateStopLoss = async (id, slPrice) => {
    try {
      await updateStopLoss(id, slPrice);
      showToast(`Stop Loss updated to ₹${slPrice}`, 'success');
      await syncTradingState();
    } catch (err) {
      showToast('Failed to update stop loss', 'error');
    }
  };

  // Reset Portfolio Handler
  const handleResetPortfolio = async () => {
    if (!window.confirm('Reset virtual portfolio to initial capital ₹10,00,000?')) return;
    try {
      await resetPortfolio();
      showToast('Portfolio reset to ₹10,00,000', 'success');
      await syncTradingState();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Portfolio reset failed. No changes confirmed.", "error");
    }
  };

  const handleExportHistory = async () => {
    setExporting(true);
    try {
      const res = await exportTradeHistory();
      const url = URL.createObjectURL(res.data);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'papertrade-closed-trades.csv';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      showToast('Unable to export trade history.', 'error');
    } finally { setExporting(false); }
  };

  // Keyboard Shortcuts Listener
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;

      if (e.key === 'Escape') {
        setOrderModalData(null);
        setShowCalculator(false);
        setShowShortcuts(false);
      } else if (e.key === '?') {
        setShowShortcuts((prev) => !prev);
      } else if (e.key === '1') {
        openTerminal('trade');
      } else if (e.key === '2') {
        setActiveTab('oi');
      } else if (e.key === '3') {
        setActiveTab('pnl');
      } else if (e.key === '4') {
        setActiveTab('payoff');
      } else if (e.shiftKey && (e.key === 'X' || e.key === 'x')) {
        handleExitAllPositions();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleExitAllPositions]);

  return (
    <div className="tradelab-app min-h-screen bg-[#f4f6fa] text-slate-100 flex flex-col font-sans selection:bg-cyan-500/20">
      {/* Toast Notification */}
      {toast && (
        <div
          role="status"
          className={`fixed top-4 right-4 left-4 sm:left-auto sm:max-w-sm z-50 px-4 py-3 rounded-xl border shadow-2xl text-xs font-semibold flex items-start gap-2.5 toast-in ${
            toast.type === 'success'
              ? 'bg-emerald-950 border-emerald-600 text-emerald-200'
              : toast.type === 'error'
              ? 'bg-rose-950 border-rose-600 text-rose-200'
              : 'bg-cyan-950 border-cyan-600 text-cyan-200'
          }`}
        >
          {toast.type === 'success' ? <CheckCircle2 size={16} className="shrink-0 mt-px" />
            : toast.type === 'error' ? <AlertTriangle size={16} className="shrink-0 mt-px" />
            : <Info size={16} className="shrink-0 mt-px" />}
          <span className="leading-snug">{toast.message}</span>
        </div>
      )}

      {/* Main App Header */}
      <Header
        indices={indices}
        portfolio={portfolio}
        replayState={replayState}
        feedInfo={feedInfo}
        activeTab={activeTab}
        setActiveTab={(tab) => tab === 'terminal' ? openTerminal('trade') : setActiveTab(tab)}
        onResetPortfolio={handleResetPortfolio}
        onOpenReplay={() => setShowReplayBar(true)}
        onOpenCalculator={() => setShowCalculator(true)}
        onOpenShortcuts={() => setShowShortcuts(true)}
        onOpenReport={() => setShowDailyReportModal(true)}
        onOpenAuth={(tab = 'login') => {
          setAuthModalTab(tab);
          setShowAuthModal(true);
        }}
      />

      {/* Replay Docked Bar (when enabled) */}
      {(showReplayBar || replayState.is_replaying || replayState.is_active) && (
        <div className="px-4 py-2 bg-[#f4f6fa] border-b border-amber-900/40">
          <ReplayControls
            replayState={replayState}
            onClose={() => setShowReplayBar(false)}
            onStateChange={() => {
              syncReplayState();
              syncTradingState();
              syncMarketIndices();
            }}
          />
        </div>
      )}

      {/* Main Content Area */}
      <main className="app-main flex-1 min-w-0 p-3 lg:p-4 pb-24 md:pb-4 max-w-[1920px] w-full mx-auto">
        {/* Terminal navigation: panels stay mounted to preserve chart and debate state. */}
        {activeTab === 'terminal' && (
          <div className="terminal-nav mb-4 bg-white border border-slate-200 rounded-2xl p-2 sm:p-3 shadow-sm">
            <div className="flex items-center justify-between gap-2 px-2 pb-2">
              <h1 className="text-base sm:text-lg font-bold text-ink">Terminal</h1>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-cyan-700 bg-cyan-50 rounded-full px-2 py-1">Paper trading</span>
            </div>
            <div role="tablist" aria-label="Terminal views" className="grid grid-cols-3 gap-1 bg-[#eef1f6] p-1 rounded-xl" onKeyDown={(event) => {
              const ids = ['trade', 'chat', 'history'];
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
              event.preventDefault(); event.stopPropagation();
              const index = ids.indexOf(terminalTab);
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
              setTerminalTab(ids[next]); document.getElementById(`terminal-tab-${ids[next]}`)?.focus();
            }}>
              {[
                { id: 'trade', label: 'Option Buy/Sell', icon: Activity },
                { id: 'chat', label: 'Chat', icon: MessageSquare },
                { id: 'history', label: 'History', icon: History },
              ].map(({ id, label, icon: Icon }) => (
                <button key={id} id={`terminal-tab-${id}`} type="button" role="tab" aria-selected={terminalTab === id} aria-controls={`terminal-panel-${id}`} tabIndex={terminalTab === id ? 0 : -1}
                  onClick={() => openTerminal(id)}
                  className={`min-w-0 flex items-center justify-center gap-1.5 min-h-[44px] px-1.5 sm:px-3 py-2 rounded-lg text-[11px] sm:text-sm font-semibold transition-colors focus-visible:ring-2 focus-visible:ring-cyan-500 ${terminalTab === id ? 'bg-cyan-600 text-white shadow-sm' : 'text-[#475569] hover:bg-white hover:text-cyan-700'}`}>
                  <Icon size={16} className="shrink-0" /><span>{label}</span>
                  {id === 'trade' && positions.length > 0 && <span className="hidden sm:inline rounded-full bg-white/20 px-1.5 text-[10px]">{positions.length}</span>}
                </button>
              ))}
            </div>
          </div>
        )}
        {(replayState.is_replaying || replayState.is_active) && <div role="status" className="p-2 text-sm text-amber-700 bg-amber-50 rounded">Historical replay is playback-only until a separate simulation wallet is available.</div>}
        <section id="terminal-panel-trade" role="tabpanel" aria-labelledby="terminal-tab-trade" hidden={activeTab !== 'terminal' || terminalTab !== 'trade'}>
          <WelcomeGuide marketOpen={feedInfo.marketOpen} onOpenDebate={() => openTerminal('chat')} />
          <div className="terminal-grid grid grid-cols-1 lg:grid-cols-12 gap-3 h-auto lg:h-[calc(100vh-235px)] lg:min-h-[660px]">
            {/* Left 7 Columns: Complete Option Chain */}
            <div className="terminal-chain min-w-0 lg:col-span-7 h-[540px] sm:h-[620px] lg:h-full flex flex-col min-h-[420px]">
              <OptionChain
                selectedIndex={selectedIndex}
                onSelectIndex={(idx) => {
                  setSelectedIndex(idx);
                  setSelectedContract(null);
                }}
                spotPrice={spotPrice}
                onOpenOrder={handleOpenOrder}
                onSelectContract={(contract) => setSelectedContract(contract)}
                onExecuteBasket={async (legs) => {
                  try {
                    for (const leg of legs) {
                      await handlePlaceOrder({
                        symbol: `${selectedIndex}${leg.strike}${leg.option_type}`,
                        underlying: selectedIndex,
                        expiry: leg.expiry || null,
                        strike: Number(leg.strike),
                        option_type: leg.option_type,
                        side: leg.side,
                        order_type: 'MARKET',
                        lots: Number(leg.lots || 1),
                        current_ltp: Number(leg.price || 100),
                        price: Number(leg.price || 100),
                      });
                    }
                    showToast(`Basket executed successfully (${legs.length} legs)!`, 'success');
                  } catch (e) {
                    showToast(`Basket execution failed: ${e.message}`, 'error');
                  }
                }}
              />
            </div>

            {/* Right 5 Columns: Split Top = Chart, Bottom = Positions / Orders */}
            <div className="terminal-side min-w-0 lg:col-span-5 flex flex-col gap-3 h-auto lg:h-full">
              {/* Top Half: Responsive Candlestick Chart */}
              <div className="terminal-chart min-w-0 h-[340px] sm:h-[380px] lg:h-[44%] lg:min-h-[260px]">
                <TradingChart
                  selectedIndex={selectedIndex}
                  contract={selectedContract}
                  onClearContract={() => setSelectedContract(null)}
                  onSelectIndex={(idx) => {
                    setSelectedIndex(idx);
                    setSelectedContract(null);
                  }}
                />
              </div>

              {/* Bottom Half: Tabs for Positions & Orders */}
              <div ref={positionsRef} className="terminal-positions min-w-0 h-[360px] sm:h-[400px] lg:h-auto lg:flex-1 flex flex-col min-h-[260px] overflow-hidden scroll-mt-20">
                {/* Panel Switcher Tab Header */}
                <div className="flex items-center gap-1 mb-1.5 bg-slate-900/60 p-1 rounded-lg border border-slate-800 text-xs w-fit">
                  <button
                    onClick={() => setRightBottomTab('positions')}
                    className={`px-3 py-1 rounded font-semibold flex items-center gap-1.5 transition-all ${
                      rightBottomTab === 'positions'
                        ? 'bg-cyan-600 text-white shadow-md'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Activity size={13} />
                    <span>Positions ({positions.length} open)</span>
                  </button>

                  <button
                    onClick={() => setRightBottomTab('orders')}
                    className={`px-3 py-1 rounded font-semibold flex items-center gap-1.5 transition-all ${
                      rightBottomTab === 'orders'
                        ? 'bg-cyan-600 text-white shadow-md'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Clock size={13} />
                    <span>Pending Orders ({orders.length})</span>
                  </button>
                </div>

                {/* Active Panel View */}
                <div className="flex-1 overflow-hidden">
                  {rightBottomTab === 'positions' ? (
                    <PositionsPanel
                      positions={positions}
                      openOnly
                      portfolio={portfolio}
                      onExitPosition={handleExitPosition}
                      onExitAllPositions={handleExitAllPositions}
                      onUpdateStopLoss={handleUpdateStopLoss}
                      onOpenReport={() => setShowDailyReportModal(true)}
                    />
                  ) : (
                    <OrdersPanel
                      orders={orders}
                      onCancelOrder={handleCancelOrder}
                    />
                  )}
                </div>
              </div>

              {/* Quick trade dock: hidden until asked for, so Positions stays in view */}
              <div className="rounded-xl border border-slate-800 bg-slate-900/50">
                <button
                  onClick={() => setShowScalper((v) => !v)}
                  className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-slate-300 hover:text-ink"
                >
                  <span className="flex items-center gap-2">
                    <Zap size={13} className="text-amber-400" />
                    Quick trade (1-tap ATM buy)
                  </span>
                  {showScalper ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
                {showScalper && (
                  <div className="px-2 pb-2">
                    <QuickScalperBar selectedIndex={selectedIndex} spotPrice={spotPrice} onPlaceOrder={handlePlaceOrder} />
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* History: trade ledger and the same live-updated debate audit trail. */}
        <section id="terminal-panel-history" role="tabpanel" aria-labelledby="terminal-tab-history" hidden={activeTab !== 'terminal' || terminalTab !== 'history'} className="max-w-7xl mx-auto space-y-3">
          <div className="history-toolbar bg-white rounded-xl border border-slate-200 p-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex gap-1 bg-[#eef1f6] rounded-lg p-1">
              <button aria-pressed={historyView === 'trades'} onClick={() => setHistoryView('trades')} className={`px-3 py-2 rounded-md text-xs font-semibold ${historyView === 'trades' ? 'bg-white text-cyan-700 shadow-sm' : 'text-[#475569]'}`}>Trade History</button>
              <button aria-pressed={historyView === 'debates'} onClick={() => setHistoryView('debates')} className={`px-3 py-2 rounded-md text-xs font-semibold ${historyView === 'debates' ? 'bg-white text-cyan-700 shadow-sm' : 'text-[#475569]'}`}>Debate History</button>
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => setShowDailyReportModal(true)} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white text-xs font-semibold"><FileText size={14} /> Daily Report</button>
              {historyView === 'trades' && <button disabled={!user || exporting} onClick={handleExportHistory} className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-800 text-ink text-xs font-semibold disabled:opacity-50"><Download size={14} />{exporting ? 'Exporting...' : 'Export closed trades'}</button>}
            </div>
          </div>
          <div hidden={historyView !== 'trades'} className="history-ledger h-[650px]">
            <PositionsPanel key={`history-${user?.id || 'guest'}`} positions={positions} closedPositions={closedPositions} allTrades={allTrades} portfolio={portfolio}
              historyMode onExitPosition={handleExitPosition} onExitAllPositions={handleExitAllPositions} onUpdateStopLoss={handleUpdateStopLoss} onOpenReport={() => setShowDailyReportModal(true)} />
          </div>
          <div id="terminal-debate-history" hidden={historyView !== 'debates'} />
        </section>

        <section id="terminal-panel-chat" role="tabpanel" aria-labelledby="terminal-tab-chat" hidden={activeTab !== 'terminal' || terminalTab !== 'chat'} className="max-w-7xl mx-auto">
          <DebateArena key={user?.id || 'guest'} selectedIndex={selectedIndex} onSelectIndex={(idx) => { setSelectedIndex(idx); setSelectedContract(null); }}
            onExecuteTrade={handleExecuteDebateTrade} onOpenHistory={openDebateHistory} onOpenChat={() => openTerminal('chat')}
            historyVisible={activeTab === 'terminal' && terminalTab === 'history' && historyView === 'debates'}
            onTradeChanged={(msg) => { if (msg) showToast(msg, 'success'); syncTradingState(); }} />
        </section>

        {/* Tab 2: OI & Greeks Analysis */}
        {activeTab === 'oi' && (
          <div className="max-w-6xl mx-auto">
            <Suspense fallback={<div className="p-4 text-slate-500">Loading…</div>}><PcrOiPanel selectedIndex={selectedIndex} spotPrice={spotPrice} /></Suspense>
          </div>
        )}

        {/* Tab 3: P&L Journal & Calendar Heatmap */}
        {activeTab === 'pnl' && (
          <div className="max-w-6xl mx-auto">
            <Suspense fallback={<div className="p-4 text-slate-500">Loading…</div>}><PnlHeatmap /></Suspense>
          </div>
        )}

        {/* Tab 4: Strategy Payoff Analyzer */}
        {activeTab === 'payoff' && (
          <div className="max-w-6xl mx-auto">
            <Suspense fallback={<div className="p-4 text-slate-500">Loading…</div>}><StrategyPayoff
              selectedIndex={selectedIndex}
              spotPrice={spotPrice}
              onExecuteSuccess={() => {
                syncTradingState();
                openTerminal('trade');
              }}
            /></Suspense>
          </div>
        )}

      </main>

      <BottomNav activeTab={activeTab} setActiveTab={(tab) => tab === 'terminal' ? openTerminal('trade') : setActiveTab(tab)} positionsCount={positions.length} />

      {/* Instant 1-Click Order Modal */}
      {orderModalData && (
        <OrderModal
          orderData={orderModalData}
          availableCash={portfolio.available_margin ?? portfolio.cash_balance ?? portfolio.capital ?? 1000000}
          onClose={() => setOrderModalData(null)}
          onSubmitOrder={handlePlaceOrder}
        />
      )}

      {/* Position Size & Risk Calculator Modal */}
      {showCalculator && (
        <PositionSizeModal
          availableCapital={portfolio.available_margin ?? portfolio.cash_balance ?? portfolio.capital ?? 1000000}
          selectedIndex={selectedIndex}
          onClose={() => setShowCalculator(false)}
          onApplyToOrder={(data) => {
            setOrderModalData({
              symbol: data.symbol,
              strike: spotPrice,
              optionType: 'CE',
              side: 'BUY',
              lots: data.lots,
              ltp: data.price,
              bid: data.price,
              ask: data.price,
              lotSize: selectedIndex === 'BANKNIFTY' ? 15 : 25,
            });
          }}
        />
      )}

      {/* Keyboard Shortcuts Modal */}
      {showShortcuts && (
        <ShortcutsModal onClose={() => setShowShortcuts(false)} />
      )}

      {/* AI Daily Trading Report Modal */}
      <Suspense fallback={<div className="p-4 text-slate-500">Loading…</div>}><DailyReportModal
        isOpen={showDailyReportModal}
        onClose={() => setShowDailyReportModal(false)}
      /></Suspense>

      {/* Authentication Modal (Sign In / Register) */}
      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
        initialTab={authModalTab}
        onAuthSuccess={(msg) => {
          showToast(msg, 'success');
          syncTradingState();
        }}
      />
    </div>
  );
}
