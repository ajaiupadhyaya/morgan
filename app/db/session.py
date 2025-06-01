from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Write this to the correct path
session_path = "/mnt/data/morgan_extracted/morgan/app/db/session.py"
os.makedirs(os.path.dirname(session_path), exist_ok=True)

with open(session_path, "w") as f:
    f.write(session_code)

# Now create blank __init__.py files for required modules
init_paths = [
    "/mnt/data/morgan_extracted/morgan/app/__init__.py",
    "/mnt/data/morgan_extracted/morgan/app/api/__init__.py",
    "/mnt/data/morgan_extracted/morgan/app/db/__init__.py",
    "/mnt/data/morgan_extracted/morgan/app/models/__init__.py",
    "/mnt/data/morgan_extracted/morgan/app/core/__init__.py",
]

for path in init_paths:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("")

"Session file and __init__.py modules created. Ready to write auth_router next."