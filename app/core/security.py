import logging
from datetime import datetime, timedelta
from typing import Any, Union, Optional, Dict

from jose import jwt, JWTError, ExpiredSignatureError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import pyotp # For 2FA
from cryptography.fernet import Fernet, InvalidToken as FernetInvalidToken # For encrypting API keys

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User # Assuming User model has is_2fa_enabled, two_factor_secret, alpaca_api_key etc.
from app.schemas.user import UserCreate, UserResponse # Ensure User model matches UserResponse
from app.schemas.token import TokenPayload

# Configure logging
logger = logging.getLogger(__name__)

# --- Password Hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") #

# --- OAuth2 Scheme ---
# The tokenUrl should match the actual login endpoint if it's different
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token") # (adjusted tokenUrl)

# --- Fernet Encryption for API Keys ---
# Ensure FERNET_SECRET_KEY is set in your environment variables and is a URL-safe base64-encoded 32-byte key.
# Generate one with: from cryptography.fernet import Fernet; Fernet.generate_key().decode()
# For simplicity, using a fallback if not set, BUT THIS IS NOT SECURE FOR PRODUCTION.
try:
    if not settings.FERNET_SECRET_KEY:
        logger.warning("FERNET_SECRET_KEY not set in environment. Using a default, insecure key. THIS IS NOT FOR PRODUCTION.")
        # This default key is for demonstration/development only and is INSECURE.
        # Replace with a securely generated and stored key in production.
        _fernet_key = Fernet.generate_key()
    else:
        _fernet_key = settings.FERNET_SECRET_KEY.encode()
    
    cipher_suite = Fernet(_fernet_key)
except Exception as e:
    logger.critical(f"Failed to initialize Fernet cipher suite. Ensure FERNET_SECRET_KEY is valid: {e}")
    # Fallback to a dummy cipher that will likely fail operations, forcing a fix.
    # Or, you could raise an exception here to prevent the app from starting with insecure crypto.
    cipher_suite = None # This will cause encryption/decryption to fail if not handled


