auth_router_code = """
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Any

from app.models.models import User
from app.db.session import get_db
from app.core.auth import create_access_token, authenticate_user, get_password_hash, get_current_active_user
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=dict)
def register_user(email: str, password: str, db: Session = Depends(get_db)) -> Any:
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(
        email=email,
        hashed_password=get_password_hash(password),
        is_active=True,
        is_superuser=False
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User registered successfully", "user_id": new_user.id}

@router.post("/token", response_model=dict)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
) -> Any:
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=dict)
def read_users_me(current_user: User = Depends(get_current_active_user)) -> Any:
    return {
        "email": current_user.email,
        "is_active": current_user.is_active,
        "created_at": str(current_user.created_at)
    }
"""

auth_router_path = "/mnt/data/morgan_extracted/morgan/app/api/auth_router.py"
with open(auth_router_path, "w") as f:
    f.write(auth_router_code)

"✅ `auth_router.py` created with register, login, and profile endpoints. Next, we'll hook it into main.py."