"""
Fyers Broker API v3 Authentication Router
Supports 3-legged OAuth flow, direct token configuration, and real-time status check.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from app.services.fyers_service import fyers_service, clean_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fyers", tags=["auth"])


class FyersCredentialsRequest(BaseModel):
    client_id: str
    secret_key: str
    redirect_uri: Optional[str] = None


class FyersTokenRequest(BaseModel):
    access_token: str


@router.get("/status")
async def get_fyers_status():
    """Returns current Fyers broker integration status and credentials state."""
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
    """Saves Fyers API credentials and returns generated login URL."""
    fyers_service.set_credentials(req.client_id, req.secret_key, redirect_uri=req.redirect_uri)
    auth_url = fyers_service.generate_auth_url()
    if not auth_url:
        raise HTTPException(
            status_code=400,
            detail="Failed to generate Fyers login URL. Please verify Client ID and Secret Key."
        )
    return {
        "status": "success",
        "message": "Credentials updated successfully.",
        "auth_url": auth_url,
        "redirect_uri": fyers_service.redirect_uri
    }


@router.get("/login")
async def fyers_login(redirect_uri: Optional[str] = None):
    """Redirects user directly to Fyers OAuth Login page."""
    auth_url = fyers_service.generate_auth_url(redirect_uri=redirect_uri)
    if not auth_url:
        raise HTTPException(status_code=400, detail="Fyers credentials not set. Please provide Client ID and Secret Key.")
    return RedirectResponse(url=auth_url)


@router.post("/token")
async def set_fyers_token(req: FyersTokenRequest):
    """Directly sets and validates Fyers access token."""
    valid, msg = fyers_service.set_access_token(req.access_token)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Token validation failed: {msg}")

    return {
        "status": "success",
        "is_configured": True,
        "message": "Fyers Access Token successfully verified and active!"
    }


from fastapi.responses import HTMLResponse, RedirectResponse

@router.get("/callback", response_class=HTMLResponse)
async def fyers_callback(
    auth_code: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    s: Optional[str] = Query(None)
):
    """Callback URL invoked automatically by Fyers OAuth after user login.
    Exchanges auth code for access token and seamlessly lands user on home page.
    """
    target_code = auth_code or code
    if not target_code:
        logger.error(f"Fyers callback received without auth code: s={s}")
        return HTMLResponse(
            content="""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="2;url=/">
    <title>mybullandbear - Auth Error</title>
    <style>
        body { background: #0c1017; color: #f0f6fc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #161b22; border: 1px solid #f85149; border-radius: 12px; padding: 32px 40px; text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.5); max-width: 440px; }
        h2 { margin: 0 0 10px; font-size: 20px; color: #f85149; }
        p { color: #8b949e; font-size: 14px; margin: 0 0 20px; }
        a { color: #38bdf8; text-decoration: none; font-size: 14px; font-weight: 600; }
    </style>
</head>
<body>
    <div class="card">
        <h2>⚠️ Authorization Incomplete</h2>
        <p>No authorization code was received from Fyers. Redirecting back to mybullandbear...</p>
        <a href="/">Go to Dashboard Now</a>
    </div>
    <script>setTimeout(() => { window.location.href = '/'; }, 2000);</script>
</body>
</html>""",
            status_code=400
        )

    success = fyers_service.authenticate_with_code(target_code)
    if success:
        valid, msg = fyers_service.validate_connection()
        logger.info(f"Fyers OAuth Authentication Successful: valid={valid}")
        return HTMLResponse(
            content="""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="1;url=/">
    <title>mybullandbear - Connected</title>
    <style>
        body {
            background-color: #0c1017;
            color: #f0f6fc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
        }
        .card {
            background: #161b22;
            border: 1px solid #238636;
            border-radius: 12px;
            padding: 36px 44px;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.6);
            max-width: 460px;
        }
        .spinner {
            width: 44px;
            height: 44px;
            border: 3px solid rgba(56, 189, 248, 0.2);
            border-top: 3px solid #38bdf8;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin: 0 auto 20px;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        h2 { margin: 0 0 10px; font-size: 22px; color: #3fb950; font-weight: 700; }
        p { color: #8b949e; font-size: 14px; margin: 0 0 24px; line-height: 1.5; }
        .btn {
            display: inline-block;
            background: #238636;
            color: #ffffff;
            font-weight: 600;
            font-size: 14px;
            padding: 10px 22px;
            border-radius: 6px;
            text-decoration: none;
            transition: background 0.2s ease;
        }
        .btn:hover { background: #2ea043; }
    </style>
</head>
<body>
    <div class="card">
        <div class="spinner"></div>
        <h2>mybullandbear</h2>
        <p>✅ Fyers OAuth Authentication Successful!<br>Redirecting directly to the live dashboard...</p>
        <a class="btn" href="/">Open Dashboard</a>
    </div>
    <script>
        // Redirect seamlessly to home page
        setTimeout(() => {
            window.location.href = '/';
        }, 800);
    </script>
</body>
</html>"""
        )
    else:
        logger.error(f"Fyers OAuth Authentication Failed: {fyers_service.last_error}")
        return HTMLResponse(
            content=f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="3;url=/">
    <title>mybullandbear - Auth Error</title>
    <style>
        body {{ background: #0c1017; color: #f0f6fc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
        .card {{ background: #161b22; border: 1px solid #da3633; border-radius: 12px; padding: 32px 40px; text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.5); max-width: 440px; }}
        h2 {{ margin: 0 0 10px; font-size: 20px; color: #f85149; }}
        p {{ color: #8b949e; font-size: 14px; margin: 0 0 20px; }}
        a {{ color: #38bdf8; text-decoration: none; font-size: 14px; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>⚠️ Authentication Failed</h2>
        <p>{fyers_service.last_error or "Unable to exchange authorization code. Please verify credentials."}</p>
        <a href="/">Return to Dashboard</a>
    </div>
    <script>setTimeout(() => {{ window.location.href = '/'; }}, 3000);</script>
</body>
</html>""",
            status_code=400
        )
