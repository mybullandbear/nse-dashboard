"""
Resilient Fyers Broker API v3 Client
"""
import json
import logging
import os
import time
from typing import Optional, Dict, Any, List, Tuple
from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from fyers_apiv3 import fyersModel
    HAS_FYERS = True
except ImportError:
    fyersModel = None
    HAS_FYERS = False


def clean_token(token: Optional[str]) -> Optional[str]:
    """Sanitize access token string."""
    if not token:
        return None
    token = token.strip().strip('"').strip("'")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if ":" in token:
        parts = token.split(":", 1)
        if len(parts) > 1 and len(parts[1].strip()) > 10:
            token = parts[1].strip()
    return token or None


class FyersClient:
    def __init__(self):
        self.config_path = settings.FYERS_CONFIG_PATH
        self.client_id: Optional[str] = settings.FYERS_CLIENT_ID
        self.secret_key: Optional[str] = settings.FYERS_SECRET_KEY
        self.redirect_uri: str = settings.FYERS_REDIRECT_URI
        self.access_token: Optional[str] = None
        self.fyers: Optional[Any] = None
        self.last_error: Optional[str] = None
        self.last_rate_limit_time: float = 0.0

        self.load_config()
        if self.client_id and self.access_token and HAS_FYERS:
            self._init_client()

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                    self.client_id = data.get("client_id") or self.client_id
                    self.secret_key = data.get("secret_key") or self.secret_key
                    self.redirect_uri = data.get("redirect_uri") or self.redirect_uri
                    self.access_token = clean_token(data.get("access_token"))
            except Exception as e:
                logger.warning(f"Error loading fyers_config.json: {e}")

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump({
                    "client_id": self.client_id,
                    "secret_key": self.secret_key,
                    "redirect_uri": self.redirect_uri,
                    "access_token": self.access_token
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving fyers_config.json: {e}")

    def _init_client(self):
        if not HAS_FYERS or not self.client_id or not self.access_token:
            return
        try:
            self.fyers = fyersModel.FyersModel(
                client_id=self.client_id,
                token=self.access_token,
                is_async=False,
                log_path=""
            )
            logger.info("Fyers API Client Initialized.")
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Failed to init Fyers client: {e}")

    def is_configured(self) -> bool:
        if not self.access_token:
            self.load_config()
        if self.fyers is None and self.client_id and self.access_token and HAS_FYERS:
            self._init_client()
        return self.fyers is not None and bool(self.access_token)

    def generate_auth_url(self, redirect_uri: Optional[str] = None) -> Optional[str]:
        if not HAS_FYERS or not self.client_id or not self.secret_key:
            return None
        r_uri = redirect_uri or self.redirect_uri
        try:
            session = fyersModel.SessionModel(
                client_id=self.client_id,
                secret_key=self.secret_key,
                redirect_uri=r_uri,
                response_type="code",
                grant_type="authorization_code"
            )
            return session.generate_authcode()
        except Exception as e:
            logger.error(f"Error generating Fyers auth URL: {e}")
            return None

    def authenticate_with_code(self, auth_code: str, redirect_uri: Optional[str] = None) -> bool:
        if not HAS_FYERS or not self.client_id or not self.secret_key:
            return False

        candidates = [redirect_uri] if redirect_uri else []
        for u in [
            self.redirect_uri,
            "http://137.23.42.11:8000/api/fyers/callback",
            "https://137.23.42.11/api/fyers/callback",
            "http://localhost:8000/api/fyers/callback",
            "http://127.0.0.1:8000/api/fyers/callback",
            "https://trade.fyers.in/api-login/redirect-uri/index.html"
        ]:
            if u and u not in candidates:
                candidates.append(u)

        for r_uri in candidates:
            try:
                session = fyersModel.SessionModel(
                    client_id=self.client_id,
                    secret_key=self.secret_key,
                    redirect_uri=r_uri,
                    response_type="code",
                    grant_type="authorization_code"
                )
                session.set_token(auth_code)
                res = session.generate_token()
                if res and res.get("s") == "ok" and "access_token" in res:
                    self.access_token = clean_token(res["access_token"])
                    self.redirect_uri = r_uri
                    self.save_config()
                    self._init_client()
                    logger.info(f"Fyers auth succeeded with: {r_uri}")
                    return True
            except Exception as e:
                logger.debug(f"Auth attempt failed on {r_uri}: {e}")

        return False

    def get_quotes(self, symbols: List[str]) -> Optional[Dict[str, Any]]:
        """Fetch quotes in a single batched call with rate-limit cooldown."""
        if not self.is_configured():
            return None
        # Prime tier cooldown is minimal (2.0s) vs standard tier (60.0s)
        cooldown = 2.0 if getattr(settings, "FYERS_TIER", "PRIME") == "PRIME" else 60.0
        if (time.time() - self.last_rate_limit_time) < cooldown:
            return None
        try:
            res = self.fyers.quotes(data={"symbols": ",".join(symbols)})
            if isinstance(res, dict) and res.get("s") == "ok":
                return res
            if isinstance(res, dict) and res.get("code") in [429, -360]:
                self.last_rate_limit_time = time.time()
                self.last_error = res.get("message")
            return None
        except Exception as e:
            logger.warning(f"Error fetching quotes: {e}")
            return None

    def get_option_chain_raw(self, fyers_symbol: str, strike_count: int = 40) -> Optional[Dict[str, Any]]:
        """Fetch raw option chain from Fyers API with rate-limit cooldown."""
        if not self.is_configured():
            return None
        # Prime tier cooldown is minimal (2.0s) vs standard tier (60.0s)
        cooldown = 2.0 if getattr(settings, "FYERS_TIER", "PRIME") == "PRIME" else 60.0
        if (time.time() - self.last_rate_limit_time) < cooldown:
            return None
        try:
            res = self.fyers.optionchain(data={
                "symbol": fyers_symbol,
                "strikecount": strike_count,
                "timestamp": ""
            })
            if isinstance(res, dict) and res.get("s") == "ok":
                return res
            if isinstance(res, dict) and res.get("code") in [429, -360]:
                self.last_rate_limit_time = time.time()
                self.last_error = res.get("message")
            return None
        except Exception as e:
            logger.warning(f"Error fetching option chain for {fyers_symbol}: {e}")
            return None

fyers_client = FyersClient()
