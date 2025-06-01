from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from app.db.session import get_db
from app.models.models import User, Trade, Prediction
from app.services.trading import TradingService
from app.ml.engine import MLEngine
from app.core.config import settings

router = APIRouter()
ml_engine = MLEngine()

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@router.get("/account")
async def get_account_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get account information"""
    trading_service = TradingService(
        current_user.alpaca_api_key,
        current_user.alpaca_secret_key,
        settings.ALPACA_BASE_URL
    )
    return trading_service.get_account()

@router.get("/portfolio")
async def get_portfolio(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get portfolio information"""
    trading_service = TradingService(
        current_user.alpaca_api_key,
        current_user.alpaca_secret_key,
        settings.ALPACA_BASE_URL
    )
    return {
        "value": trading_service.get_portfolio_value(),
        "positions": trading_service.get_positions()
    }

@router.post("/predict/{symbol}")
async def predict_price(
    symbol: str,
    model_type: str = "lstm",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get price prediction for a symbol"""
    try:
        prediction = ml_engine.predict(symbol, model_type)
        
        # Save prediction to database
        db_prediction = Prediction(
            user_id=current_user.id,
            symbol=symbol,
            prediction=prediction["prediction"],
            confidence=0.8,  # This should be calculated by the model
            model_name=model_type,
            features={}  # Add relevant features
        )
        db.add(db_prediction)
        db.commit()
        
        return prediction
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/trade/{symbol}")
async def execute_trade(
    symbol: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Execute a trade based on ML prediction"""
    try:
        # Get prediction
        prediction = ml_engine.predict(symbol)
        
        # Initialize trading service
        trading_service = TradingService(
            current_user.alpaca_api_key,
            current_user.alpaca_secret_key,
            settings.ALPACA_BASE_URL
        )
        
        # Execute trade
        trade = trading_service.execute_trade(
            db=db,
            user_id=current_user.id,
            symbol=symbol,
            prediction=prediction["prediction"],
            confidence=0.8  # This should be calculated by the model
        )
        
        return trade
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/trades")
async def get_trades(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get trade history"""
    trading_service = TradingService(
        current_user.alpaca_api_key,
        current_user.alpaca_secret_key,
        settings.ALPACA_BASE_URL
    )
    return trading_service.get_trade_history(start_date, end_date)

@router.post("/train/{symbol}")
async def train_model(
    symbol: str,
    model_type: str = "lstm",
    epochs: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Train ML model for a symbol"""
    try:
        if model_type == "lstm":
            ml_engine.train_lstm(symbol, epochs)
        elif model_type == "xgboost":
            ml_engine.train_xgboost(symbol)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid model type"
            )
        
        return {"status": "success", "message": f"Model trained for {symbol}"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/performance")
async def get_model_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get model performance metrics"""
    # This would typically involve calculating various performance metrics
    # such as accuracy, Sharpe ratio, returns, etc.
    return {
        "accuracy": 0.65,
        "sharpe_ratio": 1.2,
        "returns": 0.15,
        "timestamp": datetime.now().isoformat()
    } 