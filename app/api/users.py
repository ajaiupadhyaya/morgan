from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field # Added for request body validation
from typing import Optional, Any
import logging

# Assuming these imports are from your refined security module
from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.user import User # Assuming User model has portfolio_size, risk_tolerance

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/users", # Standard prefix for user-related, non-auth endpoints
    tags=["Users"]
)

# --- Pydantic Models for Request/Response ---
class UserPreferencesUpdate(BaseModel):
    """Schema for updating user preferences."""
    # Ensure these field names match your User model attributes
    portfolio_size: Optional[float] = Field(None, gt=0, description="User's preferred portfolio size for simulation or display.")
    risk_tolerance: Optional[float] = Field(None, ge=0, le=1, description="User's risk tolerance (e.g., a value between 0 and 1).")
    full_name: Optional[str] = Field(None, min_length=1, max_length=100)
    # Add other updatable, non-sensitive preferences here

class UserPreferencesResponse(BaseModel):
    """Response schema for user preferences."""
    email: str
    full_name: Optional[str] = None
    portfolio_size: Optional[float] = None
    risk_tolerance: Optional[float] = None
    # Include other relevant fields that are safe to return

    class Config:
        from_attributes = True


@router.put("/me/preferences", response_model=UserPreferencesResponse, summary="Update Current User Preferences")
async def update_user_preferences(
    preferences_in: UserPreferencesUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> UserPreferencesResponse:
    """
    Update non-sensitive preferences for the currently authenticated user.
    API keys should be managed via /auth/api-keys/alpaca endpoint.
    """
    logger.info(f"Updating preferences for user: {current_user.email}")
    update_data = preferences_in.model_dump(exclude_unset=True)
    updated_fields_count = 0

    if "portfolio_size" in update_data and update_data["portfolio_size"] is not None:
        # Add any validation specific to portfolio_size if needed
        current_user.portfolio_size = update_data["portfolio_size"]
        updated_fields_count +=1
    
    if "risk_tolerance" in update_data and update_data["risk_tolerance"] is not None:
        # Add any validation specific to risk_tolerance if needed
        current_user.risk_tolerance = update_data["risk_tolerance"]
        updated_fields_count += 1

    if "full_name" in update_data and update_data["full_name"] is not None:
        current_user.full_name = update_data["full_name"]
        updated_fields_count += 1

    # Add other preference updates here

    if updated_fields_count > 0:
        try:
            db.commit()
            db.refresh(current_user)
            logger.info(f"Preferences updated successfully for user: {current_user.email}")
        except Exception as e: # Catch potential DB errors
            db.rollback()
            logger.error(f"Database error updating preferences for {current_user.email}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not update preferences due to a database error."
            )
    else:
        logger.info(f"No preference data provided to update for user: {current_user.email}")
        # Optionally, you could return a 304 Not Modified or a message indicating no changes
        # For simplicity, we'll return the current state.

    return UserPreferencesResponse.model_validate(current_user)