"""
Fyers API v3 Fetcher & Auto-Authentication Service.
"""
import json
import logging
import os
import re
from typing import Optional, Dict, Any

try:
    from fyers_apiv3 import fyersModel
    HAS_FYERS = True
except ImportError:
    fyersModel = None
    HAS_FYERS = False

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "fyers_config.json")
REDIRECT_URI = "http://localhost:8000/api/fyers/callback"


def clean_token(token: Optional[str]) -> Optional[str]:
    """Sanitize access token by removing whitespace, quotes, Bearer prefix, or prepended client_id."""
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


class FyersService:
    """
    Fyers Broker API v3 Client with Auto-OAuth Authentication & Persistence.
    """

    def __init__(self):
        self.client_id: Optional[str] = os.environ.get("FYERS_CLIENT_ID")
        self.secret_key: Optional[str] = os.environ.get("FYERS_SECRET_KEY")
        self.access_token: Optional[str] = clean_token(os.environ.get("FYERS_ACCESS_TOKEN"))
        self.redirect_uri: str = os.environ.get("FYERS_REDIRECT_URI", "http://137.23.42.11:8000/api/fyers/callback")
        self.fyers: Optional[Any] = None
        self.last_error: Optional[str] = None

        self._load_saved_config()
        if self.client_id and self.access_token and HAS_FYERS:
            self._init_client()

    def _load_saved_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    self.client_id = data.get("client_id") or self.client_id
                    self.secret_key = data.get("secret_key") or self.secret_key
                    self.redirect_uri = data.get("redirect_uri") or self.redirect_uri
                    raw_token = data.get("access_token") or self.access_token
                    self.access_token = clean_token(raw_token)
            except Exception as e:
                logger.warning(f"Error loading fyers_config.json: {e}")

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({
                    "client_id": self.client_id,
                    "secret_key": self.secret_key,
                    "redirect_uri": self.redirect_uri,
                    "access_token": self.access_token
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving fyers_config.json: {e}")

    def set_credentials(self, client_id: str, secret_key: Optional[str] = None, redirect_uri: Optional[str] = None):
        if client_id and client_id.strip():
            self.client_id = client_id.strip()
        if secret_key and secret_key.strip():
            self.secret_key = secret_key.strip()
        if redirect_uri and redirect_uri.strip():
            self.redirect_uri = redirect_uri.strip()
        self._save_config()

    def _init_client(self):
        self.access_token = clean_token(self.access_token)
        if not HAS_FYERS or not self.client_id or not self.access_token:
            return
        try:
            self.fyers = fyersModel.FyersModel(
                client_id=self.client_id,
                token=self.access_token,
                is_async=False,
                log_path=""
            )
            logger.info("Fyers API Client Initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Fyers API client: {e}")

    def is_configured(self) -> bool:
        if self.fyers is None and self.client_id and self.access_token and HAS_FYERS:
            self._init_client()
        return self.fyers is not None and bool(self.access_token)

    def validate_connection(self) -> tuple[bool, str]:
        """Test Fyers API connection by fetching a live quote."""
        if not self.is_configured():
            return False, "Fyers credentials or access token missing."
        try:
            res = self.get_quotes(['NSE:NIFTY50-INDEX'])
            if res and res.get("s") == "ok" and res.get("d"):
                self.last_error = None
                return True, "Fyers API Connection Active & Verified!"
            err = self.last_error or (res.get("message") if isinstance(res, dict) else None) or "Failed to fetch quotes from Fyers API."
            return False, err
        except Exception as e:
            return False, f"Connection test failed: {e}"

    def _handle_api_response(self, res: Any) -> bool:
        """Returns True if response is valid, False if token error or rate limit occurred."""
        if isinstance(res, dict):
            code = res.get("code")
            msg_orig = str(res.get("message", ""))
            msg = msg_orig.lower()
            s_val = str(res.get("s", "")).lower()

            is_token_err = (
                code in [-14, -15, -16, -17, -99, 401, 403] or
                any(kw in msg for kw in ["token", "invalid key", "unauthorized", "session expired", "jwt"])
            )
            if is_token_err and s_val != "ok":
                err_msg = msg_orig or f"Authentication error code {code}"
                logger.error(f"Fyers Access Token Invalid/Expired ({err_msg}). Invalidating session.")
                self.last_error = f"Token Expired/Invalid: {err_msg}"
                self.fyers = None
                self.access_token = None
                self._save_config()
                return False
            elif code == -13 or "rate" in msg or "limit" in msg or code == 429:
                logger.warning(f"Fyers API Rate Limit hit ({msg_orig}). Backing off briefly.")
                self.last_error = f"Rate Limit: {msg_orig}"
                return False
            elif s_val != "ok" and not res.get("d") and not res.get("data"):
                self.last_error = msg_orig or f"Fyers API error ({s_val})"
                return False

            self.last_error = None
        return True

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
        r_uri = redirect_uri or self.redirect_uri
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
                self._save_config()
                self._init_client()
                return True
            else:
                logger.error(f"Fyers token generation failed: {res}")
        except Exception as e:
            logger.error(f"Exception during Fyers authentication: {e}")
        return False

    def get_quotes(self, symbols: list[str]) -> Optional[Dict[str, Any]]:
        if not self.fyers:
            return None
        try:
            data = {"symbols": ",".join(symbols)}
            res = self.fyers.quotes(data=data)
            if not self._handle_api_response(res):
                return None
            return res
        except Exception as e:
            logger.error(f"Fyers quotes fetch error: {e}")
            return None

    def get_option_chain(self, symbol: str = "NIFTY", stype: str = "INDEX") -> Optional[Dict[str, Any]]:
        if not self.fyers:
            return None
        try:
            sym_upper = symbol.upper()
            if sym_upper == "NIFTY":
                fyers_symbol = "NSE:NIFTY50-INDEX"
            elif sym_upper == "BANKNIFTY":
                fyers_symbol = "NSE:NIFTYBANK-INDEX"
            elif sym_upper == "FINNIFTY":
                fyers_symbol = "NSE:FINNIFTY-INDEX"
            elif sym_upper == "MIDCPNIFTY":
                fyers_symbol = "NSE:MIDCPNIFTY-INDEX"
            elif stype == "INDEX":
                fyers_symbol = f"NSE:{sym_upper}-INDEX"
            else:
                fyers_symbol = f"NSE:{sym_upper}-EQ"

            data = {
                "symbol": fyers_symbol,
                "strikecount": 50,
                "timestamp": ""
            }
            res = self.fyers.optionchain(data=data)
            if not self._handle_api_response(res):
                return None
            if res and res.get("s") == "ok":
                return self._transform_fyers_to_nse_format(res, symbol, spot_price=0)
        except Exception as e:
            logger.error(f"Fyers option chain error: {e}")
        return None


    def _parse_fyers_expiry(self, symbol_str: str, underlying: str = "NIFTY") -> str:
        """
        Parse Fyers option symbol (e.g. 'NSE:NIFTY26JUL24000CE', 'NSE:FINNIFTY26JUL2823400CE')
        into standardized NSE format 'DD-MMM-YYYY' (e.g. '30-Jul-2026').
        Fyers uses 26 for year 2026, which was previously misidentified as day 26.
        """
        import calendar
        sym = symbol_str.split(":")[-1]
        m = re.match(r"^([A-Z]+)(\d{2})([A-Z]{3}|[1-9]|10|11|12|[OND])(.*)(CE|PE)$", sym)
        if not m:
            return "30-Jul-2026"

        month_map = {"JAN":1, "FEB":2, "MAR":3, "APR":4, "MAY":5, "JUN":6, "JUL":7, "AUG":8, "SEP":9, "OCT":10, "NOV":11, "DEC":12}
        inv_month_map = {v: k for k, v in month_map.items()}

        und, yy_str, m_str, rest, opt_type = m.groups()
        year = 2000 + int(yy_str)

        if m_str in month_map:
            month = month_map[m_str]
            mmm = m_str
        elif m_str == 'O': month, mmm = 10, 'OCT'
        elif m_str == 'N': month, mmm = 11, 'NOV'
        elif m_str == 'D': month, mmm = 12, 'DEC'
        else:
            try:
                month = int(m_str)
                mmm = inv_month_map.get(month, "JUL")
            except ValueError:
                month, mmm = 7, "JUL"

        day = None
        if len(rest) >= 6:
            try:
                possible_dd = int(rest[:2])
                possible_strike = float(rest[2:])
                if 1 <= possible_dd <= 31 and possible_strike > 100:
                    day = possible_dd
            except ValueError:
                pass

        if day is None:
            # Monthly expiry: last Tuesday of the month for all symbols per user specification
            target_wday = 1  # Tuesday
            cal = calendar.monthcalendar(year, month)
            for week in reversed(cal):
                if week[target_wday] != 0:
                    day = week[target_wday]
                    break
            if not day:
                day = 28

        return f"{day:02d}-{mmm.capitalize()}-{year}"

    def _transform_fyers_to_nse_format(self, fyers_res: dict, symbol: str, spot_price: float = 0) -> dict:
        data_list = fyers_res.get("data", {}).get("optionsChain", [])

        if not spot_price and data_list:
            for item in data_list:
                if item.get("strike_price") == -1:
                    spot_price = item.get("ltp", 0)
                    break

        expiry_set = set()
        by_strike: dict[float, dict] = {}

        for item in data_list:
            strike = item.get("strike_price", -1)
            if strike <= 0:
                continue

            opt_type = item.get("option_type", "")
            raw_sym = item.get("symbol", "")
            expiry_str = item.get("expiry") or ""

            if not expiry_str or len(expiry_str) < 5:
                expiry_str = self._parse_fyers_expiry(raw_sym, symbol)

            if expiry_str:
                expiry_set.add(expiry_str)

            if strike not in by_strike:
                by_strike[strike] = {
                    "strikePrice": strike,
                    "expiryDate": expiry_str,
                    "CE": {},
                    "PE": {}
                }

            contract_dict = {
                "strikePrice": strike,
                "expiryDate": expiry_str,
                "lastPrice": item.get("ltp", 0),
                "change": item.get("ltpch", 0),
                "pChange": item.get("ltpchp", 0),
                "openInterest": item.get("oi", 0),
                "changeinOpenInterest": item.get("oich", 0),
                "totalTradedVolume": item.get("volume", 0),
                "impliedVolatility": item.get("iv", 0),
                "bidprice": item.get("bid", 0),
                "askPrice": item.get("ask", 0),
            }

            if opt_type == "CE":
                by_strike[strike]["CE"] = contract_dict
            elif opt_type == "PE":
                by_strike[strike]["PE"] = contract_dict

        records_data = list(by_strike.values())
        exp_list = sorted(list(expiry_set)) if expiry_set else ["30-Jul-2026"]

        return {
            "records": {
                "underlyingValue": spot_price,
                "expiryDates": exp_list,
                "data": records_data,
            },
            "filtered": {
                "data": records_data
            }
        }


fyers_service = FyersService()
