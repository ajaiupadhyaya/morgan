# File: app/services/financial_data_service.py

import logging
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timezone, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import desc
from polygon import RESTClient
from polygon.rest.models import TickerDetails, StockFinancial # Import specific Polygon models for type hints
import redis
from redis.exceptions import RedisError
import json

from app.core.config import settings
# Models
from app.models.models import (
    CompanyProfile,
    FinancialReport,
    KeyRatioSet,
    FinancialStatementType,
    TimeframeType
)
# Schemas
from app.schemas.financials import (
    CompanyProfileCreate,
    FinancialReportCreate,
    KeyRatioSetCreate # For storing calculated ratios
)
# For getting price, we might need TradingService or a dedicated price service.
# For now, we'll assume a helper or placeholder for price.

logger = logging.getLogger(__name__)

# Placeholder for a price fetching function if TradingService isn't directly used here
# In a real app, this might come from another service or a price cache.
def get_current_market_price(symbol: str, trading_service_instance: Optional[Any] = None) -> Optional[float]:
    """Placeholder to get current market price.
    Ideally, integrate with TradingService or a dedicated price service.
    """
    if trading_service_instance: # If a TradingService instance is available
        try:
            return trading_service_instance.get_latest_price(symbol)
        except Exception as e:
            logger.warning(f"Could not get live price for {symbol} via TradingService: {e}")
            return None
    logger.warning(f"Live price fetching for {symbol} not implemented in FinancialDataService. Ratios needing price will be affected.")
    return None # Fallback

