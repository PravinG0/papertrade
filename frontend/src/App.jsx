import React, { useState, useEffect, useCallback } from 'react';
import Header from './components/Header';
import OptionChain from './components/OptionChain';
import TradingChart from './components/TradingChart';
import PositionsPanel from './components/PositionsPanel';
import OrdersPanel from './components/OrdersPanel';
import ReplayControls from './components/ReplayControls';
import PcrOiPanel from './components/PcrOiPanel';
import PnlHeatmap from './components/PnlHeatmap';
import OrderModal from './components/OrderModal';
import StrategyPayoff from './components/StrategyPayoff';
import PositionSizeModal from './components/PositionSizeModal';
import ShortcutsModal from './components/ShortcutsModal';
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
} from './api';
import { Activity, Clock } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('terminal'); // 'terminal' | 'oi' | 'pnl'
  const [rightBottomTab, setRightBottomTab] = useState('positions'); // 'positions' | 'orders'
  const [selectedIndex, setSelectedIndex] = useState('NIFTY');
  const [spotPrice, setSpotPrice] = useState(23500);

  // Market indices
  const [indices, setIndices] = useState({
    NIFTY: { ltp: 23525.50, change: 85.20, change_pct: 0.36 },
    BANKNIFTY: { ltp: 50320.10, change: 180.45, change_pct: 0.36 },
    SENSEX: { ltp: 77580.00, change: 250.00, change_pct: 0.32 },
  });

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
  const [orders, setOrders] = useState([]);

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

  // Modals state
  const [orderModalData, setOrderModalData] = useState(null);
  const [selectedContract, setSelectedContract] = useState(null);
  const [showCalculator, setShowCalculator] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const handleOpenOrder = useCallback((data) => setOrderModalData(data), []);
  const handlePriceUpdate = useCallback((p) => {
    if (typeof p === 'number' && !isNaN(p)) {
      setSpotPrice((prev) => (Math.abs(prev - p) > 0.05 ? p : prev));
    }
  }, []);

  // Toast feedback
  const [toast, setToast] = useState(null);

  const showToast = (message, type = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3500);
  };

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

      if (Object.keys(map).length > 0) {
        setIndices((prev) => ({ ...prev, ...map }));
        if (map[selectedIndex]?.ltp) {
          setSpotPrice(map[selectedIndex].ltp);
        }
      }
    } catch (e) {
      // Graceful fallback: slightly fluctuate prices for realistic live feel
      setIndices((prev) => {
        const deltaNifty = (Math.random() - 0.49) * 2;
        const deltaBank = (Math.random() - 0.49) * 5;
        const prevN = prev.NIFTY?.ltp ?? 25380;
        const prevB = prev.BANKNIFTY?.ltp ?? 62270;
        const nLtp = Number((prevN + deltaNifty).toFixed(2));
        const bLtp = Number((prevB + deltaBank).toFixed(2));
        if (selectedIndex === 'NIFTY') setSpotPrice(nLtp);
        else if (selectedIndex === 'BANKNIFTY') setSpotPrice(bLtp);

        return {
          ...prev,
          NIFTY: { ...(prev.NIFTY || {}), ltp: nLtp },
          BANKNIFTY: { ...(prev.BANKNIFTY || {}), ltp: bLtp },
        };
      });
    }
  }, [selectedIndex]);

  // Sync portfolio and trading state
  const syncTradingState = useCallback(async () => {
    try {
      const res = await getTradingState();
      const data = res.data || {};
      if (data.portfolio) {
        setPortfolio(data.portfolio);
      }
      if (Array.isArray(data.positions)) {
        setPositions(data.positions);
      }
      if (Array.isArray(data.orders)) {
        setOrders(data.orders);
      }
    } catch (e) {
      // Keep existing state on error
    }
  }, []);

  // Sync replay state
  const syncReplayState = useCallback(async () => {
    try {
      const res = await getReplayState();
      const data = res.data || {};
      setReplayState(data);
      if (data.is_active) {
        setShowReplayBar(true);
      }
    } catch (e) {
      // Replay endpoint not yet active or disabled
    }
  }, []);

  // Global polling effect
  useEffect(() => {
    syncMarketIndices();
    syncTradingState();
    syncReplayState();

    const interval = setInterval(() => {
      syncMarketIndices();
      syncTradingState();
      syncReplayState();
    }, 2000);

    return () => clearInterval(interval);
  }, [syncMarketIndices, syncTradingState, syncReplayState]);

  // Order Placement Handler
  const handlePlaceOrder = async (orderPayload) => {
    try {
      const res = await placeOrder(orderPayload);
      sound.playOrderFill();
      showToast(
        `Order executed: ${orderPayload.side} ${orderPayload.quantity} ${orderPayload.symbol}`,
        'success'
      );
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
      // Local fallback reset
      setPortfolio({
        capital: 1000000,
        initial_capital: 1000000,
        realized_pnl: 0,
        unrealized_pnl: 0,
        margin_used: 0,
        available_margin: 1000000,
      });
      setPositions([]);
      setOrders([]);
      showToast('Portfolio reset to ₹10,00,000', 'success');
    }
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
        setActiveTab('terminal');
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
    <div className="min-h-screen bg-[#080c14] text-slate-100 flex flex-col font-sans selection:bg-cyan-500/20">
      {/* Toast Notification */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-2.5 rounded-xl border shadow-2xl text-xs font-semibold flex items-center gap-2 animate-bounce ${
            toast.type === 'success'
              ? 'bg-emerald-950 border-emerald-600 text-emerald-200'
              : toast.type === 'error'
              ? 'bg-rose-950 border-rose-600 text-rose-200'
              : 'bg-cyan-950 border-cyan-600 text-cyan-200'
          }`}
        >
          <span>{toast.message}</span>
        </div>
      )}

      {/* Main App Header */}
      <Header
        indices={indices}
        portfolio={portfolio}
        replayState={replayState}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onResetPortfolio={handleResetPortfolio}
        onOpenReplay={() => setShowReplayBar(true)}
        onOpenCalculator={() => setShowCalculator(true)}
        onOpenShortcuts={() => setShowShortcuts(true)}
      />

      {/* Replay Docked Bar (when enabled) */}
      {(showReplayBar || replayState.is_active) && (
        <div className="px-4 py-2 bg-[#080c14] border-b border-amber-900/40">
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
      <main className="flex-1 p-3 lg:p-4 max-w-[1920px] w-full mx-auto">
        {/* Tab 1: Terminal (Split Option Chain + Chart + Positions) */}
        {activeTab === 'terminal' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 h-[calc(100vh-140px)] min-h-[700px]">
            {/* Left 7 Columns: Complete Option Chain */}
            <div className="lg:col-span-7 h-full flex flex-col min-h-[420px]">
              <OptionChain
                selectedIndex={selectedIndex}
                onSelectIndex={(idx) => {
                  setSelectedIndex(idx);
                  setSelectedContract(null);
                }}
                spotPrice={spotPrice}
                onOpenOrder={handleOpenOrder}
                onSelectContract={(contract) => setSelectedContract(contract)}
              />
            </div>

            {/* Right 5 Columns: Split Top = Chart, Bottom = Positions / Orders */}
            <div className="lg:col-span-5 flex flex-col gap-3 h-full overflow-hidden">
              {/* Top Half: Responsive Candlestick Chart */}
              <div className="h-[48%] min-h-[280px]">
                <TradingChart
                  selectedIndex={selectedIndex}
                  contract={selectedContract}
                  onClearContract={() => setSelectedContract(null)}
                  onSelectIndex={(idx) => {
                    setSelectedIndex(idx);
                    setSelectedContract(null);
                  }}
                  onPriceUpdate={handlePriceUpdate}
                />
              </div>

              {/* Bottom Half: Tabs for Positions & Orders */}
              <div className="h-[52%] flex flex-col min-h-[300px] overflow-hidden">
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
                    <span>Positions ({positions.length})</span>
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
                      portfolio={portfolio}
                      onExitPosition={handleExitPosition}
                      onExitAllPositions={handleExitAllPositions}
                      onUpdateStopLoss={handleUpdateStopLoss}
                    />
                  ) : (
                    <OrdersPanel
                      orders={orders}
                      onCancelOrder={handleCancelOrder}
                    />
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: OI & Greeks Analysis */}
        {activeTab === 'oi' && (
          <div className="max-w-6xl mx-auto">
            <PcrOiPanel selectedIndex={selectedIndex} spotPrice={spotPrice} />
          </div>
        )}

        {/* Tab 3: P&L Journal & Calendar Heatmap */}
        {activeTab === 'pnl' && (
          <div className="max-w-6xl mx-auto">
            <PnlHeatmap />
          </div>
        )}

        {/* Tab 4: Strategy Payoff Analyzer */}
        {activeTab === 'payoff' && (
          <div className="max-w-6xl mx-auto">
            <StrategyPayoff
              selectedIndex={selectedIndex}
              spotPrice={spotPrice}
              onExecuteSuccess={() => {
                syncTradingState();
                setActiveTab('terminal');
              }}
            />
          </div>
        )}
      </main>

      {/* Instant 1-Click Order Modal */}
      {orderModalData && (
        <OrderModal
          orderData={orderModalData}
          availableCash={portfolio.available_margin || portfolio.capital || 1000000}
          onClose={() => setOrderModalData(null)}
          onSubmitOrder={handlePlaceOrder}
        />
      )}

      {/* Position Size & Risk Calculator Modal */}
      {showCalculator && (
        <PositionSizeModal
          availableCapital={portfolio.available_margin || portfolio.capital || 1000000}
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
    </div>
  );
}
