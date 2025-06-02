from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError # For more specific DB exceptions if needed
from datetime import timedelta
from typing import Any, Dict
import logging
import re

from pydantic import BaseModel, validator, Field

# Assuming these are correctly set up in your project structure
from app.core import security # Main security logic
from app.core.config import settings
from app.core.rate_limiter import RateLimiter # Custom rate limiter
from app.db.session import get_db # DB session dependency
from app.models.user import User # SQLAlchemy User model
from app.schemas.user import UserCreate, UserResponse # Pydantic User schemas
from app.schemas.token import Token, TokenPayload # Pydantic Token schemas

# Configure logging
# Adopting the logger name from the file for consistency if this file is run as a module
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth", # Adding a prefix for all auth routes for better organization
    tags=["Authentication"] # Tag for API documentation
)

# Rate limiter instances
login_limiter = RateLimiter(max_attempts=5, window_minutes=15)
register_limiter = RateLimiter(max_attempts=3, window_minutes=60) #

# --- Pydantic Models for Request Bodies ---

class TwoFactorRequest(BaseModel):
    """Request model for 2FA token verification."""
    token: str = Field(..., min_length=6, max_length=6, description="6-digit 2FA token")

    @validator('token')
    def validate_token_format(cls, v: str) -> str:
        if not re.match(r'^\d{6}$', v): #
            raise ValueError('2FA token must be exactly 6 digits.')
        return v

class AlpacaKeysRequest(BaseModel):
    """Request model for storing Alpaca API keys."""
    api_key: str = Field(..., min_length=10, description="Alpaca API Key") #
    secret_key: str = Field(..., min_length=10, description="Alpaca Secret Key") #
    is_paper: bool = True

    @validator('api_key', 'secret_key')
    def validate_keys_length(cls, v: str) -> str:
        # Basic validation, more complex checks could be added if needed
        if len(v.strip()) < 10: #
            raise ValueError('API keys must be at least 10 characters long.')
        return v.strip()

# --- API Endpoints ---

