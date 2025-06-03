# File: app/api/endpoints.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Optional, Any
from datetime import datetime
import redis
from redis.exceptions import RedisError
import json
import logging

# Pydantic Base Model for defining new schemas directly here for now
from pydantic import BaseModel, Field, EmailStr # Added EmailStr

# Core application imports
from app.core.config import settings
from app.core import security
from app.db.session import get_db
from app.models.user import User
from app.models.trade import Trade
# from app.models.prediction import Prediction # If using PredictionResponse for stored predictions
# from app.models.portfolio import Portfolio, Position # If PortfolioResponse/PositionResponse use from_attributes

# Services and Engines
from app.services.trading import TradingService
from app.ml.engine import MLEngine

# --- Schemas ---
# Schemas we assume are already created in app/schemas/
from app.schemas.trade import TradeResponse, TradeExecutionResponse
from app.schemas.prediction import GetPredictionResponse # For /predict endpoint

# TODO: Move the following Pydantic schema definitions to appropriate files
# in the app/schemas/ directory (e.g., app/schemas/account.py, app/schemas/portfolio.py, etc.)

# --- Schemas for Account Endpoint ---
class AccountBalanceSchema(BaseModel):
    """Represents various balances in an account."""
    cash: Optional[float] = None
    buying_power: Optional[float] = None
    equity: Optional[float] = None
    # Add other balance fields as returned by Alpaca, e.g., last_equity, long_market_value

class AccountResponse(BaseModel):
    """
    Schema for the /account endpoint response.
    Reflects typical fields from Alpaca's account object.
    """
    id: str
    account_number: str
    status: str
    currency: str
    buying_power: float
    cash: float
    equity: float
    created_at: datetime # Alpaca provides this, ensure it's parsed to datetime
    # Add other relevant fields like: portfolio_value, daytrade_count, crypto_status, etc.
    # Example:
    # last_equity: Optional[float] = None
    # long_market_value: Optional[float] = None
    # shorting_enabled: Optional[bool] = None
    # ... and so on, based on the actual structure of trading_service.get_account()._raw

# --- Schemas for Portfolio Endpoint ---
class PositionSchema(BaseModel):
    """Schema for an individual position within a portfolio."""
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: Optional[float] = None # current_price can sometimes be None if market is closed or data is delayed
    market_value: float
    unrealized_pl: float
    unrealized_pl_percent: float # Often as 'unrealized_plpc' from APIs

class PortfolioResponse(BaseModel):
    """Schema for the /portfolio endpoint response."""
    user_email: EmailStr # Use Pydantic's EmailStr for validation
    total_portfolio_value: float
    cash_balance: Optional[float] = None # Often useful to show alongside portfolio value
    positions: List[PositionSchema]
    # Add other summary fields like total_return, daily_change_percent if calculated

# --- Schema for Model Training Endpoint ---
class ModelTrainingResponse(BaseModel):
    """Schema for the /train/{symbol} endpoint response."""
    message: str
    symbol: str
    model_type: str
    status: str = Field(default="initiated", description="Status of the training job (e.g., initiated, in_progress, completed, failed)")

# --- Schema for Backtest Endpoint ---
class BacktestResultRowSchema(BaseModel):
    """Schema for a single row in the backtest results summary."""
    actual_price: Optional[float] = None
    predicted_price_signal: Optional[float] = None # Or however your backtest_strategy names it
    direction_match: Optional[bool] = None
    # Add other relevant columns from your backtest DataFrame summary

class BacktestResponse(BaseModel):
    """Schema for the /backtest/{symbol} endpoint response."""
    symbol: str
    model_type: str
    directional_accuracy: Optional[float] = Field(None, ge=0, le=1)
    # results_summary is a list of dicts from df.to_dict('records')
    results_summary: Optional[List[BacktestResultRowSchema]] = None # Make this more specific
    error: Optional[str] = None # If backtest itself encounters an error

# --- End of TODO for moving schemas ---


logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Application Endpoints"]
)

# Initialize ML Engine
try:
    ml_engine = MLEngine()
except Exception as e:
    logger.critical(f"Failed to initialize MLEngine: {e}", exc_info=True)
    ml_engine = None

# Initialize Redis Client
try:
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("Successfully connected to Redis.")
except RedisError as e:
    logger.error(f"Failed to connect to Redis: {e}. Caching will be disabled.", exc_info=True)
    redis_client = None
except Exception as e:
    logger.error(f"An unexpected error occurred during Redis initialization: {e}. Caching will be disabled.", exc_info=True)
    redis_client = None


