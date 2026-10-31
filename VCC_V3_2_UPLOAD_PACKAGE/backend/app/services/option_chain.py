"""
Option Chain Processing & Authoritative ATM Engine Service

Parses NSE / Provider option chain data and computes:
- Authoritative ATM strike (preferring available chain, half-up rounding, stock step resolution)
- Data Quality Validation (NO_VALID_DATA enforcement)
- PCR (multiple variants)
- Max Pain
- OI-based Support/Resistance
- Greeks estimation (Black-Scholes with pure math fallback)
- OI Interpretation (Fresh Long/Short, Covering, Unwinding)
"""
import logging
import math
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any

from app.schemas import (
    OptionChainResponse,
    OptionStrikeData,
    OptionGreeks,
    PCRData,
    SupportResistance,
)

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.07  # ~7% Indian risk-free rate
TRADING_DAYS_PER_YEAR = 252

# Canonical Index Strike Intervals
INDEX_STRIKE_STEPS: Dict[str, float] = {
    "NIFTY": 50.0,
    "BANKNIFTY": 100.0,
    "FINNIFTY": 50.0,
    "MIDCPNIFTY": 50.0,
    "SENSEX": 100.0,
}


def resolve_strike_step(
    symbol: str,
    available_strikes: Optional[List[float]] = None,
    configured_step: Optional[float] = None
) -> Tuple[float, str]:
    """
    Resolves strike step for index or stock options.
    If available_strikes has >= 2 strikes, derives step directly from option chain.
    """
    sym_upper = symbol.upper()

    # 1. Derive from actual option chain if available
    if available_strikes and len(available_strikes) >= 2:
        valid_strikes = sorted(list(set([float(s) for s in available_strikes if s is not None and isinstance(s, (int, float)) and s > 0])))
        if len(valid_strikes) >= 2:
            diffs = [round(valid_strikes[i+1] - valid_strikes[i], 4) for i in range(len(valid_strikes)-1)]
            pos_diffs = [d for d in diffs if d > 0]
            if pos_diffs:
                derived_step = min(pos_diffs)
                return float(derived_step), "CHAIN_DERIVED"

    # 2. Configured or Index config lookup
    if configured_step and configured_step > 0:
        return float(configured_step), "CONFIGURED"

    for idx_key, step_val in INDEX_STRIKE_STEPS.items():
        if idx_key in sym_upper:
            return step_val, "INDEX_CONFIG"

    return 50.0, "DEFAULT_FALLBACK"


def calculate_atm_strike(
    spot_price: float,
    available_strikes: Optional[List[float]] = None,
    symbol: str = "NIFTY",
    configured_step: Optional[float] = None
) -> Tuple[float, str, float, str]:
    """
    Authoritative ATM Strike Calculation Engine.
    Prefers nearest valid available strike from option chain.
    Uses deterministic half-up rounding (upper strike preference for midpoints).

    Returns tuple: (atm_strike, atm_source, strike_step, strike_step_source)
    """
    if spot_price is None or not isinstance(spot_price, (int, float)) or math.isnan(spot_price) or spot_price <= 0:
        return (0.0, "INVALID_SPOT", 0.0, "NONE")

    spot = float(spot_price)
    strike_step, strike_step_source = resolve_strike_step(symbol, available_strikes, configured_step)

    # Filter & deduplicate valid available strikes
    clean_strikes = []
    if available_strikes:
        clean_strikes = sorted(list(set([float(s) for s in available_strikes if s is not None and isinstance(s, (int, float)) and not math.isnan(s) and s > 0])))

    if clean_strikes:
        # Case A: Exact match
        for s in clean_strikes:
            if abs(s - spot) < 1e-6:
                return (s, "EXACT_MATCH", strike_step, strike_step_source)

        # Case B: Out of bounds low
        if spot < clean_strikes[0]:
            return (clean_strikes[0], "AVAILABLE_CHAIN_OUT_OF_BOUNDS_LOW", strike_step, strike_step_source)

        # Case C: Out of bounds high
        if spot > clean_strikes[-1]:
            return (clean_strikes[-1], "AVAILABLE_CHAIN_OUT_OF_BOUNDS_HIGH", strike_step, strike_step_source)

        # Case D: Between two available strikes
        for i in range(len(clean_strikes) - 1):
            s_low = clean_strikes[i]
            s_high = clean_strikes[i + 1]
            if s_low < spot < s_high:
                d_low = spot - s_low
                d_high = s_high - spot
                if abs(d_low - d_high) < 1e-6:
                    # Midpoint case: Half-up / upper strike preference
                    return (s_high, "AVAILABLE_CHAIN_MIDPOINT_UPPER", strike_step, strike_step_source)
                elif d_low < d_high:
                    return (s_low, "AVAILABLE_CHAIN_NEAREST", strike_step, strike_step_source)
                else:
                    return (s_high, "AVAILABLE_CHAIN_NEAREST", strike_step, strike_step_source)

        # Fallback nearest
        best_strike = min(clean_strikes, key=lambda x: abs(x - spot))
        return (best_strike, "AVAILABLE_CHAIN_NEAREST", strike_step, strike_step_source)

    # Case E: Theoretical Grid Fallback (No chain available)
    step = strike_step if strike_step > 0 else 50.0
    k = math.floor((spot / step) + 0.5)
    atm_grid = float(k * step)
    return (atm_grid, "THEORETICAL_GRID", step, strike_step_source)


