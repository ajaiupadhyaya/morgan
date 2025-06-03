# File: app/schemas/account.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class AccountResponse(BaseModel):
    """
    Schema for the /account endpoint response.
    Reflects typical fields from Alpaca's account object.
    Ensure field names and types match the data from trading_service.get_account().
    """
    id: str
    account_number: str
    status: str # e.g., "ACTIVE", "INACTIVE"
    currency: str # e.g., "USD"
    buying_power: float # Ensure this is float
    cash: float # Ensure this is float
    equity: float # Ensure this is float
    created_at: datetime # Ensure this is parsed to datetime if a string from API

    # Optional fields based on typical Alpaca account structure:
    portfolio_value: Optional[float] = Field(None, description="Total value of portfolio including cash and positions")
    last_equity: Optional[float] = Field(None, description="Equity from previous trading day")
    long_market_value: Optional[float] = Field(None, description="Current market value of long positions")
    short_market_value: Optional[float] = Field(None, description="Current market value of short positions (usually 0 or negative)")
    initial_margin: Optional[float] = Field(None)
    maintenance_margin: Optional[float] = Field(None)
    daytrade_count: Optional[int] = Field(None)
    shorting_enabled: Optional[bool] = Field(None)
    # Add any other fields you deem relevant from the Alpaca account object

    # Pydantic V2 configuration
    model_config = {
        "from_attributes": True # If you ever populate this directly from an ORM object
                               # For dicts, direct unpacking **account_data_dict is fine
    }