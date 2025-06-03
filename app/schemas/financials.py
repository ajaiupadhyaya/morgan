# File: app/schemas/financials.py

from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import date, datetime

# Import the Enums from your SQLAlchemy models file
# This ensures consistency between your DB models and your Pydantic schemas
from app.models.models import FinancialStatementType, TimeframeType

# --- Company Profile Schemas ---

class CompanyProfileBase(BaseModel):
    """
    Base schema for company profile information.
    """
    symbol: str = Field(..., example="AAPL", description="Stock ticker symbol")
    name: Optional[str] = Field(None, example="Apple Inc.", description="Company name")
    cik: Optional[str] = Field(None, example="0000320193", description="Central Index Key (CIK)")
    sector: Optional[str] = Field(None, example="Technology", description="Company sector")
    industry: Optional[str] = Field(None, example="Consumer Electronics", description="Company industry")
    description: Optional[str] = Field(None, example="Apple Inc. designs, manufactures, and markets smartphones...", description="Company description")
    country: Optional[str] = Field(None, example="USA", description="Country of incorporation/operation")
    exchange: Optional[str] = Field(None, example="NASDAQ", description="Primary stock exchange")
    currency: Optional[str] = Field(None, example="USD", description="Reporting currency")
    market_cap: Optional[float] = Field(None, example=2800000000000.0, description="Market capitalization")
    shares_outstanding: Optional[float] = Field(None, example=15000000000.0, description="Number of shares outstanding")
    phone: Optional[str] = Field(None, example="1-408-996-1010")
    ceo: Optional[str] = Field(None, example="Timothy D. Cook")
    url: Optional[HttpUrl] = Field(None, example="https://www.apple.com", description="Company website URL")
    logo_url: Optional[HttpUrl] = Field(None, example="https://logo.clearbit.com/apple.com", description="URL to company logo")
    list_date: Optional[date] = Field(None, example="1980-12-12", description="Date the company was listed")
    last_refreshed: Optional[datetime] = Field(None, description="Timestamp when this profile data was last fetched/updated")

class CompanyProfileCreate(CompanyProfileBase):
    """Schema for creating a new company profile (e.g., when first fetching from source)."""
    # All fields inherited from CompanyProfileBase are used.
    # Add any fields specific to creation if different from base.
    pass

class CompanyProfileUpdate(BaseModel):
    """Schema for updating a company profile. All fields are optional."""
    name: Optional[str] = None
    cik: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    phone: Optional[str] = None
    ceo: Optional[str] = None
    url: Optional[HttpUrl] = None
    logo_url: Optional[HttpUrl] = None
    list_date: Optional[date] = None
    last_refreshed: Optional[datetime] = Field(default_factory=datetime.utcnow)


class CompanyProfileResponse(CompanyProfileBase):
    """Schema for returning company profile information via API."""
    id: int # The ID from the database

    # If you want to nest related financial data in the response, you would add:
    # financial_reports: List["FinancialReportResponse"] = [] # Forward reference
    # key_ratios: List["KeyRatioSetResponse"] = [] # Forward reference

    # Pydantic V2 configuration
    model_config = {
        "from_attributes": True  # Enables creating this schema from an ORM model instance
    }


# --- Financial Report Schemas ---

class FinancialReportBase(BaseModel):
    """Base schema for financial report data."""
    symbol: str = Field(..., example="AAPL", description="Stock ticker symbol")
    report_type: FinancialStatementType = Field(..., description="Type of financial statement (e.g., income_statement)")
    timeframe: TimeframeType = Field(..., description="annual, quarterly, or TTM")
    
    fiscal_year: Optional[int] = Field(None, example=2023)
    fiscal_period: Optional[str] = Field(None, example="FY", description="e.g., Q1, Q2, FY")
    
    filing_date: date = Field(..., example="2023-10-27", description="Date the SEC filing was made available")
    period_of_report_date: date = Field(..., example="2023-09-30", description="The end date of the period these financials cover")
    start_date: Optional[date] = Field(None, example="2022-10-01", description="The start date of the period these financials cover")
    
    # The 'data' field will hold the various line items from the financial report
    data: Dict[str, Any] = Field(..., description="Raw financial data line items as JSON from the source (e.g., revenues, assets)")
    
    source_filing_url: Optional[HttpUrl] = Field(None, description="URL of the SEC filing")
    source_filing_file_url: Optional[HttpUrl] = Field(None, description="URL of the specific XBRL document")
    acceptance_datetime_est: Optional[str] = Field(None, description="Filing acceptance datetime (EST), often a string like YYYYMMDDHHMMSS")
    last_refreshed: Optional[datetime] = Field(None, description="Timestamp when this report was last fetched/updated")

class FinancialReportCreate(FinancialReportBase):
    """Schema for creating a new financial report record."""
    company_profile_id: int # Required when creating and linking to a company profile
    pass

class FinancialReportResponse(FinancialReportBase):
    """Schema for returning financial report information via API."""
    id: int
    company_profile_id: int

    model_config = {"from_attributes": True}


# --- Key Ratio Set Schemas ---

class KeyRatioSetBase(BaseModel):
    """Base schema for a set of key financial ratios."""
    symbol: str = Field(..., example="AAPL", description="Stock ticker symbol")
    date: date = Field(..., description="Date for which these ratios are applicable")
    period_type: Optional[TimeframeType] = Field(None, description="Annual, Quarterly, TTM for which ratios are calculated")

    # Define specific ratio fields. These are examples; adjust based on what you'll calculate/store.
    price_to_earnings_ratio: Optional[float] = Field(None, example=28.5)
    price_to_sales_ratio: Optional[float] = Field(None, example=7.2)
    price_to_book_ratio: Optional[float] = Field(None, example=40.1)
    earnings_per_share: Optional[float] = Field(None, example=5.67)
    dividend_yield: Optional[float] = Field(None, example=0.006, description="Expressed as a decimal, e.g., 0.006 for 0.6%")
    return_on_equity: Optional[float] = Field(None, example=0.15, description="Expressed as a decimal, e.g., 0.15 for 15%")
    debt_to_equity_ratio: Optional[float] = Field(None, example=1.5)
    current_ratio: Optional[float] = Field(None, example=1.2)
    quick_ratio: Optional[float] = Field(None, example=0.9)
    gross_profit_margin: Optional[float] = Field(None, example=0.43, description="Expressed as a decimal")
    operating_profit_margin: Optional[float] = Field(None, example=0.28, description="Expressed as a decimal")
    net_profit_margin: Optional[float] = Field(None, example=0.25, description="Expressed as a decimal")
    last_refreshed: Optional[datetime] = Field(None)

class KeyRatioSetCreate(KeyRatioSetBase):
    """Schema for creating a new key ratio set record."""
    company_profile_id: int # Required when creating and linking
    pass

class KeyRatioSetResponse(KeyRatioSetBase):
    """Schema for returning key ratio set information via API."""
    id: int
    company_profile_id: int

    model_config = {"from_attributes": True}

# If using forward references for nested responses in CompanyProfileResponse,
# you might need to update them after all schemas are defined:
# CompanyProfileResponse.model_rebuild()
# FinancialReportResponse.model_rebuild() # If it nests anything
# KeyRatioSetResponse.model_rebuild() # If it nests anything