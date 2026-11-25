import axios from 'axios';

const getBaseUrl = () => {
  const envUrl = import.meta.env?.VITE_API_URL;
  if (envUrl && envUrl.trim()) {
    const clean = envUrl.trim().replace(/\/$/, '');
    return clean.endsWith('/api') ? clean : `${clean}/api`;
  }
  // Default to Render production backend if running on Vercel
  if (typeof window !== 'undefined' && window.location.hostname.includes('vercel.app')) {
    return 'https://papertrade-1-uv24.onrender.com/api';
  }
  return '/api';
};

const api = axios.create({
  baseURL: getBaseUrl(),
  timeout: 20000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor: attach JWT Bearer token if present in localStorage
api.interceptors.request.use(
  (config) => {
    try {
      const token = localStorage.getItem('token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    } catch (e) {
      // Ignore localStorage access errors
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Authentication Endpoints
export const registerUser = (userData) => api.post('/auth/register', userData);
export const loginUser = (credentials) => api.post('/auth/login', credentials);
export const googleLogin = (credential) => api.post('/auth/google', { credential });
export const getMe = () => api.get('/auth/me');
export const logoutUser = () => api.post('/auth/logout');

export const auth = {
  register: registerUser,
  login: loginUser,
  googleLogin,
  getMe,
  logout: logoutUser,
};

// Attach helpers directly on api object as requested
api.register = registerUser;
api.login = loginUser;
api.googleLogin = googleLogin;
api.getMe = getMe;
api.logout = logoutUser;
api.auth = auth;

// Market Feed Endpoints
export const getStatus = () => api.get('/status');

export const getIndices = () => api.get('/indices');

export const getCandles = (symbol = 'NIFTY', interval = '15m', range_period = '5d', strike = null, option_type = null, expiry = null, signal) =>
  api.get('/candles', {
    signal,
    params: {
      symbol,
      interval,
      range: range_period,
      range_period,
      ...(strike ? { strike } : {}),
      ...(option_type ? { option_type } : {}),
      ...(expiry ? { expiry } : {}),
    },
  });

export const getOptionChain = (symbol = 'NIFTY', strikes = 10, expiry = null) =>
  api.get('/option-chain', {
    params: {
      symbol,
      strikes,
      ...(expiry ? { expiry } : {}),
    },
  });

export const getExpiries = (symbol = 'NIFTY') =>
  api.get('/expiries', {
    params: { symbol },
  });

// Trading & Portfolio Endpoints
export const getTradingState = () => api.get('/trading/state');

export const placeOrder = (orderData) => api.post('/trading/order', orderData, { timeout: 45000 });

export const cancelOrder = (id) =>
  api.post(`/trading/order/${id}/cancel`).catch(() => api.delete(`/trading/order/${id}`));

export const exitPosition = (id) =>
  api.post(`/trading/position/${id}/exit`).catch(() => api.post('/trading/exit', { position_id: id }));

export const exitAllPositions = () =>
  api.post('/trading/exit-all').catch(() => api.post('/trading/positions/exit-all'));

export const updateStopLoss = (id, slPrice) =>
  api.post(`/trading/position/${id}/stoploss`, { stop_loss: Number(slPrice) })
    .catch(() => api.put(`/trading/position/${id}`, { stop_loss: Number(slPrice) }));

export const resetPortfolio = () => api.post('/trading/reset');

export const getTradeHistory = () => api.get('/trading/history');
export const exportTradeHistory = () => api.get('/trading/export', { responseType: 'blob' });

export const getAllTrades = () => api.get('/trading/all-trades');

// Daily Trading Report Endpoints
export const getDailyReport = (date = null) =>
  api.get('/reports/daily', { params: date ? { date } : {} });

export const generateDailyReport = (date = null) =>
  api.post('/reports/daily/generate', { date }, { timeout: 60000 });

export const getReportDates = () => api.get('/reports/dates');

// Replay Mode Endpoints
export const getReplayDates = () => api.get('/replay/dates');

export const startReplay = (date) =>
  api.post('/replay/start', typeof date === 'object' ? date : { date });

export const controlReplay = (action, speed = 1) =>
  api.post('/replay/control', { action, speed });

export const getReplayState = () => api.get('/replay/state');

// Institutional & Analytics Endpoints
export const getPcrOi = (symbol = 'NIFTY') =>
  api.get('/analytics/pcr-oi', {
    params: { symbol },
  }).catch(() => api.get('/pcr-oi', { params: { symbol } }));

export const getPnlCalendar = () =>
  api.get('/analytics/pnl-calendar').catch(() => api.get('/trading/pnl-calendar'));

export const getStrategyPayoff = (payload) =>
  api.post('/analytics/payoff', payload);

// AI Debate Studio Endpoints (90-second timeout to allow Bull, Bear & Judge LLM deliberation)
export const runDebate = (symbol = 'NIFTY') =>
  api.post('/debate/run', { symbol }, { timeout: 90000 });

export const getLatestDebate = (symbol = null) =>
  api.get('/debate/latest', { params: symbol ? { symbol } : {} });

export const getDebateHistory = (limit = 20) =>
  api.get('/debate/history', { params: { limit } });

export const executeDebateVerdict = (debateId, payload = {}) =>
  api.post(`/debate/${debateId}/execute`, payload);

// Auto-Debate Scheduler Endpoints
export const startScheduler = (payload = {}) =>
  api.post('/scheduler/start', payload, { timeout: 30000 });

export const stopScheduler = () =>
  api.post('/scheduler/stop');

export const getSchedulerStatus = () =>
  api.get('/scheduler/status');

api.startScheduler = startScheduler;
api.stopScheduler = stopScheduler;
api.getSchedulerStatus = getSchedulerStatus;

export default api;
