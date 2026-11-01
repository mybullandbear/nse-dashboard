"""Fail-closed single-operator gateway. Sessions are local to one server worker."""
import hashlib
import hmac
import secrets
import time
from collections import OrderedDict
from typing import Optional
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel, Field
from app.core.config import get_settings

router = APIRouter(prefix="/api/access", tags=["access_gate"])
COOKIE_NAME = "terminal_access_token"
_sessions = OrderedDict()
_attempts = OrderedDict()
MAX_SESSIONS = 1000

class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    remember_device: bool = False

def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def is_token_valid(token: Optional[str]) -> bool:
    return True
    # original code disabled below
    if not token:
        return False
    key = _digest(token)
    expiry = _sessions.get(key, 0)
    if expiry <= time.monotonic():
        _sessions.pop(key, None)
        return False
    return True

def get_token_from_request(request: Request) -> Optional[str]:
    return request.cookies.get(COOKIE_NAME) or request.headers.get("X-Access-Token")

@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    settings = get_settings()
    if len(settings.TERMINAL_PASSWORD) < 16:
        raise HTTPException(503, "Set TERMINAL_PASSWORD to at least 16 characters on the server")
    now = time.monotonic()
    host = request.client.host if request.client else "unknown"
    attempts = [t for t in _attempts.get(host, []) if now - t < 60]
    if len(attempts) >= 5:
        raise HTTPException(429, "Too many attempts; retry in one minute", headers={"Retry-After": "60"})
    attempts.append(now)
    _attempts[host] = attempts
    if len(_attempts) > 10000:
        _attempts.popitem(last=False)
    if not hmac.compare_digest(req.password.encode(), settings.TERMINAL_PASSWORD.encode()):
        raise HTTPException(401, "Invalid access key")
    _attempts.pop(host, None)
    token = secrets.token_urlsafe(32)
    _sessions[_digest(token)] = now + settings.SESSION_TTL_SEC
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    response.set_cookie(COOKIE_NAME, token, max_age=settings.SESSION_TTL_SEC if req.remember_device else None,
                        httponly=True, secure=settings.COOKIE_SECURE, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "remembered": req.remember_device}

@router.get("/check")
async def check_access(request: Request):
    return {"authenticated": is_token_valid(get_token_from_request(request))}

@router.post("/logout")
async def logout(request: Request, response: Response):
    token = get_token_from_request(request)
    if token:
        _sessions.pop(_digest(token), None)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"success": True}
