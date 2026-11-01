"""
Fyers Broker API v3 Integration Service
Handles OAuth 3-legged authentication, session validation, quotes, and option chains.
"""
import json
import logging
import os
import re
from typing import Optional, Dict, Any, Tuple
from app.core.config import get_settings

logger = logging.getLogger(__name__)

try:
    from fyers_apiv3 import fyersModel
    HAS_FYERS = True
except ImportError:
    fyersModel = None
    HAS_FYERS = False


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
    Singleton service managing Fyers v3 API connection, OAuth flow, and market data queries.
    """

    def __init__(self):
        settings = get_settings()
        self.config_path = settings.FYERS_CONFIG_PATH
        self.client_id: Optional[str] = os.environ.get("FYERS_CLIENT_ID") or settings.FYERS_CLIENT_ID
        self.secret_key: Optional[str] = os.environ.get("FYERS_SECRET_KEY") or settings.FYERS_SECRET_KEY
        self.access_token: Optional[str] = clean_token(os.environ.get("FYERS_ACCESS_TOKEN"))
        self.redirect_uri: str = os.environ.get("FYERS_REDIRECT_URI", getattr(settings, "FYERS_REDIRECT_URI", "http://137.23.42.11:8000/api/fyers/callback"))
        self.fyers: Optional[Any] = None
        self.last_error: Optional[str] = None

        self._load_config()
        if self.client_id and self.access_token and HAS_FYERS:
            self._init_client()

    def _load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
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

    def set_credentials(self, client_id: str, secret_key: Optional[str] = None, redirect_uri: Optional[str] = None):
        if client_id and client_id.strip():
            self.client_id = client_id.strip()
        if secret_key and secret_key.strip():
            self.secret_key = secret_key.strip()
        if redirect_uri and redirect_uri.strip():
            self.redirect_uri = redirect_uri.strip()
        self._save_config()

    def set_access_token(self, token: str) -> Tuple[bool, str]:
        cleaned = clean_token(token)
        if not cleaned:
            return False, "Token cannot be empty"
        self.access_token = cleaned
        self._save_config()
        self._init_client()
        return self.validate_connection()

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
            logger.info("Fyers API Client Initialized.")
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Failed to initialize Fyers API client: {e}")

    def is_configured(self) -> bool:
        if not self.access_token:
            self._load_config()
        if self.fyers is None and self.client_id and self.access_token and HAS_FYERS:
            self._init_client()
        return self.fyers is not None and bool(self.access_token)

    def validate_connection(self) -> Tuple[bool, str]:
        """Test Fyers API connection by fetching a live quote for NIFTY."""
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
        """Returns True if response is valid, False if an error occurred."""
        if isinstance(res, dict):
            code = res.get("code")
            msg_orig = str(res.get("message", ""))
            msg = msg_orig.lower()
            s_val = str(res.get("s", "")).lower()

            if s_val == "ok":
                self.last_error = None
                return True

            # True Authentication / Token Expiration errors ONLY:
            # -14: Token missing/invalid, -15: Token expired, -16: Token signature mismatch, 401: Unauthorized
            is_explicit_token_err = (
                (code in [-14, -15, -16, 401]) and
                any(kw in msg for kw in ["token", "expired", "unauthorized", "invalid key", "jwt"])
            )
            if is_explicit_token_err:
                err_msg = msg_orig or f"Authentication error code {code}"
                logger.error(f"Fyers Access Token Expired ({err_msg}). Re-authentication needed.")
                self.last_error = f"Token Expired/Invalid: {err_msg}"
                self.fyers = None
                # NOTE: Never erase access_token from disk config so transient broker glitches don't destroy credentials.
                return False

            # Rate Limit Errors
            if code == -13 or code == 429 or "rate" in msg or "limit" in msg:
                logger.warning(f"Fyers Rate Limit Hit ({code}): {msg_orig}. Session preserved.")
                self.last_error = f"Rate Limit: {msg_orig}"
                return False

            # Transient Network, Connection, or Gateway Errors (-99, -17, connection drops)
            # DO NOT invalidate session! Session and token remain completely intact.
            logger.warning(f"Fyers API transient error ({code}): {msg_orig}. Preserving session.")
            self.last_error = f"Fyers API error ({code}): {msg_orig}"
            return False

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

        auth_code = str(auth_code).strip()
        if "code=" in auth_code or "auth_code=" in auth_code:
            import urllib.parse
            parsed = urllib.parse.urlparse(auth_code)
            params = urllib.parse.parse_qs(parsed.query)
            auth_code = (params.get("auth_code") or params.get("code") or [auth_code])[0]

        candidate_uris = []
        if redirect_uri:
            candidate_uris.append(redirect_uri.strip())
        if self.redirect_uri and self.redirect_uri not in candidate_uris:
            candidate_uris.append(self.redirect_uri.strip())

        preset_uris = [
            "http://137.23.63.209:8000/api/fyers/callback",
            "http://137.23.63.209/api/fyers/callback",
            "http://137.23.63.209:8000/",
            "http://137.23.63.209/",
            "https://trade.fyers.in/api-login/redirect-uri/index.html",
            "http://localhost:8000/api/fyers/callback",
            "http://127.0.0.1:8000/api/fyers/callback",
            "http://137.23.42.11:8000/api/fyers/callback",
            "https://137.23.42.11/api/fyers/callback",
        ]
        for u in preset_uris:
            if u not in candidate_uris:
                candidate_uris.append(u)

        for u in list(candidate_uris):
            if ":8000" in u:
                u_no_port = u.replace(":8000", "")
                if u_no_port not in candidate_uris:
                    candidate_uris.append(u_no_port)
            if u.endswith("/"):
                u_no_slash = u.rstrip("/")
                if u_no_slash not in candidate_uris:
                    candidate_uris.append(u_no_slash)

        for r_uri in candidate_uris:
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
                    self._save_config()
                    self._init_client()
                    logger.info(f"Fyers authentication succeeded with redirect_uri: {r_uri}")
                    return True
                else:
                    logger.debug(f"Auth attempt with {r_uri} returned: {res}")
            except Exception as e:
                logger.debug(f"Exception during auth attempt with {r_uri}: {e}")

        logger.error("All candidate redirect URIs failed for Fyers token exchange.")
        return False

    def get_quotes(self, symbols: list[str]) -> Optional[Dict[str, Any]]:
        if not self.fyers:
            return None
        data = {"symbols": ",".join(symbols)}
        import time
        for attempt in range(2):
            try:
                res = self.fyers.quotes(data=data)
                if not self._handle_api_response(res):
                    if attempt == 0 and isinstance(res, dict) and res.get("code") in [-99, -13]:
                        time.sleep(0.35)
                        continue
                    return None
                return res
            except Exception as e:
                err_str = str(e).lower()
                if attempt == 0 and any(w in err_str for w in ["connection", "remote", "timeout", "aborted", "reset"]):
                    logger.warning(f"Fyers quotes connection drop ({e}), retrying in 350ms...")
                    time.sleep(0.35)
                    continue
                logger.warning(f"Fyers quotes fetch error: {e}")
                return None
        return None

    def get_option_chain(self, symbol: str = "NIFTY") -> Optional[Dict[str, Any]]:
        if not self.fyers:
            return None
        sym_upper = symbol.upper()
        if sym_upper == "NIFTY":
            fyers_symbol = "NSE:NIFTY50-INDEX"
        elif sym_upper == "BANKNIFTY":
            fyers_symbol = "NSE:NIFTYBANK-INDEX"
        elif sym_upper == "FINNIFTY":
            fyers_symbol = "NSE:FINNIFTY-INDEX"
        elif sym_upper == "MIDCPNIFTY":
            fyers_symbol = "NSE:MIDCPNIFTY-INDEX"
        elif sym_upper == "SENSEX":
            fyers_symbol = "BSE:SENSEX-INDEX"
        else:
            fyers_symbol = f"NSE:{sym_upper}-INDEX"

        data = {
            "symbol": fyers_symbol,
            "strikecount": 50,
            "timestamp": ""
        }
        import time
        for attempt in range(2):
            try:
                res = self.fyers.optionchain(data=data)
                if not self._handle_api_response(res):
                    if attempt == 0 and isinstance(res, dict) and res.get("code") in [-99, -13]:
                        time.sleep(0.35)
                        continue
                    return None
                if res and res.get("s") == "ok":
                    return self._transform_fyers_to_standard_format(res, symbol)
            except Exception as e:
                err_str = str(e).lower()
                if attempt == 0 and any(w in err_str for w in ["connection", "remote", "timeout", "aborted", "reset"]):
                    logger.warning(f"Fyers option chain transient drop for {symbol} ({e}), retrying in 350ms...")
                    time.sleep(0.35)
                    continue
                logger.warning(f"Fyers option chain error for {symbol}: {e}")
                return None
        return None

    def _transform_fyers_to_standard_format(self, fyers_res: dict, symbol: str) -> dict:
        data_list = fyers_res.get("data", {}).get("optionsChain", [])
        spot_price = 0.0
        spot_change = 0.0
        spot_pchange = 0.0

        for item in data_list:
            if item.get("strike_price") == -1:
                spot_price = float(item.get("ltp", 0.0))
                spot_change = float(item.get("ltpch", 0.0))
                spot_pchange = float(item.get("ltpchp", 0.0))
                break

        by_strike: dict[float, dict] = {}
        expiry_set = set()

        for item in data_list:
            strike = float(item.get("strike_price", -1))
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

            contract = {
                "strikePrice": strike,
                "expiryDate": expiry_str,
                "lastPrice": float(item.get("ltp", 0.0)),
                "change": float(item.get("ltpch", 0.0)),
                "pChange": float(item.get("ltpchp", 0.0)),
                "openInterest": int(item.get("oi", 0)),
                "changeinOpenInterest": int(item.get("oich", 0)),
                "totalTradedVolume": int(item.get("volume", 0)),
                "impliedVolatility": float(item.get("iv", 0.0)),
                "bidprice": float(item.get("bid", 0.0)),
                "askPrice": float(item.get("ask", 0.0)),
            }

            if opt_type == "CE":
                by_strike[strike]["CE"] = contract
            elif opt_type == "PE":
                by_strike[strike]["PE"] = contract

        records_data = sorted(list(by_strike.values()), key=lambda x: x["strikePrice"])
        exp_list = sorted(list(expiry_set)) if expiry_set else ["CURRENT"]

        return {
            "records": {
                "underlyingValue": spot_price,
                "spot_change": spot_change,
                "spot_pchange": spot_pchange,
                "expiryDates": exp_list,
                "data": records_data,
            },
            "filtered": {
                "data": records_data
            }
        }

    def _parse_fyers_expiry(self, symbol_str: str, underlying: str = "NIFTY") -> str:
        """Parse Fyers option symbol into standard DD-MMM-YYYY format."""
        import calendar
        sym = symbol_str.split(":")[-1]
        m = re.match(r"^([A-Z]+)(\d{2})([A-Z]{3}|[1-9]|10|11|12|[OND])(.*)(CE|PE)$", sym)
        if not m:
            return "CURRENT"

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
                mmm = inv_month_map.get(month, "SEP")
            except ValueError:
                month, mmm = 9, "SEP"

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
            # Last Thursday / Tuesday
            cal = calendar.monthcalendar(year, month)
            for week in reversed(cal):
                if week[3] != 0: # Thursday
                    day = week[3]
                    break
            if not day:
                day = 28

        return f"{day:02d}-{mmm.capitalize()}-{year}"

    def get_positions(self) -> Dict[str, Any]:
        """
        Fetches live positions directly from Fyers broker API.
        Extracts real-time unrealized and realized P&L, buy average, and net quantity.
        Zero theoretical estimation.
        """
        if not self.fyers:
            return {"s": "error", "message": "Fyers client not configured or logged in", "netPositions": [], "overall": {}}
        try:
            res = self.fyers.positions()
            if self._handle_api_response(res) and isinstance(res, dict):
                return {
                    "s": "ok",
                    "netPositions": res.get("netPositions", []),
                    "overall": res.get("overall", {}),
                    "code": res.get("code", 200),
                    "message": res.get("message", "")
                }
            return {"s": "error", "message": self.last_error or "Failed to fetch positions", "netPositions": [], "overall": {}}
        except Exception as e:
            logger.error(f"Fyers get_positions exception: {e}")
            return {"s": "error", "message": str(e), "netPositions": [], "overall": {}}

    def get_funds(self) -> Dict[str, Any]:
        """
        Fetches account margin and available trading balance directly from Fyers broker API.
        """
        if not self.fyers:
            return {"s": "error", "message": "Fyers client not configured", "available_balance": 0.0, "total_balance": 0.0}
        try:
            res = self.fyers.funds()
            if self._handle_api_response(res) and isinstance(res, dict):
                limits = res.get("fund_limit", [])
                avail = 0.0
                total = 0.0
                for item in limits:
                    title = str(item.get("title", "")).lower()
                    amt = float(item.get("equityAmount", 0.0))
                    if "available" in title or item.get("id") == 10:
                        avail = amt
                    elif "total" in title or item.get("id") == 1:
                        total = amt
                return {
                    "s": "ok",
                    "available_balance": avail,
                    "total_balance": total,
                    "raw": limits
                }
            return {"s": "error", "message": self.last_error or "Failed to fetch funds", "available_balance": 0.0, "total_balance": 0.0}
        except Exception as e:
            logger.error(f"Fyers get_funds exception: {e}")
            return {"s": "error", "message": str(e), "available_balance": 0.0, "total_balance": 0.0}

    def place_order(
        self,
        symbol: str,
        qty: int,
        side: int,  # 1: BUY, -1: SELL
        order_type: int = 2,  # 1: LIMIT, 2: MARKET, 3: STOP (SL-M), 4: STOPLIMIT (SL-L)
        product_type: str = "INTRADAY",  # "INTRADAY" or "MARGIN"
        limit_price: float = 0.0,
        stop_price: float = 0.0,
        stop_loss: float = 0.0,
        take_profit: float = 0.0
    ) -> Dict[str, Any]:
        """
        Submits an order to Fyers exchange gateway.
        """
        if not self.fyers:
            return {"s": "error", "message": "Fyers client not configured or token expired"}
        
        data = {
            "symbol": symbol,
            "qty": int(qty),
            "type": int(order_type),
            "side": int(side),
            "productType": str(product_type).upper(),
            "limitPrice": float(limit_price or 0.0),
            "stopPrice": float(stop_price or 0.0),
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
            "stopLoss": float(stop_loss or 0.0),
            "takeProfit": float(take_profit or 0.0)
        }
        try:
            logger.info(f"Submitting Fyers order: {data}")
            res = self.fyers.place_order(data=data)
            self._handle_api_response(res)
            return res if isinstance(res, dict) else {"s": "error", "message": str(res)}
        except Exception as e:
            logger.error(f"Fyers place_order exception: {e}")
            return {"s": "error", "message": str(e)}

    def exit_position(self, position_id: str, symbol: Optional[str] = None, qty: Optional[int] = None, side: Optional[int] = None) -> Dict[str, Any]:
        """
        Squares off an open position in Fyers using position ID or market counter-order.
        """
        if not self.fyers:
            return {"s": "error", "message": "Fyers client not configured"}
        
        # 1. Try native exit_position API
        try:
            data = {"id": position_id}
            res = self.fyers.exit_position(data=data)
            if isinstance(res, dict) and res.get("s") == "ok":
                return res
        except Exception as e:
            logger.warning(f"Native exit_position failed ({e}), attempting market square-off...")

        # 2. Fallback: Place counter market order
        if symbol and qty and qty > 0 and side is not None:
            counter_side = -1 if side == 1 else 1
            return self.place_order(symbol=symbol, qty=qty, side=counter_side, order_type=2, product_type="INTRADAY")
        
        return {"s": "error", "message": "Failed to exit position"}

    def exit_all_positions(self) -> Dict[str, Any]:
        """
        Emergency Square Off All open positions in Fyers account.
        """
        pos_data = self.get_positions()
        net_pos = pos_data.get("netPositions", [])
        results = []
        for p in net_pos:
            net_qty = int(p.get("netQty", 0))
            if net_qty != 0:
                pid = p.get("id") or p.get("symbol")
                sym = p.get("symbol")
                side = 1 if net_qty > 0 else -1
                res = self.exit_position(position_id=pid, symbol=sym, qty=abs(net_qty), side=side)
                results.append({"symbol": sym, "qty": net_qty, "result": res})
        return {"s": "ok", "exited": results, "count": len(results)}

    def resolve_option_symbol(self, symbol: str, strike: float, option_type: str) -> Optional[str]:
        """
        Resolves the exact Fyers contract symbol for an index strike and option type (CE/PE)
        by inspecting the live option chain.
        """
        try:
            if not self.fyers:
                return None
            sym_upper = symbol.upper()
            if sym_upper == "NIFTY":
                fyers_idx = "NSE:NIFTY50-INDEX"
            elif sym_upper == "BANKNIFTY":
                fyers_idx = "NSE:NIFTYBANK-INDEX"
            elif sym_upper == "FINNIFTY":
                fyers_idx = "NSE:FINNIFTY-INDEX"
            elif sym_upper == "MIDCPNIFTY":
                fyers_idx = "NSE:MIDCPNIFTY-INDEX"
            elif sym_upper == "SENSEX":
                fyers_idx = "BSE:SENSEX-INDEX"
            else:
                fyers_idx = f"NSE:{sym_upper}-INDEX"

            res = self.fyers.optionchain(data={"symbol": fyers_idx, "strikecount": 40, "timestamp": ""})
            if res and res.get("s") == "ok":
                chain_list = res.get("data", {}).get("optionsChain", [])
                opt_t = option_type.upper()
                for c in chain_list:
                    if float(c.get("strike_price", 0)) == float(strike) and c.get("option_type") == opt_t:
                        return c.get("symbol")
        except Exception as e:
            logger.warning(f"Error resolving option symbol for {symbol} {strike} {option_type}: {e}")
        return None


fyers_service = FyersService()
