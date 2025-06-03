# File: app/core/security.py

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Union, Optional, Dict, List
import re
import secrets # For generating secure random strings for backup codes

from jose import jwt, JWTError, ExpiredSignatureError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import pyotp # For 2FA
from cryptography.fernet import Fernet, InvalidToken as FernetInvalidToken
import redis # For token blacklisting

from app.core.config import settings
from app.db.session import get_db # Assuming get_db can be used here if needed by dependencies
from app.models.user import User
from app.schemas.user import UserCreate # UserResponse not directly used here, but UserCreate is
from app.schemas.token import TokenPayload

logger = logging.getLogger(__name__)

# --- Password Hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- OAuth2 Scheme ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token")

# --- Fernet Encryption for API Keys ---
cipher_suite: Optional[Fernet] = None
if settings.FERNET_SECRET_KEY and settings.FERNET_SECRET_KEY != "k1_ZytG0nPLyQ45FmJ2AsI8gwhz2J9A15wD0Ml6tjHK=":
    try:
        cipher_suite = Fernet(settings.FERNET_SECRET_KEY.encode())
        logger.info("Fernet cipher suite initialized for data encryption.")
    except Exception as e:
        logger.critical(f"Failed to initialize Fernet cipher suite with provided FERNET_SECRET_KEY: {e}. Encryption/decryption will fail.", exc_info=True)
else:
    logger.critical(
        "CRITICAL SECURITY WARNING (security.py): FERNET_SECRET_KEY is not set or is using the insecure default. "
        "Sensitive data encryption (like Alpaca keys) will not be secure. "
        "Please set a strong, unique FERNET_SECRET_KEY environment variable for production."
    )

# --- Redis Client for Token Blacklist ---
redis_blacklist_client: Optional[redis.Redis] = None
if settings.REDIS_URL:
    try:
        redis_blacklist_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        redis_blacklist_client.ping()
        logger.info("Redis client for token blacklist initialized successfully.")
    except RedisError as e:
        logger.error(f"Failed to connect to Redis for token blacklist: {e}. Token blacklisting will not work.", exc_info=True)
else:
    logger.warning("REDIS_URL not configured. Token blacklisting feature will be disabled.")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def validate_password_strength(password: str) -> List[str]:
    """
    Validates password strength. Returns a list of error messages if any,
    or an empty list if the password is strong enough.
    """
    errors = []
    if len(password) < settings.MIN_PASSWORD_LENGTH: # Assuming MIN_PASSWORD_LENGTH in settings
        errors.append(f"Password must be at least {settings.MIN_PASSWORD_LENGTH} characters long.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password): # Example special characters
        errors.append("Password must contain at least one special character.")
    
    # Common password check (very basic, consider more advanced checks or services)
    if password.lower() in ["password", "123456", "qwerty", "admin", settings.PROJECT_NAME.lower()]:
        errors.append("Password is too common.")
        
    return errors


# --- Token Creation and Handling ---
def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    current_time = datetime.now(timezone.utc)
    
    if expires_delta:
        expire = current_time + expires_delta
    elif data.get("is_temp_2fa"): # Specific expiry for temporary 2FA tokens
        expire = current_time + timedelta(minutes=settings.TWO_FACTOR_TEMP_TOKEN_EXPIRE_MINUTES)
    else: # Default expiry for regular access tokens
        expire = current_time + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": current_time}) # Add issued_at time
    # Consider adding a unique token ID (jti) if needed for advanced invalidation
    # to_encode.update({"jti": secrets.token_urlsafe(16)})
    
    try:
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"Error encoding JWT: {e}", exc_info=True)
        # This is a server error, should not happen if SECRET_KEY and ALGORITHM are correct
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create access token due to a server configuration issue."
        )

