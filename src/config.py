"""
Configuration settings for GitShare FastAPI backend
"""
import os
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Supabase
    supabase_url: str
    supabase_key: str
    supabase_service_key: str | None = None  # Optional, defaults to anon key
    
    # GitHub OAuth
    github_client_id: str
    github_client_secret: str
    
    # Security
    encryption_key: str
    
    # Backend URL - will auto-detect from Vercel if not set
    backend_url: str = ""
    
    # Environment
    environment: str = "development"
    debug: bool = True
    
    # Production settings
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    enable_cors: bool = True
    rate_limit_enabled: bool = True
    max_requests_per_minute: int = 60
    
    class Config:
        env_file = ".env"
        case_sensitive = False
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Auto-configure backend URL based on deployment platform
        if not self.backend_url:
            self.backend_url = self._get_backend_url()
    
    def _get_backend_url(self) -> str:
        """
        Determine backend URL priority:
        1. BACKEND_URL env var (set this to your stable production domain in Vercel)
        2. VERCEL_PROJECT_PRODUCTION_URL (Vercel system variable)
        3. VERCEL_URL (current deployment - less stable)
        4. localhost:8000 (local development)
        """
        # Manual override - set this in Vercel to your stable production domain
        # Example: https://git-share-server-siddharthshukla48s-projects.vercel.app
        backend = os.getenv("BACKEND_URL")
        if backend:
            return backend.rstrip('/')
        
        # Vercel production URL (if available)
        vercel_prod = os.getenv("VERCEL_PROJECT_PRODUCTION_URL")
        if vercel_prod:
            return f"https://{vercel_prod}"
        
        # Current Vercel deployment URL (changes with each deploy)
        vercel_url = os.getenv("VERCEL_URL")
        if vercel_url:
            return f"https://{vercel_url}"
        
        # Local development fallback
        return "http://localhost:8000"
    
    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def log_level_value(self) -> int:
        """Convert log level string to logging constant"""
        import logging
        return getattr(logging, self.log_level.upper(), logging.INFO)


# Global settings instance
settings = Settings()