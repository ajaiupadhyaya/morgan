import { Position, Order } from '../types/trading';

export interface StrategyConfig {
  name: string;
  description: string;
  riskLevel: 'low' | 'medium' | 'high';
  maxPositionSize: number;
  stopLossPercentage: number;
  takeProfitPercentage: number;
  maxDrawdown: number;
  rebalanceFrequency: 'daily' | 'weekly' | 'monthly';
  indicators: string[];
}

export interface MarketData {
  symbol: string;
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  indicators: Record<string, number>;
}

export abstract class BaseStrategy {
  protected config: StrategyConfig;
  protected positions: Position[];
  protected performance: {
    totalReturn: number;
    sharpeRatio: number;
    maxDrawdown: number;
    winRate: number;
  };

  constructor(config: StrategyConfig) {
    this.config = config;
    this.positions = [];
    this.performance = {
      totalReturn: 0,
      sharpeRatio: 0,
      maxDrawdown: 0,
      winRate: 0,
    };
  }

  abstract analyze(marketData: MarketData): Promise<{
    signal: 'buy' | 'sell' | 'hold';
    confidence: number;
    reason: string;
  }>;

  abstract optimize(historicalData: MarketData[]): Promise<void>;

  abstract backtest(historicalData: MarketData[]): Promise<{
    totalReturn: number;
    sharpeRatio: number;
    maxDrawdown: number;
    winRate: number;
    trades: Order[];
  }>;

  protected calculatePositionSize(capital: number, riskPerTrade: number): number {
    const maxRiskAmount = capital * (riskPerTrade / 100);
    return Math.min(maxRiskAmount, this.config.maxPositionSize);
  }

  protected calculateStopLoss(entryPrice: number, direction: 'long' | 'short'): number {
    const stopLossPercentage = this.config.stopLossPercentage / 100;
    return direction === 'long'
      ? entryPrice * (1 - stopLossPercentage)
      : entryPrice * (1 + stopLossPercentage);
  }

  protected calculateTakeProfit(entryPrice: number, direction: 'long' | 'short'): number {
    const takeProfitPercentage = this.config.takeProfitPercentage / 100;
    return direction === 'long'
      ? entryPrice * (1 + takeProfitPercentage)
      : entryPrice * (1 - takeProfitPercentage);
  }

  protected updatePerformance(returns: number[]): void {
    this.performance.totalReturn = returns.reduce((a, b) => a + b, 0);
    this.performance.sharpeRatio = this.calculateSharpeRatio(returns);
    this.performance.maxDrawdown = this.calculateMaxDrawdown(returns);
    this.performance.winRate = this.calculateWinRate(returns);
  }

  private calculateSharpeRatio(returns: number[]): number {
    const riskFreeRate = 0.02; // 2% annual risk-free rate
    const excessReturns = returns.map(r => r - riskFreeRate / 252); // Daily risk-free rate
    const avgExcessReturn = excessReturns.reduce((a, b) => a + b, 0) / returns.length;
    const stdDev = Math.sqrt(
      excessReturns.reduce((a, b) => a + Math.pow(b - avgExcessReturn, 2), 0) / returns.length
    );
    return stdDev === 0 ? 0 : (avgExcessReturn / stdDev) * Math.sqrt(252);
  }

  private calculateMaxDrawdown(returns: number[]): number {
    let peak = 0;
    let maxDrawdown = 0;
    let currentValue = 1;

    returns.forEach(return_ => {
      currentValue *= (1 + return_);
      if (currentValue > peak) {
        peak = currentValue;
      }
      const drawdown = (peak - currentValue) / peak;
      maxDrawdown = Math.max(maxDrawdown, drawdown);
    });

    return maxDrawdown;
  }

  private calculateWinRate(returns: number[]): number {
    const winningTrades = returns.filter(r => r > 0).length;
    return returns.length === 0 ? 0 : winningTrades / returns.length;
  }
} 