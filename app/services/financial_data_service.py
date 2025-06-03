# File: app/services/financial_data_service.py

import logging
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session
from polygon import RESTClient # Polygon.io's official REST client
import redis
from redis.exceptions import RedisError
import json

from app.core.config import settings
# Models
from app.models.models import (
    CompanyProfile, 
    FinancialReport, 
    KeyRatioSet, # We'll use this later for calculated/stored ratios
    FinancialStatementType, 
    TimeframeType
)
# Schemas
from app.schemas.financials import (
    CompanyProfileCreate, 
    CompanyProfileUpdate,
    FinancialReportCreate,
    # KeyRatioSetCreate # For later
)

logger = logging.getLogger(__name__)

class FinancialDataService:
    def __init__(self, db_session: Session, redis_client: Optional[redis.Redis] = None):
        self.db = db_session
        self.redis = redis_client
        try:
            # The Polygon client will automatically use the POLYGON_API_KEY environment variable
            # if settings.POLYGON_API_KEY is set, or you can pass it directly.
            if not settings.POLYGON_API_KEY:
                logger.error("POLYGON_API_KEY not configured in settings. FinancialDataService may not function.")
                self.polygon_client = None
            else:
                self.polygon_client = RESTClient(settings.POLYGON_API_KEY)
                logger.info("Polygon.io RESTClient initialized for FinancialDataService.")
        except Exception as e:
            logger.error(f"Failed to initialize Polygon.io RESTClient: {e}", exc_info=True)
            self.polygon_client = None

    def _get_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        if not self.redis:
            return None
        try:
            cached_data = self.redis.get(cache_key)
            if cached_data:
                logger.debug(f"Cache hit for key: {cache_key}")
                return json.loads(cached_data)
        except RedisError as e:
            logger.warning(f"Redis error getting cache for {cache_key}: {e}")
        except json.JSONDecodeError as e:
            logger.warning(f"Error decoding cached JSON for {cache_key}: {e}")
        return None

    def _set_to_cache(self, cache_key: str, data: Any, ttl_seconds: int = 3600 * 24): # Default 1 day TTL
        if not self.redis:
            return
        try:
            self.redis.setex(cache_key, ttl_seconds, json.dumps(data))
            logger.debug(f"Data cached for key: {cache_key} with TTL: {ttl_seconds}s")
        except RedisError as e:
            logger.warning(f"Redis error setting cache for {cache_key}: {e}")
        except (TypeError, OverflowError) as serialization_error:
            logger.error(f"Failed to serialize data for caching {cache_key}: {serialization_error}")

    # --- Company Profile Methods ---
    def fetch_and_store_company_profile(self, symbol: str) -> Optional[CompanyProfile]:
        """
        Fetches company profile from Polygon.io and stores/updates it in the database.
        """
        if not self.polygon_client:
            logger.error(f"Polygon client not available. Cannot fetch profile for {symbol}.")
            return None

        cache_key = f"polygon:company_profile:{symbol}"
        profile_data_dict = self._get_from_cache(cache_key)
        
        if not profile_data_dict:
            try:
                logger.info(f"Fetching company profile for {symbol} from Polygon.io...")
                # Using /v3/reference/tickers/{ticker} endpoint
                # The client library might have a method like `get_ticker_details` or similar
                # For example: resp = self.polygon_client.get_ticker_details(symbol)
                # The structure below is an *example* based on typical API responses.
                # You'll need to adapt it to the actual response structure from polygon-api-client.
                
                # Example using raw HTTP request if client method is not straightforward
                # ticker_details_url = f"https://api.polygon.io/v3/reference/tickers/{symbol.upper()}"
                # resp = self.polygon_client.get(ticker_details_url) # Assuming client handles auth and base URL
                # raw_profile_data = resp.results if hasattr(resp, 'results') else {}
                
                # Using the official client's expected method structure (check their docs for exact method)
                # This is a common pattern, actual method name may vary, e.g., reference_client.get_ticker_details
                raw_profile_data_obj = self.polygon_client.get_ticker_details(symbol.upper()) #
                
                # Assuming raw_profile_data_obj is an object with attributes matching keys below
                # Or if it's a dict, access like raw_profile_data_obj.get('name')
                profile_data_dict = {
                    "symbol": getattr(raw_profile_data_obj, 'ticker', symbol.upper()),
                    "name": getattr(raw_profile_data_obj, 'name', None),
                    "cik": getattr(raw_profile_data_obj, 'cik', None),
                    "sector": getattr(raw_profile_data_obj, 'sector', None) or getattr(raw_profile_data_obj, 'sic_description', None), # (sector might be derived from SIC)
                    "industry": getattr(raw_profile_data_obj, 'industry', None), # May also need derivation from SIC
                    "description": getattr(raw_profile_data_obj, 'description', None),
                    "country": getattr(raw_profile_data_obj.address, 'country', None) if hasattr(raw_profile_data_obj, 'address') and raw_profile_data_obj.address else None,
                    "exchange": getattr(raw_profile_data_obj, 'primary_exchange', None),
                    "currency": getattr(raw_profile_data_obj, 'currency_name', None),
                    "market_cap": getattr(raw_profile_data_obj, 'market_cap', None),
                    "shares_outstanding": getattr(raw_profile_data_obj, 'weighted_shares_outstanding', None) or getattr(raw_profile_data_obj, 'share_class_shares_outstanding', None),
                    "phone": getattr(raw_profile_data_obj, 'phone_number', None),
                    "ceo": None, # Polygon Ticker Details doesn't seem to list CEO directly
                    "url": getattr(raw_profile_data_obj, 'homepage_url', None),
                    "logo_url": getattr(raw_profile_data_obj.branding, 'logo_url', None) if hasattr(raw_profile_data_obj, 'branding') and raw_profile_data_obj.branding else None,
                    "list_date": getattr(raw_profile_data_obj, 'list_date', None),
                    "last_refreshed": datetime.utcnow() # Our refresh time
                }
                self._set_to_cache(cache_key, profile_data_dict)
                
            except Exception as e:
                logger.error(f"Error fetching company profile for {symbol} from Polygon.io: {e}", exc_info=True)
                return None
        else:
            logger.info(f"Using cached company profile for {symbol}.")
            # Ensure list_date is a date object if loaded from JSON string
            if profile_data_dict.get("list_date") and isinstance(profile_data_dict["list_date"], str):
                profile_data_dict["list_date"] = date.fromisoformat(profile_data_dict["list_date"])
            if profile_data_dict.get("last_refreshed") and isinstance(profile_data_dict["last_refreshed"], str):
                profile_data_dict["last_refreshed"] = datetime.fromisoformat(profile_data_dict["last_refreshed"].replace("Z", "+00:00"))


        # Upsert to DB
        db_company_profile = self.db.query(CompanyProfile).filter(CompanyProfile.symbol == symbol).first()
        if db_company_profile:
            logger.info(f"Updating existing company profile for {symbol} in DB.")
            # Use CompanyProfileUpdate schema for partial updates if defined, or update fields directly
            for key, value in profile_data_dict.items():
                if hasattr(db_company_profile, key) and value is not None:
                    setattr(db_company_profile, key, value)
            db_company_profile.last_refreshed = datetime.utcnow() # DB refresh time
        else:
            logger.info(f"Creating new company profile for {symbol} in DB.")
            profile_create_schema = CompanyProfileCreate(**profile_data_dict)
            db_company_profile = CompanyProfile(**profile_create_schema.model_dump())
            self.db.add(db_company_profile)
        
        try:
            self.db.commit()
            self.db.refresh(db_company_profile)
            return db_company_profile
        except Exception as e:
            self.db.rollback()
            logger.error(f"DB error storing company profile for {symbol}: {e}", exc_info=True)
            return None

    def get_company_profile(self, symbol: str) -> Optional[CompanyProfile]:
        """Retrieves a company profile from the database."""
        logger.debug(f"Fetching company profile for {symbol} from DB.")
        return self.db.query(CompanyProfile).filter(CompanyProfile.symbol == symbol).first()

    # --- Financial Reports Methods ---
    def fetch_and_store_financial_reports(self, symbol: str, timeframe: TimeframeType = TimeframeType.ANNUAL, limit: int = 5) -> List[FinancialReport]:
        """
        Fetches financial reports (e.g., 10-K, 10-Q) from Polygon.io and stores them.
        Polygon.io's /vX/reference/financials endpoint.
        """
        if not self.polygon_client:
            logger.error(f"Polygon client not available. Cannot fetch financials for {symbol}.")
            return []

        # Ensure company profile exists to link financials
        company_profile = self.get_company_profile(symbol)
        if not company_profile:
            company_profile = self.fetch_and_store_company_profile(symbol)
            if not company_profile:
                logger.error(f"Cannot fetch financials for {symbol} as company profile could not be obtained.")
                return []
        
        company_profile_id = company_profile.id
        
        cache_key = f"polygon:financials:{symbol}:{timeframe.value}:{limit}"
        reports_data_list = self_get_from_cache(cache_key)

        if not reports_data_list:
            try:
                logger.info(f"Fetching {timeframe.value} financial reports for {symbol} (limit {limit}) from Polygon.io...")
                # The polygon client's method might be like:
                # client.vx.list_stock_financials(ticker=symbol, timeframe=timeframe.value, limit=limit, sort="filing_date")
                # This method paginates, so you might need to handle multiple pages if limit > 100 (max per page for financials)
                # For simplicity, assuming limit is within a single page or client handles pagination.
                
                financials_iter = self.polygon_client.list_stock_financials(
                    ticker=symbol.upper(),
                    timeframe=timeframe.value, # 'annual' or 'quarterly'
                    limit=limit, # How many past reports
                    sort="filing_date" # Get the most recent ones
                )
                
                reports_data_list = []
                for report in financials_iter:
                    # Adapt this to the actual structure of 'report' object from polygon-api-client
                    # The 'report.financials' object contains statement-specific nested data (balance_sheet, income_statement etc.)
                    report_dict = {
                        "symbol": symbol.upper(),
                        "report_type": self._determine_report_type(report.financials), # Helper to determine primary type
                        "timeframe": TimeframeType(report.timeframe), # Ensure it maps to our Enum
                        "fiscal_year": report.fiscal_year,
                        "fiscal_period": report.fiscal_period,
                        "filing_date": date.fromisoformat(report.filing_date),
                        "period_of_report_date": date.fromisoformat(report.end_date), # Polygon calls this 'end_date'
                        "start_date": date.fromisoformat(report.start_date) if report.start_date else None,
                        "data": self._structure_financials_data(report.financials), # Helper to structure the 'financials' object
                        "source_filing_url": report.source_filing_url,
                        "source_filing_file_url": report.source_filing_file_url,
                        "acceptance_datetime_est": getattr(report, 'acceptance_datetime', None), # Polygon calls it 'acceptance_datetime'
                        "last_refreshed": datetime.utcnow()
                    }
                    reports_data_list.append(report_dict)
                
                if reports_data_list:
                    self._set_to_cache(cache_key, reports_data_list)

            except Exception as e:
                logger.error(f"Error fetching financial reports for {symbol} from Polygon.io: {e}", exc_info=True)
                return []
        else:
            logger.info(f"Using cached financial reports for {symbol} ({timeframe.value}).")
            # Deserialize dates if loaded from JSON
            for report_dict in reports_data_list:
                for date_key in ["filing_date", "period_of_report_date", "start_date"]:
                    if report_dict.get(date_key) and isinstance(report_dict[date_key], str):
                        report_dict[date_key] = date.fromisoformat(report_dict[date_key])
                if report_dict.get("last_refreshed") and isinstance(report_dict["last_refreshed"], str):
                    report_dict["last_refreshed"] = datetime.fromisoformat(report_dict["last_refreshed"].replace("Z", "+00:00"))


        stored_reports = []
        for report_data in reports_data_list:
            # Upsert logic for financial reports (based on symbol, period_of_report_date, report_type, timeframe)
            existing_report = self.db.query(FinancialReport).filter_by(
                symbol=report_data["symbol"],
                period_of_report_date=report_data["period_of_report_date"],
                report_type=report_data["report_type"], # This needs _determine_report_type to be consistent
                timeframe=report_data["timeframe"]
            ).first()

            if existing_report:
                logger.debug(f"Updating existing financial report for {symbol} - {report_data['period_of_report_date']}")
                for key, value in report_data.items():
                    if hasattr(existing_report, key) and value is not None:
                        setattr(existing_report, key, value)
                existing_report.last_refreshed = datetime.utcnow()
                db_report = existing_report
            else:
                logger.debug(f"Creating new financial report for {symbol} - {report_data['period_of_report_date']}")
                report_create_schema = FinancialReportCreate(company_profile_id=company_profile_id, **report_data)
                db_report = FinancialReport(**report_create_schema.model_dump())
                self.db.add(db_report)
            
            try:
                self.db.commit() # Commit each report or batch commit
                self.db.refresh(db_report)
                stored_reports.append(db_report)
            except Exception as e:
                self.db.rollback()
                logger.error(f"DB error storing financial report for {symbol} ({report_data['period_of_report_date']}): {e}", exc_info=True)
                # Continue to next report or stop? For now, continue.
        
        return stored_reports

    def _determine_report_type(self, financials_obj: Any) -> FinancialStatementType:
        """
        Helper to determine the primary type of financial statement from Polygon's financials object.
        Polygon's 'financials' object contains income_statement, balance_sheet, cash_flow_statement.
        This function needs to decide which one to prioritize or how to map it.
        For simplicity, we might assume each fetched 'report' from Polygon is one primary type.
        Or, the API might let you query for specific statement types.
        Let's assume for now we get a specific report type if queried, or default to income_statement.
        The `timeframe` in `list_stock_financials` applies to all statements within that filing.
        The actual 'report_type' for our DB model should probably be based on which statement's data we are primarily storing in the 'data' field.
        If Polygon's structure gives one filing (e.g. 10-K) and that filing contains multiple statements,
        we might need to store them as separate FinancialReport entries in our DB or have a more complex 'data' structure.
        
        Looking at Polygon.io docs, each result item from `list_stock_financials` is a single "filing context"
        which contains `financials.balance_sheet`, `financials.cash_flow_statement`, `financials.income_statement`.
        Our `FinancialReport` model is designed to store one specific statement type.
        So, `fetch_and_store_financial_reports` would need to be called multiple times for the same filing date
        if we want to store each statement type separately, or iterate through them.
        
        For this initial version, let's simplify: if FinancialReport stores ALL statements for a filing in its 'data' JSON,
        then `report_type` could be a generic 'FILING_COMPOSITE'.
        However, our model has `report_type: Mapped[FinancialStatementType]`.
        This implies we'd create THREE DB entries for each Polygon.io response from `list_stock_financials`
        if we want to store income, balance, and cash flow separately.

        Let's refine `fetch_and_store_financial_reports` to handle this by creating multiple entries.
        And this helper will just pass through or determine based on iteration.
        For now, this helper is a placeholder if data is already typed.
        """
        if hasattr(financials_obj, 'income_statement') and financials_obj.income_statement:
            return FinancialStatementType.INCOME_STATEMENT # Default or based on primary content
        elif hasattr(financials_obj, 'balance_sheet') and financials_obj.balance_sheet:
            return FinancialStatementType.BALANCE_SHEET
        # Add more logic if needed
        return FinancialStatementType.INCOME_STATEMENT # Fallback

    def _structure_financials_data(self, financials_obj: Any) -> Dict[str, Any]:
        """
        Structures the raw financials object from Polygon into a more usable dictionary.
        The `financials_obj` from Polygon contains `balance_sheet`, `cash_flow_statement`, `income_statement`, `comprehensive_income`.
        Each of these is an object with `label`, `unit`, `value`, `order`, `xpath`, `formula`.
        We want to extract the 'value' for each line item.
        """
        structured_data = {}
        if hasattr(financials_obj, 'income_statement'):
            structured_data['income_statement'] = {
                key: getattr(item, 'value', None) 
                for key, item in financials_obj.income_statement.items()
            }
        if hasattr(financials_obj, 'balance_sheet'):
            structured_data['balance_sheet'] = {
                key: getattr(item, 'value', None)
                for key, item in financials_obj.balance_sheet.items()
            }
        if hasattr(financials_obj, 'cash_flow_statement'):
            structured_data['cash_flow_statement'] = {
                key: getattr(item, 'value', None)
                for key, item in financials_obj.cash_flow_statement.items()
            }
        # Add comprehensive_income if needed
        return structured_data


    def get_financial_reports(self, symbol: str, report_type: Optional[FinancialStatementType] = None, timeframe: Optional[TimeframeType] = None, limit: int = 5) -> List[FinancialReport]:
        """Retrieves financial reports from the database for a given symbol."""
        logger.debug(f"Fetching financial reports for {symbol} from DB.")
        query = self.db.query(FinancialReport).filter(FinancialReport.symbol == symbol)
        if report_type:
            query = query.filter(FinancialReport.report_type == report_type)
        if timeframe:
            query = query.filter(FinancialReport.timeframe == timeframe)
        return query.order_by(FinancialReport.period_of_report_date.desc()).limit(limit).all()

    # --- Key Ratios Methods (Placeholder for now) ---
    def calculate_and_store_key_ratios(self, symbol: str, report_date: date) -> Optional[KeyRatioSet]:
        """
        Calculates key ratios based on available financial data and market data, then stores them.
        This is a complex method that would:
        1. Fetch latest CompanyProfile (for shares_outstanding, market_cap if not live).
        2. Fetch relevant FinancialReports (for earnings, revenue, debt, equity, etc.).
        3. Fetch current market price (from TradingService or price cache).
        4. Calculate ratios.
        5. Create/Update KeyRatioSet in DB.
        """
        logger.info(f"Calculating key ratios for {symbol} for date {report_date} (Not Implemented).")
        # TODO: Implement logic to fetch necessary data, calculate ratios, and store
        # Example:
        # profile = self.get_company_profile(symbol)
        # income_statement_annual = self.get_financial_reports(symbol, FinancialStatementType.INCOME_STATEMENT, TimeframeType.ANNUAL, limit=1)
        # balance_sheet_annual = self.get_financial_reports(symbol, FinancialStatementType.BALANCE_SHEET, TimeframeType.ANNUAL, limit=1)
        # ... and so on ...
        # market_price = get_live_price(symbol) # Needs a price source
        #
        # if not all([profile, income_statement_annual, balance_sheet_annual, market_price]):
        #     logger.error("Not enough data to calculate ratios.")
        #     return None
        #
        # # Calculation logic here...
        # eps = ...
        # pe_ratio = market_price / eps if eps else None
        # ...
        #
        # ratio_data = KeyRatioSetCreate(
        #     company_profile_id=profile.id,
        #     symbol=symbol,
        #     date=report_date, # or date of latest financials/market data
        #     period_type=TimeframeType.ANNUAL, # Or derive based on data used
        #     earnings_per_share=eps,
        #     price_to_earnings_ratio=pe_ratio,
        #     # ... other ratios
        #     last_refreshed=datetime.utcnow()
        # )
        # # Upsert logic for KeyRatioSet
        return None

    def get_key_ratios(self, symbol: str, date_gte: Optional[date] = None, limit: int = 5) -> List[KeyRatioSet]:
        """Retrieves key ratio sets from the database."""
        logger.debug(f"Fetching key ratios for {symbol} from DB.")
        query = self.db.query(KeyRatioSet).filter(KeyRatioSet.symbol == symbol)
        if date_gte:
            query = query.filter(KeyRatioSet.date >= date_gte)
        return query.order_by(KeyRatioSet.date.desc()).limit(limit).all()