# --- Helper Function to Get User-Specific Trading Service ---
def get_user_trading_service(current_user: User) -> TradingService: # Return type changed
    """
    Helper to instantiate TradingService with user-specific decrypted Alpaca keys.
    Raises HTTPException if keys are missing or decryption fails.
    """
    if not current_user.alpaca_api_key or not current_user.alpaca_secret_key:
        logger.warning(f"User {current_user.email} has no Alpaca API keys configured.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alpaca API keys are not configured. Please add them via /auth/api-keys/alpaca."
        )

    decrypted_api_key = security.decrypt_data_field(current_user.alpaca_api_key)
    decrypted_secret_key = security.decrypt_data_field(current_user.alpaca_secret_key)

    if not decrypted_api_key or not decrypted_secret_key:
        logger.error(f"Failed to decrypt Alpaca keys for user {current_user.email}.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process API keys. Please check server logs or re-enter your keys."
        )
    
    base_url = settings.ALPACA_BASE_URL
    if hasattr(current_user, 'alpaca_is_paper') and current_user.alpaca_is_paper is False:
        # TODO: Define settings.ALPACA_LIVE_BASE_URL if different from paper
        logger.info(f"User {current_user.email} is configured for live trading.")
        # base_url = settings.ALPACA_LIVE_BASE_URL # Example

    return TradingService(
        api_key=decrypted_api_key,
        secret_key=decrypted_secret_key,
        base_url=base_url
    )

# --- API Endpoints ---

@router.get("/health", summary="Health Check", response_model=Dict[str, Any])
async def health_check() -> Dict[str, Any]:
    """
    Provides a basic health check of the API.
    """
    # TODO: Expand to check DB and Redis connectivity (e.g., simple query, ping)
    db_status = "unknown"
    redis_status = "unknown"
    ml_engine_status = "operational" if ml_engine else "unavailable"

    try:
        db_temp = next(get_db()) # Get a DB session
        db_temp.execute(security.text("SELECT 1")) # Use security.text if importing text from sqlalchemy
        db_status = "operational"
    except Exception:
        db_status = "degraded"
    finally:
        if 'db_temp' in locals() and db_temp: db_temp.close()
    
    if redis_client:
        try:
            redis_client.ping()
            redis_status = "operational"
        except RedisError:
            redis_status = "degraded"
    else:
        redis_status = "unavailable"
        
    return {
        "status": "healthy" if db_status == "operational" and redis_status == "operational" and ml_engine_status == "operational" else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "database": db_status,
            "redis_cache": redis_status,
            "ml_engine": ml_engine_status
        }
    }


