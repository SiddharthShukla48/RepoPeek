"""
Pydantic schemas for request/response validation
"""
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
import re


class GitHubAuthRequest(BaseModel):
    """Request body for GitHub OAuth code exchange"""
    code: str = Field(..., min_length=1, description="GitHub OAuth authorization code")
    redirect_uri: str = Field(..., description="OAuth redirect URI")
    
    @validator('code')
    def validate_code(cls, v):
        if not v or not v.strip():
            raise ValueError('Authorization code cannot be empty')
        return v.strip()


class GenerateLinkRequest(BaseModel):
    """Request body for generating a share link"""
    token: str = Field(..., min_length=1, description="GitHub access token")
    owner: str = Field(..., min_length=1, max_length=100, description="Repository owner")
    repo: str = Field(..., min_length=1, max_length=100, description="Repository name")
    user_id: str = Field(..., description="GitHub user ID")
    expires_in_days: int = Field(default=7, ge=1, le=60, description="Number of days until link expires")
    
    @validator('owner', 'repo')
    def validate_github_name(cls, v):
        """Validate GitHub username/repo name format"""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('Invalid GitHub username or repository name format')
        return v.strip()


class GenerateLinkResponse(BaseModel):
    """Response for link generation"""
    share_link: str
    link_id: str
    expires_at: str
    is_existing: Optional[bool] = False


class RepoContentResponse(BaseModel):
    """Response for repository content"""
    owner: str
    repo: str
    name: str
    description: Optional[str]
    stars: int
    forks: int
    language: Optional[str]
    contents: list
    
    
class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    version: str = "1.0.0"


# Exporting schemas
__all__ = [
    "GitHubAuthRequest",
    "GenerateLinkRequest", 
    "GenerateLinkResponse",
    "RepoContentResponse",
    "ErrorResponse",
    "HealthResponse"
]