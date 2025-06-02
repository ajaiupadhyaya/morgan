from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import logging # Optional: for logging connection issues

from app.core.config import settings

logger = logging.getLogger(__name__) # Optional

try:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True) # pool_pre_ping is good for resilience
    # For more control over connection pooling, you can add parameters like:
    # engine = create_engine(
    #     settings.DATABASE_URL,
    #     pool_size=10,  # Example: Number of connections to keep open in the pool
    #     max_overflow=20,  # Example: Max connections that can be opened beyond pool_size
    #     pool_timeout=30,  # Example: Seconds to wait before giving up on getting a connection
    #     pool_recycle=1800 # Example: Recycle connections after 30 minutes
    # )
    logger.info("Database engine created successfully.")
except Exception as e:
    logger.error(f"Failed to create database engine: {e}", exc_info=True)
    # Depending on your application's needs, you might want to raise the exception
    # or handle it to prevent the app from starting if the DB is critical.
    raise  # Re-raise to ensure the app doesn't start with a bad DB config

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) #
logger.info("Database SessionLocal created.")

def get_db():
    """
    FastAPI dependency to get a database session.
    Ensures the database session is always closed after the request.
    """
    db = SessionLocal() #
    try:
        yield db #
    finally:
        db.close() #