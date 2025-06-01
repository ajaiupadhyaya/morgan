from pydantic_settings import BaseSettings
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # API Configuration
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Vuoksi AI Trader"
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/morgan")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    # Alpaca API
    ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")
    ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    
    # Polygon.io API
    POLYGON_API_KEY: Optional[str] = os.getenv("POLYGON_API_KEY")
    
    # ML Configuration
    MODEL_PATH: str = "models"
    TRAINING_DATA_PATH: str = "data/training"
    PREDICTION_CACHE_TTL: int = 3600  # 1 hour
    
    # Trading Configuration
    DEFAULT_PORTFOLIO_SIZE: float = 100000.0
    MAX_POSITION_SIZE: float = 0.1  # 10% of portfolio
    STOP_LOSS_PERCENTAGE: float = 0.02  # 2%
    
    class Config:
        case_sensitive = True

settings = Settings() 