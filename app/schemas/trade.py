# File: app/schemas/trade.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class TradeBase(BaseModel):
    """
    Base schema for common trade attributes.
    """
    symbol: str = Field(..., example="AAPL")
    side: str = Field(..., example="buy")  # 'buy' or 'sell'
    quantity: float = Field(..., example=10.5)
    price: float = Field(..., example=150.25) # Execution price
    
    predicted_price: Optional[float] = Field(None, example=155.00)
    confidence: Optional[float] = Field(None, example=0.85) # Model confidence (e.g., 0-1)
    model_used: Optional[str] = Field(None, example="lstm_AAPL_v1")
    
    strategy_tag: Optional[str] = Field(None, example="momentum_breakout")
    notes: Optional[str] = Field(None, example="Entry based on strong volume signal.")
    order_id: Optional[str] = Field(None, example="alpaca_order_id_123") # Alpaca order ID
    timestamp: datetime = Field(default_factory=datetime.utcnow, example="2023-10-26T10:00:00Z")


class TradeCreate(TradeBase):
    """
    Schema for creating a new trade record.
    Trades are typically created by the system during execution, not directly by user API calls,
    but this schema can be used internally or if an endpoint for manual trade logging is added.
    It expects user_id to be set by the system based on the authenticated user.
    """
    # user_id will be set based on the authenticated user in the endpoint logic
    pass


class TradeUpdate(BaseModel):
    """
    Schema for updating an existing trade record (e.g., adding notes).
    Make fields optional as needed.
    """
    notes: Optional[str] = Field(None, example="Updated trade notes after review.")
    strategy_tag: Optional[str] = Field(None, example="classified_earnings_play")
    # Other fields that might be updatable post-creation


class TradeResponse(TradeBase):
    """
    Schema for returning trade information to the client.
    Includes the trade ID and user ID.
    """
    id: int
    user_id: int # To know which user this trade belongs to
    
    # Inherits all fields from TradeBase

    # Pydantic V2 configuration to enable ORM mode (from_attributes)
    model_config = {
        "from_attributes": True
    }

# Schema for the response from the /execute-trade endpoint
class TradeExecutionResponse(BaseModel):
    """
    Schema for the response after attempting to execute a trade.
    """
    status: str = Field(..., example="success | error | skipped")
    message: Optional[str] = Field(None, example="Trade executed successfully.")
    order_details: Optional[dict] = Field(None, description="Details of the order if placed (from Alpaca).") # From order._raw
    trade_log_id: Optional[int] = Field(None, description="ID of the trade record in the database.")
    # Add any other relevant fields from the dictionary returned by TradingService.execute_trade