# --- Token Blacklisting ---
def blacklist_token(token_jti: str) -> bool:
    """
    Adds a token's JTI (JWT ID) to the blacklist with an expiry matching the token's original expiry.
    This requires tokens to have a 'jti' and 'exp' claim.
    The token itself isn't stored, just its unique identifier.
    """
    if not redis_blacklist_client:
        logger.warning("Redis for blacklist not available. Cannot blacklist token.")
        return False # Or raise an error depending on desired behavior

    # This function expects a JTI (JWT ID) claim in the token to blacklist it effectively.
    # If not using JTI, you could blacklist the raw token, but that's less ideal.
    # For simplicity, if JTI is not present, we might log a warning or skip.
    # Here, we assume `token_jti` is the identifier to blacklist.
    
    # We also need the token's expiry to set a TTL on the blacklist entry.
    # This would typically be extracted from the token *before* it's blacklisted.
    # The calling function (e.g., logout endpoint) should pass the token's JTI and its remaining validity period.
    
    # Simplified: For a logout scenario, the /logout endpoint would extract 'jti' and 'exp' from the current token
    # then call this function.
    # For example, if logout endpoint passes `jti` and `remaining_validity_seconds`:
    # redis_blacklist_client.setex(f"bl_jti:{token_jti}", remaining_validity_seconds, "blacklisted")

    # For a simpler blacklist without JTI, just storing the token hash (not recommended for production)
    # For demonstration of the concept with raw token string (less secure, larger storage):
    # This example assumes 'token_jti' IS the raw token string for simplicity of the example.
    # A better approach involves 'jti'.
    
    # Let's assume token_jti is the actual token string for this example's simplicity for logout
    # The auth_router.py's /logout would need to pass the raw token string.
    # And its expiry. For now, let's use a fixed expiry for blacklisted tokens slightly longer than active ones.
    try:
        # Key: bl:{token_string_or_jti}, Value: "1" or timestamp, Expiry: token's original exp + buffer
        # The key should be the actual token string or its JTI.
        # For logout, the token is still valid, so its 'exp' can be read.
        # This is a simplified example. Proper JTI-based blacklisting is better.
        # If just blacklisting the token signature for settings.ACCESS_TOKEN_EXPIRE_MINUTES
        redis_blacklist_client.setex(f"blacklist:{token_jti}", 
                                     timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES + 5), 
                                     "true")
        logger.info(f"Token (or JTI) starting with {token_jti[:10]}... added to blacklist.")
        return True
    except RedisError as e:
        logger.error(f"Redis error blacklisting token: {e}", exc_info=True)
        return False


def is_token_blacklisted(token: str) -> bool: # token is the raw token string
    """Checks if a token (or its JTI) is in the blacklist."""
    if not redis_blacklist_client:
        return False # If Redis isn't available, can't check blacklist (fail open or closed?)
    try:
        # If using JTI, the 'token' here would be the JTI extracted from the decoded payload.
        # For this simplified example where we blacklist the token string:
        is_blacklisted = redis_blacklist_client.exists(f"blacklist:{token}")
        if is_blacklisted:
            logger.debug(f"Token starting with {token[:10]}... found in blacklist.")
        return bool(is_blacklisted)
    except RedisError as e:
        logger.error(f"Redis error checking token blacklist: {e}", exc_info=True)
        return False # Fail safe (assume not blacklisted if Redis fails) or True (fail closed)?

