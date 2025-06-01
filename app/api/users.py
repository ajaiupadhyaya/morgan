from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Any
from datetime import timedelta

from app.core.auth import (
    authenticate_user,
    create_access_token,
    get_password_hash,
    get_current_active_user
)
from app.core.config import settings
from app.db.session import get_db
from app.models.models import User

router = APIRouter()

@router.post("/register")
async def register_user(
    email: str,
    password: str,
    db: Session = Depends(get_db)
) -> Any:
    """Register a new user"""
    # Check if user already exists
    db_user = db.query(User).filter(User.email == email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    hashed_password = get_password_hash(password)
    db_user = User(
        email=email,
        hashed_password=hashed_password,
        is_active=True
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return {"message": "User created successfully"}

@router.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
) -> Any:
    """Get access token for user"""
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

@router.get("/me")
async def read_users_me(
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """Get current user information"""
    return {
        "email": current_user.email,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at
    }

@router.put("/me")
async def update_user(
    alpaca_api_key: str = None,
    alpaca_secret_key: str = None,
    portfolio_size: float = None,
    risk_tolerance: float = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Any:
    """Update user settings"""
    if alpaca_api_key:
        current_user.alpaca_api_key = alpaca_api_key
    if alpaca_secret_key:
        current_user.alpaca_secret_key = alpaca_secret_key
    if portfolio_size:
        current_user.portfolio_size = portfolio_size
    if risk_tolerance:
        current_user.risk_tolerance = risk_tolerance
    
    db.commit()
    db.refresh(current_user)
    
    return {
        "message": "User settings updated successfully",
        "email": current_user.email,
        "portfolio_size": current_user.portfolio_size,
        "risk_tolerance": current_user.risk_tolerance
    } 