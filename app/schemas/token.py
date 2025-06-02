from pydantic import BaseModel, Field
from typing import Optional, Any # Added Any for potential other claims

class Token(BaseModel):
    """
    Pydantic model for the access token response.
    """
    access_token: str
    token_type: str = "bearer" # Default to "bearer"
    requires_2fa: Optional[bool] = Field(None, description="Indicates if 2FA verification is pending after login.")


class TokenPayload(BaseModel):
    """
    Pydantic model for the data encoded within a JWT.
    """
    sub: Optional[str] = None  # Subject of the token (typically user email or ID)
    is_temp_2fa: Optional[bool] = Field(False, description="Indicates if this is a temporary token for 2FA verification.")
    exp: Optional[int] = None # Standard JWT expiration time claim (Unix timestamp)
    # You can add other custom claims here as needed
    # Example: iat: Optional[int] = None (Issued At)
    # Example: jti: Optional[str] = None (JWT ID)
    # For flexibility, you can also allow extra fields if your tokens might have other dynamic claims:
    # class Config:
    #     extra = "allow"