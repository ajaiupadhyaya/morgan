# File: app/schemas/portfolio.py

from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional

class PositionSchema(BaseModel):
    """Schema for an individual position within a portfolio."""
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: Optional[float] = Field(None, description="Current market price of the asset")
    market_value: float
    unrealized_pl: float = Field(description="Unrealized profit or loss")
    # The Alpaca API often returns this as 'unrealized_plpc' (percent change)
    # Ensure your TradingService.get_positions() normalizes the field name if needed,
    # or use an alias here. For now, assuming 'unrealized_pl_percent'.
    unrealized_pl_percent: float = Field(description="Unrealized profit or loss in percent")

    # Pydantic V2 configuration
    model_config = {
        "from_attributes": True # If created from ORM objects
    }

class PortfolioResponse(BaseModel):
    """Schema for the /portfolio endpoint response."""
    user_email: EmailStr # Assuming you want to include this for context
    total_portfolio_value: float
    cash_balance: Optional[float] = Field(None, description="Available cash in the portfolio")
    positions: List[PositionSchema]
    # You could add other summary fields here, like:
    # total_unrealized_pl: Optional[float] = None
    # daily_change_percent: Optional[float] = None