from sqlalchemy.orm import Session
from app.db.session import engine
from app.models.models import Base
from app.core.config import settings
from app.core.auth import get_password_hash

def init_db() -> None:
    """Initialize the database with tables and initial data"""
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    # Create initial superuser if it doesn't exist
    from app.models.models import User
    from app.db.session import SessionLocal
    
    db = SessionLocal()
    try:
        superuser = db.query(User).filter(User.email == "admin@morgan.com").first()
        if not superuser:
            superuser = User(
                email="admin@morgan.com",
                hashed_password=get_password_hash("admin123"),  # Change this in production!
                is_active=True,
                is_superuser=True
            )
            db.add(superuser)
            db.commit()
            print("Created initial superuser")
    finally:
        db.close()

if __name__ == "__main__":
    print("Creating initial data")
    init_db()
    print("Initial data created") 