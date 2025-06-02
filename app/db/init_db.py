import logging
from sqlalchemy.orm import Session

# Core application imports
from app.core.config import settings
# Updated import path for get_password_hash
from app.core.security import get_password_hash

# Database session and models
from app.db.session import engine, SessionLocal
# This import assumes your Base and User model are accessible via app.models.models
# e.g., defined in app/models/models.py or app/models/user.py and exposed via app/models/__init__.py
from app.models.models import Base, User


logger = logging.getLogger(__name__)

# Ensure SUPERUSER_EMAIL and SUPERUSER_PASSWORD are in your Settings
# Add them to app/core/config.py if they aren't:
# SUPERUSER_EMAIL: EmailStr = os.getenv("SUPERUSER_EMAIL", "admin@example.com")
# SUPERUSER_PASSWORD: str = os.getenv("SUPERUSER_PASSWORD", "changethispassword")

def init_db(db: Optional[Session] = None) -> None:
    """
    Initialize the database with tables and an initial superuser.
    Creates tables defined by models inheriting from Base.
    Creates a superuser if one does not exist, using credentials from settings.
    """
    logger.info("Initializing database: Creating tables...")
    try:
        Base.metadata.create_all(bind=engine) #
        logger.info("Database tables created (if they didn't exist).")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}", exc_info=True)
        # Depending on the error, you might want to raise it or handle it
        return # Stop if table creation fails

    # Manage session: use provided session or create a new one
    session_provided = db is not None
    if not session_provided:
        db = SessionLocal() #
        logger.debug("Created new DB session for init_db.")
    
    try:
        # Check if superuser email and password are set in settings
        if not settings.SUPERUSER_EMAIL or not settings.SUPERUSER_PASSWORD:
            logger.warning(
                "SUPERUSER_EMAIL or SUPERUSER_PASSWORD not set in environment/settings. "
                "Skipping superuser creation."
            )
            return

        # Create initial superuser if it doesn't exist
        superuser = db.query(User).filter(User.email == settings.SUPERUSER_EMAIL).first() #
        
        if not superuser:
            logger.info(f"Creating initial superuser: {settings.SUPERUSER_EMAIL}")
            
            # Basic check for default password in a deployed environment
            if settings.ENVIRONMENT != "development" and settings.SUPERUSER_PASSWORD == "changethispassword":
                logger.critical(
                    "CRITICAL SECURITY WARNING: Default SUPERUSER_PASSWORD is being used in a non-development environment. "
                    "This is highly insecure. Please set a strong, unique SUPERUSER_PASSWORD environment variable."
                )
                # Optionally, you could prevent superuser creation here or raise an error
                # For now, it will proceed but log a critical warning.

            superuser_in = User( #
                email=settings.SUPERUSER_EMAIL,
                hashed_password=get_password_hash(settings.SUPERUSER_PASSWORD), #
                is_active=True, #
                is_superuser=True, #
                # Add other default fields for User if necessary
                # e.g., full_name="Default Admin"
            )
            db.add(superuser) #
            db.commit() #
            logger.info(f"Initial superuser {settings.SUPERUSER_EMAIL} created successfully.")
        else:
            logger.info(f"Superuser {settings.SUPERUSER_EMAIL} already exists. Skipping creation.")
            
    except Exception as e:
        logger.error(f"Error during superuser creation: {e}", exc_info=True)
        if not session_provided: # Only rollback if we created the session
            db.rollback()
    finally:
        if not session_provided: # Only close if we created the session
            db.close()
            logger.debug("Closed DB session for init_db.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO) # Basic logging for standalone script execution
    logger.info("Attempting to create initial database data...")
    init_db()
    logger.info("Initial database data creation process finished.")