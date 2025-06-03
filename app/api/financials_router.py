# File: app/api/financials_router.py

import logging
from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_active_user # For authentication
from app.models.user import User # For type hinting current_user
from app.services.financial_data_service import FinancialDataService
from app.schemas.financials import ( # Schemas you created in app/schemas/financials.py
    CompanyProfileResponse,
    FinancialReportResponse,
    KeyRatioSetResponse
)
from app.models.models import FinancialStatementType, TimeframeType # Enums

# For injecting TradingService into FinancialDataService if needed for prices
from app.services.trading import TradingService # Assuming TradingService can be instantiated
from app.core.config import settings # For dummy keys if real ones not needed by TradingService's get_latest_price

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/financials", # Base prefix for all financial data routes
    tags=["Financial Data"],
    dependencies=[Depends(get_current_active_user)] # Secure all routes in this router
)

# Dependency to get FinancialDataService instance
# This also shows how to inject another service (TradingService) if needed
def get_financial_data_service(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user) # For user-specific TradingService
) -> FinancialDataService:
    # Instantiate TradingService to pass to FinancialDataService for live prices
    # This part assumes get_user_trading_service is robust or you have a way to get a price provider
    # For simplicity, if user-specific keys aren't set, price fetching might fail or use a generic service.
    # Let's use the helper from endpoints.py if we assume this router is part of the main app.
    # This dependency injection can get complex.
    # Alternative: FinancialDataService doesn't fetch live prices itself, but expects them if needed.

    # Simplified approach: Instantiate a generic TradingService if only used for its get_latest_price method
    # and that method can operate with dummy keys for just fetching public price data.
    # This is a placeholder and depends on how TradingService.get_latest_price is implemented.
    # A dedicated PriceService would be cleaner.
    
    # Using the user's configured TradingService instance
    # Copied helper logic from main endpoints.py for consistency
    # This part needs to be robust.
    user_trading_service: Optional[TradingService] = None
    if current_user.alpaca_api_key and current_user.alpaca_secret_key:
        decrypted_api_key = security.decrypt_data_field(current_user.alpaca_api_key)
        decrypted_secret_key = security.decrypt_data_field(current_user.alpaca_secret_key)
        if decrypted_api_key and decrypted_secret_key:
            base_url = settings.ALPACA_BASE_URL
            if hasattr(current_user, 'alpaca_is_paper') and current_user.alpaca_is_paper is False:
                # base_url = settings.ALPACA_LIVE_BASE_URL # If defined
                pass
            user_trading_service = TradingService(
                api_key=decrypted_api_key,
                secret_key=decrypted_secret_key,
                base_url=base_url
            )
        else:
            logger.warning(f"Could not decrypt Alpaca keys for user {current_user.email} for FinancialDataService's TradingService.")
    else:
        logger.warning(f"User {current_user.email} has no Alpaca keys for FinancialDataService's TradingService.")

    if not user_trading_service:
        # Fallback if user keys are not available, price fetching for ratios might be limited
        logger.info("FinancialDataService: Using dummy TradingService for price fetching fallback (may not work for live prices).")
        user_trading_service = TradingService(api_key="dummy", secret_key="dummy", base_url=settings.ALPACA_BASE_URL)


    # Assuming redis_client is globally available or passed similarly if needed by FinancialDataService directly
    # For now, FinancialDataService initializes its own if REDIS_URL is set in settings
    # from app.api.endpoints import redis_client # If sharing a global redis_client
    
    return FinancialDataService(db_session=db, trading_service=user_trading_service) # Pass trading_service


