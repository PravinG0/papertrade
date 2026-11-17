import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
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
export const getMe = () => api.get('/auth/me');
export const logoutUser = () => api.post('/auth/logout');

// Attach helpers directly on api object as requested
api.register = registerUser;
api.login = loginUser;
api.getMe = getMe;
api.logout = logoutUser;

// Market Feed Endpoints
export const getStatus = () => api.get('/status');

export const getIndices = () => api.get('/indices');

export const getCandles = (symbol = 'NIFTY', interval = '15m', range_period = '5d', strike = null, option_type = null) =>
  api.get('/candles', {
    params: {
      symbol,
      interval,
      range: range_period,
      range_period,
      ...(strike ? { strike } : {}),
      ...(option_type ? { option_type } : {}),
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

export const placeOrder = (orderData) => api.post('/trading/order', orderData);

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

export default api;
