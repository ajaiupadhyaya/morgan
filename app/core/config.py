import os
import logging
from typing import Optional, List # List added for potential CORS expansion
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import EmailStr # For validating SUPERUSER_EMAIL

# Configure logger for this module
logger = logging.getLogger(__name__)

# Load environment variables from .env file at the project root
# Ensure your .env file is in the root directory where the application is launched from.
load_dotenv()

class Settings(BaseSettings):
    # API Settings
    API_V1_STR: str = os.getenv("API_V1_STR", "/api") #
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "Morgan Trading Platform") #

    # Environment Setting
    # Useful for conditional logic (e.g., in init_db.py, or for debug modes)
    # Common values: "development", "staging", "production"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()

    # Security Settings
    # WARNING: THIS IS A CRITICAL SECRET AND MUST BE OVERRIDDEN IN PRODUCTION
    # WITH A STRONG, RANDOMLY GENERATED KEY (e.g., openssl rand -hex 32).
    # DO NOT USE THE DEFAULT IN PRODUCTION.
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-very-secret-key-that-must-be-changed-immediately") #
    
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 8)))  # 8 days
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    
    TWO_FACTOR_TEMP_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("TWO_FACTOR_TEMP_TOKEN_EXPIRE_MINUTES", "5")) # Expiry for temporary 2FA tokens

    # Fernet Encryption Key for sensitive data like external API keys
    # WARNING: THIS IS A CRITICAL SECRET FOR ENCRYPTION.
    # IT MUST BE A URL-SAFE BASE64-ENCODED 32-BYTE KEY.
    # Generate one with: from cryptography.fernet import Fernet; Fernet.generate_key().decode()
    # STORE THIS SECURELY AS AN ENVIRONMENT VARIABLE.
    # The default value provided here is FOR DEVELOPMENT/DEMONSTRATION ONLY and is HIGHLY INSECURE for production.
    FERNET_SECRET_KEY: str = os.getenv("FERNET_SECRET_KEY", "k1_ZytG0nPLyQ45FmJ2AsI8gwhz2J9A15wD0Ml6tjHK=") # Default is INSECURE

    # CORS (Cross-Origin Resource Sharing)
    # Can be a single URL or a comma-separated list of URLs for multiple origins.
    # e.g., FRONTEND_URL="http://localhost:5173,https://your.production.domain"
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173") #
    
    # Database Settings
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/morgan") # (updated default to use 'db' service name often used in Docker)
    
    # Initial Superuser Credentials (Loaded from environment variables for security)
    # These are used by app/db/init_db.py
    SUPERUSER_EMAIL: EmailStr = os.getenv("SUPERUSER_EMAIL", "admin@example.com")
    # WARNING: Set a strong password for SUPERUSER_PASSWORD in your .env file for production.
    # The default "changethispassword" is insecure.
    SUPERUSER_PASSWORD: str = os.getenv("SUPERUSER_PASSWORD", "changethispassword")

    # Alpaca API (Global defaults, if any. User-specific keys are stored encrypted in the DB)
    # These might not be needed if the app exclusively uses user-provided keys.
    ALPACA_API_KEY: Optional[str] = os.getenv("ALPACA_API_KEY") #
    ALPACA_API_SECRET: Optional[str] = os.getenv("ALPACA_API_SECRET") #
    ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets") #
    # ALPACA_LIVE_BASE_URL: str = os.getenv("ALPACA_LIVE_BASE_URL", "https://api.alpaca.markets") # Example for live trading

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0") # (updated default to use 'redis' service name and specify DB 0)
    
    # ML Model Settings
    MODEL_PATH: str = os.getenv("MODEL_PATH", "app/ml/models") #
    
    # Polygon.io API
    POLYGON_API_KEY: Optional[str] = os.getenv("POLYGON_API_KEY") #
    
    # ML Configuration
    TRAINING_DATA_PATH: str = os.getenv("TRAINING_DATA_PATH", "data/training") #
    PREDICTION_CACHE_TTL: int = int(os.getenv("PREDICTION_CACHE_TTL", "3600"))  # 1 hour in seconds
    
    # Trading Configuration (Global defaults. User-specific settings might override these)
    DEFAULT_PORTFOLIO_SIZE: float = float(os.getenv("DEFAULT_PORTFOLIO_SIZE", "100000.0")) #
    MAX_POSITION_SIZE: float = float(os.getenv("MAX_POSITION_SIZE", "0.1"))  # 10% of portfolio
    STOP_LOSS_PERCENTAGE: float = float(os.getenv("STOP_LOSS_PERCENTAGE", "0.02"))  # 2%

    # Pydantic settings configuration (for Pydantic V2 and pydantic-settings)
    model_config = SettingsConfigDict(
        env_file=".env",         # Specifies the .env file to load (pydantic-settings handles this implicitly too)
        env_file_encoding='utf-8',
        case_sensitive=True,     # Environment variable names are case-sensitive
        extra='ignore'           # Ignore extra fields not defined in the model
    )

settings = Settings()

# --- Runtime Security Checks & Warnings ---
# These will log warnings if insecure default settings are detected at runtime.
# It's crucial to heed these warnings for production deployments.

if settings.SECRET_KEY == "your-very-secret-key-that-must-be-changed-immediately":
    logger.critical(
        "CRITICAL SECURITY WARNING (config.py): Default 'SECRET_KEY' is in use. "
        "This is highly insecure. Generate a strong, random key (e.g., `openssl rand -hex 32`) "
        "and set it as the SECRET_KEY environment variable for production."
    )

if settings.FERNET_SECRET_KEY == "k1_ZytG0nPLyQ45FmJ2AsI8gwhz2J9A15wD0Ml6tjHK=":
    logger.critical(
        "CRITICAL SECURITY WARNING (config.py): Default 'FERNET_SECRET_KEY' is in use. "
        "This key is for DEVELOPMENT/DEMONSTRATION ONLY and is INSECURE for encrypting sensitive data. "
        "Generate a unique Fernet key (`from cryptography.fernet import Fernet; Fernet.generate_key().decode()`) "
        "and set it as the FERNET_SECRET_KEY environment variable for production."
    )

if settings.ENVIRONMENT != "development" and settings.SUPERUSER_PASSWORD == "changethispassword":
    logger.critical(
        "CRITICAL SECURITY WARNING (config.py): Default 'SUPERUSER_PASSWORD' ('changethispassword') "
        "is being used in a non-development environment ('%s'). This is highly insecure. "
        "Set a strong, unique SUPERUSER_PASSWORD environment variable for production.",
        settings.ENVIRONMENT
    )

# Optional: Log some key settings on startup (be careful not to log secrets)
logger.info(f"Application '{settings.PROJECT_NAME}' running in '{settings.ENVIRONMENT}' mode.")
logger.info(f"CORS configured for frontend URL(s): {settings.FRONTEND_URL}")
logger.info(f"Database URL: {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else 'configured (details hidden)'}") # Avoid logging credentials
logger.info(f"Redis URL: {settings.REDIS_URL.split('@')[-1] if '@' in settings.REDIS_URL else 'configured (details hidden)'}")