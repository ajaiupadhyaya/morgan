import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add a request interceptor to include the auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Auth endpoints
export const auth = {
  login: async (email: string, password: string) => {
    const response = await api.post('/token', { email, password });
    return response.data;
  },
  register: async (email: string, password: string) => {
    const response = await api.post('/register', { email, password });
    return response.data;
  },
  getCurrentUser: async () => {
    const response = await api.get('/me');
    return response.data;
  },
};

// Trading endpoints
export const trading = {
  getPortfolio: async () => {
    const response = await api.get('/portfolio');
    return response.data;
  },
  getPositions: async () => {
    const response = await api.get('/positions');
    return response.data;
  },
  placeOrder: async (order: {
    symbol: string;
    quantity: number;
    type: 'BUY' | 'SELL';
    price?: number;
  }) => {
    const response = await api.post('/orders', order);
    return response.data;
  },
  getOrders: async () => {
    const response = await api.get('/orders');
    return response.data;
  },
};

// Analytics endpoints
export const analytics = {
  getPerformance: async () => {
    const response = await api.get('/analytics/performance');
    return response.data;
  },
  getPortfolioHistory: async () => {
    const response = await api.get('/analytics/portfolio-history');
    return response.data;
  },
  getTopPerformers: async () => {
    const response = await api.get('/analytics/top-performers');
    return response.data;
  },
};

// Settings endpoints
export const settings = {
  updateUserSettings: async (settings: {
    riskTolerance: 'low' | 'medium' | 'high';
    maxPositionSize: number;
    stopLossPercentage: number;
    takeProfitPercentage: number;
  }) => {
    const response = await api.put('/settings/user', settings);
    return response.data;
  },
  updateApiSettings: async (settings: {
    alpacaApiKey: string;
    alpacaApiSecret: string;
    alpacaEndpoint: string;
    polygonApiKey?: string;
  }) => {
    const response = await api.put('/settings/api', settings);
    return response.data;
  },
  getSettings: async () => {
    const response = await api.get('/settings');
    return response.data;
  },
};

export default api; 