def validate_option_chain(
    spot_price: float,
    spot_timestamp: Optional[str],
    strikes: List[Any]
) -> Tuple[bool, str]:
    """
    Validates Option Chain completeness and data integrity.
    If spot is missing, strikes empty, LTP missing/invalid, or OI missing/invalid:
    Returns (False, "NO_VALID_DATA: <reason>")
    """
    if spot_price is None or not isinstance(spot_price, (int, float)) or math.isnan(spot_price) or spot_price <= 0:
        return (False, "NO_VALID_DATA: Missing or non-positive spot price")

    if not spot_timestamp:
        return (False, "NO_VALID_DATA: Missing spot timestamp")

    if not strikes:
        return (False, "NO_VALID_DATA: Empty option strikes matrix")

    valid_contracts = 0
    for s in strikes:
        strike_val = getattr(s, "strike_price", None) if not isinstance(s, dict) else (s.get("strike_price") if "strike_price" in s else s.get("strikePrice"))
        if strike_val is None or not isinstance(strike_val, (int, float)) or math.isnan(strike_val) or strike_val <= 0:
            continue

        ce = getattr(s, "ce_tick", None) if not isinstance(s, dict) else s.get("CE", s.get("ce_tick"))
        pe = getattr(s, "pe_tick", None) if not isinstance(s, dict) else s.get("PE", s.get("pe_tick"))

        def is_valid_num(v):
            if v is None:
                return False
            if isinstance(v, (int, float)) and not math.isnan(v) and v >= 0:
                return True
            return False

        def get_val(obj, attr1, attr2):
            if not obj:
                return None
            if not isinstance(obj, dict):
                return getattr(obj, attr1, None)
            v = obj.get(attr1)
            if v is not None:
                return v
            return obj.get(attr2)

        ce_ltp = get_val(ce, "ltp", "lastPrice")
        pe_ltp = get_val(pe, "ltp", "lastPrice")
        ce_oi = get_val(ce, "oi", "openInterest")
        pe_oi = get_val(pe, "oi", "openInterest")

        if is_valid_num(ce_ltp) and is_valid_num(pe_ltp) and is_valid_num(ce_oi) and is_valid_num(pe_oi):
            valid_contracts += 1

    if valid_contracts == 0:
        return (False, "NO_VALID_DATA: All contracts missing valid LTP or OI")

    return (True, "VALID_CHAIN")


def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _round_to_strike(price: float, step: float = 50) -> float:
    atm_strike, _, _, _ = calculate_atm_strike(price, symbol="NIFTY", configured_step=step)
    return atm_strike


def _days_to_expiry(expiry_str: str) -> float:
    """Calculate calendar days to expiry. Uses 365-day convention consistent with T = days/365."""
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d%b%Y", "%d-%b-%y"):
        try:
            expiry = datetime.strptime(expiry_str.strip(), fmt)
            now = datetime.now()
            delta_seconds = (expiry - now).total_seconds()
            return max(delta_seconds / 86400.0, 0.001)
        except Exception:
            continue
    return 1.0