@router.post("/token", response_model=Token, summary="Login and Get Access Token")
async def login_for_access_token(
    request: Request,
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Token:
    """
    Authenticates a user and returns an access token.
    Implements rate limiting and security logging.
    Handles standard login and 2FA-required login flows.
    """
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    logger.info(f"Login attempt for user: {form_data.username} from IP: {client_ip}, User-Agent: {user_agent}")

    if not login_limiter.allow_request(f"login_{form_data.username}_{client_ip}"): #
        logger.warning(f"Rate limit exceeded for user: {form_data.username} from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later."
        )

    try:
        user = security.authenticate_user(db, form_data.username, form_data.password) #
        if not user:
            logger.warning(f"Authentication failed for user: {form_data.username} (invalid credentials)")
            # Increment failed attempt for rate limiter
            login_limiter.increment_attempt(f"login_{form_data.username}_{client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active: #
            logger.warning(f"Login attempt for inactive user: {form_data.username}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

        # Check if 2FA is required and enabled
        if user.is_2fa_enabled and security.is_2fa_required_for_user(user): #
            logger.info(f"2FA required for user: {user.email}. Issuing temporary token.")
            temp_token_data = {"sub": user.email, "is_temp_2fa": True}
            temp_token = security.create_access_token( # Assuming create_access_token handles custom claims
                data=temp_token_data,
                expires_delta=timedelta(minutes=settings.TWO_FACTOR_TEMP_TOKEN_EXPIRE_MINUTES) # Configurable
            )
            return Token(access_token=temp_token, token_type="bearer", requires_2fa=True)

        # Create full access token if 2FA not required or already passed
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES) #
        access_token = security.create_access_token(
            data={"sub": user.email}, expires_delta=access_token_expires #
        )
        logger.info(f"User {user.email} logged in successfully. Full access token issued.")
        login_limiter.reset_attempts(f"login_{form_data.username}_{client_ip}") # Reset on success
        return Token(access_token=access_token, token_type="bearer", requires_2fa=False)

    except HTTPException:
        raise # Re-raise HTTPException to let FastAPI handle it
    except Exception as e:
        logger.error(f"Server error during login for {form_data.username}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred during login."
        )


@router.post("/verify-2fa", response_model=Token, summary="Verify 2FA Token")
async def verify_two_factor_auth(
    two_factor_data: TwoFactorRequest,
    # Expecting the temporary token from /token endpoint for 2FA verification
    current_user_payload: dict = Depends(security.get_current_user_payload_temp_2fa),
    db: Session = Depends(get_db)
) -> Token:
    """
    Verifies a 2FA token and returns a full access token upon success.
    Requires a temporary token indicating 2FA is pending.
    """
    user_email = current_user_payload.get("sub")
    if not user_email:
        logger.error("2FA verification attempt with invalid temporary token payload.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid temporary token")

    logger.info(f"2FA verification attempt for user: {user_email}")
    user = security.get_user(db, email=user_email)
    if not user:
        logger.error(f"User not found during 2FA verification: {user_email}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        is_valid = security.verify_2fa_token(user, two_factor_data.token) #
        if not is_valid:
            logger.warning(f"Invalid 2FA token for user: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid 2FA token"
            )

        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = security.create_access_token(
            data={"sub": user.email}, expires_delta=access_token_expires
        )
        logger.info(f"2FA verified for user: {user.email}. Full access token issued.")
        return Token(access_token=access_token, token_type="bearer", requires_2fa=False)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Server error during 2FA verification for {user.email}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify 2FA token due to a server error."
        )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Register New User")
async def register_user(
    request: Request,
    user_in: UserCreate,
    db: Session = Depends(get_db)
) -> UserResponse:
    """
    Registers a new user with validation and security checks.
    Implements rate limiting.
    """
    client_ip = request.client.host if request.client else "unknown"
    logger.info(f"Registration attempt for email: {user_in.email} from IP: {client_ip}")

    if not register_limiter.allow_request(f"register_{client_ip}"): #
        logger.warning(f"Rate limit exceeded for registration from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again later."
        )

    try:
        # Check if user already exists is handled within security.create_user to prevent enumeration
        # security.create_user should raise an HTTPException if email exists or password is weak
        new_user = security.create_user(db, user_in) #
        if not new_user:
            # This case should ideally be handled by exceptions from create_user
            logger.error(f"User creation failed for email {user_in.email} with no specific exception from security.create_user.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User registration failed due to an unexpected error."
            )
        logger.info(f"User registered successfully: {new_user.email}")
        # Return UserResponse schema, which should be ORM compatible
        return UserResponse.model_validate(new_user)
        
    except HTTPException as http_exc:
        # If security.create_user raises an HTTPException (e.g., email exists, weak password), re-raise it.
        logger.warning(f"Registration failed for {user_in.email}: {http_exc.detail}")
        raise http_exc #
    except SQLAlchemyError as e:
        logger.error(f"Database error during registration for {user_in.email}: {str(e)}", exc_info=True)
        # Avoid revealing specific DB errors to the client
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed due to a database error."
        )
    except ValueError as ve: # For Pydantic validation errors if any slip through to security.create_user
        logger.warning(f"Validation error during registration for {user_in.email}: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Unexpected server error during registration for {user_in.email}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during registration."
        )


@router.get("/users/me", response_model=UserResponse, summary="Get Current User Profile")
async def read_users_me(
    current_user: User = Depends(security.get_current_active_user) # Ensures user is active
) -> UserResponse:
    """
    Fetches the profile of the currently authenticated and active user.
    """
    logger.debug(f"Fetching profile for user: {current_user.email}")
    return UserResponse.model_validate(current_user)


@router.post("/api-keys/alpaca", status_code=status.HTTP_201_CREATED, summary="Store Encrypted Alpaca API Keys")
async def store_alpaca_keys(
    alpaca_keys: AlpacaKeysRequest,
    current_user: User = Depends(security.get_current_active_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Securely stores encrypted Alpaca API keys for the authenticated user.
    """
    logger.info(f"Storing Alpaca API keys for user: {current_user.email}, paper: {alpaca_keys.is_paper}")
    try:
        success = security.store_encrypted_alpaca_keys( #
            db=db,
            user_id=current_user.id,
            api_key_data=alpaca_keys.api_key,
            secret_key_data=alpaca_keys.secret_key,
            is_paper=alpaca_keys.is_paper
        )
        if not success:
            logger.error(f"Failed to store Alpaca keys for user {current_user.email} (security function returned false).")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to store Alpaca API keys.")
        
        logger.info(f"Alpaca API keys stored successfully for user: {current_user.email}")
        return {"message": "Alpaca API keys stored successfully."}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error storing Alpaca keys for user {current_user.email}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred while storing Alpaca API keys."
        )


@router.delete("/api-keys/alpaca", status_code=status.HTTP_200_OK, summary="Delete Stored Alpaca API Keys")
async def delete_user_alpaca_keys(
    current_user: User = Depends(security.get_current_active_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Deletes stored Alpaca API keys for the authenticated user.
    """
    logger.info(f"Deleting Alpaca API keys for user: {current_user.email}")
    try:
        success = security.delete_alpaca_keys(db=db, user_id=current_user.id) #
        if not success:
            # This might mean keys didn't exist or deletion failed.
            # For idempotency, returning success even if keys didn't exist is often fine.
            # The security function should ideally differentiate actual failure vs. no keys found.
            logger.warning(f"Alpaca key deletion for {current_user.email} returned false (keys might not have existed or failed to delete).")
            # Depending on strictness, this could be an error or a success with a different message.
            # Assuming security.delete_alpaca_keys returns False on actual error.
            # raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No Alpaca API keys found to delete or deletion failed.")
            # For simplicity, if it returns false, we assume it's a failure.
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete Alpaca API keys.")

        logger.info(f"Alpaca API keys deleted for user: {current_user.email}")
        return {"message": "Alpaca API keys deleted successfully."}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting Alpaca keys for user {current_user.email}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred while deleting Alpaca API keys."
        )


@router.post("/setup-2fa", summary="Set Up 2FA for User Account")
async def setup_two_factor_auth(
    current_user: User = Depends(security.get_current_active_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Sets up 2FA for the user account.
    Returns QR code data URI for authenticator app setup.
    """
    logger.info(f"Setting up 2FA for user: {current_user.email}")
    if current_user.is_2fa_enabled:
        logger.warning(f"2FA setup attempt for user {current_user.email} who already has it enabled.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is already enabled for this account.")
    try:
        # security.setup_2fa should generate secret, store it (hashed/encrypted), and return provisioning URI
        qr_code_data_uri = security.setup_2fa(db=db, user=current_user) #
        if not qr_code_data_uri:
            logger.error(f"Failed to setup 2FA for {current_user.email} (security function returned no URI).")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to set up 2FA.")
        
        logger.info(f"2FA setup initiated for user: {current_user.email}. QR code URI provided.")
        return {"message": "2FA setup initiated. Scan the QR code with your authenticator app.", "qr_code_uri": qr_code_data_uri}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting up 2FA for user {current_user.email}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred during 2FA setup."
        )


@router.post("/disable-2fa", summary="Disable 2FA for User Account")
async def disable_two_factor_auth(
    two_factor_data: TwoFactorRequest, # User must provide a current 2FA token to disable
    current_user: User = Depends(security.get_current_active_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Disables 2FA for the user account. Requires a current valid 2FA token.
    """
    logger.info(f"Attempting to disable 2FA for user: {current_user.email}")
    if not current_user.is_2fa_enabled:
        logger.warning(f"2FA disable attempt for user {current_user.email} who does not have it enabled.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not currently enabled for this account.")
        
    try:
        # Verify current 2FA token before disabling
        is_valid_token = security.verify_2fa_token(current_user, two_factor_data.token) #
        if not is_valid_token:
            logger.warning(f"Invalid 2FA token provided by {current_user.email} for disabling 2FA.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid 2FA token. Disabling 2FA failed."
            )
        
        security.disable_2fa(db=db, user=current_user) # Function in security.py to clear 2FA secret and flag
        
        logger.info(f"2FA disabled successfully for user: {current_user.email}")
        return {"message": "2FA disabled successfully."}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling 2FA for user {current_user.email}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred while disabling 2FA."
        )


@router.post("/logout", summary="Logout User")
async def logout(
    # The token itself is usually sent in the Authorization header and validated by get_current_active_user
    # However, get_current_active_user returns the User model. We might need the raw token for blacklisting.
    # A custom dependency can be created to extract the token string.
    # For now, assuming security.get_current_active_user handles token validation.
    current_user: User = Depends(security.get_current_active_user),
    # token: str = Depends(oauth2_scheme) # If you need the raw token for blacklisting
) -> Dict[str, str]:
    """
    Logs out the current user.
    If using token blacklisting, the current token will be added to the blacklist.
    """
    logger.info(f"User logout initiated for: {current_user.email}")
    
    # Example: if security.py has a blacklist_token function
    # token_to_blacklist = token # if extracted via Depends(oauth2_scheme)
    # success = security.blacklist_token(token_to_blacklist)
    # if not success:
    #     logger.warning(f"Failed to blacklist token for user {current_user.email}")
    #     # Decide if this should be an error or just a warning
    # else:
    #     logger.info(f"Token blacklisted for user {current_user.email}")
    #

    # For truly stateless JWTs without a blacklist, logout is client-side (deleting the token).
    # This endpoint can still be useful for server-side session cleanup if any exists,
    # or as a conventional endpoint even if it doesn't do much server-side without blacklisting.
    
    return {"message": "Logout successful. Please discard your token."}