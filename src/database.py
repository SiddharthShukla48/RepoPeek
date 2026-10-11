"""
Supabase database connection and utilities
"""
from supabase import create_client, Client
from cryptography.fernet import Fernet
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import logging

from .config import settings

logger = logging.getLogger(__name__)

# Initialize Supabase client with service role key for full access
# Service role bypasses RLS policies
supabase_key = settings.supabase_service_key or settings.supabase_key
supabase: Client = create_client(settings.supabase_url, supabase_key)

# Initialize encryption cipher
cipher = Fernet(settings.encryption_key.encode())


def get_supabase_client() -> Client:
    """Get Supabase client instance"""
    return supabase


def encrypt_token(token: str) -> str:
    """Encrypt a GitHub token"""
    return cipher.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a GitHub token"""
    return cipher.decrypt(encrypted_token.encode()).decode()


class ShareLinkDB:
    """Database operations for share links"""
    
    TABLE_NAME = "share_links"
    
    @staticmethod
    async def create_link(
        link_id: str,
        owner: str,
        repo: str,
        token: str,
        user_id: str,
        expires_in_days: int = 7
    ) -> Dict[str, Any]:
        """Create a new share link with encrypted token"""
        try:
            encrypted_token = encrypt_token(token)
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=expires_in_days)
            
            data = {
                "link_id": link_id,
                "owner": owner,
                "repo": repo,
                "encrypted_token": encrypted_token,
                "user_id": user_id,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "access_count": 0
            }
            
            response = supabase.table(ShareLinkDB.TABLE_NAME).insert(data).execute()
            
            logger.info(f"Share link created: {link_id} for {owner}/{repo}")
            return response.data[0] if response.data else None
            
        except Exception as e:
            logger.error(f"Error creating share link: {e}")
            raise
    
    @staticmethod
    async def get_link(link_id: str) -> Optional[Dict[str, Any]]:
        """Get share link by ID"""
        try:
            response = supabase.table(ShareLinkDB.TABLE_NAME)\
                .select("*")\
                .eq("link_id", link_id)\
                .execute()
            
            if not response.data:
                return None
            
            link_data = response.data[0]
            
            # Check if expired
            expires_at = datetime.fromisoformat(link_data["expires_at"])
            if expires_at < datetime.now(timezone.utc):
                logger.info(f"Link {link_id} has expired")
                return None
            
            return link_data
            
        except Exception as e:
            logger.error(f"Error getting share link: {e}")
            raise
    
    @staticmethod
    async def get_existing_link(user_id: str, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        """Get existing valid link for a repo"""
        try:
            response = supabase.table(ShareLinkDB.TABLE_NAME)\
                .select("*")\
                .eq("user_id", user_id)\
                .eq("owner", owner)\
                .eq("repo", repo)\
                .execute()
            
            if not response.data:
                return None
            
            # Check if any links are still valid
            for link_data in response.data:
                expires_at = datetime.fromisoformat(link_data["expires_at"])
                if expires_at > datetime.now(timezone.utc):
                    return link_data
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting existing share link: {e}")
            raise
    
    @staticmethod
    async def increment_access_count(link_id: str, client_ip: str) -> None:
        """Increment access count and update last access info"""
        try:
            # Get current data
            link = await ShareLinkDB.get_link(link_id)
            if not link:
                return
            
            # Update access count
            supabase.table(ShareLinkDB.TABLE_NAME)\
                .update({
                    "access_count": link["access_count"] + 1,
                    "last_accessed_at": datetime.now(timezone.utc).isoformat(),
                    "last_ip": client_ip
                })\
                .eq("link_id", link_id)\
                .execute()
            
            pass
            
        except Exception as e:
            logger.error(f"Error incrementing access count: {e}")
            # Don't raise - this is non-critical
    
    @staticmethod
    async def get_user_links(user_id: str) -> list:
        """Get all links created by a user"""
        try:
            response = supabase.table(ShareLinkDB.TABLE_NAME)\
                .select("link_id, owner, repo, created_at, expires_at, access_count")\
                .eq("user_id", user_id)\
                .order("created_at", desc=True)\
                .execute()
            
            return response.data
            
        except Exception as e:
            logger.error(f"Error getting user links: {e}")
            raise
    
    @staticmethod
    async def revoke_link(link_id: str, user_id: str) -> bool:
        """Revoke (delete) a share link - only if owned by user"""
        try:
            # Check if link exists and user owns it
            link_check = supabase.table(ShareLinkDB.TABLE_NAME)\
                .select("link_id, user_id")\
                .eq("link_id", link_id)\
                .execute()
            
            if not link_check.data:
                return False
            
            stored_user_id = link_check.data[0]["user_id"]
            
            # Check ownership
            if str(stored_user_id) != str(user_id):
                return False
            
            # Delete the link
            supabase.table(ShareLinkDB.TABLE_NAME)\
                .delete()\
                .eq("link_id", link_id)\
                .eq("user_id", stored_user_id)\
                .execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Error revoking link: {e}")
            raise