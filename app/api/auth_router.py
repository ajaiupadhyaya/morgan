from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from datetime import timedelta
from typing import Any
import logging
import re
from pydantic import BaseModel, validator

from app.core import security
from app.core.config import settings
from app.core.rate_limiter import RateLimiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse
from app.schemas.token import Token

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter()

# Rate limiter instances
login_limiter = RateLimiter(max_attempts=5, window_minutes=15)  # 5 attempts per 15 min
register_limiter = RateLimiter(max_attempts=3, window_minutes=60)  # 3 attempts per hour

class TwoFactorRequest(BaseModel):
    token: str
    
    @validator('token')
    def validate_token(cls, v):
        if not re.match(r'^\d{6}$', v):
            raise ValueError('2FA token must be 6 digits')
        return v

class AlpacaKeysRequest(BaseModel):
    api_key: str
    secret_key: str
    is_paper: bool = True
    
    @validator('api_key', 'secret_key')
    def validate_keys(cls, v):
        if len(v.strip()) < 10:
            raise ValueError('API keys must be at least 10 characters')
        return v.strip()

@router.post("/token", response_model=Token)
async def login(
    request: Request,
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    Authenticate user and return access token.
    Includes rate limiting and comprehensive security logging.
    """
    client_ip = request.client.host
    
    # Rate limiting check
    if not login_limiter.allow_request(client_ip):
        logger.warning(f"Rate limit exceeded for login attempt from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )
    
    try:
        # Log login attempt (don't log passwords!)
        logger.info(f"Login attempt for email: {form_data.username} from IP: {client_ip}")
        
        user = security.authenticate_user(db, form_data.username, form_data.password)
        if not user:
            logger.warning(f"Failed login attempt for email: {form_data.username} from IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Check if user account is active
        if not user.is_active:
            logger.warning(f"Login attempt for inactive user: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is disabled",
            )
        
        # Check if 2FA is required and enabled for this user
        if user.two_factor_enabled:
            # Return temporary token that requires 2FA completion
            temp_token = security.create_temp_token(data={"sub": user.email})
            logger.info(f"2FA required for user: {user.email}")
            return {
                "access_token": temp_token, 
                "token_type": "bearer",
                "requires_2fa": True
            }
        
        # Create full access token
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = security.create_access_token(
            data={"sub": user.email}, expires_delta=access_token_expires
        )
        
        logger.info(f"Successful login for user: {user.email}")
        return {
            "access_token": access_token, 
            "token_type": "bearer",
            "requires_2fa": False
        }
        
    except SQLAlchemyError as e:
        logger.error(f"Database error during login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service temporarily unavailable"
        )
    except Exception as e:
        logger.error(f"Unexpected error during login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )

@router.post("/verify-2fa", response_model=Token)
async def verify_two_factor(
    request: Request,
    two_factor_data: TwoFactorRequest,
    current_user: User = Depends(security.get_current_temp_user),
    db: Session = Depends(get_db)
) -> Any:
    """
    Verify 2FA token and return full access token.
    """
    client_ip = request.client.host
    
    try:
        # Verify 2FA token
        is_valid = security.verify_2fa_token(current_user, two_factor_data.token)
        if not is_valid:
            logger.warning(f"Invalid 2FA token for user: {current_user.email} from IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid 2FA token"
            )
        
        # Create full access token
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = security.create_access_token(
            data={"sub": current_user.email}, expires_delta=access_token_expires
        )
        
        logger.info(f"2FA verification successful for user: {current_user.email}")
        return {
            "access_token": access_token, 
            "token_type": "bearer",
            "requires_2fa": False
        }
        
    except Exception as e:
        logger.error(f"Error during 2FA verification: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="2FA verification failed"
        )

@router.post("/register", response_model=UserResponse)
async def register(
    request: Request,
    db: Session = Depends(get_db),
    user_in: UserCreate,
) -> Any:
    """
    Register new user with comprehensive validation and security checks.
    """
    client_ip = request.client.host
    
    # Rate limiting check
    if not register_limiter.allow_request(client_ip):
        logger.warning(f"Rate limit exceeded for registration from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again later.",
        )
    
    try:
        logger.info(f"Registration attempt for email: {user_in.email} from IP: {client_ip}")
        
        # Check if user already exists (prevent email enumeration)
        existing_user = db.query(User).filter(User.email == user_in.email).first()
        if existing_user:
            logger.warning(f"Registration attempt for existing email: {user_in.email}")
            # Don't reveal that user exists - generic message
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registration request could not be processed. Please contact support if this persists.",
            )
        
        # Validate password strength
        if not security.validate_password_strength(user_in.password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password does not meet security requirements. Must contain at least 8 characters, including uppercase, lowercase, numbers, and special characters.",
            )
        
        # Create user
        user = security.create_user(db, user_in)
        
        logger.info(f"User registration successful: {user.email}")
        return user
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except SQLAlchemyError as e:
        logger.error(f"Database error during registration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration service temporarily unavailable"
        )
    except Exception as e:
        logger.error(f"Unexpected error during registration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )

@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(security.get_current_user),
) -> Any:
    """
    Get current user information.
    """
    logger.info(f"Profile access for user: {current_user.email}")
    return current_user

@router.post("/api-keys/alpaca")
async def store_alpaca_keys(
    keys_data: AlpacaKeysRequest,
    current_user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Securely store encrypted Alpaca API keys for the user.
    """
    try:
        logger.info(f"Storing Alpaca API keys for user: {current_user.email} (paper: {keys_data.is_paper})")
        
        # Encrypt and store the keys
        success = security.store_encrypted_alpaca_keys(
            db=db,
            user_id=current_user.id,
            api_key=keys_data.api_key,
            secret_key=keys_data.secret_key,
            is_paper=keys_data.is_paper
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to store API keys"
            )
        
        return {"message": "API keys stored successfully", "is_paper": keys_data.is_paper}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error storing Alpaca keys for user {current_user.email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store API keys"
        )

@router.delete("/api-keys/alpaca")
async def delete_alpaca_keys(
    current_user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Delete stored Alpaca API keys for the user.
    """
    try:
        logger.info(f"Deleting Alpaca API keys for user: {current_user.email}")
        
        success = security.delete_alpaca_keys(db=db, user_id=current_user.id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No API keys found to delete"
            )
        
        return {"message": "API keys deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting Alpaca keys for user {current_user.email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete API keys"
        )

@router.post("/setup-2fa")
async def setup_two_factor_auth(
    current_user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Set up 2FA for the user account.
    Returns QR code data for authenticator app setup.
    """
    try:
        logger.info(f"Setting up 2FA for user: {current_user.email}")
        
        qr_code_data = security.setup_2fa(db=db, user=current_user)
        
        return {
            "message": "2FA setup initiated",
            "qr_code": qr_code_data["qr_code"],
            "secret": qr_code_data["secret"],
            "backup_codes": qr_code_data["backup_codes"]
        }
        
    except Exception as e:
        logger.error(f"Error setting up 2FA for user {current_user.email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to setup 2FA"
        )

@router.post("/disable-2fa")
async def disable_two_factor_auth(
    two_factor_data: TwoFactorRequest,
    current_user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Disable 2FA for the user account (requires current 2FA token).
    """
    try:
        logger.info(f"Disabling 2FA for user: {current_user.email}")
        
        # Verify current 2FA token before disabling
        is_valid = security.verify_2fa_token(current_user, two_factor_data.token)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid 2FA token"
            )
        
        security.disable_2fa(db=db, user=current_user)
        
        return {"message": "2FA disabled successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling 2FA for user {current_user.email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disable 2FA"
        )

@router.post("/logout")
async def logout(
    current_user: User = Depends(security.get_current_user),
) -> dict:
    """
    Logout user (invalidate token if using token blacklist).
    """
    logger.info(f"User logout: {current_user.email}")
    
    # If you implement token blacklisting, add token to blacklist here
    # security.blacklist_token(token)
    
    return {"message": "Logged out successfully"}