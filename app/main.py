from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from typing import List, Optional
import uvicorn
from app.api import auth, trading, analytics, settings
from app.core.config import settings as app_settings

app = FastAPI(
    title="Morgan Trading Platform",
    description="Advanced Quantitative Trading Platform",
    version="1.0.0"
)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[app_settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Include routers
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(trading.router, prefix="/api", tags=["trading"])
app.include_router(analytics.router, prefix="/api", tags=["analytics"])
app.include_router(settings.router, prefix="/api", tags=["settings"])

@app.get("/")
async def root():
    return {
        "message": "Welcome to Morgan Trading Platform API",
        "status": "operational",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "services": {
            "api": "operational",
            "database": "operational",
            "ml_engine": "operational"
        }
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 