class FinancialDataService:
    def __init__(self, db_session: Session, redis_client: Optional[redis.Redis] = None, trading_service: Optional[Any] = None): # Added trading_service
        self.db = db_session
        self.redis = redis_client
        self.trading_service = trading_service # For fetching live prices for ratios
        if not settings.POLYGON_API_KEY:
            logger.error("POLYGON_API_KEY not configured. FinancialDataService may not function for fetching.")
            self.polygon_client = None
        else:
            try:
                self.polygon_client = RESTClient(settings.POLYGON_API_KEY)
                logger.info("Polygon.io RESTClient initialized for FinancialDataService.")
            except Exception as e:
                logger.error(f"Failed to initialize Polygon.io RESTClient: {e}", exc_info=True)
                self.polygon_client = None

    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
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

    def _set_to_cache(self, cache_key: str, data: Any, ttl_seconds: int = 3600 * 24): # Default 1 day
        if not self.redis:
            return
        try:
            # Custom default function to handle date/datetime for JSON serialization
            def json_converter(o):
                if isinstance(o, (datetime, date)):
                    return o.isoformat()
                raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")
            
            self.redis.setex(cache_key, ttl_seconds, json.dumps(data, default=json_converter))
            logger.debug(f"Data cached for key: {cache_key} with TTL: {ttl_seconds}s")
        except RedisError as e:
            logger.warning(f"Redis error setting cache for {cache_key}: {e}")
        except (TypeError, OverflowError) as serialization_error:
            logger.error(f"Failed to serialize data for caching {cache_key}: {serialization_error}")

    def _map_polygon_ticker_details_to_profile_dict(self, symbol: str, details: TickerDetails) -> Dict[str, Any]:
        """Maps Polygon.io TickerDetails object to our CompanyProfile dictionary structure."""
        profile_dict = {
            "symbol": getattr(details, 'ticker', symbol.upper()),
            "name": getattr(details, 'name', None),
            "cik": getattr(details, 'cik', None),
            "sector": getattr(details, 'sector', None) or getattr(details, 'sic_description', None),
            "industry": getattr(details, 'industry', None), # May also need derivation from SIC
            "description": getattr(details, 'description', None),
            "country": None, # Default
            "exchange": getattr(details, 'primary_exchange', None),
            "currency": getattr(details, 'currency_name', None),
            "market_cap": getattr(details, 'market_cap', None),
            "shares_outstanding": getattr(details, 'weighted_shares_outstanding', None) or \
                                  getattr(details, 'share_class_shares_outstanding', None),
            "phone": getattr(details, 'phone_number', None),
            "url": getattr(details, 'homepage_url', None),
            "logo_url": None, # Default
            "list_date": date.fromisoformat(details.list_date) if getattr(details, 'list_date', None) else None,
            "last_refreshed": datetime.now(timezone.utc) # Our refresh time
        }
        if hasattr(details, 'address') and details.address:
            profile_dict["country"] = getattr(details.address, 'country_code', None) or getattr(details.address, 'country', None)
        if hasattr(details, 'branding') and details.branding:
            profile_dict["logo_url"] = getattr(details.branding, 'logo_url', None) or getattr(details.branding, 'icon_url', None)
        
        # Polygon sometimes returns CIK as a string of digits, sometimes as integer. Standardize.
        if profile_dict["cik"] is not None and not isinstance(profile_dict["cik"], str):
            profile_dict["cik"] = str(profile_dict["cik"]).zfill(10) # CIK is 10 digits

        return profile_dict

    def fetch_and_upsert_company_profile(self, symbol: str) -> Optional[CompanyProfile]:
        if not self.polygon_client:
            logger.error("Polygon client not initialized. Cannot fetch profile.")
            return None

        cache_key = f"polygon:company_profile:{symbol.upper()}"
        # Attempt to load from cache
        cached_dict = self._get_from_cache(cache_key)
        profile_data_dict: Optional[Dict[str, Any]] = None

        if cached_dict:
            logger.info(f"Using cached company profile for {symbol}.")
            profile_data_dict = cached_dict
            # Deserialize dates if loaded from JSON string
            if profile_data_dict.get("list_date") and isinstance(profile_data_dict["list_date"], str):
                try:
                    profile_data_dict["list_date"] = date.fromisoformat(profile_data_dict["list_date"])
                except ValueError:
                    logger.warning(f"Invalid date format for list_date in cached data for {symbol}: {profile_data_dict['list_date']}")
                    profile_data_dict["list_date"] = None
            if profile_data_dict.get("last_refreshed") and isinstance(profile_data_dict["last_refreshed"], str):
                try:
                    profile_data_dict["last_refreshed"] = datetime.fromisoformat(profile_data_dict["last_refreshed"].replace("Z","+00:00"))
                except ValueError:
                     profile_data_dict["last_refreshed"] = datetime.now(timezone.utc) # Fallback

        if not profile_data_dict: # Not in cache or cache invalid
            try:
                logger.info(f"Fetching company profile for {symbol} from Polygon.io...")
                details: TickerDetails = self.polygon_client.get_ticker_details(symbol.upper())
                profile_data_dict = self._map_polygon_ticker_details_to_profile_dict(symbol, details)
                self._set_to_cache(cache_key, profile_data_dict)
            except Exception as e: # Catch specific Polygon exceptions if known, e.g., NoResultsError
                logger.error(f"Error fetching company profile for {symbol} from Polygon.io: {e}", exc_info=True)
                return None
        
        if not profile_data_dict: # Should not happen if API call was successful
            return None

        # Upsert to DB
        # Remove last_refreshed from dict before passing to Pydantic schema if it's meant for schema's default_factory
        db_last_refreshed_time = profile_data_dict.pop("last_refreshed", datetime.now(timezone.utc))

        try:
            profile_schema_data = CompanyProfileCreate(**profile_data_dict) # Validate with Pydantic
        except Exception as e: # Pydantic validation error
            logger.error(f"Pydantic validation error for company profile {symbol}: {e}", exc_info=True)
            return None

        db_profile = self.db.query(CompanyProfile).filter(CompanyProfile.symbol == profile_schema_data.symbol).first()
        if db_profile:
            logger.info(f"Updating existing company profile for {symbol} in DB.")
            for key, value in profile_schema_data.model_dump(exclude_unset=True).items():
                setattr(db_profile, key, value)
            db_profile.last_refreshed = db_last_refreshed_time # Use the refresh time from fetch/cache
        else:
            logger.info(f"Creating new company profile for {symbol} in DB.")
            db_profile = CompanyProfile(**profile_schema_data.model_dump())
            db_profile.last_refreshed = db_last_refreshed_time
        
        try:
            self.db.add(db_profile)
            self.db.commit()
            self.db.refresh(db_profile)
            return db_profile
        except Exception as e:
            self.db.rollback()
            logger.error(f"DB error storing company profile for {symbol}: {e}", exc_info=True)
            return None

    def get_company_profile_from_db(self, symbol: str) -> Optional[CompanyProfile]:
        logger.debug(f"Fetching company profile for {symbol.upper()} from DB.")
        return self.db.query(CompanyProfile).filter(CompanyProfile.symbol == symbol.upper()).first()

    def _extract_financial_values(self, statement_section: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Extracts 'value' from each line item in a Polygon.io financial statement section (e.g., income_statement)."""
        if not statement_section:
            return {}
        return {key: getattr(item, 'value', None) for key, item in statement_section.items()}

    def fetch_and_upsert_financial_reports(self, symbol: str, timeframe_enum: TimeframeType = TimeframeType.ANNUAL, limit: int = 5) -> List[FinancialReport]:
        if not self.polygon_client:
            logger.error(f"Polygon client not initialized. Cannot fetch financials for {symbol}.")
            return []

        profile = self.get_company_profile_from_db(symbol)
        if not profile:
            profile = self.fetch_and_upsert_company_profile(symbol) # Attempt to fetch profile if missing
            if not profile:
                logger.error(f"Company profile for {symbol} not found and could not be fetched. Cannot store financials.")
                return []
        
        company_profile_id = profile.id
        timeframe_value = timeframe_enum.value.lower() # Polygon expects 'annual' or 'quarterly'
        cache_key = f"polygon:financials:{symbol.upper()}:{timeframe_value}:{limit}"
        
        # This list will store dicts mapped from Polygon's StockFinancial objects
        raw_reports_as_dicts: List[Dict[str, Any]] = self._get_from_cache(cache_key) or []

        if not raw_reports_as_dicts:
            try:
                logger.info(f"Fetching {timeframe_value} financial reports for {symbol} (limit {limit}) from Polygon.io...")
                financials_iter = self.polygon_client.list_stock_financials(
                    ticker=symbol.upper(),
                    timeframe=timeframe_value,
                    limit=limit,
                    sort="filing_date" # Get most recent first
                )
                
                fetched_polygon_reports = list(financials_iter) # Convert iterator
                
                for report_obj in fetched_polygon_reports: # report_obj is a StockFinancial
                    # Map Polygon's StockFinancial object to a dictionary for caching and processing
                    financials_data_points = {}
                    if hasattr(report_obj, 'financials'):
                        financials_data_points["income_statement"] = self._extract_financial_values(getattr(report_obj.financials, 'income_statement', None))
                        financials_data_points["balance_sheet"] = self._extract_financial_values(getattr(report_obj.financials, 'balance_sheet', None))
                        financials_data_points["cash_flow_statement"] = self._extract_financial_values(getattr(report_obj.financials, 'cash_flow_statement', None))
                        financials_data_points["comprehensive_income"] = self._extract_financial_values(getattr(report_obj.financials, 'comprehensive_income', None))

                    report_dict = {
                        "filing_date": report_obj.filing_date,
                        "start_date": report_obj.start_date,
                        "end_date": report_obj.end_date, # This is period_of_report_date
                        "fiscal_year": getattr(report_obj, 'fiscal_year', None),
                        "fiscal_period": getattr(report_obj, 'fiscal_period', None),
                        "timeframe": getattr(report_obj, 'timeframe', timeframe_value), # 'annual' or 'quarterly'
                        "source_filing_url": getattr(report_obj, 'source_filing_url', None),
                        "source_filing_file_url": getattr(report_obj, 'source_filing_file_url', None),
                        "acceptance_datetime": getattr(report_obj, 'acceptance_datetime', None),
                        "financials": financials_data_points # This contains the extracted values
                    }
                    raw_reports_as_dicts.append(report_dict)
                
                if raw_reports_as_dicts:
                    self._set_to_cache(cache_key, raw_reports_as_dicts)
                
            except Exception as e:
                logger.error(f"Error fetching financial reports for {symbol} from Polygon.io: {e}", exc_info=True)
                return []
        else:
            logger.info(f"Using cached financial reports for {symbol} ({timeframe_value}).")

        stored_db_reports: List[FinancialReport] = []
        for report_data_dict in raw_reports_as_dicts:
            financial_statements_from_report = report_data_dict.get("financials", {})
            
            for stmt_type_enum in FinancialStatementType: # Iterate: INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT
                polygon_stmt_key = stmt_type_enum.value # e.g., "income_statement"
                
                # Extract the specific statement's line items
                statement_line_items = financial_statements_from_report.get(polygon_stmt_key)
                if not statement_line_items: # Skip if this statement type is not in the current report_data_dict.financials
                    continue

                try:
                    period_of_report_date = date.fromisoformat(report_data_dict["end_date"])
                    filing_date_val = date.fromisoformat(report_data_dict["filing_date"])
                    start_date_val = date.fromisoformat(report_data_dict["start_date"]) if report_data_dict.get("start_date") else None

                    report_create_data = {
                        "company_profile_id": company_profile_id,
                        "symbol": symbol.upper(),
                        "report_type": stmt_type_enum,
                        "timeframe": TimeframeType(report_data_dict["timeframe"]), # Map string to Enum
                        "fiscal_year": report_data_dict.get("fiscal_year"),
                        "fiscal_period": report_data_dict.get("fiscal_period"),
                        "filing_date": filing_date_val,
                        "period_of_report_date": period_of_report_date,
                        "start_date": start_date_val,
                        "data": statement_line_items, # Store only the specific statement's data
                        "source_filing_url": report_data_dict.get("source_filing_url"),
                        "source_filing_file_url": report_data_dict.get("source_filing_file_url"),
                        "acceptance_datetime_est": report_data_dict.get("acceptance_datetime"), # Polygon provides this as YYYYMMDDHHMMSS string
                        "last_refreshed": datetime.now(timezone.utc)
                    }
                    validated_data = FinancialReportCreate(**report_create_data)
                except Exception as val_err: # Catch Pydantic validation error or date parsing error
                    logger.error(f"Validation/Data error for financial report {symbol} {stmt_type_enum.value} for period ending {report_data_dict.get('end_date')}: {val_err}", exc_info=True)
                    continue # Skip this problematic report entry

                # Upsert logic
                db_report = self.db.query(FinancialReport).filter_by(
                    company_profile_id=company_profile_id,
                    report_type=stmt_type_enum,
                    timeframe=validated_data.timeframe,
                    period_of_report_date=validated_data.period_of_report_date
                ).first()

                if db_report:
                    logger.debug(f"Updating {stmt_type_enum.value} for {symbol} - {validated_data.period_of_report_date}")
                    for key, value in validated_data.model_dump(exclude_unset=True).items():
                        if key not in ["company_profile_id", "symbol", "report_type", "timeframe", "period_of_report_date"]: # Don't update PK components
                             setattr(db_report, key, value)
                    db_report.last_refreshed = datetime.now(timezone.utc)
                else:
                    logger.debug(f"Creating {stmt_type_enum.value} for {symbol} - {validated_data.period_of_report_date}")
                    db_report = FinancialReport(**validated_data.model_dump())
                    self.db.add(db_report)
                
                try:
                    self.db.commit()
                    self.db.refresh(db_report)
                    stored_db_reports.append(db_report)
                except Exception as e:
                    self.db.rollback()
                    logger.error(f"DB error storing {stmt_type_enum.value} for {symbol} ({validated_data.period_of_report_date}): {e}", exc_info=True)
        
        return stored_db_reports

    def get_financial_reports_from_db(self, symbol: str, 
                                   report_type: Optional[FinancialStatementType] = None, 
                                   timeframe: Optional[TimeframeType] = None, 
                                   limit: int = 20) -> List[FinancialReport]:
        logger.debug(f"Fetching financial reports for {symbol.upper()} from DB (type: {report_type}, timeframe: {timeframe}).")
        query = self.db.query(FinancialReport).filter(FinancialReport.symbol == symbol.upper())
        if report_type:
            query = query.filter(FinancialReport.report_type == report_type)
        if timeframe:
            query = query.filter(FinancialReport.timeframe == timeframe)
        return query.order_by(FinancialReport.period_of_report_date.desc(), FinancialReport.filing_date.desc()).limit(limit).all()


    # --- Key Ratios Methods ---
    def get_or_calculate_and_store_key_ratios(self, symbol: str, effective_date: Optional[date] = None) -> Optional[KeyRatioSet]:
        """
        Fetches existing key ratios for a symbol and date. If not found,
        calculates them using available data and stores them.
        If effective_date is None, uses the date of the latest available financials.
        """
        symbol_upper = symbol.upper()
        if not effective_date:
            # Try to find the date of the latest annual financial report
            latest_annual_report = self.db.query(FinancialReport.period_of_report_date)\
                .filter(FinancialReport.symbol == symbol_upper, FinancialReport.timeframe == TimeframeType.ANNUAL)\
                .order_by(desc(FinancialReport.period_of_report_date))\
                .first()
            if latest_annual_report:
                effective_date = latest_annual_report[0]
            else: # Fallback to latest quarterly if no annual
                latest_quarterly_report = self.db.query(FinancialReport.period_of_report_date)\
                    .filter(FinancialReport.symbol == symbol_upper, FinancialReport.timeframe == TimeframeType.QUARTERLY)\
                    .order_by(desc(FinancialReport.period_of_report_date))\
                    .first()
                if latest_quarterly_report:
                    effective_date = latest_quarterly_report[0]
                else: # Fallback to today if no financials found to determine effective_date
                    effective_date = date.today()
        
        logger.info(f"Getting/Calculating key ratios for {symbol_upper} effective {effective_date}.")

        # Check if ratios for this symbol and date (or period_type) already exist
        existing_ratios = self.db.query(KeyRatioSet).filter_by(
            symbol=symbol_upper,
            date=effective_date 
            # Potentially also filter by period_type if you store ratios for different timeframes on the same date
        ).first()

        if existing_ratios and (datetime.now(timezone.utc) - (existing_ratios.last_refreshed or datetime.min.replace(tzinfo=timezone.utc))).days < 30: # Example: refresh if older than 30 days
            logger.info(f"Returning existing, recent key ratios for {symbol_upper} on {effective_date}.")
            return existing_ratios

        # --- Data Gathering for Ratio Calculation ---
        profile = self.get_company_profile_from_db(symbol_upper)
        if not profile:
            logger.warning(f"Cannot calculate ratios for {symbol_upper}: Company profile not found.")
            return None

        # Fetch latest annual and quarterly financials (most recent ones up to the effective_date)
        annual_income_stmt = self._get_latest_financial_statement(symbol_upper, FinancialStatementType.INCOME_STATEMENT, TimeframeType.ANNUAL, effective_date)
        annual_balance_sheet = self._get_latest_financial_statement(symbol_upper, FinancialStatementType.BALANCE_SHEET, TimeframeType.ANNUAL, effective_date)
        
        # TTM (Trailing Twelve Months) data often needs to be summed from last 4 quarters
        # For simplicity, we'll use latest annual for some ratios, or you could implement TTM calculation.
        # EPS often comes directly from income statement (diluted_earnings_per_share)

        ratios_dict: Dict[str, Optional[float]] = {
            "price_to_earnings_ratio": None, "price_to_sales_ratio": None, "price_to_book_ratio": None,
            "earnings_per_share": None, "dividend_yield": None, "return_on_equity": None,
            "debt_to_equity_ratio": None, "current_ratio": None, "quick_ratio": None,
            "gross_profit_margin": None, "operating_profit_margin": None, "net_profit_margin": None,
        }

        # --- Ratio Calculations ---
        current_price = get_current_market_price(symbol_upper, self.trading_service)

        # Earnings Per Share (EPS) - often directly from income statement
        if annual_income_stmt and annual_income_stmt.data:
            # Polygon.io path: financials.income_statement.diluted_earnings_per_share.value
            eps_value = annual_income_stmt.data.get("diluted_earnings_per_share") or \
                        annual_income_stmt.data.get("basic_earnings_per_share")
            if isinstance(eps_value, (int, float)):
                ratios_dict["earnings_per_share"] = float(eps_value)

        # Price-to-Earnings (P/E)
        if current_price and ratios_dict["earnings_per_share"] and ratios_dict["earnings_per_share"] != 0:
            ratios_dict["price_to_earnings_ratio"] = current_price / ratios_dict["earnings_per_share"]

        # Revenue, Net Income, Gross Profit, Operating Income
        total_revenue, net_income, gross_profit, operating_income = None, None, None, None
        if annual_income_stmt and annual_income_stmt.data:
            total_revenue = annual_income_stmt.data.get("revenues") # Polygon: financials.income_statement.revenues.value
            net_income = annual_income_stmt.data.get("net_income_loss") # Polygon: financials.income_statement.net_income_loss.value
            gross_profit = annual_income_stmt.data.get("gross_profit") # Polygon: financials.income_statement.gross_profit.value
            operating_income = annual_income_stmt.data.get("operating_income_loss") # Polygon: financials.income_statement.operating_income_loss.value

        # Price-to-Sales (P/S)
        if current_price and profile and profile.shares_outstanding and total_revenue and profile.shares_outstanding !=0:
            sales_per_share = total_revenue / profile.shares_outstanding
            if sales_per_share != 0:
                ratios_dict["price_to_sales_ratio"] = current_price / sales_per_share
        
        # Margins
        if total_revenue and total_revenue != 0:
            if gross_profit is not None:
                ratios_dict["gross_profit_margin"] = gross_profit / total_revenue
            if operating_income is not None:
                ratios_dict["operating_profit_margin"] = operating_income / total_revenue
            if net_income is not None:
                ratios_dict["net_profit_margin"] = net_income / total_revenue

        # Balance Sheet items
        total_assets, total_liabilities, total_equity, current_assets, current_liabilities, cash_and_equivalents, inventory = \
            None, None, None, None, None, None, None
        if annual_balance_sheet and annual_balance_sheet.data:
            total_assets = annual_balance_sheet.data.get("assets") # Polygon: financials.balance_sheet.assets.value
            total_liabilities = annual_balance_sheet.data.get("liabilities") # Polygon: financials.balance_sheet.liabilities.value
            total_equity = annual_balance_sheet.data.get("equity") # Polygon: financials.balance_sheet.equity.value
            current_assets = annual_balance_sheet.data.get("current_assets") # Polygon: financials.balance_sheet.current_assets.value
            current_liabilities = annual_balance_sheet.data.get("current_liabilities") # Polygon: financials.balance_sheet.current_liabilities.value
            cash_and_equivalents = annual_balance_sheet.data.get("cash_and_cash_equivalents_at_carrying_value") # Example path
            inventory = annual_balance_sheet.data.get("inventory") # Example path

        # Debt-to-Equity (D/E)
        if total_liabilities is not None and total_equity is not None and total_equity != 0:
            ratios_dict["debt_to_equity_ratio"] = total_liabilities / total_equity

        # Price-to-Book (P/B)
        if current_price and profile and profile.shares_outstanding and total_equity and profile.shares_outstanding != 0:
            book_value_per_share = total_equity / profile.shares_outstanding
            if book_value_per_share != 0:
                ratios_dict["price_to_book_ratio"] = current_price / book_value_per_share
        
        # Return on Equity (ROE)
        if net_income is not None and total_equity is not None and total_equity != 0:
            ratios_dict["return_on_equity"] = net_income / total_equity
            
        # Current Ratio
        if current_assets is not None and current_liabilities is not None and current_liabilities != 0:
            ratios_dict["current_ratio"] = current_assets / current_liabilities

        # Quick Ratio (Acid Test)
        if current_assets is not None and inventory is not None and current_liabilities is not None and current_liabilities != 0:
            ratios_dict["quick_ratio"] = (current_assets - inventory) / current_liabilities

        # Dividend Yield - Requires dividend data, not easily available from just financials/profile.
        # For now, will leave as None. Polygon.io has a separate Dividends API.

        # --- Store Calculated Ratios ---
        if existing_ratios:
            logger.info(f"Updating existing key ratios for {symbol_upper} on {effective_date}.")
            for key, value in ratios_dict.items():
                if hasattr(existing_ratios, key): # Check if the attribute exists on the model
                    setattr(existing_ratios, key, value)
            existing_ratios.last_refreshed = datetime.now(timezone.utc)
            db_ratio_set = existing_ratios
        else:
            logger.info(f"Creating new key ratios set for {symbol_upper} on {effective_date}.")
            # Ensure all required fields for KeyRatioSetCreate are present
            key_ratio_create_data = KeyRatioSetCreate(
                company_profile_id=profile.id,
                symbol=symbol_upper,
                date=effective_date,
                period_type=TimeframeType.ANNUAL, # Assuming annual for now based on data used
                **ratios_dict # Unpack calculated ratios
            )
            db_ratio_set = KeyRatioSet(**key_ratio_create_data.model_dump())
            db_ratio_set.last_refreshed = datetime.now(timezone.utc)
            self.db.add(db_ratio_set)

        try:
            self.db.commit()
            self.db.refresh(db_ratio_set)
            logger.info(f"Successfully calculated and stored/updated key ratios for {symbol_upper} on {effective_date}.")
            return db_ratio_set
        except Exception as e:
            self.db.rollback()
            logger.error(f"DB error storing key ratios for {symbol_upper}: {e}", exc_info=True)
            return None

    def _get_latest_financial_statement(self, symbol: str, stmt_type: FinancialStatementType, timeframe: TimeframeType, effective_date: date) -> Optional[FinancialReport]:
        """Helper to get the most recent financial statement of a specific type and timeframe on or before an effective date."""
        return self.db.query(FinancialReport)\
            .filter(FinancialReport.symbol == symbol,
                    FinancialReport.report_type == stmt_type,
                    FinancialReport.timeframe == timeframe,
                    FinancialReport.period_of_report_date <= effective_date)\
            .order_by(desc(FinancialReport.period_of_report_date))\
            .first()