@router.post("/fetch/{symbol}", summary="Fetch and Store Fundamental Data for a Symbol", response_model=CompanyProfileResponse)
async def fetch_fundamental_data_for_symbol(
    symbol: str,
    service: FinancialDataService = Depends(get_financial_data_service)
) -> CompanyProfileResponse:
    """
    Triggers fetching of company profile and recent financial reports (e.g., last 5 annual)
    for the given stock symbol from Polygon.io and stores/updates them in the database.
    Returns the company profile.
    """
    logger.info(f"Request to fetch all fundamental data for symbol: {symbol.upper()}")
    
    profile = service.fetch_and_upsert_company_profile(symbol)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Could not fetch or create profile for symbol {symbol}")

    # Fetch recent annual and quarterly reports as an example
    service.fetch_and_upsert_financial_reports(symbol, timeframe_enum=TimeframeType.ANNUAL, limit=5)
    service.fetch_and_upsert_financial_reports(symbol, timeframe_enum=TimeframeType.QUARTERLY, limit=8) 
    
    # Optionally trigger initial ratio calculation here
    # service.get_or_calculate_and_store_key_ratios(symbol)

    return CompanyProfileResponse.model_validate(profile)


@router.get("/company/{symbol}/profile", summary="Get Company Profile", response_model=CompanyProfileResponse)
async def get_company_profile(
    symbol: str,
    service: FinancialDataService = Depends(get_financial_data_service)
) -> CompanyProfileResponse:
    """
    Retrieves the stored company profile for the given stock symbol from the database.
    If not found, attempts to fetch from Polygon.io and store it.
    """
    logger.info(f"Request for company profile: {symbol.upper()}")
    profile = service.get_company_profile_from_db(symbol)
    if not profile:
        logger.info(f"Profile for {symbol} not in DB, attempting to fetch from source...")
        profile = service.fetch_and_upsert_company_profile(symbol)
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Company profile not found for symbol {symbol}")
    return CompanyProfileResponse.model_validate(profile)


@router.get("/company/{symbol}/reports", summary="Get Financial Reports", response_model=List[FinancialReportResponse])
async def get_financial_reports(
    symbol: str,
    report_type: Optional[FinancialStatementType] = Query(None, description="Filter by report type (e.g., income_statement)"),
    timeframe: Optional[TimeframeType] = Query(None, description="Filter by timeframe (e.g., annual, quarterly)"),
    limit: int = Query(5, ge=1, le=50, description="Maximum number of reports to return per type/timeframe combination"),
    service: FinancialDataService = Depends(get_financial_data_service)
) -> List[FinancialReportResponse]:
    """
    Retrieves stored financial reports for the given stock symbol.
    Allows filtering by report_type and timeframe.
    """
    logger.info(f"Request for financial reports: {symbol.upper()}, type: {report_type}, timeframe: {timeframe}, limit: {limit}")
    reports = service.get_financial_reports_from_db(symbol, report_type, timeframe, limit)
    if not reports:
        # Optionally, you could try to trigger a fetch here if data is expected but missing
        # logger.info(f"No reports found for {symbol} with specified filters. Consider fetching.")
        # For now, just return empty list if not found in DB after a potential fetch attempt.
        # If you want to auto-fetch, the logic in fetch_and_upsert_financial_reports handles that.
        # This endpoint primarily serves what's already in the DB.
        pass # Returns empty list if no reports match
        
    return [FinancialReportResponse.model_validate(report) for report in reports]


@router.get("/company/{symbol}/ratios", summary="Get Key Financial Ratios", response_model=Optional[KeyRatioSetResponse])
async def get_key_ratios(
    symbol: str,
    effective_date: Optional[date] = Query(None, description="Get ratios as of this date (YYYY-MM-DD). Defaults to latest available."),
    service: FinancialDataService = Depends(get_financial_data_service)
) -> Optional[KeyRatioSetResponse]:
    """
    Retrieves (or calculates if missing/stale) key financial ratios for the given stock symbol.
    The calculation logic for ratios is comprehensive and may require various data points.
    """
    logger.info(f"Request for key ratios: {symbol.upper()}, effective_date: {effective_date}")
    ratios = service.get_or_calculate_and_store_key_ratios(symbol, effective_date)
    if not ratios:
        # This could mean data wasn't available to calculate, or calculation failed.
        # The service logs details.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Key ratios not available or could not be calculated for symbol {symbol} for the specified date.")
    return KeyRatioSetResponse.model_validate(ratios)