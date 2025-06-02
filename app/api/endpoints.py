from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Optional, Any
from datetime import datetime
import redis
from redis.exceptions import RedisError
import json
import logging

# Core application imports
from app.core.config import settings
from app.core import security # Using the consolidated security module
from app.db.session import get_db
from app.models.user import User # SQLAlchemy User model
from app.models.trade import Trade # Assuming Trade model is in app.models.trade
# from app.models.prediction import Prediction # If you have a Prediction model

# Services and Engines
from app.services.trading import TradingService
from app.ml.engine import MLEngine

# Schemas (assuming these will be created)
# from app.schemas.trade import TradeResponse, TradeCreate # Example
# from app.schemas.prediction import PredictionResponse # Example
# from app.schemas.account import AccountResponse # Example
# For now, using Dict or Any where specific schemas are pending

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Application Endpoints"] # General tag for these core app endpoints
)

# Initialize ML Engine
try:
    ml_engine = MLEngine()
except Exception as e:
    logger.critical(f"Failed to initialize MLEngine: {e}", exc_info=True)
    ml_engine = None # Or raise to prevent app startup

# Initialize Redis Client
try:
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("Successfully connected to Redis.")
except RedisError as e:
    logger.error(f"Failed to connect to Redis: {e}. Caching will be disabled.", exc_info=True)
    redis_client = None
except Exception as e: # Catch other potential errors like misconfiguration
    logger.error(f"An unexpected error occurred during Redis initialization: {e}. Caching will be disabled.", exc_info=True)
    redis_client = None


# --- Helper Function to Get User-Specific Trading Service ---
def get_user_trading_service(current_user: User) -> Optional[TradingService]:
    """
    Helper to instantiate TradingService with user-specific decrypted Alpaca keys.
    """
    if not current_user.alpaca_api_key or not current_user.alpaca_secret_key:
        logger.warning(f"User {current_user.email} has no Alpaca API keys configured.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alpaca API keys are not configured for this account. Please add them via /auth/api-keys/alpaca."
        )

    decrypted_api_key = security.decrypt_data_field(current_user.alpaca_api_key)
    decrypted_secret_key = security.decrypt_data_field(current_user.alpaca_secret_key)

    if not decrypted_api_key or not decrypted_secret_key:
        logger.error(f"Failed to decrypt Alpaca keys for user {current_user.email}.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not decrypt API keys. Check server logs."
        )
    
    # Determine base_url based on user's preference (paper/live)
    base_url = settings.ALPACA_BASE_URL # Default
    if hasattr(current_user, 'alpaca_is_paper') and current_user.alpaca_is_paper is False:
        # TODO: Define a LIVE Alpaca URL in settings if it's different and user is not paper trading
        # base_url = settings.ALPACA_LIVE_BASE_URL 
        pass # For now, assuming settings.ALPACA_BASE_URL can be paper or live based on key type

    return TradingService(
        api_key=decrypted_api_key,
        secret_key=decrypted_secret_key,
        base_url=base_url # Or determine live/paper from user.alpaca_is_paper
    )

# --- API Endpoints ---

