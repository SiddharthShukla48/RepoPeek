"""
GitShare FastAPI Backend
Secure backend for sharing private GitHub repositories
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging
from contextlib import asynccontextmanager

from .config import settings
from .routes import router as api_router

# Configure logging based on environment
logging.basicConfig(
    level=settings.log_level_value,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s' if not settings.is_production 
           else '%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Rate limiter setup
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    logger.info(f"Starting GitShare API in {settings.environment} mode")
    yield
    logger.info("Shutting down GitShare API")


# Initialize FastAPI app
app = FastAPI(
    title="GitShare API",
    description="Secure API for sharing private GitHub repositories",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,  # Disable docs in production
    redoc_url="/redoc" if not settings.is_production else None
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# CORS configuration - Allow all Chrome extensions for easy distribution
# 
# This accepts requests from:
#   - chrome-extension://[any-extension-id]  (any user's extension)
#   - http://localhost:[any-port]            (local development)
#   - http://127.0.0.1:[any-port]            (local development)
#
# Why this is safe:
#   GitHub OAuth authentication still required for all operations
#   Tokens are encrypted in database
#   Each user can only access their own repositories
#   Links expire automatically
#   Rate limiting prevents abuse
#
# This allows zero-configuration setup for end users - they just load the
# extension ZIP and it works immediately without needing to configure origins.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^chrome-extension://[a-z]+$|^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Global exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors"""
    logger.warning(f"Validation error from {request.client.host}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation Error",
            "detail": exc.errors()
        }
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors"""
    logger.error(f"Unhandled error from {request.client.host}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "detail": "An unexpected error occurred" if settings.is_production else str(exc)
        }
    )

# Include all routes
app.include_router(api_router)


@app.get("/")
async def read_root():
    """Root endpoint"""
    return {
        "message": "GitShare API",
        "version": "1.0.0",
        "docs": "/docs" if not settings.is_production else None
    }


@app.get("/favicon.{ext}")
async def favicon(ext: str):
    """Return 204 No Content for favicon requests to avoid 404 logs"""
    from fastapi.responses import Response
    return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=not settings.is_production,
        log_level="info" if settings.is_production else "debug"
    )