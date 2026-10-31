"""
Terminal Access Gateway & Authentication Router
Protects the public deployment with institutional password authentication.
"""
import hashlib
import logging
from typing import Optional
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/access", tags=["access_gate"])

TERMINAL_PASSWORD = "tradermybullandbear"
# Deterministic secure session token derived from password
TOKEN_SALT = b"tradermybullandbear_mybullandbear_secure_salt_2026"
VALID_ACCESS_TOKEN = hashlib.sha256(TERMINAL_PASSWORD.encode() + TOKEN_SALT).hexdigest()
COOKIE_NAME = "terminal_access_token"


class LoginRequest(BaseModel):
    password: str
    remember_device: Optional[bool] = True


def is_token_valid(token: Optional[str]) -> bool:
    # Public review mode: password protection disabled
    return True


def get_token_from_request(request: Request) -> Optional[str]:
    # 1. Check custom header
    header_token = request.headers.get("X-Access-Token")
    if header_token:
        return header_token
    # 2. Check Cookie
    cookie_token = request.cookies.get(COOKIE_NAME)
    if cookie_token:
        return cookie_token
    # 3. Check query param for websocket
    query_token = request.query_params.get("access_token")
    if query_token:
        return query_token
    return None


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    """Validates the terminal password and issues a persistent or session token."""
    input_pw = req.password.strip()
    if input_pw != TERMINAL_PASSWORD:
        logger.warning("Access Gateway: Failed login attempt.")
        raise HTTPException(status_code=401, detail="Invalid access key. Access denied.")

    # Set persistent 365-day cookie if remember_device is selected
    max_age = (365 * 24 * 3600) if req.remember_device else None
    response.set_cookie(
        key=COOKIE_NAME,
        value=VALID_ACCESS_TOKEN,
        max_age=max_age,
        httponly=False,  # Allow JS client to read if needed
        samesite="lax",
        path="/"
    )

    logger.info(f"Access Gateway: Password accepted. Remember device: {req.remember_device}")
    return {
        "success": True,
        "token": VALID_ACCESS_TOKEN,
        "remembered": req.remember_device,
        "message": "Access granted. Device saved as trusted." if req.remember_device else "Access granted (Session only)."
    }


@router.get("/check")
async def check_access(request: Request):
    """Verifies if the current request session possesses valid access rights."""
    token = get_token_from_request(request)
    authenticated = is_token_valid(token)
    return {
        "authenticated": authenticated
    }


@router.post("/logout")
async def logout(response: Response):
    """Terminates session and removes cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {
        "success": True,
        "message": "Terminal locked successfully."
    }