@router.get("/health", summary="Health Check")
async def health_check():
    """
    Provides a basic health check of the API.
    """
    # TODO: Could be expanded to check DB and Redis connectivity
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@router.get("/account", summary="Get Alpaca Account Information") # response_model=AccountResponse - Add when schema is defined
async def get_account_info(
    current_user: User = Depends(security.get_current_active_user)
) -> Dict[str, Any]: # Replace with AccountResponse
    """
    Retrieves Alpaca account information for the authenticated user.
    Uses user-specific, decrypted Alpaca API keys.
    """
    logger.info(f"Fetching Alpaca account info for user: {current_user.email}")
    trading_service = get_user_trading_service(current_user)
    if not trading_service: # Should be handled by HTTPException in helper
        return {"error": "Trading service could not be initialized"} 

    try:
        account = trading_service.get_account()
        if account is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to retrieve account info from Alpaca.")
        return account
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving account info for {current_user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while fetching account information.")


@router.get("/portfolio", summary="Get Alpaca Portfolio Information") # response_model=PortfolioResponse - Add when schema is defined
async def get_portfolio_info(
    current_user: User = Depends(security.get_current_active_user)
) -> Dict[str, Any]: # Replace with PortfolioResponse
    """
    Retrieves Alpaca portfolio information (positions, value) for the authenticated user.
    """
    logger.info(f"Fetching Alpaca portfolio info for user: {current_user.email}")
    trading_service = get_user_trading_service(current_user)
    
    try:
        # Example: Combine multiple calls from TradingService
        portfolio_value = trading_service.get_portfolio_value()
        positions = trading_service.get_positions()
        
        if portfolio_value is None: # Positions can be an empty list
             raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to retrieve portfolio value from Alpaca.")

        return {
            "user_email": current_user.email,
            "total_portfolio_value": portfolio_value,
            "positions": positions
            # Add other relevant portfolio metrics
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving portfolio info for {current_user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while fetching portfolio information.")


# Define a Pydantic model for TradeResponse if not already done in schemas
# Example:
# class TradeResponse(BaseModel):
#     id: int
#     symbol: str
#     side: str
#     quantity: float
#     price: float
#     timestamp: datetime
#     model_used: Optional[str] = None
#     confidence: Optional[float] = None
#     order_id: Optional[str] = None
#     class Config:
#         from_attributes = True

@router.get("/trades", summary="Get User's Trade History from DB") # response_model=List[TradeResponse]
async def get_db_trade_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user),
    skip: int = 0,
    limit: int = 100
) -> List[Dict[str, Any]]: # Replace with List[TradeResponse]
    """
    Retrieves the trade history for the authenticated user from the application's database.
    """
    logger.info(f"Fetching trade history from DB for user: {current_user.email}")
    try:
        trades = (
            db.query(Trade)
            .filter(Trade.user_id == current_user.id)
            .order_by(Trade.timestamp.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        # Convert SQLAlchemy models to dicts, or use Pydantic model_validate if TradeResponse is defined
        return [
            { # Manually construct dict if TradeResponse schema is not ready
                "id": trade.id, "symbol": trade.symbol, "side": trade.side,
                "quantity": trade.quantity, "price": trade.price, "timestamp": trade.timestamp,
                "model_used": trade.model_used, "confidence": trade.confidence, "order_id": trade.order_id
            } for trade in trades
        ]
    except Exception as e:
        logger.error(f"Database error fetching trade history for {current_user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not retrieve trade history.")


@router.post("/train/{symbol}", summary="Train ML Model for a Symbol")
async def train_model_for_symbol(
    symbol: str,
    model_type: str = Query("lstm", enum=["lstm", "xgboost"], description="Type of model to train."),
    epochs: Optional[int] = Query(50, description="Number of epochs for LSTM training."), # Example extra param
    # current_user: User = Depends(security.get_current_active_user) # If only admins can train
    # For now, assuming any authenticated user can trigger training for exploration
    # Or, if it's resource-intensive, restrict to admin/specific roles.
    # For simplicity, let's make it accessible to authenticated users for now.
    current_user: User = Depends(security.get_current_active_user)
) -> Dict[str, str]:
    """
    Triggers training for a specified ML model and symbol.
    Requires authentication.
    """
    logger.info(f"Model training requested for {symbol} ({model_type}) by user {current_user.email}")
    if not ml_engine:
        logger.error("MLEngine not available for training.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ML Engine is not available.")

    success = False
    if model_type == "lstm":
        success = ml_engine.train_lstm(symbol, epochs=epochs if epochs else 50)
    elif model_type == "xgboost":
        success = ml_engine.train_xgboost(symbol) # Add params like n_estimators if needed
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported model type: {model_type}")

    if success:
        return {"message": f"{model_type.upper()} model training initiated successfully for {symbol}."}
    else:
        logger.error(f"Model training failed for {symbol} ({model_type}). Check ML Engine logs.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to train {model_type} model for {symbol}.")


# Define PredictionResponse schema
# class PredictionResponse(BaseModel):
#     symbol: str
#     predicted_price: float
#     confidence: float
#     model_type: str
#     latest_data_date: str

@router.get("/predict/{symbol}", summary="Get ML Prediction for a Symbol") # response_model=PredictionResponse
async def get_prediction(
    symbol: str,
    model_type: str = Query("lstm", enum=["lstm", "xgboost"], description="Type of model for prediction."),
    current_user: User = Depends(security.get_current_active_user) # Protected endpoint
) -> Dict[str, Any]: # Replace with PredictionResponse
    """
    Fetches an ML prediction for a given symbol. Uses Redis for caching.
    Requires authentication.
    """
    logger.info(f"Prediction requested for {symbol} ({model_type}) by user {current_user.email}")
    if not ml_engine:
        logger.error("MLEngine not available for prediction.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ML Engine is not available.")
    if not redis_client:
        logger.warning("Redis client not available. Prediction will not be cached.")
    
    cache_key = f"prediction:{symbol}:{model_type}"
    
    if redis_client:
        try:
            cached_result = redis_client.get(cache_key)
            if cached_result:
                logger.info(f"Returning cached prediction for {symbol} ({model_type}).")
                return json.loads(cached_result)
        except RedisError as e:
            logger.warning(f"Redis error getting cache for {cache_key}: {e}. Fetching new prediction.")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to decode cached JSON for {cache_key}: {e}. Fetching new prediction.")


    prediction_result = ml_engine.predict(symbol, model_type=model_type)
    if "error" in prediction_result:
        logger.error(f"Prediction error for {symbol} ({model_type}): {prediction_result['error']}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=prediction_result["error"])

    if redis_client:
        try:
            redis_client.setex(cache_key, settings.PREDICTION_CACHE_TTL, json.dumps(prediction_result))
            logger.info(f"Cached new prediction for {symbol} ({model_type}).")
        except RedisError as e:
            logger.warning(f"Redis error setting cache for {cache_key}: {e}")
        except (TypeError, OverflowError) as serialization_error:
            logger.error(f"Failed to serialize prediction_data for caching {cache_key}: {serialization_error}")
            
    return prediction_result


@router.post("/execute-trade/{symbol}", summary="Execute a Trade Based on ML Prediction") # response_model=TradeExecutionResponse (define this)
async def execute_ml_trade(
    symbol: str,
    model_type: str = Query("lstm", enum=["lstm", "xgboost"], description="ML model to use for the trade decision."),
    confidence_threshold: float = Query(0.7, ge=0, le=1, description="Minimum model confidence to execute trade."),
    risk_per_trade: float = Query(0.01, gt=0, le=0.1, description="Fraction of portfolio to risk per trade."), # Example limits
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Dict[str, Any]: # Replace with a proper TradeExecutionResponse schema
    """
    Executes a trade for the given symbol based on the ML model's prediction.
    Uses user-specific Alpaca keys and logs the trade to the database.
    """
    logger.info(
        f"Trade execution requested for {symbol} by user {current_user.email} "
        f"using {model_type} model (confidence_threshold={confidence_threshold}, risk={risk_per_trade})."
    )
    
    trading_service = get_user_trading_service(current_user)
    if not ml_engine: # Check if ml_engine was initialized
        logger.error("MLEngine not available for trade execution.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ML Engine is not available.")

    try:
        # The execute_trade method in TradingService handles fetching prediction,
        # checking confidence, calculating size, placing order, and DB logging.
        trade_execution_result = trading_service.execute_trade(
            db=db,
            symbol=symbol,
            model_type=model_type,
            user_id=current_user.id,
            confidence_threshold=confidence_threshold,
            risk_per_trade=risk_per_trade
        )
        
        if trade_execution_result.get("status") == "error":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, # Or 500 if it's a server-side execution issue
                detail=trade_execution_result.get("message", "Trade execution failed.")
            )
        
        logger.info(f"Trade execution for {symbol} by {current_user.email} resulted in: {trade_execution_result.get('status')}")
        return trade_execution_result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during trade execution for {symbol} by {current_user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred during trade execution.")


# Define BacktestResponse schema
# class BacktestResponse(BaseModel):
#     symbol: str
#     model_type: str
#     directional_accuracy: Optional[float] = None
#     results_summary: Optional[List[Dict]] = None
#     error: Optional[str] = None

@router.get("/backtest/{symbol}", summary="Run Backtest for a Symbol and Model") # response_model=BacktestResponse
async def run_backtest(
    symbol: str,
    model_type: str = Query("lstm", enum=["lstm", "xgboost"], description="Model to backtest."),
    lookback: int = Query(60, description="Lookback period for features."),
    test_data_points: int = Query(50, description="Number of data points for testing."),
    current_user: User = Depends(security.get_current_active_user) # Protected endpoint
) -> Dict[str, Any]: # Replace with BacktestResponse
    """
    Runs a simplified backtest for the given symbol and model type.
    Requires authentication.
    Note: Current TradingService.backtest_strategy uses yfinance, not live Alpaca data.
    If it were to use live Alpaca data or account-specific parameters,
    get_user_trading_service() would be needed here.
    """
    logger.info(
        f"Backtest requested for {symbol} ({model_type}) by user {current_user.email} "
        f"with lookback={lookback}, test_points={test_data_points}."
    )
    if not ml_engine: # Check if ml_engine was initialized
        logger.error("MLEngine not available for backtesting.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ML Engine is not available.")

    # The backtest_strategy in TradingService currently uses MLEngine which uses yfinance.
    # It does not require live Alpaca keys for its current implementation.
    # If TradingService itself was needed for parameters from the live account,
    # then we would instantiate it with user keys.
    # For now, directly calling the method from a generic TradingService instance is okay
    # if it doesn't depend on user-specific live Alpaca account state.
    # However, for consistency, let's assume TradingService might evolve.
    # For now, the original code's direct instantiation is fine as backtest_simple/strategy
    # in our refined TradingService doesn't use self.api directly.
    
    # This instantiation is only if backtest_strategy needed API keys.
    # trading_service = get_user_trading_service(current_user)
    # For now, the backtest is self-contained in TradingService using MLEngine
    
    # Re-instantiate a generic TradingService if its methods are static or don't need user keys
    # Or, if backtest_strategy becomes a static method or part of MLEngine.
    # For simplicity, let's assume TradingService can be instantiated without keys if only using backtest_strategy.
    # This depends on the final design of TradingService.backtest_strategy.
    # The original code instantiated it with global keys for backtest.
    # Our refined TradingService.backtest_strategy does not use self.api.
    
    # Let's assume the backtest_strategy is part of the ml_engine or can be called without a fully authenticated trading_service
    # For now, to match the structure of TradingService:
    # This is a bit awkward if backtest_strategy doesn't need API keys.
    # A better design might be to move backtest_strategy to MLEngine or make it callable without live API keys.
    
    # Simplest approach: if backtest_strategy in TradingService doesn't use self.api,
    # we can instantiate a dummy TradingService or make backtest_strategy a static/class method.
    # Given our TradingService.backtest_strategy uses ml_engine:
    
    # Let's assume backtest_strategy is a method of TradingService that doesn't need live keys.
    # We can instantiate a dummy one or make it a static method.
    # For now, let's assume it's okay to call it on a TradingService instance that might not have valid keys
    # IF AND ONLY IF backtest_strategy itself doesn't use self.api.
    # Our refined TradingService.backtest_strategy does NOT use self.api.
    
    # Create a temporary service instance for backtesting if it doesn't require user keys
    # This is a slight simplification; ideally, backtesting logic might be separate or
    # clearly demarcated if it needs no live API interaction.
    temp_trading_service = TradingService(api_key="dummy", secret_key="dummy", base_url=settings.ALPACA_BASE_URL)

    try:
        backtest_result = temp_trading_service.backtest_strategy(
            symbol=symbol,
            model_type=model_type,
            lookback=lookback,
            test_data_points=test_data_points
        )
        if backtest_result is None or "error" in (backtest_result or {}):
            error_detail = (backtest_result or {}).get("error", "Backtest failed or returned no result.")
            logger.error(f"Backtest for {symbol} ({model_type}) failed: {error_detail}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_detail)
        
        return backtest_result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during backtest for {symbol} ({model_type}): {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred during backtest.")


@router.get("/models", summary="List Supported ML Models")
async def list_supported_models() -> Dict[str, List[str]]:
    """
    Lists the ML model types supported by the system for training and prediction.
    """
    # This could be made dynamic by inspecting MLEngine or a config
    return {"supported_models": ["lstm", "xgboost"]}