# --- User Authentication and Retrieval ---
def get_user(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()

def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user(db, email)
    if not user:
        logger.debug(f"Authentication failed: User {email} not found.")
        return None
    if not verify_password(password, user.hashed_password):
        logger.debug(f"Authentication failed: Invalid password for user {email}.")
        return None
    logger.info(f"User {email} authenticated successfully.")
    return user

def create_user(db: Session, user_in: UserCreate) -> User:
    existing_user = get_user(db, email=user_in.email)
    if existing_user:
        logger.warning(f"Registration attempt for existing email: {user_in.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The user with this email already exists.",
        )

    password_strength_errors = validate_password_strength(user_in.password)
    if password_strength_errors:
        logger.warning(f"Registration attempt for {user_in.email} with weak password: {', '.join(password_strength_errors)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password does not meet security requirements: {', '.join(password_strength_errors)}"
        )

    hashed_password = get_password_hash(user_in.password)
    db_user = User(
        email=user_in.email,
        hashed_password=hashed_password,
        full_name=user_in.full_name,
        is_active=True, # New users are active by default
        is_superuser=False # New users are not superusers by default
    )
    try:
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        logger.info(f"User {user_in.email} created successfully with ID {db_user.id}.")
        return db_user
    except Exception as e:
        db.rollback()
        logger.error(f"Database error during user creation for {user_in.email}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create user due to a database error."
        )

def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> TokenPayload:
    """Decodes JWT, checks blacklist, returns payload, raising HTTPException on errors."""
    if is_token_blacklisted(token): # Check blacklist first
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
        
        # Pass all claims to TokenPayload for validation and access
        return TokenPayload(**payload_dict)

    except ExpiredSignatureError:
        # Logging the subject if available helps in tracing
        sub_claim = "unknown"
        try:
            unverified_payload = jwt.decode(token, algorithms=[settings.JWT_ALGORITHM], options={"verify_signature": False, "verify_exp": False})
            sub_claim = unverified_payload.get("sub", "unknown")
        except JWTError:
            pass # Ignore if can't even decode without verification
        logger.info(f"Token has expired for sub: {sub_claim}.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e:
        logger.warning(f"Token decoding failed: {e}", exc_info=True)
        raise credentials_exception

def get_current_user(
    db: Session = Depends(get_db),
    token_payload: TokenPayload = Depends(get_current_user_payload)
) -> User:
    if token_payload.is_temp_2fa: # Check for the temporary 2FA token flag
        logger.debug("Attempt to access restricted route with temporary 2FA token.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="2FA verification required. Temporary token cannot be used for this action.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user(db, email=token_payload.sub)
    if user is None:
        logger.warning(f"User {token_payload.sub} from token not found in DB.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # Use 401 for consistency with other auth failures
            detail="User not found or token invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        logger.warning(f"Access attempt by inactive user: {current_user.email}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return current_user

def get_current_user_payload_temp_2fa(token_payload: TokenPayload = Depends(get_current_user_payload)) -> TokenPayload:
    if not token_payload.is_temp_2fa:
        logger.warning("Attempt to use non-temporary token for 2FA verification.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not a temporary 2FA token."
        )
    return token_payload

# --- 2FA (Two-Factor Authentication) ---
def _generate_backup_codes(count: int = 10, length: int = 8) -> List[str]:
    """Generates a list of random backup codes."""
    # Example: "xxxx-xxxx" format
    return [f"{secrets.token_hex(length // 2)}-{secrets.token_hex(length // 2)}" for _ in range(count)]

def setup_2fa(db: Session, user: User) -> Dict[str, Any]:
    """
    Sets up 2FA for a user. Generates new secret, stores encrypted secret,
    returns provisioning URI and new backup codes.
    Assumes User model has `two_factor_secret` (encrypted) and `is_2fa_enabled` fields.
    Also assumes User model can store hashed backup codes or an indicator they exist.
    """
    if user.is_2fa_enabled and user.two_factor_secret:
        logger.info(f"2FA already configured for user {user.email}. Re-setup might be intended.")
        # Potentially invalidate old secret and backup codes if re-setting up.

    two_factor_secret = pyotp.random_base32()
    encrypted_secret = encrypt_data_field(two_factor_secret)
    if not encrypted_secret:
        logger.error(f"Failed to encrypt 2FA secret for user {user.email}.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not setup 2FA due to encryption error.")

    user.two_factor_secret = encrypted_secret
    user.is_2fa_enabled = True # Enable 2FA flag

    backup_codes = _generate_backup_codes()
    # TODO: Securely handle backup codes.
    # Option 1 (Recommended for user responsibility): Display once, user stores them. Server doesn't store plaintext.
    # Option 2 (More complex server-side): Store hashes of backup codes in DB and mark them as used.
    # For now, we generate and return them. The User model would need a field if we store hashes.
    # user.hashed_backup_codes = [get_password_hash(code) for code in backup_codes] # Example
    
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        logger.error(f"Database error during 2FA setup for {user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save 2FA setup due to DB error.")

    provisioning_uri = pyotp.totp.TOTP(two_factor_secret).provisioning_uri(
        name=user.email, issuer_name=settings.PROJECT_NAME
    )
    logger.info(f"2FA setup initiated for user {user.email}.")
    # IMPORTANT: The raw `two_factor_secret` should NOT be returned in the API response.
    # The `provisioning_uri` contains it. The backup codes are for the user.
    return {"qr_code_uri": provisioning_uri, "backup_codes": backup_codes}


def verify_2fa_token(user: User, token: str, window: int = 1) -> bool:
    """
    Verifies a 2FA token. Allows for a small window for clock drift.
    Optionally, can consume a backup code if token is a backup code.
    """
    if not user.is_2fa_enabled or not user.two_factor_secret:
        logger.warning(f"2FA verification attempt for user {user.email} but 2FA is not properly enabled/setup.")
        return False
    
    try:
        decrypted_secret = decrypt_data_field(user.two_factor_secret)
        if not decrypted_secret:
            logger.error(f"Failed to decrypt 2FA secret for user {user.email} during verification.")
            return False
            
        totp = pyotp.TOTP(decrypted_secret)
        is_valid_totp = totp.verify(token, window=window) # Allow current, previous, and next token

        if is_valid_totp:
            logger.info(f"TOTP token successfully verified for user {user.email}.")
            return True
        
        # TODO: Implement backup code verification if desired
        # This would involve checking the provided 'token' against stored (hashed) backup codes
        # and marking the used backup code as invalid.
        # For example:
        # if verify_backup_code(user, token): # verify_backup_code would check against hashed codes and invalidate
        #     logger.info(f"Backup code used successfully by user {user.email}.")
        #     return True
            
        logger.warning(f"Invalid 2FA (TOTP or backup) token for user {user.email}.")
        return False
    except Exception as e:
        logger.error(f"Error verifying 2FA token for {user.email}: {e}", exc_info=True)
        return False

def disable_2fa(db: Session, user: User) -> bool:
    if not user.is_2fa_enabled:
        logger.info(f"2FA already disabled for user {user.email}.")
        return True # Idempotent

    user.is_2fa_enabled = False
    user.two_factor_secret = None
    # TODO: Invalidate/clear any stored backup codes or indicators.
    # user.hashed_backup_codes = None # Example
    try:
        db.add(user)
        db.commit()
        logger.info(f"2FA disabled for user {user.email}.")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Database error during 2FA disable for {user.email}: {e}", exc_info=True)
        # Raise an HTTP exception if this is called from an API endpoint context
        # For now, just returning False from a security utility.
        return False


def is_2fa_required_for_user(user: User) -> bool:
    """Determines if 2FA is required for the user during login."""
    # Could add more complex logic here (e.g., trusted devices, IP ranges)
    return user.is_2fa_enabled


# --- Alpaca API Key Encryption/Decryption ---
def encrypt_data_field(data: str) -> Optional[str]:
    if not cipher_suite:
        logger.error("Cipher suite not initialized. Cannot encrypt data.")
        # This should ideally prevent the operation or raise a clear server error.
        raise ValueError("Encryption service not available. Check server configuration.")
    try:
        return cipher_suite.encrypt(data.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}", exc_info=True)
        raise ValueError("Encryption failed.") # Or a more specific custom exception

def decrypt_data_field(encrypted_data_str: Optional[str]) -> Optional[str]:
    if not cipher_suite:
        logger.error("Cipher suite not initialized. Cannot decrypt data.")
        raise ValueError("Decryption service not available. Check server configuration.")
    if not encrypted_data_str:
        return None
    try:
        return cipher_suite.decrypt(encrypted_data_str.encode()).decode()
    except FernetInvalidToken: # Specific error for bad token/key
        logger.error("Decryption failed: Invalid Fernet token (key mismatch or corrupted data).")
        return None # Or raise, depending on how you want to handle this
    except Exception as e:
        logger.error(f"Decryption failed: {e}", exc_info=True)
        return None # Or raise

def store_encrypted_alpaca_keys(db: Session, user_id: int, api_key_data: str, secret_key_data: str, is_paper: bool) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error(f"Cannot store Alpaca keys: User with ID {user_id} not found.")
        return False

    try:
        encrypted_api_key = encrypt_data_field(api_key_data)
        encrypted_secret_key = encrypt_data_field(secret_key_data)
    except ValueError as e: # Catch encryption errors
        logger.error(f"Encryption of Alpaca keys failed for user {user.email}: {e}")
        return False

    user.alpaca_api_key = encrypted_api_key
    user.alpaca_secret_key = encrypted_secret_key
    user.alpaca_is_paper = is_paper
    
    try:
        db.add(user)
        db.commit()
        logger.info(f"Alpaca API keys stored (encrypted) for user {user.email}.")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Database error storing Alpaca keys for user {user.email}: {e}", exc_info=True)
        return False

def delete_alpaca_keys(db: Session, user_id: int) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning(f"Attempt to delete Alpaca keys for non-existent user ID {user_id}.")
        return True # Idempotent, no keys to delete for this user

    if not user.alpaca_api_key and not user.alpaca_secret_key:
        logger.info(f"No Alpaca keys found to delete for user {user.email}.")
        return True

    user.alpaca_api_key = None
    user.alpaca_secret_key = None
    user.alpaca_is_paper = None # Reset this as well
    
    try:
        db.add(user)
        db.commit()
        logger.info(f"Alpaca API keys deleted for user {user.email}.")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Database error deleting Alpaca keys for user {user.email}: {e}", exc_info=True)
        return False