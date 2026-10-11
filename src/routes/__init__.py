"""
API route handlers
"""
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import httpx
import secrets
import logging
from datetime import datetime, timezone
from typing import Dict, Any
import os

from ..config import settings
from ..database import ShareLinkDB, decrypt_token
from ..schemas import (
    GitHubAuthRequest,
    GenerateLinkRequest,
    GenerateLinkResponse,
    RepoContentResponse,
    ErrorResponse,
    HealthResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Setup Jinja2 templates
template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=template_dir)


# GitHub OAuth endpoints
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API = "https://api.github.com/user"
GITHUB_REPO_API = "https://api.github.com/repos"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }


@router.post("/api/github-auth")
async def exchange_github_code(
    auth_request: GitHubAuthRequest,
    request: Request
) -> JSONResponse:
    """
    Exchange GitHub OAuth code for access token (SERVER-SIDE ONLY)
    This keeps the client secret secure on the backend
    """
    try:
        # Exchange code for token with GitHub
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,  # Backend only!
                    "code": auth_request.code,
                    "redirect_uri": auth_request.redirect_uri
                },
                headers={"Accept": "application/json"}
            )
            
            if token_response.status_code != 200:
                logger.error(f"GitHub token exchange failed: {token_response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to authenticate with GitHub"
                )
            
            token_data = token_response.json()
            
            if "error" in token_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=token_data.get("error_description", "Authentication failed")
                )
            
            access_token = token_data["access_token"]
            
            # Get user info
            user_response = await client.get(
                GITHUB_USER_API,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                }
            )
            
            if user_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to fetch user information"
                )
            
            user_data = user_response.json()
        
        response_data = {
            "success": True,
            "token": access_token,
            "user": {
                "id": user_data["id"],
                "login": user_data["login"],
                "name": user_data.get("name"),
                "avatar_url": user_data.get("avatar_url")
            }
        }
        
        # Return with explicit CORS headers
        return JSONResponse(
            content=response_data,
            headers={
                "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                "Access-Control-Allow-Credentials": "true",
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GitHub auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )


@router.post("/api/generate-link", response_model=GenerateLinkResponse)
async def generate_share_link(
    link_request: GenerateLinkRequest,
    request: Request
) -> Dict[str, Any]:
    """
    Generate a shareable link for a private GitHub repository
    Token is encrypted before storage
    """
    try:
        # Verify token is valid and has access to the repo
        async with httpx.AsyncClient() as client:
            repo_response = await client.get(
                f"{GITHUB_REPO_API}/{link_request.owner}/{link_request.repo}",
                headers={
                    "Authorization": f"Bearer {link_request.token}",
                    "Accept": "application/json"
                }
            )
            
            if repo_response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Repository not found or access denied"
                )
            elif repo_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to verify repository access"
                )
            
            repo_data = repo_response.json()
            
            # Check if repo is private
            if not repo_data.get("private", False):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Repository is not private. No need to create a share link."
                )
        
        # Check if a valid link already exists for this repo
        existing_link = await ShareLinkDB.get_existing_link(
            user_id=link_request.user_id,
            owner=link_request.owner,
            repo=link_request.repo
        )
        
        if existing_link:
            # Return existing link
            share_link = f"{settings.backend_url}/view/{existing_link['link_id']}"
            return {
                "share_link": share_link,
                "link_id": existing_link['link_id'],
                "expires_at": existing_link["expires_at"],
                "is_existing": True
            }
        
        # Generate secure link ID
        link_id = secrets.token_urlsafe(16)
        
        # Store link in database with encrypted token
        link_data = await ShareLinkDB.create_link(
            link_id=link_id,
            owner=link_request.owner,
            repo=link_request.repo,
            token=link_request.token,  # Will be encrypted in DB
            user_id=link_request.user_id,
            expires_in_days=link_request.expires_in_days
        )
        
        share_link = f"{settings.backend_url}/view/{link_id}"
        
        return {
            "share_link": share_link,
            "link_id": link_id,
            "expires_at": link_data["expires_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Link generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate share link"
        )


@router.get("/view/{link_id}", response_class=HTMLResponse)
async def view_shared_repo(
    link_id: str,
    request: Request
):
    """
    View shared repository content as HTML page
    Fetches content SERVER-SIDE using encrypted token (never exposed to client)
    """
    try:
        # Validate link_id format
        if not link_id or len(link_id) < 20:
            return HTMLResponse(
                content="<h1>404 - Invalid Link</h1><p>This link is not valid.</p>",
                status_code=404
            )
        
        # Get link from database
        link_data = await ShareLinkDB.get_link(link_id)
        
        if not link_data:
            return HTMLResponse(
                content="<h1>404 - Link Not Found</h1><p>This link does not exist or has expired.</p>",
                status_code=404
            )
        
        # Check expiration
        expires_at = datetime.fromisoformat(link_data["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            return HTMLResponse(
                content="<h1>⏱️ Link Expired</h1><p>This link has expired. Please request a new one.</p>",
                status_code=404
            )
        
        # Decrypt token (stays on server!)
        token = decrypt_token(link_data["encrypted_token"])
        owner = link_data["owner"]
        repo = link_data["repo"]
        
        # Fetch repository data SERVER-SIDE
        async with httpx.AsyncClient() as client:
            # Get repo info
            repo_response = await client.get(
                f"{GITHUB_REPO_API}/{owner}/{repo}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                }
            )
            
            if repo_response.status_code != 200:
                return HTMLResponse(
                    content="<h1>❌ Repository Not Accessible</h1><p>This repository is no longer accessible.</p>",
                    status_code=404
                )
            
            # Get contents
            contents_response = await client.get(
                f"{GITHUB_REPO_API}/{owner}/{repo}/contents",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                }
            )
            
            if contents_response.status_code != 200:
                contents_data = []
            else:
                contents_data = contents_response.json()
            
            repo_data = repo_response.json()
            
            # Get commits count
            commits_response = await client.get(
                f"{GITHUB_REPO_API}/{owner}/{repo}/commits?per_page=1",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                }
            )
            
            commits_count = 0
            if commits_response.status_code == 200:
                # GitHub returns Link header with pagination info
                link_header = commits_response.headers.get("Link", "")
                if "rel=\"last\"" in link_header:
                    # Extract the page number from the last link
                    import re
                    match = re.search(r'page=(\d+)>; rel="last"', link_header)
                    if match:
                        commits_count = int(match.group(1))
                else:
                    # If no pagination, count the commits we got
                    commits_data = commits_response.json()
                    commits_count = len(commits_data) if isinstance(commits_data, list) else 1
        
        # Increment access count (non-blocking)
        await ShareLinkDB.increment_access_count(link_id, request.client.host)
        
        # Render HTML template (NO TOKEN!)
        return templates.TemplateResponse("viewer.html", {
            "request": request,
            "link_id": link_id,
            "repo": repo_data,
            "contents": contents_data,
            "owner": owner,
            "repo_name": repo,
            "expires_at": link_data["expires_at"],
            "commits_count": commits_count
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"View repo error: {e}")
        return HTMLResponse(
            content=f"<h1>Error</h1><p>An error occurred while loading the repository.</p><p>{str(e) if not settings.is_production else ''}</p>",
            status_code=500
        )


@router.get("/api/view/{link_id}/commits")
async def get_commits(
    link_id: str,
    page: int = 1,
    per_page: int = 30,
    request: Request = None
) -> Dict[str, Any]:
    """
    Get commits for a shared link
    """
    try:
        # Get and validate link
        link_data = await ShareLinkDB.get_link(link_id)
        
        if not link_data:
            raise HTTPException(status_code=404, detail="Link not found")
        
        # Check expiration
        expires_at = datetime.fromisoformat(link_data["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Link expired")
        
        owner = link_data["owner"]
        repo = link_data["repo"]
        token = decrypt_token(link_data["encrypted_token"])
        
        # Fetch commits from GitHub
        github_url = f"{GITHUB_REPO_API}/{owner}/{repo}/commits?page={page}&per_page={per_page}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                github_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch commits")
        
        commits = response.json()
        
        # Format commits data
        formatted_commits = [
            {
                "sha": commit["sha"][:7],
                "message": commit["commit"]["message"].split('\n')[0],
                "author": {
                    "name": commit["commit"]["author"]["name"],
                    "avatar": commit["author"]["avatar_url"] if commit.get("author") else None,
                    "username": commit["author"]["login"] if commit.get("author") else None
                },
                "date": commit["commit"]["author"]["date"],
                "url": commit["html_url"]
            }
            for commit in commits
        ]
        
        return {"commits": formatted_commits}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Commits fetch error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/view/{link_id}/forks")
async def get_forks(
    link_id: str,
    page: int = 1,
    per_page: int = 30,
    request: Request = None
) -> Dict[str, Any]:
    """
    Get forks for a shared link
    """
    try:
        # Get and validate link
        link_data = await ShareLinkDB.get_link(link_id)
        
        if not link_data:
            raise HTTPException(status_code=404, detail="Link not found")
        
        # Check expiration
        expires_at = datetime.fromisoformat(link_data["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Link expired")
        
        owner = link_data["owner"]
        repo = link_data["repo"]
        token = decrypt_token(link_data["encrypted_token"])
        
        # Fetch forks from GitHub
        github_url = f"{GITHUB_REPO_API}/{owner}/{repo}/forks?page={page}&per_page={per_page}&sort=stargazers"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                github_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch forks")
        
        forks = response.json()
        
        # Format forks data
        formatted_forks = [
            {
                "owner": {
                    "username": fork["owner"]["login"],
                    "avatar": fork["owner"]["avatar_url"],
                    "url": fork["owner"]["html_url"]
                },
                "name": fork["name"],
                "full_name": fork["full_name"],
                "description": fork.get("description"),
                "stars": fork["stargazers_count"],
                "forks": fork["forks_count"],
                "updated_at": fork["updated_at"],
                "url": fork["html_url"]
            }
            for fork in forks
        ]
        
        return {"forks": formatted_forks}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Forks fetch error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/view/{link_id}/stargazers")
async def get_stargazers(
    link_id: str,
    page: int = 1,
    per_page: int = 30,
    request: Request = None
) -> Dict[str, Any]:
    """
    Get stargazers for a shared link
    """
    try:
        # Get and validate link
        link_data = await ShareLinkDB.get_link(link_id)
        
        if not link_data:
            raise HTTPException(status_code=404, detail="Link not found")
        
        # Check expiration
        expires_at = datetime.fromisoformat(link_data["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Link expired")
        
        owner = link_data["owner"]
        repo = link_data["repo"]
        token = decrypt_token(link_data["encrypted_token"])
        
        # Fetch stargazers from GitHub
        github_url = f"{GITHUB_REPO_API}/{owner}/{repo}/stargazers?page={page}&per_page={per_page}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                github_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch stargazers")
        
        stargazers = response.json()
        
        # Format stargazers data
        formatted_stargazers = [
            {
                "username": user["login"],
                "avatar": user["avatar_url"],
                "url": user["html_url"],
                "type": user["type"]
            }
            for user in stargazers
        ]
        
        return {"stargazers": formatted_stargazers}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stargazers fetch error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/view/{link_id}/contents")
async def get_directory_contents(
    link_id: str,
    path: str = "",
    request: Request = None
) -> Dict[str, Any]:
    """
    Get directory contents for a shared link
    """
    try:
        # Get and validate link
        link_data = await ShareLinkDB.get_link(link_id)
        
        if not link_data:
            raise HTTPException(status_code=404, detail="Link not found")
        
        # Check expiration
        expires_at = datetime.fromisoformat(link_data["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Link expired")
        
        owner = link_data["owner"]
        repo = link_data["repo"]
        token = decrypt_token(link_data["encrypted_token"])
        
        # Fetch directory contents from GitHub
        github_url = f"{GITHUB_REPO_API}/{owner}/{repo}/contents/{path}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                github_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
        
        if response.status_code != 200:
            logger.error(f"GitHub API error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch directory contents")
        
        contents = response.json()
        
        # If single file, wrap in array
        if isinstance(contents, dict):
            contents = [contents]
        
        # Filter out sensitive files
        filtered_contents = [
            {
                "name": item["name"],
                "path": item["path"],
                "type": item["type"],
                "size": item.get("size", 0)
            }
            for item in contents
            if not item["name"].startswith('.')
        ]
        
        return {"contents": filtered_contents}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Directory contents error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/view/{link_id}/file")
async def get_file_content(
    link_id: str,
    path: str,
    request: Request = None
) -> Dict[str, Any]:
    """
    Get file content for a shared link
    """
    try:
        # Get and validate link
        link_data = await ShareLinkDB.get_link(link_id)
        
        if not link_data:
            raise HTTPException(status_code=404, detail="Link not found")
        
        # Check expiration
        expires_at = datetime.fromisoformat(link_data["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Link expired")
        
        owner = link_data["owner"]
        repo = link_data["repo"]
        token = decrypt_token(link_data["encrypted_token"])
        
        # Fetch file from GitHub
        github_url = f"{GITHUB_REPO_API}/{owner}/{repo}/contents/{path}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                github_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
        
        if response.status_code != 200:
            logger.error(f"GitHub API error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch file")
        
        file_data = response.json()
        
        # Decode base64 content
        import base64
        content = base64.b64decode(file_data["content"]).decode("utf-8")
        
        return {
            "name": file_data["name"],
            "content": content,
            "size": file_data["size"]
        }
        
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Binary file cannot be displayed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File content error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/view/{link_id}/raw")
async def get_raw_file_content(
    link_id: str,
    path: str,
    request: Request = None
):
    """
    Get raw file content (for PDFs, images, etc.) for a shared link
    Returns binary content with appropriate content-type
    """
    try:
        # Get and validate link
        link_data = await ShareLinkDB.get_link(link_id)
        
        if not link_data:
            raise HTTPException(status_code=404, detail="Link not found")
        
        # Check expiration
        expires_at = datetime.fromisoformat(link_data["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Link expired")
        
        owner = link_data["owner"]
        repo = link_data["repo"]
        token = decrypt_token(link_data["encrypted_token"])
        
        # Fetch file from GitHub
        github_url = f"{GITHUB_REPO_API}/{owner}/{repo}/contents/{path}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                github_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
        
        if response.status_code != 200:
            logger.error(f"GitHub API error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch file")
        
        file_data = response.json()
        
        # Decode base64 content
        import base64
        from fastapi.responses import Response
        
        content = base64.b64decode(file_data["content"])
        
        # Determine content type
        filename = file_data["name"]
        ext = filename.split('.')[-1].lower()
        
        content_types = {
            'pdf': 'application/pdf',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'svg': 'image/svg+xml',
            'webp': 'image/webp',
        }
        
        content_type = content_types.get(ext, 'application/octet-stream')
        
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{filename}"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Raw file content error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/revoke-link")
async def revoke_share_link(
    link_id: str,
    user_id: str,
    request: Request
) -> Dict[str, Any]:
    """Revoke a share link"""
    try:
        success = await ShareLinkDB.revoke_link(link_id, user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Link not found or you don't have permission to revoke it"
            )
        
        return {"success": True, "message": "Link revoked successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Revoke link error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke link"
        )
