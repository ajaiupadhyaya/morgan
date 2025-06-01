import * as tf from '@tensorflow/tfjs';
import * as use from '@tensorflow-models/universal-sentence-encoder';

interface SentimentConfig {
  modelUrl: string;
  threshold: number;
  maxSequenceLength: number;
}

interface SentimentResult {
  score: number;
  label: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  keywords: string[];
}

export class SentimentAnalyzer {
  private model: use.UniversalSentenceEncoder | null = null;
  private config: SentimentConfig;
  private keywords: Set<string>;

  constructor(config: SentimentConfig) {
    this.config = config;
    this.keywords = new Set([
      'bullish', 'bearish', 'growth', 'decline', 'profit', 'loss',
      'positive', 'negative', 'outperform', 'underperform', 'buy',
      'sell', 'hold', 'upgrade', 'downgrade', 'target', 'forecast',
      'earnings', 'revenue', 'guidance', 'dividend', 'acquisition',
      'merger', 'spinoff', 'bankruptcy', 'restructuring', 'layoff',
      'hiring', 'expansion', 'contraction', 'innovation', 'disruption',
      'competition', 'market share', 'pricing', 'cost', 'efficiency',
      'productivity', 'quality', 'service', 'customer', 'supplier',
      'regulation', 'compliance', 'risk', 'opportunity', 'threat',
      'strength', 'weakness', 'advantage', 'disadvantage', 'trend',
      'momentum', 'volatility', 'liquidity', 'leverage', 'debt',
      'equity', 'cash', 'investment', 'return', 'yield', 'premium',
      'discount', 'valuation', 'multiple', 'ratio', 'margin',
      'efficiency', 'growth', 'decline', 'stability', 'uncertainty',
    ]);
  }

  async initialize(): Promise<void> {
    this.model = await use.load();
  }

  private preprocessText(text: string): string {
    return text
      .toLowerCase()
      .replace(/[^\w\s]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, this.config.maxSequenceLength);
  }

  private extractKeywords(text: string): string[] {
    const words = text.toLowerCase().split(/\s+/);
    return words.filter(word => this.keywords.has(word));
  }

  private async getEmbedding(text: string): Promise<tf.Tensor> {
    if (!this.model) {
      throw new Error('Model not initialized');
    }
    const embeddings = await this.model.embed([text]);
    return embeddings;
  }

  private calculateSentimentScore(embedding: tf.Tensor): number {
    // Simple sentiment scoring based on embedding similarity with positive/negative reference points
    const positiveReference = tf.tensor1d([1, 1, 1, 1, 1]);
    const negativeReference = tf.tensor1d([-1, -1, -1, -1, -1]);

    const positiveSimilarity = tf.matMul(embedding, positiveReference);
    const negativeSimilarity = tf.matMul(embedding, negativeReference);

    const score = (positiveSimilarity.dataSync()[0] - negativeSimilarity.dataSync()[0]) / 2;
    return Math.max(-1, Math.min(1, score));
  }

  async analyzeSentiment(text: string): Promise<SentimentResult> {
    if (!this.model) {
      await this.initialize();
    }

    const preprocessedText = this.preprocessText(text);
    const embedding = await this.getEmbedding(preprocessedText);
    const score = this.calculateSentimentScore(embedding);
    const keywords = this.extractKeywords(preprocessedText);

    let label: 'bullish' | 'bearish' | 'neutral';
    if (score > this.config.threshold) {
      label = 'bullish';
    } else if (score < -this.config.threshold) {
      label = 'bearish';
    } else {
      label = 'neutral';
    }

    const confidence = Math.abs(score);

    embedding.dispose();

    return {
      score,
      label,
      confidence,
      keywords,
    };
  }

  async analyzeBatch(texts: string[]): Promise<SentimentResult[]> {
    if (!this.model) {
      await this.initialize();
    }

    const results: SentimentResult[] = [];
    for (const text of texts) {
      const result = await this.analyzeSentiment(text);
      results.push(result);
    }

    return results;
  }

  async saveModel(path: string): Promise<void> {
    if (!this.model) {
      throw new Error('No model to save');
    }
    await this.model.save(`file://${path}`);
  }

  async loadModel(path: string): Promise<void> {
    this.model = await use.load({ modelUrl: path });
  }
} 