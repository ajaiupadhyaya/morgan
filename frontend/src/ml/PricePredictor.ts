import * as tf from '@tensorflow/tfjs';
import type { MarketData } from '../types/trading';

interface PredictionConfig {
  sequenceLength: number;
  predictionHorizon: number;
  features: string[];
  target: string;
  validationSplit: number;
  epochs: number;
  batchSize: number;
}

export class PricePredictor {
  private model: tf.LayersModel | null = null;
  private config: PredictionConfig;
  private scaler: {
    min: number;
    max: number;
  } = { min: 0, max: 1 };

  constructor(config: PredictionConfig) {
    this.config = config;
  }

  async buildModel(): Promise<void> {
    const model = tf.sequential();

    // LSTM layers for sequence processing
    model.add(
      tf.layers.lstm({
        units: 50,
        returnSequences: true,
        inputShape: [this.config.sequenceLength, this.config.features.length],
      })
    );
    model.add(tf.layers.dropout({ rate: 0.2 }));
    model.add(
      tf.layers.lstm({
        units: 30,
        returnSequences: false,
      })
    );
    model.add(tf.layers.dropout({ rate: 0.2 }));

    // Dense layers for prediction
    model.add(tf.layers.dense({ units: 20, activation: 'relu' }));
    model.add(tf.layers.dense({ units: this.config.predictionHorizon }));

    model.compile({
      optimizer: tf.train.adam(0.001),
      loss: 'meanSquaredError',
      metrics: ['mae'],
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

  private denormalizeData(data: number[][]): number[][] {
    return data.map(row =>
      row.map(
        value => value * (this.scaler.max - this.scaler.min) + this.scaler.min
      )
    );
  }

  private prepareSequences(data: MarketData[]): {
    X: tf.Tensor;
    y: tf.Tensor;
  } {
    const sequences: number[][] = [];
    const targets: number[] = [];

    for (let i = 0; i < data.length - this.config.sequenceLength - this.config.predictionHorizon; i++) {
      const sequence = data
        .slice(i, i + this.config.sequenceLength)
        .map(d => this.config.features.map(f => d[f as keyof MarketData] as number));
      sequences.push(sequence.flat());

      const target = data[i + this.config.sequenceLength + this.config.predictionHorizon - 1][
        this.config.target as keyof MarketData
      ] as number;
      targets.push(target);
    }

    const normalizedSequences = this.normalizeData(sequences);
    const normalizedTargets = this.normalizeData([targets])[0];

    return {
      X: tf.tensor3d(
        normalizedSequences.map(seq =>
          Array.from({ length: this.config.sequenceLength }, (_, i) =>
            seq.slice(i * this.config.features.length, (i + 1) * this.config.features.length)
          )
        )
      ),
      y: tf.tensor2d(normalizedTargets, [normalizedTargets.length, 1]),
    };
  }

  async train(historicalData: MarketData[]): Promise<void> {
    if (!this.model) {
      await this.buildModel();
    }

    const { X, y } = this.prepareSequences(historicalData);
    const validationSplit = this.config.validationSplit;

    await this.model!.fit(X, y, {
      epochs: this.config.epochs,
      batchSize: this.config.batchSize,
      validationSplit,
      callbacks: {
        onEpochEnd: (epoch: number, logs?: tf.Logs) => {
          console.log(
            `Epoch ${epoch + 1}: loss = ${logs?.loss.toFixed(4)}, val_loss = ${logs?.val_loss.toFixed(4)}`
          );
        },
      },
    });

    X.dispose();
    y.dispose();
  }

  async predict(recentData: MarketData[]): Promise<number[]> {
    if (!this.model) {
      throw new Error('Model not trained');
    }

    if (recentData.length < this.config.sequenceLength) {
      throw new Error('Insufficient data for prediction');
    }

    const sequence = recentData
      .slice(-this.config.sequenceLength)
      .map(d => this.config.features.map(f => d[f as keyof MarketData] as number));

    const normalizedSequence = this.normalizeData([sequence.flat()])[0];
    const input = tf.tensor3d(
      [Array.from({ length: this.config.sequenceLength }, (_, i) =>
        normalizedSequence.slice(i * this.config.features.length, (i + 1) * this.config.features.length)
      )]
    );

    const prediction = this.model.predict(input) as tf.Tensor;
    const normalizedPrediction = await prediction.array() as number[][];
    const denormalizedPrediction = this.denormalizeData(normalizedPrediction)[0];

    input.dispose();
    prediction.dispose();

    return denormalizedPrediction;
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