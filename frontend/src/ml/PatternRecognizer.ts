import * as tf from '@tensorflow/tfjs';
import type { MarketData } from '../types/trading';

interface PatternConfig {
  windowSize: number;
  patterns: {
    name: string;
    description: string;
    minConfidence: number;
  }[];
}

interface PatternResult {
  pattern: string;
  confidence: number;
  startIndex: number;
  endIndex: number;
  description: string;
}

export class PatternRecognizer {
  private model: tf.LayersModel | null = null;
  private config: PatternConfig;
  private scaler: {
    min: number;
    max: number;
  } = { min: 0, max: 1 };

  constructor(config: PatternConfig) {
    this.config = config;
  }

  async buildModel(): Promise<void> {
    const model = tf.sequential();

    // Convolutional layers for pattern detection
    model.add(
      tf.layers.conv1d({
        filters: 32,
        kernelSize: 3,
        activation: 'relu',
        inputShape: [this.config.windowSize, 5], // OHLCV
      })
    );
    model.add(tf.layers.maxPooling1d({ poolSize: 2 }));
    model.add(
      tf.layers.conv1d({
        filters: 64,
        kernelSize: 3,
        activation: 'relu',
      })
    );
    model.add(tf.layers.maxPooling1d({ poolSize: 2 }));
    model.add(tf.layers.flatten());

    // Dense layers for pattern classification
    model.add(tf.layers.dense({ units: 64, activation: 'relu' }));
    model.add(tf.layers.dropout({ rate: 0.3 }));
    model.add(tf.layers.dense({ units: this.config.patterns.length, activation: 'softmax' }));

    model.compile({
      optimizer: tf.train.adam(0.001),
      loss: 'categoricalCrossentropy',
      metrics: ['accuracy'],
    });

    this.model = model;
  }

  private normalizeData(data: number[][]): number[][] {
    const flatData = data.flat();
    this.scaler.min = Math.min(...flatData);
    this.scaler.max = Math.max(...flatData);
    return data.map(row =>
      row.map(value => (value - this.scaler.min) / (this.scaler.max - this.scaler.min))
    );
  }

  private prepareData(data: MarketData[]): tf.Tensor {
    const sequences: number[][] = [];
    for (let i = 0; i <= data.length - this.config.windowSize; i++) {
      const sequence = data
        .slice(i, i + this.config.windowSize)
        .map(d => [d.open, d.high, d.low, d.close, d.volume]);
      sequences.push(sequence.flat());
    }

    const normalizedSequences = this.normalizeData(sequences);
    return tf.tensor3d(
      normalizedSequences.map(seq =>
        Array.from({ length: this.config.windowSize }, (_, i) =>
          seq.slice(i * 5, (i + 1) * 5)
        )
      )
    );
  }

  async train(historicalData: MarketData[], labels: number[]): Promise<void> {
    if (!this.model) {
      await this.buildModel();
    }

    const X = this.prepareData(historicalData);
    const y = tf.oneHot(tf.tensor1d(labels, 'int32'), this.config.patterns.length);

    await this.model!.fit(X, y, {
      epochs: 50,
      batchSize: 32,
      validationSplit: 0.2,
      callbacks: {
        onEpochEnd: (epoch: number, logs?: tf.Logs) => {
          console.log(
            `Epoch ${epoch + 1}: loss = ${logs?.loss.toFixed(4)}, accuracy = ${logs?.acc.toFixed(4)}`
          );
        },
      },
    });

    X.dispose();
    y.dispose();
  }

  async detectPatterns(data: MarketData[]): Promise<PatternResult[]> {
    if (!this.model) {
      throw new Error('Model not trained');
    }

    if (data.length < this.config.windowSize) {
      throw new Error('Insufficient data for pattern detection');
    }

    const X = this.prepareData(data);
    const predictions = this.model.predict(X) as tf.Tensor;
    const predictionArray = await predictions.array() as number[][];

    const results: PatternResult[] = [];
    for (let i = 0; i < predictionArray.length; i++) {
      const patternIndex = predictionArray[i].indexOf(Math.max(...predictionArray[i]));
      const confidence = predictionArray[i][patternIndex];

      if (confidence >= this.config.patterns[patternIndex].minConfidence) {
        results.push({
          pattern: this.config.patterns[patternIndex].name,
          confidence,
          startIndex: i,
          endIndex: i + this.config.windowSize - 1,
          description: this.config.patterns[patternIndex].description,
        });
      }
    }

    X.dispose();
    predictions.dispose();

    return results;
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