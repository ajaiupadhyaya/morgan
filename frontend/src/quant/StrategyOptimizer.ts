import * as tf from '@tensorflow/tfjs';
import type { MarketData } from '../types/trading';
import type { StrategyConfig } from '../strategies/BaseStrategy';

interface OptimizationConfig {
  populationSize: number;
  generations: number;
  mutationRate: number;
  crossoverRate: number;
  objective: 'sharpeRatio' | 'sortinoRatio' | 'calmarRatio' | 'maxDrawdown';
  constraints: {
    maxPositionSize: [number, number];
    stopLossPercentage: [number, number];
    takeProfitPercentage: [number, number];
    maxDrawdown: [number, number];
  };
}

interface OptimizationResult {
  parameters: StrategyConfig;
  metrics: {
    sharpeRatio: number;
    sortinoRatio: number;
    calmarRatio: number;
    maxDrawdown: number;
    totalReturn: number;
    winRate: number;
  };
}

export class StrategyOptimizer {
  private config: OptimizationConfig;
  private model: tf.LayersModel | null = null;

  constructor(config: OptimizationConfig) {
    this.config = config;
  }

  async buildModel(): Promise<void> {
    const model = tf.sequential();

    // Input layer for strategy parameters
    model.add(
      tf.layers.dense({
        units: 64,
        activation: 'relu',
        inputShape: [4], // [positionSize, stopLoss, takeProfit, maxDrawdown]
      })
    );
    model.add(tf.layers.dropout({ rate: 0.2 }));
    model.add(tf.layers.dense({ units: 32, activation: 'relu' }));
    model.add(tf.layers.dropout({ rate: 0.2 }));
    model.add(tf.layers.dense({ units: 16, activation: 'relu' }));
    model.add(tf.layers.dense({ units: 1, activation: 'linear' })); // Performance prediction

    model.compile({
      optimizer: tf.train.adam(0.001),
      loss: 'meanSquaredError',
      metrics: ['mae'],
    });

    this.model = model;
  }

  private generateInitialPopulation(): StrategyConfig[] {
    const population: StrategyConfig[] = [];
    for (let i = 0; i < this.config.populationSize; i++) {
      population.push({
        name: `Strategy_${i}`,
        description: 'Optimized strategy',
        riskLevel: 'medium',
        maxPositionSize: this.randomInRange(...this.config.constraints.maxPositionSize),
        stopLossPercentage: this.randomInRange(...this.config.constraints.stopLossPercentage),
        takeProfitPercentage: this.randomInRange(...this.config.constraints.takeProfitPercentage),
        maxDrawdown: this.randomInRange(...this.config.constraints.maxDrawdown),
        rebalanceFrequency: 'daily',
        indicators: ['sma', 'ema', 'rsi', 'macd'],
      });
    }
    return population;
  }

  private randomInRange(min: number, max: number): number {
    return min + Math.random() * (max - min);
  }

  private calculateMetrics(returns: number[]): {
    sharpeRatio: number;
    sortinoRatio: number;
    calmarRatio: number;
    maxDrawdown: number;
    totalReturn: number;
    winRate: number;
  } {
    const totalReturn = returns.reduce((a, b) => a + b, 0);
    const avgReturn = totalReturn / returns.length;
    const stdDev = Math.sqrt(
      returns.reduce((a, b) => a + Math.pow(b - avgReturn, 2), 0) / returns.length
    );

    // Sharpe Ratio
    const riskFreeRate = 0.02; // 2% annual risk-free rate
    const sharpeRatio = stdDev === 0 ? 0 : (avgReturn - riskFreeRate / 252) / stdDev * Math.sqrt(252);

    // Sortino Ratio
    const downsideReturns = returns.filter(r => r < 0);
    const downsideStdDev = Math.sqrt(
      downsideReturns.reduce((a, b) => a + Math.pow(b, 2), 0) / returns.length
    );
    const sortinoRatio = downsideStdDev === 0 ? 0 : (avgReturn - riskFreeRate / 252) / downsideStdDev * Math.sqrt(252);

    // Maximum Drawdown
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

    // Calmar Ratio
    const calmarRatio = maxDrawdown === 0 ? 0 : (avgReturn * 252) / maxDrawdown;

    // Win Rate
    const winRate = returns.filter(r => r > 0).length / returns.length;

    return {
      sharpeRatio,
      sortinoRatio,
      calmarRatio,
      maxDrawdown,
      totalReturn,
      winRate,
    };
  }

