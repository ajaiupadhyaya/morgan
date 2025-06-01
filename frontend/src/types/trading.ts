export interface Position {
  symbol: string;
  quantity: number;
  averagePrice: number;
  currentPrice: number;
  marketValue: number;
  unrealizedPnL: number;
  realizedPnL: number;
  entryDate: string;
  lastUpdateDate: string;
}

export interface Order {
  id: string;
  symbol: string;
  type: 'market' | 'limit';
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  status: 'pending' | 'filled' | 'cancelled' | 'rejected';
  timestamp: string;
  filledAt?: string;
  filledPrice?: number;
  reason?: string;
}

export interface OrderBook {
  symbol: string;
  timestamp: string;
  bids: [number, number][]; // [price, quantity]
  asks: [number, number][]; // [price, quantity]
}

export interface Trade {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  timestamp: string;
  orderId: string;
}

export interface MarketData {
  symbol: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap: number;
  trades: number;
} 