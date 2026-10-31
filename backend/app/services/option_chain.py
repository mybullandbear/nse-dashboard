"""
Option Chain Processing & Metrics Engine
Parses option chains, identifies ATM strikes, computes PCR variants and Max Pain.
"""
import math
import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from app.core.config import get_settings


class StrikeContract(BaseModel):
    strikePrice: float
    expiryDate: str = ""
    lastPrice: float = 0.0
    change: float = 0.0
    pChange: float = 0.0
    openInterest: int = 0
    changeinOpenInterest: int = 0
    totalTradedVolume: int = 0
    impliedVolatility: float = 0.0
    bidprice: float = 0.0
    askPrice: float = 0.0
    signal: Optional[str] = None
    signal_label: Optional[str] = None
    signal_cls: Optional[str] = None
    ott: Optional[float] = None
    ott_state: Optional[str] = None
    adx: Optional[float] = None
    alphatrend: Optional[float] = None
    alphatrend_state: Optional[str] = None
    trend_direction: Optional[float] = None
    trend_direction_state: Optional[str] = None
    hull: Optional[float] = None
    hull_state: Optional[str] = None
    buildup: Optional[str] = None
    reason: Optional[str] = None


class StrikeRow(BaseModel):
    strikePrice: float
    expiryDate: str = ""
    CE: StrikeContract
    PE: StrikeContract
    hull_signal: Optional[Dict[str, Any]] = None


class ParsedOptionChain(BaseModel):
    symbol: str
    spot_price: float
    spot_change: float = 0.0
    spot_pchange: float = 0.0
    atm_strike: float
    expiry: str
    expiry_list: List[str] = []
    pcr: float
    pcr_atm_5: float
    max_pain: float
    total_ce_oi: int
    total_pe_oi: int
    strikes: List[StrikeRow]
    timestamp: Optional[str] = None
    source: str = "LIVE"
    atm_2_signals: Optional[Dict[str, Any]] = None
    spot_hull: Optional[Dict[str, Any]] = None


