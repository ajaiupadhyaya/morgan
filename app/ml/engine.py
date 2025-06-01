import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
import xgboost as xgb
from sklearn.preprocessing import MinMaxScaler
import joblib
import os
from datetime import datetime, timedelta
import yfinance as yf
from app.core.config import settings

class MLEngine:
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.model_path = settings.MODEL_PATH
        os.makedirs(self.model_path, exist_ok=True)
        
    def prepare_data(self, symbol: str, lookback: int = 60) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare data for model training/prediction"""
        # Fetch historical data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        df = yf.download(symbol, start=start_date, end=end_date)
        
        # Calculate technical indicators
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['RSI'] = self._calculate_rsi(df['Close'])
        df['MACD'] = self._calculate_macd(df['Close'])
        
        # Prepare features
        features = ['Close', 'Volume', 'SMA_20', 'SMA_50', 'RSI', 'MACD']
        data = df[features].values
        
        # Scale the data
        scaler = MinMaxScaler()
        scaled_data = scaler.fit_transform(data)
        
        # Create sequences
        X, y = [], []
        for i in range(lookback, len(scaled_data)):
            X.append(scaled_data[i-lookback:i])
            y.append(scaled_data[i, 0])  # Predict next day's close price
            
        return np.array(X), np.array(y), scaler
    
    def train_lstm(self, symbol: str, epochs: int = 50) -> None:
        """Train LSTM model for a given symbol"""
        X, y, scaler = self.prepare_data(symbol)
        
        # Build LSTM model
        model = Sequential([
            LSTM(units=50, return_sequences=True, input_shape=(X.shape[1], X.shape[2])),
            Dropout(0.2),
            LSTM(units=50, return_sequences=False),
            Dropout(0.2),
            Dense(units=1)
        ])
        
        model.compile(optimizer='adam', loss='mean_squared_error')
        model.fit(X, y, epochs=epochs, batch_size=32, validation_split=0.1, verbose=0)
        
        # Save model and scaler
        model.save(os.path.join(self.model_path, f'lstm_{symbol}.h5'))
        joblib.dump(scaler, os.path.join(self.model_path, f'scaler_{symbol}.pkl'))
        
        self.models[f'lstm_{symbol}'] = model
        self.scalers[f'scaler_{symbol}'] = scaler
    
    def train_xgboost(self, symbol: str) -> None:
        """Train XGBoost model for a given symbol"""
        X, y, scaler = self.prepare_data(symbol)
        X = X.reshape(X.shape[0], -1)  # Flatten the input
        
        model = xgb.XGBRegressor(
            objective='reg:squarederror',
            n_estimators=100,
            learning_rate=0.1,
            max_depth=5
        )
        
        model.fit(X, y)
        
        # Save model and scaler
        joblib.dump(model, os.path.join(self.model_path, f'xgb_{symbol}.pkl'))
        joblib.dump(scaler, os.path.join(self.model_path, f'scaler_xgb_{symbol}.pkl'))
        
        self.models[f'xgb_{symbol}'] = model
        self.scalers[f'scaler_xgb_{symbol}'] = scaler
    
    def predict(self, symbol: str, model_type: str = 'lstm') -> Dict:
        """Make prediction for a given symbol"""
        if f'{model_type}_{symbol}' not in self.models:
            self.load_model(symbol, model_type)
            
        X, _, scaler = self.prepare_data(symbol)
        model = self.models[f'{model_type}_{symbol}']
        
        if model_type == 'lstm':
            prediction = model.predict(X[-1:])
        else:  # xgboost
            X_flat = X[-1:].reshape(1, -1)
            prediction = model.predict(X_flat)
            
        # Inverse transform prediction
        prediction = scaler.inverse_transform(
            np.concatenate([prediction, np.zeros((1, scaler.n_features_in_ - 1))], axis=1)
        )[:, 0]
        
        return {
            'symbol': symbol,
            'prediction': float(prediction[0]),
            'timestamp': datetime.now().isoformat(),
            'model_type': model_type
        }
    
    def load_model(self, symbol: str, model_type: str) -> None:
        """Load saved model and scaler"""
        model_path = os.path.join(self.model_path, f'{model_type}_{symbol}.h5' if model_type == 'lstm' else f'{model_type}_{symbol}.pkl')
        scaler_path = os.path.join(self.model_path, f'scaler_{symbol}.pkl')
        
        if model_type == 'lstm':
            self.models[f'{model_type}_{symbol}'] = load_model(model_path)
        else:
            self.models[f'{model_type}_{symbol}'] = joblib.load(model_path)
            
        self.scalers[f'scaler_{symbol}'] = joblib.load(scaler_path)
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_macd(self, prices: pd.Series) -> pd.Series:
        """Calculate MACD"""
        exp1 = prices.ewm(span=12, adjust=False).mean()
        exp2 = prices.ewm(span=26, adjust=False).mean()
        return exp1 - exp2 