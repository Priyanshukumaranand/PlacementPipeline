"""
Google OAuth authentication endpoints for Gmail API access.

Flow:
1. GET /auth/login -> Redirects to Google OAuth consent screen
2. Google redirects back to /auth/callback with code
3. /auth/callback exchanges code for tokens and saves them
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from pydantic import BaseModel
import os


# Response Models
class AuthStatusResponse(BaseModel):
    """Authentication status check response."""
    authenticated: bool
    expired: bool
    has_refresh_token: bool
    message: str


class AuthSuccessResponse(BaseModel):
    """Successful authentication response."""
    success: bool
    message: str
    token_saved: str | None = None
    has_refresh_token: bool = False


class AuthErrorResponse(BaseModel):
    """Authentication error response."""
    success: bool = False
    error: str
    message: str


router = APIRouter(prefix="/auth", tags=["Authentication"])

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify"
]


def get_oauth_flow(redirect_uri: str) -> Flow:
    """Create OAuth flow with dynamic redirect URI."""
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    
    if not os.path.exists(creds_file):
        raise HTTPException(
            status_code=500,
            detail="credentials.json not found. Please configure Google OAuth."
        )
    
    flow = Flow.from_client_secrets_file(
        creds_file,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    return flow


@router.get("/status", response_model=AuthStatusResponse)
def auth_status() -> AuthStatusResponse:
    """Check current authentication status."""
    token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    
    if not os.path.exists(token_file):
        return AuthStatusResponse(
            authenticated=False,
            expired=True,
            has_refresh_token=False,
            message="No token found. Please sign in."
        )
    
    try:
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        
        if creds.valid:
            return {
                "authenticated": True,
                "expired": False,
                "has_refresh_token": bool(creds.refresh_token),
                "message": "Token is valid."
            }
        elif creds.expired and creds.refresh_token:
            # Try to refresh
            try:
                creds.refresh(GoogleRequest())
                # Save refreshed token
                with open(token_file, "w") as f:
                    f.write(creds.to_json())
                return {
                    "authenticated": True,
                    "expired": False,
                    "has_refresh_token": True,
                    "message": "Token was expired but has been refreshed."
                }
            except Exception as e:
                return {
                    "authenticated": False,
                    "expired": True,
                    "has_refresh_token": True,
                    "message": f"Token refresh failed: {str(e)}. Please sign in again."
                }
        else:
            return {
                "authenticated": False,
                "expired": True,
                "has_refresh_token": False,
                "message": "Token expired and no refresh token. Please sign in."
            }
    except Exception as e:
        return {
            "authenticated": False,
            "expired": True,
            "has_refresh_token": False,
            "message": f"Error reading token: {str(e)}"
        }


@router.get("/login")
def login(request: Request):
    """
    Start OAuth flow - redirects to Google consent screen.
    
    After user grants permission, Google redirects to /auth/callback.
    """
    # Build callback URL dynamically based on request
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/v1/auth/callback"
    
    flow = get_oauth_flow(redirect_uri)
    
    # Generate authorization URL
    auth_url, state = flow.authorization_url(
        access_type="offline",  # Get refresh token
        include_granted_scopes="true",
        prompt="consent"  # Force consent to get refresh token
    )
    
    return RedirectResponse(url=auth_url)


@router.get("/callback")
def callback(request: Request, code: str = None, error: str = None):
    """
    OAuth callback - exchanges authorization code for tokens.
    
    Google redirects here after user grants/denies permission.
    """
    if error:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": error,
                "message": "Authentication was denied or failed."
            }
        )
    
    if not code:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "missing_code",
                "message": "No authorization code received."
            }
        )
    
    try:
        # Build same redirect URI
        base_url = str(request.base_url).rstrip("/")
        redirect_uri = f"{base_url}/api/v1/auth/callback"
        
        flow = get_oauth_flow(redirect_uri)
        
        # Exchange code for tokens
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        # Save credentials
        token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
        with open(token_file, "w") as f:
            f.write(credentials.to_json())
        
        return JSONResponse(
            content={
                "success": True,
                "message": "✅ Authentication successful! Gmail access is now enabled.",
                "token_saved": token_file,
                "has_refresh_token": bool(credentials.refresh_token)
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e),
                "message": "Failed to exchange authorization code for tokens."
            }
        )


@router.post("/refresh")
def refresh_token():
    """
    Manually refresh the OAuth token.
    
    Use this if the token is expired but has a refresh token.
    """
    token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    
    if not os.path.exists(token_file):
        raise HTTPException(
            status_code=400,
            detail="No token file found. Please sign in first via /auth/login"
        )
    
    try:
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        
        if not creds.refresh_token:
            raise HTTPException(
                status_code=400,
                detail="No refresh token available. Please sign in again via /auth/login"
            )
        
        # Force refresh
        creds.refresh(GoogleRequest())
        
        # Save refreshed token
        with open(token_file, "w") as f:
            f.write(creds.to_json())
        
        return {
            "success": True,
            "message": "Token refreshed successfully.",
            "valid": creds.valid
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh token: {str(e)}. Try /auth/login for fresh authentication."
        )


@router.delete("/logout")
def logout():
    """
    Delete stored credentials (logout).
    
    After this, you'll need to sign in again via /auth/login.
    """
    token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    
    if os.path.exists(token_file):
        os.remove(token_file)
        return {"success": True, "message": "Logged out. Token deleted."}
    
    return {"success": True, "message": "Already logged out. No token found."}
