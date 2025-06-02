from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

# --- Base Schemas ---
class UserBase(BaseModel):
    """
    Base schema for user attributes shared across different operations.
    """
    email: EmailStr
    full_name: Optional[str] = Field(None, min_length=1, max_length=100, example="Jane Doe")

# --- Schemas for API Input (Request Bodies) ---
class UserCreate(UserBase):
    """
    Schema for creating a new user. Requires a password.
    """
    password: str = Field(..., min_length=8, example="S3curEP@sswOrd!") # Password validation in security.py

class UserUpdate(UserBase):
    """
    Schema for updating user information. All fields are optional.
    Password update should be handled with care, potentially via a dedicated endpoint.
    """
    password: Optional[str] = Field(None, min_length=8, description="New password, if changing.")
    # email: Optional[EmailStr] = None # Email updates might require re-verification
    # full_name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None # Typically for admin use
    is_superuser: Optional[bool] = None # Typically for admin use
    
    # Note: User preferences like portfolio_size, risk_tolerance, and 2FA settings
    # are better handled by specific update schemas and dedicated endpoints for clarity and security.
    # See UserPreferencesUpdate in the (now deleted) app/api/users.py or dedicated endpoints in auth_router.py.

class UserUpdatePassword(BaseModel):
    """Schema specifically for updating a user's password."""
    current_password: str = Field(..., example="oldS3curEP@sswOrd!")
    new_password: str = Field(..., min_length=8, example="newS3curEP@sswOrd!")


# --- Schemas for API Output (Response Bodies) ---
class UserResponse(UserBase):
    """
    Schema for returning user information to the client.
    Excludes sensitive data like hashed_password.
    """
    id: int
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: Optional[datetime] = None # Field(...) can be used here too if needed

    # Add non-sensitive fields from the User model that are useful for the client
    is_2fa_enabled: bool = Field(default=False, description="Indicates if 2FA is enabled for the user.")
    alpaca_is_paper: Optional[bool] = Field(None, description="Indicates if the configured Alpaca keys are for paper trading.")
    portfolio_size: Optional[float] = Field(None, description="User's configured portfolio size.")
    risk_tolerance: Optional[float] = Field(None, description="User's configured risk tolerance.")

    # Pydantic V2 configuration to enable ORM mode (from_attributes)
    model_config = {
        "from_attributes": True
    }

# Example for updating user-specific, non-critical preferences (if not handled in auth_router)
# class UserPreferencesUpdate(BaseModel):
#     portfolio_size: Optional[float] = Field(None, gt=0)
#     risk_tolerance: Optional[float] = Field(None, ge=0, le=1)
#     full_name: Optional[str] = Field(None, min_length=1, max_length=100)

# class UserPreferencesResponse(BaseModel):
#     email: EmailStr
#     full_name: Optional[str] = None
#     portfolio_size: Optional[float] = None
#     risk_tolerance: Optional[float] = None
#     model_config = {"from_attributes": True}