
# ===================================
# config.py - Configuration Management
# ===================================

import os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Alpha Vantage API
    alpha_vantage_api_key: str
    alpha_vantage_base_url: str = "https://www.alphavantage.co/query"
    
    # Rate Limiting
    rate_limit_requests: int = 5
    rate_limit_window: int = 60  # seconds
    request_timeout: int = 30
    
    # Application
    app_name: str = "Financial Analytics Dashboard API"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # Optional: Supabase
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    
    # Optional: Database
    database_url: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Global settings instance
settings = Settings()
