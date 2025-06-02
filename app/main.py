import logging
import uvicorn
from fastapi import FastAPI, HTTPException # Depends removed as not directly used here
from fastapi.middleware.cors import CORSMiddleware
# OAuth2PasswordBearer removed as routers will handle their own security dependencies from app.core.security

# Import settings
from app.core.config import settings as app_settings #

# Import routers - Adjust based on your final router structure
# Assuming auth_router.py contains the main authentication router
# and endpoints.py contains other core application endpoints.
from app.api import auth_router # Our comprehensive auth router
from app.api import endpoints as app_endpoints # Our comprehensive app endpoints router

# Database initialization
from app.db import init_db # For initial DB setup
from app.db.session import SessionLocal # For DB operations if needed directly in main

# Configure logging
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title=app_settings.PROJECT_NAME, #
    description="Advanced Quantitative Trading Platform - AI-Powered Algo Trading", # Enhanced description
    version="1.0.0" #
)

# --- Event Handlers ---
@app.on_event("startup")
async def startup_event():
    """
    Application startup event.
    Initializes the database.
    """
    logger.info("Application startup...")
    try:
        # This is suitable for development/initial setup.
        # In production, migrations are typically handled separately (e.g., with Alembic CLI).
        db = SessionLocal()
        init_db.init_db(db) # Pass the session to init_db
        logger.info("Database initialization attempted.")
    except Exception as e:
        logger.error(f"Error during database initialization: {e}", exc_info=True)
    finally:
        if 'db' in locals() and db:
            db.close()
    logger.info("Morgan Trading Platform API started successfully.")

@app.on_event("shutdown")
async def shutdown_event():
    """
    Application shutdown event.
    """
    logger.info("Morgan Trading Platform API shutting down.")

# --- Middleware ---
# CORS middleware configuration
if app_settings.FRONTEND_URL: #
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).strip() for origin in app_settings.FRONTEND_URL.split(",")] if "," in app_settings.FRONTEND_URL else [app_settings.FRONTEND_URL], # Handle single or multiple origins
        allow_credentials=True, #
        allow_methods=["*"], #
        allow_headers=["*"], #
    )
    logger.info(f"CORS middleware enabled for origins: {app_settings.FRONTEND_URL}")
else:
    logger.warning("FRONTEND_URL not set, CORS middleware not fully configured.")


# --- Router Inclusion ---
# Include the consolidated authentication router
# The prefix="/auth" was already set in auth_router.py
# If API_V1_STR is /api, then auth routes will be /api/auth/...
app.include_router(auth_router.router, prefix=app_settings.API_V1_STR) #

# Include the main application endpoints router
# The prefix for these endpoints can be defined here or within endpoints.py itself.
# If API_V1_STR is /api, then these routes will be /api/... (e.g., /api/health, /api/account)
app.include_router(app_endpoints.router, prefix=app_settings.API_V1_STR) #

# Comment out or remove redundant/old router inclusions if they were previously used:
# app.include_router(auth.router, prefix="/api", tags=["auth"]) # OLD - functionality now in auth_router
# app.include_router(trading.router, prefix="/api", tags=["trading"]) # Assuming covered by app_endpoints
# app.include_router(analytics.router, prefix="/api", tags=["analytics"]) # Assuming covered by app_endpoints
# app.include_router(settings.router, prefix="/api", tags=["settings"]) # User settings likely in auth_router or dedicated user_settings_router

# --- Root and Basic Health Check ---
@app.get("/", tags=["General"])
async def root():
    """
    Root endpoint providing a welcome message.
    """
    return {
        "message": f"Welcome to {app_settings.PROJECT_NAME} API", #
        "status": "operational",
        "version": app.version #
    }

# The /health endpoint is now part of app_endpoints.router
# If you want a very basic health check directly in main.py before routers are hit:
# @app.get("/main-health", tags=["General"])
# async def main_health_check():
#     return {"status": "API core is healthy"}

# --- Main Execution ---
if __name__ == "__main__":
    logger.info("Starting Uvicorn server directly (main.py execution)...")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info" # Add log level for uvicorn
    ) #