# File: app/main.py

import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session # Added for type hint in init_db call if needed by init_db

# Import settings
from app.core.config import settings as app_settings

# Import routers
from app.api import auth_router      # Authentication routes
from app.api import endpoints as app_endpoints # Core application (trading, ML, etc.) routes
from app.api import financials_router # NEW: Financial data analysis routes

# Database initialization
from app.db import init_db
from app.db.session import SessionLocal # For creating a session for init_db

# Configure logging
# It's good practice to configure logging more centrally, e.g., using dictConfig
# For now, basic logger for this file.
logging.basicConfig(level=logging.INFO) # Ensure basicConfig is called if not done elsewhere
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title=app_settings.PROJECT_NAME,
    description="Advanced Quantitative Trading Platform - AI-Powered Algo Trading, Fundamental Analysis, and Research", # Expanded description
    version="1.1.0" # Incremented version for new features
    # You can add other OpenAPI metadata like contact, license_info, etc.
    # openapi_tags = [ # Example of defining tags for better Swagger UI organization
    #     {"name": "Authentication", "description": "User authentication and authorization."},
    #     {"name": "Application Endpoints", "description": "Core trading, ML, and general application functionalities."},
    #     {"name": "Financial Data", "description": "Access to company fundamental data and financial reports."},
    #     {"name": "General", "description": "Basic API information and health checks."},
    # ]
)

# --- Event Handlers ---
@app.on_event("startup")
async def startup_event():
    """
    Application startup event.
    Initializes the database (creates tables and default superuser if not present).
    """
    logger.info(f"Starting up {app_settings.PROJECT_NAME} API v{app.version}...")
    db: Optional[Session] = None # Ensure db is defined for finally block
    try:
        logger.info("Attempting database initialization...")
        db = SessionLocal()
        init_db.init_db(db) # Pass the session to init_db
        logger.info("Database initialization process completed.")
    except Exception as e:
        logger.error(f"CRITICAL: Error during database initialization on startup: {e}", exc_info=True)
        # Depending on severity, you might want to prevent app startup or have a degraded mode.
    finally:
        if db:
            db.close()
            logger.debug("DB session closed after init_db.")
    logger.info(f"{app_settings.PROJECT_NAME} API started successfully.")

@app.on_event("shutdown")
async def shutdown_event():
    """
    Application shutdown event.
    """
    logger.info(f"{app_settings.PROJECT_NAME} API shutting down.")
    # Add any cleanup tasks here if needed (e.g., closing other resources)

# --- Middleware ---
# CORS middleware configuration
if app_settings.FRONTEND_URL:
    # Split FRONTEND_URL by comma if multiple origins are provided
    origins = [str(origin).strip() for origin in app_settings.FRONTEND_URL.split(',')]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"], # Allows all standard methods
        allow_headers=["*"], # Allows all headers
    )
    logger.info(f"CORS middleware enabled for origins: {origins}")
else:
    logger.warning(
        "FRONTEND_URL not set in environment variables. "
        "CORS middleware not fully configured, which may restrict frontend access."
    )

# --- Router Inclusion ---
# All routers will be prefixed with API_V1_STR (e.g., /api)

# Authentication router (e.g., /api/auth/token, /api/auth/register)
# The internal prefix "/auth" is set within auth_router.py
app.include_router(auth_router.router, prefix=app_settings.API_V1_STR)

# Core application endpoints router (e.g., /api/health, /api/account, /api/predict/{symbol})
# The internal tags are set within endpoints.py
app.include_router(app_endpoints.router, prefix=app_settings.API_V1_STR)

# NEW: Financial data analysis router (e.g., /api/financials/company/{symbol}/profile)
# The internal prefix "/financials" is set within financials_router.py
app.include_router(financials_router.router, prefix=app_settings.API_V1_STR)


# --- Root Endpoint ---
@app.get("/", tags=["General"], summary="API Root")
async def root():
    """
    Root endpoint providing a welcome message and API status.
    """
    return {
        "message": f"Welcome to {app_settings.PROJECT_NAME} API",
        "status": "operational",
        "version": app.version,
        "documentation_url": "/docs" # Link to Swagger UI
    }

# The primary /health endpoint is now part of app_endpoints.router and provides more detail.
# If you need an ultra-lightweight health check here for load balancers before routing,
# you could add one, but the one in app_endpoints should suffice.

# --- Main Execution (for direct run, e.g., python main.py) ---
if __name__ == "__main__":
    # This configuration is for running with `python main.py`
    # When deploying with Gunicorn or another ASGI server, these settings are typically passed as CLI args.
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = "%(asctime)s - %(levelname)s - %(client_addr)s - \"%(request_line)s\" %(status_code)s"
    log_config["formatters"]["default"]["fmt"] = "%(asctime)s - %(levelname)s - %(message)s"
    
    logger.info(f"Starting Uvicorn server directly for {app_settings.PROJECT_NAME}...")
    uvicorn.run(
        "main:app", # Points to the 'app' instance in this 'main.py' file
        host="0.0.0.0", # Listen on all available IPs
        port=8000,      # Standard port, can be configured via env var if needed
        reload=True,    # Enable auto-reload for development (disable in production)
        log_config=log_config # Use custom log config for better formatting
    )