def parse_option_chain(raw_chain: Dict[str, Any], symbol: str = "NIFTY") -> Optional[ParsedOptionChain]:
    """Parses raw NSE or Fyers option chain into a normalized ParsedOptionChain structure."""
    if not raw_chain:
        return None

    settings = get_settings()
    step = settings.STRIKE_STEPS.get(symbol.upper(), 50)

    records = raw_chain.get("records", {})
    data_list = records.get("data", [])
    if not data_list:
        data_list = raw_chain.get("filtered", {}).get("data", [])

    if not data_list:
        return None

    spot_price = float(records.get("underlyingValue") or 0.0)
    spot_change = float(records.get("spot_change") or 0.0)
    spot_pchange = float(records.get("spot_pchange") or 0.0)
    expiries = records.get("expiryDates", ["CURRENT"])
    target_expiry = expiries[0] if expiries else "CURRENT"

    strike_map: Dict[float, StrikeRow] = {}
    tot_ce_oi = 0
    tot_pe_oi = 0

    for item in data_list:
        strike = float(item.get("strikePrice") or 0.0)
        if strike <= 0:
            continue

        ce_raw = item.get("CE", {})
        pe_raw = item.get("PE", {})

        # If spot price was missing from top-level, try to grab from contract
        if spot_price <= 0:
            spot_price = float(ce_raw.get("underlyingValue") or pe_raw.get("underlyingValue") or 0.0)

        ce_oi = int(ce_raw.get("openInterest") or 0)
        pe_oi = int(pe_raw.get("openInterest") or 0)
        tot_ce_oi += ce_oi
        tot_pe_oi += pe_oi

        row = StrikeRow(
            strikePrice=strike,
            expiryDate=str(ce_raw.get("expiryDate") or pe_raw.get("expiryDate") or target_expiry),
            CE=StrikeContract(
                strikePrice=strike,
                expiryDate=str(ce_raw.get("expiryDate") or target_expiry),
                lastPrice=float(ce_raw.get("lastPrice") or 0.0),
                change=float(ce_raw.get("change") or 0.0),
                pChange=float(ce_raw.get("pChange") or 0.0),
                openInterest=ce_oi,
                changeinOpenInterest=int(ce_raw.get("changeinOpenInterest") or 0),
                totalTradedVolume=int(ce_raw.get("totalTradedVolume") or 0),
                impliedVolatility=float(ce_raw.get("impliedVolatility") or 0.0),
                bidprice=float(ce_raw.get("bidprice") or 0.0),
                askPrice=float(ce_raw.get("askPrice") or 0.0),
            ),
            PE=StrikeContract(
                strikePrice=strike,
                expiryDate=str(pe_raw.get("expiryDate") or target_expiry),
                lastPrice=float(pe_raw.get("lastPrice") or 0.0),
                change=float(pe_raw.get("change") or 0.0),
                pChange=float(pe_raw.get("pChange") or 0.0),
                openInterest=pe_oi,
                changeinOpenInterest=int(pe_raw.get("changeinOpenInterest") or 0),
                totalTradedVolume=int(pe_raw.get("totalTradedVolume") or 0),
                impliedVolatility=float(pe_raw.get("impliedVolatility") or 0.0),
                bidprice=float(pe_raw.get("bidprice") or 0.0),
                askPrice=float(pe_raw.get("askPrice") or 0.0),
            )
        )
        strike_map[strike] = row

    if not strike_map:
        return None

    sorted_strikes = sorted(strike_map.values(), key=lambda r: r.strikePrice)
    
    # Identify ATM strike
    if spot_price > 0:
        atm_strike = round(spot_price / step) * step
    else:
        # Fallback to median strike
        atm_strike = sorted_strikes[len(sorted_strikes) // 2].strikePrice
        spot_price = atm_strike

    # Overall PCR
    overall_pcr = round(tot_pe_oi / max(1, tot_ce_oi), 3)

    # ATM ± 5 strikes PCR
    atm_strikes = [r for r in sorted_strikes if abs(r.strikePrice - atm_strike) <= (5 * step)]
    atm_ce_oi = sum(r.CE.openInterest for r in atm_strikes)
    atm_pe_oi = sum(r.PE.openInterest for r in atm_strikes)
    atm_5_pcr = round(atm_pe_oi / max(1, atm_ce_oi), 3)

    # Max Pain calculation
    max_pain = compute_max_pain(sorted_strikes)

    return ParsedOptionChain(
        symbol=symbol.upper(),
        spot_price=round(spot_price, 2),
        spot_change=round(spot_change, 2),
        spot_pchange=round(spot_pchange, 2),
        atm_strike=float(atm_strike),
        expiry=target_expiry,
        expiry_list=expiries,
        pcr=overall_pcr,
        pcr_atm_5=atm_5_pcr,
        max_pain=max_pain,
        total_ce_oi=tot_ce_oi,
        total_pe_oi=tot_pe_oi,
        strikes=sorted_strikes,
        timestamp=time.strftime("%H:%M:%S")
    )


def compute_max_pain(strikes: List[StrikeRow]) -> float:
    """Computes Max Pain strike where option buyers lose the maximum cumulative value."""
    if not strikes:
        return 0.0

    pain_by_strike = {}
    strike_prices = [r.strikePrice for r in strikes]

    for eval_strike in strike_prices:
        total_pain = 0.0
        for row in strikes:
            # CE buyer loss
            if eval_strike > row.strikePrice:
                total_pain += (eval_strike - row.strikePrice) * row.CE.openInterest
            # PE buyer loss
            if eval_strike < row.strikePrice:
                total_pain += (row.strikePrice - eval_strike) * row.PE.openInterest
        pain_by_strike[eval_strike] = total_pain

    min_pain_strike = min(pain_by_strike, key=pain_by_strike.get)
    return float(min_pain_strike)