@router.get("/account", summary="Get Alpaca Account Information", response_model=AccountResponse)
async def get_account_info(
    current_user: User = Depends(security.get_current_active_user)
) -> AccountResponse:
    """
    Retrieves Alpaca account information for the authenticated user.
    """
    logger.info(f"Fetching Alpaca account info for user: {current_user.email}")
    trading_service = get_user_trading_service(current_user)
    
    try:
        account_data_dict = trading_service.get_account() # This returns a dict (from _raw)
        if account_data_dict is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to retrieve account info from Alpaca.")
        
        # Manually create AccountResponse if keys don't perfectly match or need transformation
        # Example, ensuring datetime is correctly parsed if it comes as string from Alpaca API
        # For now, assuming Alpaca API returns fields that Pydantic can map.
        # If not, you'd do:
        # return AccountResponse(
        #     id=account_data_dict.get('id'),
        #     account_number=account_data_dict.get('account_number'),
        #     status=account_data_dict.get('status'),
        #     currency=account_data_dict.get('currency'),
        #     buying_power=float(account_data_dict.get('buying_power', 0)),
        #     cash=float(account_data_dict.get('cash', 0)),
        #     equity=float(account_data_dict.get('equity', 0)),
        #     created_at=datetime.fromisoformat(account_data_dict.get('created_at')) if account_data_dict.get('created_at') else None,
        #     # ... other fields
        # )
        return AccountResponse(**account_data_dict) # Pydantic will try to map fields
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving account info for {current_user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while fetching account information.")


@router.get("/portfolio", summary="Get Alpaca Portfolio Information", response_model=PortfolioResponse)
async def get_portfolio_info(
    current_user: User = Depends(security.get_current_active_user)
) -> PortfolioResponse:
    """
    Retrieves Alpaca portfolio information (positions, value) for the authenticated user.
    """
    logger.info(f"Fetching Alpaca portfolio info for user: {current_user.email}")
    trading_service = get_user_trading_service(current_user)
    
    try:
        portfolio_value = trading_service.get_portfolio_value()
        # Assuming TradingService.get_account() also provides cash balance
        account_details = trading_service.get_account()
        cash_balance = float(account_details.get('cash', 0)) if account_details else None
        
        positions_data = trading_service.get_positions() # Returns List[Dict]
        
        if portfolio_value is None:
             raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to retrieve portfolio value from Alpaca.")

        return PortfolioResponse(
            user_email=current_user.email,
            total_portfolio_value=portfolio_value,
            cash_balance=cash_balance,
            positions=[PositionSchema(**pos) for pos in positions_data] # Map dicts to PositionSchema
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving portfolio info for {current_user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while fetching portfolio information.")


@router.get("/trades", summary="Get User's Trade History from DB", response_model=List[TradeResponse])
async def get_db_trade_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000)
) -> List[TradeResponse]:
    """
    Retrieves the trade history for the authenticated user from the application's database.
    """
    logger.info(f"Fetching trade history from DB for user: {current_user.email} (skip={skip}, limit={limit})")
    try:
        trades = (
            db.query(Trade)
            .filter(Trade.user_id == current_user.id)
            .order_by(Trade.timestamp.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return trades # Pydantic converts List[Trade (SQLAlchemy)] to List[TradeResponse]
    except Exception as e:
        logger.error(f"Database error fetching trade history for {current_user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not retrieve trade history.")


@router.post("/train/{symbol}", summary="Train ML Model for a Symbol", response_model=ModelTrainingResponse)
async def train_model_for_symbol(
    symbol: str,
    model_type: str = Query("lstm", enum=["lstm", "xgboost"], description="Type of model to train."),
    epochs: Optional[int] = Query(50, ge=1, le=500, description="Number of epochs for LSTM training."),
    current_user: User = Depends(security.get_current_active_user)
) -> ModelTrainingResponse:
    """
    Triggers training for a specified ML model and symbol.
    """
    logger.info(f"Model training requested for {symbol} ({model_type}, epochs={epochs}) by user {current_user.email}")
    if not ml_engine:
        logger.error("MLEngine not available for training.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ML Engine is not available.")

    success = False
    status_message = "failed"
    try:
        if model_type == "lstm":
            success = ml_engine.train_lstm(symbol, epochs=epochs if epochs else 50)
        elif model_type == "xgboost":
            success = ml_engine.train_xgboost(symbol)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported model type: {model_type}")
        
        status_message = "completed" if success else "failed"

    except Exception as e:
        logger.error(f"Error during {model_type} training for {symbol}: {e}", exc_info=True)
        status_message = "error_during_training"
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An error occurred during model training for {symbol}.")

    if success:
        return ModelTrainingResponse(
            message=f"{model_type.upper()} model training initiated successfully for {symbol}.",
            symbol=symbol,
            model_type=model_type,
            status=status_message
        )
    else:
        logger.error(f"Model training function returned false for {symbol} ({model_type}). Check ML Engine logs.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to train {model_type} model for {symbol}. Status: {status_message}"
        )


@router.get("/predict/{symbol}", summary="Get ML Prediction for a Symbol", response_model=GetPredictionResponse)
async def get_prediction(
    symbol: str,
    model_type: str = Query("lstm", enum=["lstm", "xgboost"], description="Type of model for prediction."),
    current_user: User = Depends(security.get_current_active_user)
) -> GetPredictionResponse:
    """
    Fetches an ML prediction for a given symbol. Uses Redis for caching.
    """
    logger.info(f"Prediction requested for {symbol} ({model_type}) by user {current_user.email}")
    if not ml_engine:
        logger.error("MLEngine not available for prediction.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ML Engine is not available.")
    
    cache_key = f"prediction:{symbol}:{model_type}"
    
    if redis_client:
        try:
            cached_result_str = redis_client.get(cache_key)
            if cached_result_str:
                logger.info(f"Returning cached prediction for {symbol} ({model_type}).")
                # Parse and validate against GetPredictionResponse
                return GetPredictionResponse(**json.loads(cached_result_str))
        except RedisError as e:
            logger.warning(f"Redis error getting cache for {cache_key}: {e}. Fetching new prediction.")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to decode cached JSON for {cache_key}: {e}. Fetching new prediction.")
        except Exception as e: # Catch Pydantic validation errors for cached data
            logger.warning(f"Error validating cached prediction data for {cache_key}: {e}. Fetching new prediction.")

    prediction_result_dict = ml_engine.predict(symbol, model_type=model_type)
    
    if "error" in prediction_result_dict:
        logger.error(f"Prediction error from ML Engine for {symbol} ({model_type}): {prediction_result_dict['error']}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=prediction_result_dict["error"])

    if redis_client:
        try:
            # Ensure prediction_result_dict can be successfully parsed by GetPredictionResponse before caching
            validated_prediction = GetPredictionResponse(**prediction_result_dict)
            redis_client.setex(cache_key, settings.PREDICTION_CACHE_TTL, validated_prediction.model_dump_json())
            logger.info(f"Cached new prediction for {symbol} ({model_type}).")
        except RedisError as e:
            logger.warning(f"Redis error setting cache for {cache_key}: {e}")
        except (TypeError, OverflowError, Exception) as serialization_error: # Catch Pydantic validation or json.dumps errors
            logger.error(f"Failed to serialize or validate prediction_data for caching {cache_key}: {serialization_error}")
            
    return GetPredictionResponse(**prediction_result_dict)


@router.post("/execute-trade/{symbol}", summary="Execute a Trade Based on ML Prediction", response_model=TradeExecutionResponse)
async def execute_ml_trade(
    symbol: str,
    model_type: str = Query("lstm", enum=["lstm", "xgboost"], description="ML model to use for the trade decision."),
    confidence_threshold: float = Query(0.7, ge=0, le=1, description="Minimum model confidence to execute trade."),
    risk_per_trade: float = Query(0.01, gt=0, le=0.1, description="Fraction of portfolio to risk per trade."),
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> TradeExecutionResponse:
    """
    Executes a trade for the given symbol based on the ML model's prediction.
    """
    logger.info(
        f"Trade execution requested for {symbol} by user {current_user.email} "
        f"using {model_type} model (confidence_threshold={confidence_threshold}, risk={risk_per_trade})."
    )
    
    trading_service = get_user_trading_service(current_user)
    if not ml_engine:
        logger.error("MLEngine not available for trade execution.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ML Engine is not available.")

    try:
        trade_execution_result_dict = trading_service.execute_trade(
            db=db,
            symbol=symbol,
            model_type=model_type,
            user_id=current_user.id,
            confidence_threshold=confidence_threshold,
            risk_per_trade=risk_per_trade
        )
        
        if trade_execution_result_dict.get("status") == "error":
            logger.error(f"Trade execution failed for {symbol} by {current_user.email}: {trade_execution_result_dict.get('message')}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trade_execution_result_dict.get("message", "Trade execution failed.")
            )
        
        logger.info(f"Trade execution for {symbol} by {current_user.email} resulted in: {trade_execution_result_dict.get('status')}")
        return TradeExecutionResponse(**trade_execution_result_dict)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during trade execution for {symbol} by {current_user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred during trade execution.")


@router.get("/backtest/{symbol}", summary="Run Backtest for a Symbol and Model", response_model=BacktestResponse)
async def run_backtest(
    symbol: str,
    model_type: str = Query("lstm", enum=["lstm", "xgboost"], description="Model to backtest."),
    lookback: int = Query(60, ge=10, le=200, description="Lookback period for features."),
    test_data_points: int = Query(50, ge=10, le=500, description="Number of data points for testing."),
    current_user: User = Depends(security.get_current_active_user)
) -> BacktestResponse:
    """
    Runs a simplified backtest for the given symbol and model type.
    """
    logger.info(
        f"Backtest requested for {symbol} ({model_type}) by user {current_user.email} "
        f"with lookback={lookback}, test_points={test_data_points}."
    )
    if not ml_engine:
        logger.error("MLEngine not available for backtesting.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ML Engine is not available.")

    temp_trading_service = TradingService(api_key="dummy_for_backtest", secret_key="dummy_for_backtest", base_url=settings.ALPACA_BASE_URL)

    try:
        backtest_result_dict = temp_trading_service.backtest_strategy(
            symbol=symbol,
            model_type=model_type,
            lookback=lookback,
            test_data_points=test_data_points
        )
        if backtest_result_dict is None or "error" in (backtest_result_dict or {}):
            error_detail = (backtest_result_dict or {}).get("error", "Backtest failed or returned no result.")
            logger.error(f"Backtest for {symbol} ({model_type}) by {current_user.email} failed: {error_detail}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_detail)
        
        # Ensure the dictionary keys match BacktestResponse fields
        return BacktestResponse(**backtest_result_dict)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during backtest for {symbol} ({model_type}) by {current_user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred during backtest.")


@router.get("/models", summary="List Supported ML Models", response_model=Dict[str, List[str]])
async def list_supported_models() -> Dict[str, List[str]]:
    """
    Lists the ML model types supported by the system for training and prediction.
    """
    # This could be made dynamic by inspecting MLEngine capabilities or a configuration
    # For now, keeping it static as in the original.
    return {"supported_models": ["lstm", "xgboost"]}