def _estimate_greeks(
    spot: float,
    strike: float,
    days: float,
    iv: float,
    option_type: str = "CE",
) -> OptionGreeks:
    if iv <= 0 or days <= 0 or spot <= 0:
        return OptionGreeks()

    T = days / 365.0
    sigma = iv / 100.0
    r = RISK_FREE_RATE

    try:
        d1 = (math.log(spot / strike) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        if option_type == "CE":
            delta = _norm_cdf(d1)
            theta = (-(spot * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
                     - r * strike * math.exp(-r * T) * _norm_cdf(d2)) / TRADING_DAYS_PER_YEAR
        else:
            delta = _norm_cdf(d1) - 1
            theta = (-(spot * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
                     + r * strike * math.exp(-r * T) * _norm_cdf(-d2)) / TRADING_DAYS_PER_YEAR

        gamma = _norm_pdf(d1) / (spot * sigma * math.sqrt(T))
        vega = spot * _norm_pdf(d1) * math.sqrt(T) / 100

        return OptionGreeks(
            delta=round(delta, 4),
            theta=round(theta, 2),
            gamma=round(gamma, 6),
            vega=round(vega, 2),
            iv=round(iv, 2),
        )
    except Exception:
        return OptionGreeks(iv=round(iv, 2))


def _classify_oi(price_change: float, oi_change: float) -> str:
    if price_change > 0 and oi_change > 0:
        return "Fresh Long"
    elif price_change < 0 and oi_change > 0:
        return "Fresh Short"
    elif price_change > 0 and oi_change < 0:
        return "Short Covering"
    elif price_change < 0 and oi_change < 0:
        return "Long Unwinding"
    return "No Change"


def parse_option_chain(raw: dict, symbol: str = "NIFTY", target_expiry: Optional[str] = None) -> Optional[OptionChainResponse]:
    try:
        records = raw.get("records", {})
        filtered = raw.get("filtered", {})

        spot_price = float(records.get("underlyingValue", 0) or 0.0)
        expiry_list = records.get("expiryDates", [])
        data = filtered.get("data", records.get("data", []))

        now_iso = datetime.now().isoformat()

        # Extract available strikes
        raw_strikes = []
        for r in data:
            st = r.get("strikePrice")
            if st and isinstance(st, (int, float)) and st > 0:
                raw_strikes.append(float(st))

        # Calculate Authoritative ATM Strike & Telemetry
        atm_strike, atm_source, strike_step, strike_step_source = calculate_atm_strike(
            spot_price=spot_price,
            available_strikes=raw_strikes,
            symbol=symbol
        )

        # Validate Option Chain Data Integrity
        is_valid, validation_status = validate_option_chain(spot_price, now_iso, data)
        if not is_valid:
            logger.warning(f"Option chain validation failed for {symbol}: {validation_status}")
            return None

        # Expiry Selection Logic
        selected_expiry = target_expiry
        if not selected_expiry and expiry_list:
            tuesday_exps = []
            for exp_str in expiry_list:
                for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d%b%Y"):
                    try:
                        exp_dt = datetime.strptime(exp_str.strip(), fmt)
                        if exp_dt.weekday() == 1:
                            tuesday_exps.append(exp_str)
                            break
                    except Exception:
                        continue
            selected_expiry = tuesday_exps[0] if tuesday_exps else expiry_list[0]

        current_expiry = selected_expiry or (data[0].get("expiryDate", "") if data else "")

        prev_close = float(records.get("previousClose", 0) or records.get("prevClose", 0) or 0.0)
        underlying_change = spot_price - prev_close if prev_close > 0 else 0.0

        strikes_map: Dict[float, OptionStrikeData] = {}
        total_ce_oi = 0
        total_pe_oi = 0
        days = _days_to_expiry(current_expiry)

        for row in data:
            row_exp = row.get("expiryDate") or row.get("CE", {}).get("expiryDate") or row.get("PE", {}).get("expiryDate")
            if current_expiry and row_exp and row_exp != current_expiry:
                continue

            strike_price = float(row.get("strikePrice", 0) or 0.0)
            if not strike_price:
                continue

            ce = row.get("CE", {})
            pe = row.get("PE", {})

            ce_iv = float(ce.get("impliedVolatility", 0) or 0.0) if ce else 0.0
            ce_greeks = _estimate_greeks(spot_price, strike_price, days, ce_iv, "CE") if ce else OptionGreeks()

            pe_iv = float(pe.get("impliedVolatility", 0) or 0.0) if pe else 0.0
            pe_greeks = _estimate_greeks(spot_price, strike_price, days, pe_iv, "PE") if pe else OptionGreeks()

            ce_oi = int(ce.get("openInterest", 0) or 0) if ce else 0
            pe_oi = int(pe.get("openInterest", 0) or 0) if pe else 0
            ce_oi_chg = int(ce.get("changeinOpenInterest", 0) or 0) if ce else 0
            pe_oi_chg = int(pe.get("changeinOpenInterest", 0) or 0) if pe else 0

            total_ce_oi += ce_oi
            total_pe_oi += pe_oi

            strike_data = OptionStrikeData(
                strike_price=strike_price,
                expiry=current_expiry,
                ce_ltp=float(ce.get("lastPrice", 0) or 0.0) if ce else 0.0,
                ce_oi=ce_oi,
                ce_oi_change=ce_oi_chg,
                ce_volume=int(ce.get("totalTradedVolume", 0) or 0) if ce else 0,
                ce_iv=ce_iv,
                ce_bid=float(ce.get("bidprice", 0) or 0.0) if ce else 0.0,
                ce_ask=float(ce.get("askPrice", 0) or 0.0) if ce else 0.0,
                ce_greeks=ce_greeks,
                pe_ltp=float(pe.get("lastPrice", 0) or 0.0) if pe else 0.0,
                pe_oi=pe_oi,
                pe_oi_change=pe_oi_chg,
                pe_volume=int(pe.get("totalTradedVolume", 0) or 0) if pe else 0,
                pe_iv=pe_iv,
                pe_bid=float(pe.get("bidprice", 0) or 0.0) if pe else 0.0,
                pe_ask=float(pe.get("askPrice", 0) or 0.0) if pe else 0.0,
                pe_greeks=pe_greeks,
                oi_interpretation_ce=_classify_oi(underlying_change, ce_oi_chg),
                oi_interpretation_pe=_classify_oi(underlying_change, pe_oi_chg),
            )
            strikes_map[strike_price] = strike_data

        all_sorted_strikes = sorted(list(strikes_map.values()), key=lambda x: x.strike_price)

        atm_idx = 0
        min_diff = float("inf")
        for idx, s in enumerate(all_sorted_strikes):
            diff = abs(s.strike_price - atm_strike)
            if diff < min_diff:
                min_diff = diff
                atm_idx = idx

        start_idx = max(0, atm_idx - 25)
        end_idx = min(len(all_sorted_strikes), atm_idx + 26)
        strikes = all_sorted_strikes[start_idx:end_idx]

        pcr = round(total_pe_oi / total_ce_oi, 4) if total_ce_oi > 0 else 0.0
        max_pain = _calculate_max_pain(all_sorted_strikes, spot_price)

        return OptionChainResponse(
            symbol=symbol,
            expiry=current_expiry,
            spot_price=spot_price,
            atm_strike=atm_strike,
            strikes=strikes,
            all_strikes=all_sorted_strikes,
            pcr=pcr,
            max_pain=max_pain,
            timestamp=now_iso,
            expiry_list=expiry_list,
        )

    except Exception as e:
        logger.error(f"Error parsing option chain: {e}")
        return None


def _calculate_max_pain(strikes: List[OptionStrikeData], spot: float) -> float:
    if not strikes:
        return 0.0

    min_pain = float("inf")
    max_pain_strike = spot

    for test_strike_data in strikes:
        test_strike = test_strike_data.strike_price
        total_pain = 0.0

        for s in strikes:
            ce_intrinsic = max(0.0, test_strike - s.strike_price)
            total_pain += ce_intrinsic * s.ce_oi
            pe_intrinsic = max(0.0, s.strike_price - test_strike)
            total_pain += pe_intrinsic * s.pe_oi

        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = test_strike

    return max_pain_strike


def compute_pcr_variants(
    strikes: List[OptionStrikeData],
    atm_strike: float,
    strike_step: float = 50.0,
) -> PCRData:
    total_ce_oi = sum(s.ce_oi for s in strikes)
    total_pe_oi = sum(s.pe_oi for s in strikes)

    overall = round(total_pe_oi / total_ce_oi, 4) if total_ce_oi > 0 else 0.0

    atm_ce = sum(s.ce_oi for s in strikes if s.strike_price == atm_strike)
    atm_pe = sum(s.pe_oi for s in strikes if s.strike_price == atm_strike)
    atm_pcr = round(atm_pe / atm_ce, 4) if atm_ce > 0 else 0.0

    near_5 = [s for s in strikes if abs(s.strike_price - atm_strike) <= 5 * strike_step]
    ce_5 = sum(s.ce_oi for s in near_5)
    pe_5 = sum(s.pe_oi for s in near_5)
    pcr_5 = round(pe_5 / ce_5, 4) if ce_5 > 0 else 0.0

    near_10 = [s for s in strikes if abs(s.strike_price - atm_strike) <= 10 * strike_step]
    ce_10 = sum(s.ce_oi for s in near_10)
    pe_10 = sum(s.pe_oi for s in near_10)
    pcr_10 = round(pe_10 / ce_10, 4) if ce_10 > 0 else 0.0

    weighted_ce = sum(s.ce_oi * s.ce_volume for s in strikes)
    weighted_pe = sum(s.pe_oi * s.pe_volume for s in strikes)
    weighted = round(weighted_pe / weighted_ce, 4) if weighted_ce > 0 else 0.0

    interpretation, color = _pcr_interpretation(overall)

    return PCRData(
        overall=overall,
        atm=atm_pcr,
        five_strike=pcr_5,
        ten_strike=pcr_10,
        weighted=weighted,
        interpretation=interpretation,
        color=color,
        timestamp=datetime.now().isoformat(),
    )


def _pcr_interpretation(pcr: float) -> Tuple[str, str]:
    if pcr < 0.6:
        return "Extreme Bearish", "#ef4444"
    elif pcr < 0.8:
        return "Bearish", "#f97316"
    elif pcr < 1.0:
        return "Neutral", "#eab308"
    elif pcr < 1.2:
        return "Bullish", "#22c55e"
    else:
        return "Extreme Bullish", "#10b981"


def compute_support_resistance(
    strikes: List[OptionStrikeData],
    spot: float,
    top_n: int = 5,
) -> Tuple[List[SupportResistance], List[SupportResistance]]:
    pe_strikes = [(s.strike_price, s.pe_oi, s.pe_oi_change) for s in strikes if s.strike_price <= spot]
    ce_strikes = [(s.strike_price, s.ce_oi, s.ce_oi_change) for s in strikes if s.strike_price >= spot]

    pe_strikes.sort(key=lambda x: x[1], reverse=True)
    ce_strikes.sort(key=lambda x: x[1], reverse=True)

    max_pe_oi = pe_strikes[0][1] if pe_strikes else 1
    max_ce_oi = ce_strikes[0][1] if ce_strikes else 1

    supports = []
    for strike, oi, oi_chg in pe_strikes[:top_n]:
        strength = round((oi / max_pe_oi) * 100, 1)
        dist = round(((spot - strike) / spot) * 100, 2)
        supports.append(SupportResistance(
            level=strike,
            strength=strength,
            oi=oi,
            type="support",
            distance_pct=dist,
            break_probability=round(max(0, 100 - strength), 1),
        ))

    resistances = []
    for strike, oi, oi_chg in ce_strikes[:top_n]:
        strength = round((oi / max_ce_oi) * 100, 1)
        dist = round(((strike - spot) / spot) * 100, 2)
        resistances.append(SupportResistance(
            level=strike,
            strength=strength,
            oi=oi,
            type="resistance",
            distance_pct=dist,
            break_probability=round(max(0, 100 - strength), 1),
        ))

    return supports, resistances
