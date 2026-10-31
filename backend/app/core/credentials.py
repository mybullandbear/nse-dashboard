"""
Centralized Credentials Manager for mybullandbear
Loads API keys, Broker configs, and SSH details from credentials.json, .env, or OS environment.
"""
import os
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

@dataclass
class Credentials:
    groq_api_key: str
    gemini_api_key: str
    ssh_key_path: str
    vm_ip: str
    vm_user: str
    fyers_client_id: str
    fyers_secret_key: str
    fyers_redirect_uri: str
    total_fund: float = 90000.0
    groq_api_keys: List[str] = field(default_factory=list)

    @property
    def groq_key(self) -> str:
        return self.groq_api_key

    @property
    def gemini_key(self) -> str:
        return self.gemini_api_key


def load_credentials() -> Credentials:
    """Loads all credentials with multi-location fallback."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate_paths = [
        os.path.join(base_dir, "credentials.json"),
        os.path.join(base_dir, "..", "credentials.json"),
        os.path.join(os.getcwd(), "credentials.json"),
    ]

    json_data: Dict[str, Any] = {}
    for p in candidate_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    json_data = json.load(f)
                    break
            except Exception:
                pass

    fyers_dict = json_data.get("FYERS", {})

    groq_key = (
        json_data.get("GROQ_API_KEY")
        or os.getenv("GROQ_API_KEY")
        or ""
    )
    gemini_key = (
        json_data.get("GEMINI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or ""
    )
    ssh_path = (
        json_data.get("SSH_KEY_PATH")
        or os.getenv("SSH_KEY_PATH")
        or "_archive/ssh-key-2026-07-30.key"
    )
    vm_ip = (
        json_data.get("VM_IP")
        or os.getenv("VM_HOST")
        or "137.23.42.11"
    )
    vm_user = (
        json_data.get("VM_USER")
        or os.getenv("VM_USER")
        or "ubuntu"
    )
    fyers_client_id = (
        fyers_dict.get("client_id")
        or os.getenv("FYERS_CLIENT_ID")
        or "7BRKBHOFP8-100"
    )
    fyers_secret = (
        fyers_dict.get("secret_key")
        or os.getenv("FYERS_SECRET_KEY")
        or "TO0QPDNH7A"
    )
    fyers_redirect = (
        fyers_dict.get("redirect_uri")
        or os.getenv("FYERS_REDIRECT_URI")
        or "http://137.23.42.11:8000/api/fyers/callback"
    )
    total_fund = float(
        json_data.get("TOTAL_TRADING_CAPITAL")
        or os.getenv("TOTAL_TRADING_CAPITAL")
        or 90000.0
    )
    groq_keys = json_data.get("GROQ_API_KEYS") or [groq_key]

    return Credentials(
        groq_api_key=groq_key,
        gemini_api_key=gemini_key,
        ssh_key_path=ssh_path,
        vm_ip=vm_ip,
        vm_user=vm_user,
        fyers_client_id=fyers_client_id,
        fyers_secret_key=fyers_secret,
        fyers_redirect_uri=fyers_redirect,
        total_fund=total_fund,
        groq_api_keys=groq_keys,
    )

# Global singleton
credentials = load_credentials()


def save_trading_fund(amount: float) -> float:
    """Updates the active trading fund and persists it to credentials.json."""
    global credentials
    amount = float(max(1000.0, amount))
    credentials.total_fund = amount

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate_paths = [
        os.path.join(base_dir, "credentials.json"),
        os.path.join(base_dir, "..", "credentials.json"),
        os.path.join(os.getcwd(), "credentials.json"),
    ]

    for p in candidate_paths:
        try:
            data = {}
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["TOTAL_TRADING_CAPITAL"] = amount
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    return credentials.total_fund
