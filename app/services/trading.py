import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import APIError
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy.orm import Session
import redis
from redis.exceptions import RedisError
import json
from json.decoder import JSONDecodeError
import logging
import numpy as np # Added for backtest_strategy

# Assuming these are correctly set up in your project structure
from app.core.config import settings
from app.models.models import Trade # Assuming your SQLAlchemy model is named Trade
from app.ml.engine import MLEngine

# Configure logging
logger = logging.getLogger(__name__)

# Initialize Redis client and ML Engine
# For production, consider dependency injection for these for better testability
try:
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    r.ping() # Check connection
    logger.info("Successfully connected to Redis.")
except RedisError as e:
    logger.error(f"Failed to connect to Redis: {e}")
    # Depending on the application's needs, you might want to exit or have a fallback
    r = None # Or a mock/dummy Redis client

ml_engine = MLEngine()


class TradingService:
    """
    Service class for handling trading operations, including communication
    with the Alpaca API, trade execution based on ML predictions,
    and basic backtesting.
    """
    def __init__(self, api_key: str, secret_key: str, base_url: str):
        """
        Initializes the TradingService with Alpaca API credentials.

        Args:
            api_key: Alpaca API key.
            secret_key: Alpaca API secret key.
            base_url: Alpaca API base URL (e.g., paper or live).
        """
        try:
            self.api = tradeapi.REST(api_key, secret_key, base_url)
            self.api.get_account() # Verify API credentials and connection
            logger.info("Successfully connected to Alpaca API.")
        except APIError as e:
            logger.error(f"Failed to connect to Alpaca API or authenticate: {e}")
            # Handle critical failure, perhaps by raising an exception or setting a state
            self.api = None # Or raise an error to prevent service instantiation
        except Exception as e:
            logger.error(f"An unexpected error occurred during Alpaca API initialization: {e}")
            self.api = None

    def get_account(self) -> Optional[Dict[str, Any]]:
        """
        Retrieves current Alpaca account information.

        Returns:
            A dictionary containing account details, or None if an API error occurs.
        """
        if not self.api:
            logger.error("Alpaca API client not initialized.")
            return None
        try:
            return self.api.get_account()._raw
        except APIError as e:
            logger.error(f"Alpaca API error getting account: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting account: {e}")
            return None

    def get_portfolio_value(self) -> Optional[float]:
        """
        Retrieves the current total equity of the Alpaca portfolio.

        Returns:
            The portfolio equity as a float, or None if an error occurs.
        """
        account = self.get_account()
        if account:
            return float(account.get('equity', 0.0))
        return None

    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Retrieves a list of current open positions in the Alpaca account.

        Returns:
            A list of dictionaries, where each dictionary represents a position.
            Returns an empty list if an error occurs or no positions are found.
        """
        if not self.api:
            logger.error("Alpaca API client not initialized.")
            return []
        try:
            positions = self.api.list_positions()
            return [{
                'symbol': pos.symbol,
                'qty': float(pos.qty),
                'avg_entry_price': float(pos.avg_entry_price),
                'current_price': float(pos.current_price),
                'market_value': float(pos.market_value),
                'unrealized_pl': float(pos.unrealized_pl),
                'unrealized_pl_percent': float(pos.unrealized_plpc), # assuming 'unrealized_plpc' is correct
            } for pos in positions]
        except APIError as e:
            logger.error(f"Alpaca API error getting positions: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error getting positions: {e}")
            return []

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Retrieves the latest ask price for a given symbol.

        Args:
            symbol: The stock symbol (e.g., "AAPL").

        Returns:
            The latest ask price as a float, or None if an error occurs.
        """
        if not self.api:
            logger.error("Alpaca API client not initialized.")
            return None
        try:
            quote = self.api.get_latest_quote(symbol)
            return float(quote.ap) # 'ap' is typically ask price
        except APIError as e:
            logger.error(f"Alpaca API error getting latest price for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting latest price for {symbol}: {e}")
            return None

    def calculate_position_size(self, symbol: str, risk_per_trade: float = 0.01) -> Optional[float]:
        """
        Calculates the position size based on a fixed risk percentage of portfolio equity.
        TODO: Implement more advanced position sizing models (e.g., Kelly Criterion, volatility-based).

        Args:
            symbol: The stock symbol.
            risk_per_trade: The fraction of portfolio equity to risk on this trade (e.g., 0.01 for 1%).

        Returns:
            The calculated quantity of shares to trade, rounded to a sensible precision,
            or None if an error occurs.
        """
        portfolio_value = self.get_portfolio_value()
        if portfolio_value is None:
            logger.error("Could not retrieve portfolio value for position sizing.")
            return None

        current_price = self.get_latest_price(symbol)
        if current_price is None or current_price == 0:
            logger.error(f"Could not retrieve valid price for {symbol} for position sizing.")
            return None

        risk_amount = portfolio_value * risk_per_trade
        quantity = risk_amount / current_price
        
        # TODO: Adjust rounding precision based on asset type or minimum order size.
        # For typical stocks, 0 decimal places for quantity might be appropriate if fractional shares are not allowed.
        # If fractional shares are allowed by Alpaca for the symbol, adjust precision accordingly.
        return round(quantity, 0) # Example: Round to whole shares

    def place_order(self,
                      symbol: str,
                      qty: float,
                      side: str,
                      order_type: str = "market",
                      time_in_force: str = "day",
                      limit_price: Optional[float] = None,
                      stop_price: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Places a trade order with Alpaca.

        Args:
            symbol: The stock symbol.
            qty: The number of shares to trade.
            side: 'buy' or 'sell'.
            order_type: 'market', 'limit', 'stop', 'stop_limit'.
            time_in_force: 'day', 'gtc', 'opg', 'cls', 'ioc', 'fok'.
            limit_price: Required for limit orders.
            stop_price: Required for stop orders.

        Returns:
            A dictionary representing the submitted order, or None if an error occurs.
        """
        if not self.api:
            logger.error("Alpaca API client not initialized. Cannot place order.")
            return None
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type=order_type,
                time_in_force=time_in_force,
                limit_price=limit_price,
                stop_price=stop_price
            )
            logger.info(f"Order submitted for {symbol}: {side} {qty} shares @ {order_type}. Order ID: {order.id}")
            return order._raw
        except APIError as e:
            logger.error(f"Alpaca API error placing order for {symbol} ({side} {qty}): {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error placing order for {symbol}: {e}")
            return None

    def execute_trade(self,
                        db: Session,
                        symbol: str,
                        model_type: str,
                        user_id: int, # Assuming Trade model requires user_id
                        confidence_threshold: float = 0.7, # Example: configurable threshold
                        risk_per_trade: float = 0.01
                        ) -> Dict[str, Any]:
        """
        Executes a trade based on an ML model prediction.
        It checks for cached predictions, fetches new ones if necessary,
        calculates position size, places the order, and logs the trade to the database.

        Args:
            db: SQLAlchemy database session.
            symbol: The stock symbol.
            model_type: The type of ML model to use (e.g., "lstm", "xgboost").
            user_id: The ID of the user initiating the trade.
            confidence_threshold: Minimum model confidence to execute the trade.
            risk_per_trade: Risk percentage for position sizing.

        Returns:
            A dictionary containing the trade execution status and details.
        """
        prediction_data: Optional[Dict[str, Any]] = None
        cache_key = f"prediction:{symbol}:{model_type}"

        if r: # Check if Redis client is available
            try:
                if r.exists(cache_key):
                    cached_value = r.get(cache_key)
                    if cached_value:
                        prediction_data = json.loads(cached_value)
                        logger.info(f"Retrieved prediction for {symbol} ({model_type}) from cache.")
            except RedisError as e:
                logger.warning(f"Redis error checking/getting cache for {cache_key}: {e}")
            except JSONDecodeError as e:
                logger.warning(f"Failed to decode cached JSON for {cache_key}: {e}. Fetching new prediction.")
                prediction_data = None # Force refresh

        if prediction_data is None:
            logger.info(f"No valid cache for {symbol} ({model_type}). Fetching new prediction.")
            prediction_data = ml_engine.predict(symbol, model_type=model_type)
            if r and prediction_data and "error" not in prediction_data:
                try:
                    r.setex(cache_key, settings.PREDICTION_CACHE_TTL, json.dumps(prediction_data))
                    logger.info(f"Cached new prediction for {symbol} ({model_type}).")
                except RedisError as e:
                    logger.warning(f"Redis error setting cache for {cache_key}: {e}")
                except (TypeError, OverflowError) as serialization_error:
                     logger.error(f"Failed to serialize prediction_data for caching {cache_key}: {serialization_error}")


        if not prediction_data or "error" in prediction_data:
            error_msg = prediction_data.get("error", "Unknown error from ML engine") if prediction_data else "No prediction data"
            logger.error(f"Failed to get prediction for {symbol} ({model_type}): {error_msg}")
            return {"status": "error", "message": f"Prediction error: {error_msg}"}

        predicted_price = prediction_data.get("predicted_price") # Or however your prediction is structured
        confidence = prediction_data.get("confidence", 0.0)

        if confidence < confidence_threshold:
            logger.info(f"Trade for {symbol} skipped. Confidence {confidence:.2f} < threshold {confidence_threshold:.2f}.")
            return {"status": "skipped", "message": "Confidence below threshold"}

        current_price = self.get_latest_price(symbol)
        if current_price is None:
            logger.error(f"Could not get current price for {symbol}. Skipping trade.")
            return {"status": "error", "message": "Failed to get current price."}

        # Basic logic: if predicted > current, buy; else sell. Refine as needed.
        # TODO: This logic might be too simple. A robust strategy would consider more factors.
        direction = "buy" if predicted_price > current_price else "sell"

        qty = self.calculate_position_size(symbol, risk_per_trade=risk_per_trade)
        if qty is None or qty <= 0:
            logger.warning(f"Invalid or zero quantity ({qty}) calculated for {symbol}. Skipping trade.")
            return {"status": "skipped", "message": "Invalid or zero quantity for trade."}

        order_response = self.place_order(symbol, qty, direction, order_type="market", time_in_force="day")

        if order_response:
            try:
                trade = Trade(
                    user_id=user_id, # Make sure Trade model has this
                    symbol=symbol,
                    side=direction,
                    quantity=qty,
                    price=current_price,  # Note: This is the price at decision time, not necessarily fill price for market orders.
                    timestamp=datetime.utcnow(),
                    confidence=confidence,
                    predicted_price=predicted_price,
                    model_used=model_type,
                    order_id=order_response.get("id") # Ensure your Trade model has an order_id field
                    # TODO: Add other relevant fields to your Trade model and populate them here.
                )
                db.add(trade)
                db.commit()
                db.refresh(trade) # To get ID or other db-generated fields
                logger.info(f"Trade for {symbol} executed and logged. Order ID: {order_response.get('id')}, DB Trade ID: {trade.id}")
                return {"status": "success", "order": order_response, "trade_log_id": trade.id}
            except Exception as e: # Catch potential DB errors
                logger.error(f"Database error logging trade for {symbol}: {e}")
                db.rollback()
                return {"status": "error", "message": f"DB error: {e}", "order": order_response}
        else:
            logger.error(f"Failed to place order for {symbol}.")
            return {"status": "error", "message": "Order placement failed."}

    def get_trade_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Retrieves trade history (filled orders) from Alpaca for a specified number of past days.

        Args:
            days: Number of past days to fetch history for.

        Returns:
            A list of dictionaries, each representing a filled trade.
            Returns an empty list if an error occurs.
        """
        if not self.api:
            logger.error("Alpaca API client not initialized.")
            return []
        try:
            # Alpaca API expects 'after' or 'until' for date filtering of activities.
            # Using 'after' to get activities since N days ago.
            after_date = (datetime.now() - timedelta(days=days)).isoformat()
            activities = self.api.get_activities(activity_types="FILL", after=after_date, direction="desc")
            
            return [{
                "symbol": a.symbol,
                "side": a.side,
                "qty": float(a.qty),
                "price": float(a.price) if a.price else None, # Filled price
                "timestamp": a.transaction_time.isoformat(),
                "order_id": a.order_id,
                "activity_id": a.id
            } for a in activities]
        except APIError as e:
            logger.error(f"Alpaca API error getting trade history: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error getting trade history: {e}")
            return []

    def backtest_strategy(self, symbol: str, model_type: str = "lstm", lookback: int = 60, test_data_points: int = 50) -> Optional[Dict[str, Any]]:
        """
        Performs a simplified backtest of an ML model's directional accuracy.
        TODO: This is a very basic backtest. For a "perfect" system, implement:
              - Event-driven backtesting.
              - Simulation of slippage and transaction costs.
              - Comprehensive performance metrics (Sharpe, Sortino, Max Drawdown, etc.).
              - Portfolio-based backtesting if managing multiple assets.

        Args:
            symbol: The stock symbol to backtest.
            model_type: "lstm" or "xgboost".
            lookback: Number of historical data points for each prediction sequence.
            test_data_points: Number of recent data points from the prepared data to use for testing.

        Returns:
            A dictionary containing backtest results (e.g., directional accuracy, DataFrame),
            or None if an error occurs.
        """
        try:
            # Assuming ml_engine.prepare_data returns (features, labels, scaler, original_dataframe)
            # The exact return signature of prepare_data needs to be known.
            X, y, _, df_original = ml_engine.prepare_data(symbol, lookback=lookback) #

            if X is None or y is None or X.shape[0] < test_data_points or y.shape[0] < test_data_points:
                logger.error(f"Not enough data for backtesting {symbol} with {test_data_points} points.")
                return None

            y_actual_slice = y[-test_data_points:]
            X_test_slice = X[-test_data_points:]
            y_pred_list = []

            # TODO: Consider if MLEngine should have a more public method for loading models for backtesting
            # to avoid using '_load_..._model' if they are intended as private.
            if model_type == "lstm":
                model = ml_engine._load_lstm_model(symbol) #
                if not model:
                    logger.error(f"Failed to load LSTM model for {symbol} during backtest.")
                    return None
                for x_instance in X_test_slice:
                    pred = model.predict(np.expand_dims(x_instance, axis=0))[0]
                    y_pred_list.append(pred[0] if isinstance(pred, (list, np.ndarray)) else pred)
            elif model_type == "xgboost":
                model = ml_engine._load_xgboost_model(symbol) #
                if not model:
                    logger.error(f"Failed to load XGBoost model for {symbol} during backtest.")
                    return None
                # XGBoost might need X_test_slice reshaped if it was flattened during training
                # Assuming X_test_slice from prepare_data is already in the correct shape per sequence
                # If ml_engine.prepare_data returns 3D LSTM data (samples, timesteps, features),
                # XGBoost might need (samples, timesteps*features)
                # For now, assuming predict method handles reshaping or input is appropriate.
                # The original code had: X[-50:].reshape(50, -1) for xgboost input
                # This implies X_test_slice might need similar reshaping.
                # Let's assume predict method of xgboost model in ml_engine handles the shape or
                # prepare_data already provides a 2D suitable X for xgboost if model_type='xgboost'
                for x_instance in X_test_slice:
                    # Reshape if necessary, matching the training input shape for XGBoost
                    # If X_test_slice is (test_data_points, lookback, num_features)
                    # and XGBoost expects (test_data_points, lookback * num_features)
                    reshaped_x_instance = x_instance.reshape(1, -1) # Flatten each sequence for XGBoost
                    pred = model.predict(reshaped_x_instance)[0]
                    y_pred_list.append(pred)
            else:
                logger.error(f"Unsupported model_type for backtesting: {model_type}")
                return None

            df_bt = pd.DataFrame({"actual_price": y_actual_slice, "predicted_price_signal": y_pred_list})
            
            # Calculate directional accuracy (simple example)
            # Assumes y_actual_slice and y_pred_list are next-period price predictions
            df_bt["actual_direction"] = np.sign(df_bt["actual_price"].diff().fillna(0))
            # Predicted direction based on whether predicted price is > or < current actual (or previous predicted)
            # This part needs careful thought: what is the baseline for predicted direction?
            # If y_pred_list are price predictions, compare to previous actual or a neutral point.
            # For simplicity, let's assume prediction is change from previous actual or a signal strength.
            # The original code compared diffs of actual vs diffs of predicted - this is better.
            # Let's make predicted_price_signal the actual predicted price for next step for consistency.
            df_bt["predicted_direction_from_signal"] = np.sign(df_bt["predicted_price_signal"].diff().fillna(0))


            # Match direction of change from previous day
            actual_price_changes = df_bt["actual_price"].diff().fillna(0)
            predicted_price_changes = df_bt["predicted_price_signal"].diff().fillna(0) # Assuming y_pred_list are target prices

            df_bt["direction_match"] = (np.sign(actual_price_changes) == np.sign(predicted_price_changes)) & (np.sign(actual_price_changes) != 0)
            
            accuracy = df_bt["direction_match"].mean() if not df_bt.empty else 0.0
            
            logger.info(f"Backtest for {symbol} ({model_type}) completed. Directional accuracy: {accuracy:.2%}")
            
            # Return limited results to avoid large data transfer if this is an API endpoint
            return {
                "symbol": symbol,
                "model_type": model_type,
                "directional_accuracy": accuracy,
                "results_summary": df_bt[["actual_price", "predicted_price_signal", "direction_match"]].tail().to_dict('records') # Example summary
                # "full_results_df_json": df_bt.to_json(orient="split") # Optionally return full df
            }
        except Exception as e:
            logger.error(f"Error during backtest for {symbol} ({model_type}): {e}", exc_info=True)
            return None