  private async evaluateStrategy(
    strategy: StrategyConfig,
    historicalData: MarketData[]
  ): Promise<OptimizationResult> {
    // Simulate strategy performance
    const returns: number[] = [];
    let position = 0;
    let entryPrice = 0;

    for (let i = 1; i < historicalData.length; i++) {
      const currentData = historicalData[i];

      // Simple moving average crossover strategy
      const sma20 = this.calculateSMA(historicalData.slice(Math.max(0, i - 20), i + 1));
      const sma50 = this.calculateSMA(historicalData.slice(Math.max(0, i - 50), i + 1));

      if (position === 0) {
        if (sma20 > sma50) {
          position = 1;
          entryPrice = currentData.close;
        } else if (sma20 < sma50) {
          position = -1;
          entryPrice = currentData.close;
        }
      } else {
        const stopLoss = position === 1
          ? entryPrice * (1 - strategy.stopLossPercentage / 100)
          : entryPrice * (1 + strategy.stopLossPercentage / 100);
        const takeProfit = position === 1
          ? entryPrice * (1 + strategy.takeProfitPercentage / 100)
          : entryPrice * (1 - strategy.takeProfitPercentage / 100);

        if (
          (position === 1 && currentData.low <= stopLoss) ||
          (position === -1 && currentData.high >= stopLoss) ||
          (position === 1 && currentData.high >= takeProfit) ||
          (position === -1 && currentData.low <= takeProfit)
        ) {
          const exitPrice = position === 1 ? Math.min(stopLoss, takeProfit) : Math.max(stopLoss, takeProfit);
          const return_ = position * (exitPrice - entryPrice) / entryPrice;
          returns.push(return_);
          position = 0;
        }
      }
    }

    const metrics = this.calculateMetrics(returns);

    return {
      parameters: strategy,
      metrics,
    };
  }

  private calculateSMA(data: MarketData[]): number {
    return data.reduce((sum, d) => sum + d.close, 0) / data.length;
  }

  private crossover(parent1: StrategyConfig, parent2: StrategyConfig): StrategyConfig {
    return {
      name: `Strategy_${Math.random().toString(36).substr(2, 9)}`,
      description: 'Optimized strategy',
      riskLevel: Math.random() < 0.5 ? parent1.riskLevel : parent2.riskLevel,
      maxPositionSize: Math.random() < 0.5 ? parent1.maxPositionSize : parent2.maxPositionSize,
      stopLossPercentage: Math.random() < 0.5 ? parent1.stopLossPercentage : parent2.stopLossPercentage,
      takeProfitPercentage: Math.random() < 0.5 ? parent1.takeProfitPercentage : parent2.takeProfitPercentage,
      maxDrawdown: Math.random() < 0.5 ? parent1.maxDrawdown : parent2.maxDrawdown,
      rebalanceFrequency: Math.random() < 0.5 ? parent1.rebalanceFrequency : parent2.rebalanceFrequency,
      indicators: [...new Set([...parent1.indicators, ...parent2.indicators])],
    };
  }

  private mutate(strategy: StrategyConfig): StrategyConfig {
    const mutated = { ...strategy };
    if (Math.random() < this.config.mutationRate) {
      mutated.maxPositionSize = this.randomInRange(...this.config.constraints.maxPositionSize);
    }
    if (Math.random() < this.config.mutationRate) {
      mutated.stopLossPercentage = this.randomInRange(...this.config.constraints.stopLossPercentage);
    }
    if (Math.random() < this.config.mutationRate) {
      mutated.takeProfitPercentage = this.randomInRange(...this.config.constraints.takeProfitPercentage);
    }
    if (Math.random() < this.config.mutationRate) {
      mutated.maxDrawdown = this.randomInRange(...this.config.constraints.maxDrawdown);
    }
    return mutated;
  }

  async optimize(historicalData: MarketData[]): Promise<OptimizationResult> {
    let population = this.generateInitialPopulation();
    let bestResult: OptimizationResult | null = null;

    for (let generation = 0; generation < this.config.generations; generation++) {
      const results = await Promise.all(
        population.map(strategy => this.evaluateStrategy(strategy, historicalData))
      );

      // Update best result
      const currentBest = results.reduce((best, current) => {
        const bestMetric = best.metrics[this.config.objective];
        const currentMetric = current.metrics[this.config.objective];
        return currentMetric > bestMetric ? current : best;
      });

      if (!bestResult || currentBest.metrics[this.config.objective] > bestResult.metrics[this.config.objective]) {
        bestResult = currentBest;
      }

      // Selection
      const sortedResults = results.sort(
        (a, b) => b.metrics[this.config.objective] - a.metrics[this.config.objective]
      );
      const selected = sortedResults.slice(0, Math.floor(population.length / 2));

      // Crossover and Mutation
      const newPopulation: StrategyConfig[] = [];
      while (newPopulation.length < this.config.populationSize) {
        const parent1 = selected[Math.floor(Math.random() * selected.length)].parameters;
        const parent2 = selected[Math.floor(Math.random() * selected.length)].parameters;
        let child = this.crossover(parent1, parent2);
        child = this.mutate(child);
        newPopulation.push(child);
      }

      population = newPopulation;

      console.log(
        `Generation ${generation + 1}: Best ${this.config.objective} = ${bestResult.metrics[this.config.objective].toFixed(4)}`
      );
    }

    if (!bestResult) {
      throw new Error('Optimization failed to find a solution');
    }

    return bestResult;
  }

  async saveModel(path: string): Promise<void> {
    if (!this.model) {
      throw new Error('No model to save');
    }
    await this.model.save(`file://${path}`);
  }

  async loadModel(path: string): Promise<void> {
    this.model = await tf.loadLayersModel(`file://${path}`);
  }
} 