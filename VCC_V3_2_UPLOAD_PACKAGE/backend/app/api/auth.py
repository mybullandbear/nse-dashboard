"""
Authentication and Broker Integration Router (Fyers OAuth v3)
"""
import logging
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.services.fyers_fetcher import fyers_service, clean_token
from app.cache import cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fyers", tags=["auth"])


class FyersCredentialsRequest(BaseModel):
    client_id: str
    secret_key: str
    redirect_uri: Optional[str] = None


@router.get("/status")
async def get_fyers_status():
    """Get Fyers API configuration and authentication status."""
    return {
        "is_configured": fyers_service.is_configured(),
        "client_id": fyers_service.client_id or "",
        "redirect_uri": fyers_service.redirect_uri or "",
        "has_secret": bool(fyers_service.secret_key),
        "has_token": bool(fyers_service.access_token),
        "last_error": fyers_service.last_error,
    }


@router.post("/credentials")
async def set_fyers_credentials(req: FyersCredentialsRequest):
    """Set Fyers client_id and secret_key, and return generated Auth URL."""
    fyers_service.set_credentials(req.client_id, req.secret_key, redirect_uri=req.redirect_uri)
    auth_url = fyers_service.generate_auth_url()
    if not auth_url:
        raise HTTPException(status_code=400, detail="Failed to generate Fyers login URL. Check Client ID and Secret Key.")
    return {
        "status": "success",
        "message": "Credentials saved. Please open the auth_url to complete Fyers authentication.",
        "auth_url": auth_url,
        "redirect_uri": fyers_service.redirect_uri
    }


@router.get("/login")
async def fyers_login(redirect_uri: Optional[str] = None):
    """Redirect user directly to Fyers OAuth Login Page."""
    auth_url = fyers_service.generate_auth_url(redirect_uri=redirect_uri)
    if not auth_url:
        raise HTTPException(status_code=400, detail="Fyers credentials not set. Please post client_id and secret_key first.")
    return RedirectResponse(url=auth_url)



class FyersTokenRequest(BaseModel):
    access_token: str


@router.post("/token")
async def set_fyers_token(req: FyersTokenRequest):
    """Set Fyers access token directly with live verification."""
    cleaned = clean_token(req.access_token)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid token provided.")
    fyers_service.access_token = cleaned
    fyers_service._save_config()
    fyers_service._init_client()
    await cache.clear()

    valid, msg = fyers_service.validate_connection()
    if not valid:
        raise HTTPException(status_code=400, detail=f"Fyers token validation failed: {msg}")

    return {
        "status": "success",
        "is_configured": True,
        "message": "Fyers Access Token successfully verified and active!"
    }


@router.get("/callback")
async def fyers_callback(
    auth_code: Optional[str] = Query(None),
    s: Optional[str] = Query(None),
    code: Optional[str] = Query(None)
):
    """Callback URL invoked automatically by Fyers after user logs in."""
    target_code = auth_code or code
    if not target_code:
        logger.error(f"Fyers callback received without auth_code: s={s}")
        return RedirectResponse(url="/?fyers=error_no_code")

    success = fyers_service.authenticate_with_code(target_code)
    if success:
        valid, msg = fyers_service.validate_connection()
        if valid:
            await cache.clear()
            logger.info("Fyers OAuth Authentication Successful! Cache cleared.")
            return RedirectResponse(url="/?fyers=success")
        else:
            logger.error(f"Fyers OAuth token generated but validation failed: {msg}")
            return RedirectResponse(url="/?fyers=error_auth_failed")
    else:
        logger.error("Fyers OAuth Authentication Failed.")
        return RedirectResponse(url="/?fyers=error_auth_failed")