def verify_password(plain_password: str, hashed_password: str) -> bool: #
    """Verifies a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password) #

def get_password_hash(password: str) -> str: #
    """Hashes a plain password."""
    return pwd_context.hash(password) #

def validate_password_strength(password: str) -> bool:
    """
    Validates password strength.
    Example: At least 8 characters, one uppercase, one lowercase, one digit, one special character.
    TODO: Implement actual password strength validation logic.
    """
    if len(password) < 8:
        return False
    if not any(char.islower() for char in password):
        return False
    if not any(char.isupper() for char in password):
        return False
    if not any(char.isdigit() for char in password):
        return False
    # Example: check for a special character
    # if not any(not char.isalnum() for char in password):
    #     return False
    return True


# --- Token Creation and Handling ---
def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str: #
    """
    Creates a JWT access token.
    'is_temp_2fa' can be added to data for temporary 2FA tokens.
    """
    to_encode = data.copy() #
    if expires_delta: #
        expire = datetime.utcnow() + expires_delta #
    elif data.get("is_temp_2fa"):
        expire = datetime.utcnow() + timedelta(minutes=settings.TWO_FACTOR_TEMP_TOKEN_EXPIRE_MINUTES)
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES) # (modified default)
    
    to_encode.update({"exp": expire}) #
    try:
        encoded_jwt = jwt.encode(
            to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        ) # (settings.JWT_ALGORITHM added)
        return encoded_jwt
    except Exception as e:
        logger.error(f"Error encoding JWT: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create access token."
        )


# --- User Authentication and Retrieval ---
def authenticate_user(db: Session, email: str, password: str) -> Optional[User]: #
    """Authenticates a user by email and password."""
    user = db.query(User).filter(User.email == email).first() #
    if not user: #
        logger.debug(f"Authentication failed: User {email} not found.")
        return None
    if not verify_password(password, user.hashed_password): #
        logger.debug(f"Authentication failed: Invalid password for user {email}.")
        return None
    logger.info(f"User {email} authenticated successfully.")
    return user #

def get_user(db: Session, email: str) -> Optional[User]:
    """Retrieves a user by email."""
    return db.query(User).filter(User.email == email).first()

def create_user(db: Session, user_in: UserCreate) -> User: #
    """Creates a new user in the database."""
    existing_user = get_user(db, email=user_in.email)
    if existing_user:
        logger.warning(f"Registration attempt for existing email: {user_in.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The user with this email already exists in the system.",
        )

    if not validate_password_strength(user_in.password):
        logger.warning(f"Registration attempt with weak password for email: {user_in.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password does not meet security requirements. (Min 8 chars, upper, lower, digit)"
            # TODO: Provide more specific password policy details if possible.
        )

    hashed_password = get_password_hash(user_in.password) #
    db_user = User( #
        email=user_in.email, #
        hashed_password=hashed_password, #
        full_name=user_in.full_name, #
        is_active=True # New users are active by default
    )
    try:
        db.add(db_user) #
        db.commit() #
        db.refresh(db_user) #
        logger.info(f"User {user_in.email} created successfully.")
        return db_user #
    except Exception as e: # Catch potential DB errors
        logger.error(f"Database error during user creation for {user_in.email}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create user due to a database error."
        )


def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> TokenPayload:
    """Decodes JWT and returns payload, raising HTTPException on errors."""
    credentials_exception = HTTPException( #
        status_code=status.HTTP_401_UNAUTHORIZED, #
        detail="Could not validate credentials", #
        headers={"WWW-Authenticate": "Bearer"}, #
    )
    try:
        payload_dict = jwt.decode( #
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        email: Optional[str] = payload_dict.get("sub") #
        if email is None: #
            logger.warning("Token decoding failed: 'sub' (email) claim missing.")
            raise credentials_exception #
        return TokenPayload(sub=email, **payload_dict) # Include other potential payload fields
    except ExpiredSignatureError:
        logger.info("Token has expired.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e: #
        logger.warning(f"Token decoding failed: {e}")
        raise credentials_exception #

def get_current_user(
    db: Session = Depends(get_db), #
    token_payload: TokenPayload = Depends(get_current_user_payload)
) -> User: #
    """Dependency to get the current user from a valid token."""
    if token_payload.is_temp_2fa: # Check for the temporary 2FA token flag
        logger.debug("Attempt to access restricted route with temporary 2FA token.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="2FA verification required. Cannot use temporary token for this action.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user(db, email=token_payload.sub) #
    if user is None: #
        logger.warning(f"User {token_payload.sub} from token not found in DB.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials", # User might have been deleted after token issuance
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user #

def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Dependency to get the current active user."""
    if not current_user.is_active:
        logger.warning(f"Access attempt by inactive user: {current_user.email}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return current_user

def get_current_user_payload_temp_2fa(token_payload: TokenPayload = Depends(get_current_user_payload)) -> TokenPayload:
    """
    Dependency to get the payload of a temporary 2FA token.
    Ensures the token is marked as a temporary 2FA token.
    """
    if not token_payload.is_temp_2fa:
        logger.warning("Attempt to use non-temporary token for 2FA verification.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not a temporary 2FA token. Full login required or token invalid for this operation."
        )
    return token_payload

# --- 2FA (Two-Factor Authentication) ---
def setup_2fa(db: Session, user: User) -> Dict[str, Any]:
    """
    Sets up 2FA for a user. Generates a new secret, stores it (hashed/encrypted),
    and returns a provisioning URI for QR code generation and backup codes.
    Assumes User model has `two_factor_secret` (encrypted) and `is_2fa_enabled` fields.
    """
    # TODO: Check if 2FA is already enabled and handle accordingly (e.g., disallow or require re-verification).
    # For now, auth_router.py handles this check before calling.

    two_factor_secret = pyotp.random_base32()
    # IMPORTANT: Store this secret securely, ideally encrypted, associated with the user.
    # For this example, assume user.two_factor_secret can store it.
    # In a real app, you'd encrypt this before saving.
    user.two_factor_secret = encrypt_data_field(two_factor_secret) # Encrypt before storing
    user.is_2fa_enabled = True # Or set this after user confirms with a token
    
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        logger.error(f"Database error during 2FA setup for {user.email}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not setup 2FA due to DB error.")

    provisioning_uri = pyotp.totp.TOTP(two_factor_secret).provisioning_uri(
        name=user.email, issuer_name=settings.PROJECT_NAME
    )
    # TODO: Generate and securely store backup codes for the user.
    backup_codes = ["placeholder1", "placeholder2"] # Replace with actual backup code generation
    logger.info(f"2FA setup initiated for user {user.email}.")
    return {"qr_code_uri": provisioning_uri, "backup_codes": backup_codes, "secret_key_manual": two_factor_secret}

def verify_2fa_token(user: User, token: str) -> bool:
    """Verifies a 2FA token provided by the user."""
    if not user.is_2fa_enabled or not user.two_factor_secret:
        logger.warning(f"2FA verification attempt for user {user.email} but 2FA is not enabled/setup.")
        return False
    
    try:
        decrypted_secret = decrypt_data_field(user.two_factor_secret)
        if not decrypted_secret:
            logger.error(f"Failed to decrypt 2FA secret for user {user.email}.")
            return False
        totp = pyotp.TOTP(decrypted_secret)
        is_valid = totp.verify(token)
        if is_valid:
            logger.info(f"2FA token successfully verified for user {user.email}.")
        else:
            logger.warning(f"Invalid 2FA token for user {user.email}.")
        return is_valid
    except Exception as e:
        logger.error(f"Error verifying 2FA token for {user.email}: {e}", exc_info=True)
        return False

def disable_2fa(db: Session, user: User) -> None:
    """Disables 2FA for a user."""
    if not user.is_2fa_enabled:
        logger.info(f"2FA already disabled for user {user.email}.")
        return

    user.is_2fa_enabled = False
    user.two_factor_secret = None # Clear the secret
    # TODO: Invalidate any backup codes associated with this 2FA setup.
    try:
        db.add(user)
        db.commit()
        logger.info(f"2FA disabled for user {user.email}.")
    except Exception as e:
        logger.error(f"Database error during 2FA disable for {user.email}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not disable 2FA due to DB error.")

def is_2fa_required_for_user(user: User) -> bool:
    """
    Determines if 2FA is currently required for a user during login.
    This might involve checking session flags, device trust, etc.
    For now, it's simple: if 2FA is enabled, it's required on a new login.
    """
    return user.is_2fa_enabled


# --- Alpaca API Key Encryption/Decryption ---
def encrypt_data_field(data: str) -> Optional[str]:
    """Encrypts a data field using Fernet."""
    if not cipher_suite:
        logger.error("Cipher suite not initialized. Cannot encrypt data.")
        return None
    try:
        return cipher_suite.encrypt(data.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}", exc_info=True)
        return None

def decrypt_data_field(encrypted_data: str) -> Optional[str]:
    """Decrypts a data field using Fernet."""
    if not cipher_suite:
        logger.error("Cipher suite not initialized. Cannot decrypt data.")
        return None
    if not encrypted_data:
        return None
    try:
        return cipher_suite.decrypt(encrypted_data.encode()).decode()
    except FernetInvalidToken:
        logger.error("Decryption failed: Invalid Fernet token (key mismatch or corrupted data).")
        return None
    except Exception as e:
        logger.error(f"Decryption failed: {e}", exc_info=True)
        return None

def store_encrypted_alpaca_keys(db: Session, user_id: int, api_key_data: str, secret_key_data: str, is_paper: bool) -> bool:
    """
    Encrypts and stores Alpaca API keys for a user.
    Assumes User model has fields like `alpaca_api_key_encrypted`, `alpaca_secret_key_encrypted`, `alpaca_is_paper`.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error(f"Cannot store Alpaca keys: User with ID {user_id} not found.")
        return False

    encrypted_api_key = encrypt_data_field(api_key_data)
    encrypted_secret_key = encrypt_data_field(secret_key_data)

    if not encrypted_api_key or not encrypted_secret_key:
        logger.error(f"Encryption of Alpaca keys failed for user {user.email}.")
        return False

    user.alpaca_api_key = encrypted_api_key # Store encrypted version
    user.alpaca_secret_key = encrypted_secret_key # Store encrypted version
    user.alpaca_is_paper = is_paper
    
    try:
        db.add(user)
        db.commit()
        logger.info(f"Alpaca API keys stored for user {user.email}.")
        return True
    except Exception as e:
        logger.error(f"Database error storing Alpaca keys for user {user.email}: {e}", exc_info=True)
        db.rollback()
        return False


def delete_alpaca_keys(db: Session, user_id: int) -> bool:
    """Deletes Alpaca API keys for a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning(f"Attempt to delete Alpaca keys for non-existent user ID {user_id}.")
        return False # Or True for idempotency if keys not existing is fine

    if not user.alpaca_api_key and not user.alpaca_secret_key:
        logger.info(f"No Alpaca keys found to delete for user {user.email}.")
        return True # Idempotent: keys already not present

    user.alpaca_api_key = None
    user.alpaca_secret_key = None
    user.alpaca_is_paper = None # Or set to a default like True

    try:
        db.add(user)
        db.commit()
        logger.info(f"Alpaca API keys deleted for user {user.email}.")
        return True
    except Exception as e:
        logger.error(f"Database error deleting Alpaca keys for user {user.email}: {e}", exc_info=True)
        db.rollback()
        return False

# --- Token Blacklisting (Placeholder) ---
# For a stateless JWT system, true server-side logout requires a token blacklist.
# This could be implemented using Redis or another fast K/V store.
BLACKLISTED_TOKENS = set() # In-memory, not suitable for production!

def blacklist_token(token: str) -> bool:
    """
    Adds a token to the blacklist.
    TODO: Implement a persistent blacklist (e.g., Redis with TTL).
    """
    logger.info(f"Blacklisting token (first 10 chars): {token[:10]}...")
    BLACKLISTED_TOKENS.add(token)
    return True

def is_token_blacklisted(token: str) -> bool:
    """Checks if a token is in the blacklist."""
    return token in BLACKLISTED_TOKENS

# Update get_current_user_payload to check blacklist
def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> TokenPayload: # noqa: F811
    """Decodes JWT and returns payload, raising HTTPException on errors. Includes blacklist check."""
    if is_token_blacklisted(token):
        logger.warning("Access attempt with blacklisted token.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated (logged out).",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload_dict = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        email: Optional[str] = payload_dict.get("sub")
        if email is None:
            logger.warning("Token decoding failed: 'sub' (email) claim missing.")
            raise credentials_exception
        
        # Add any other claims from the token to TokenPayload if needed
        # For example, if 'is_temp_2fa' is part of the payload
        token_data = TokenPayload(sub=email, **payload_dict)
        return token_data

    except ExpiredSignatureError:
        logger.info(f"Token has expired for sub: {payload_dict.get('sub', 'unknown') if 'payload_dict' in locals() else 'unknown'}.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e:
        logger.warning(f"Token decoding failed: {e}", exc_info=True)
        raise credentials_exception