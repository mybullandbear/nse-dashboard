"""
PURE BUYING BOT – Spot-Anchored Directional (CE / PE)
Version: 2.1 – Trap Filtered
Independent Execution & Simulation Engine
"""

import os
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger("PureBuyingBotV2")
logging.basicConfig(level=logging.INFO)

# ============================================================
# --- INPUTS / CONSTANTS ---
# ============================================================
PIV_L = 10
PIV_R = 3
ATR_LEN = 14
BRK_BUF = 0.15          # slightly higher than 0.10 to reduce noise
FAIL_BUF = 0.50
TRAIL_MULT = 2.8
MIN_ATR_MOVE = 0.12     # % from VWAP or previous swing
STRONG_CLOSE = 0.60
PCR_BULL = 1.15
PCR_BEAR = 0.80
COOLDOWN_BARS = 8       # after any exit
MIN_BARS_FROM_OPEN = 12 # ~09:27 onwards preferred
MAX_TRADES_PER_DAY = 3

LOT_SIZES = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120,
    "SENSEX": 20
}

SLIPPAGE_PTS = {
    "NIFTY": 0.80,
    "BANKNIFTY": 2.50,
    "FINNIFTY": 1.50,
    "MIDCPNIFTY": 1.20
}

def calc_statutory_charges(entry_p: float, exit_p: float, qty: int) -> float:
    buy_turnover = entry_p * qty
    sell_turnover = exit_p * qty
    total_turnover = buy_turnover + sell_turnover
    brokerage = 40.0
    stt = sell_turnover * 0.00125
    txn_fee = total_turnover * 0.00050
    gst = (brokerage + txn_fee) * 0.18
    stamp_duty = buy_turnover * 0.00003
    sebi_fee = total_turnover * 0.000001
    return brokerage + stt + txn_fee + gst + stamp_duty + sebi_fee

# ============================================================
# TECHNICAL CALCULATION UTILITIES
# ============================================================
def compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    if n == 0:
        return np.array([])
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    # Wilder's RMA
    atr = np.zeros(n)
    atr[0] = tr[0]
    alpha = 1.0 / period
    for i in range(1, n):
        atr[i] = alpha * tr[i] + (1.0 - alpha) * atr[i - 1]
    return atr

def compute_breakout_tracker(highs: List[float], lows: List[float], closes: List[float]) -> Dict[str, Any]:
    n = len(closes)
    if n < PIV_L + PIV_R + 2:
        return {
            "state": "FLAT", "bias": "NEUTRAL", "res_lvl": None, "sup_lvl": None,
            "fail_level": None, "trail_level": None, "atr": 0.0, "flip_bars_ago": 999
        }
    
    h_arr = np.array(highs, dtype=float)
    l_arr = np.array(lows, dtype=float)
    c_arr = np.array(closes, dtype=float)
    atr_arr = compute_atr(h_arr, l_arr, c_arr, ATR_LEN)
    
    res_lvl = None
    sup_lvl = None
    in_long = False
    in_short = False
    long_fail = None
    short_fail = None
    long_trail = None
    short_trail = None
    last_state = "FLAT"
    flip_bar = 0
    
    for i in range(PIV_L + PIV_R, n):
        p_idx = i - PIV_R
        val_h = h_arr[p_idx]
        val_l = l_arr[p_idx]
        
        # Check pivot high
        if all(val_h >= h_arr[k] for k in range(p_idx - PIV_L, p_idx)) and \
           all(val_h > h_arr[k] for k in range(p_idx + 1, p_idx + PIV_R + 1)):
            res_lvl = val_h
            
        # Check pivot low
        if all(val_l <= l_arr[k] for k in range(p_idx - PIV_L, p_idx)) and \
           all(val_l < l_arr[k] for k in range(p_idx + 1, p_idx + PIV_R + 1)):
            sup_lvl = val_l
            
        c_bar = c_arr[i]
        a_bar = atr_arr[i] if atr_arr[i] > 0 else (h_arr[i] - l_arr[i] or 1.0)
        
        # Check exits
        if in_long:
            if long_fail is not None and c_bar < long_fail:
                in_long = False
            elif long_trail is not None and c_bar < long_trail:
                in_long = False
            else:
                long_trail = max(long_trail or (c_bar - TRAIL_MULT * a_bar), c_bar - TRAIL_MULT * a_bar)
                
        if in_short:
            if short_fail is not None and c_bar > short_fail:
                in_short = False
            elif short_trail is not None and c_bar > short_trail:
                in_short = False
            else:
                short_trail = min(short_trail or (c_bar + TRAIL_MULT * a_bar), c_bar + TRAIL_MULT * a_bar)
                
        # Check breakouts
        pos = (c_bar - l_arr[i]) / (h_arr[i] - l_arr[i]) if (h_arr[i] - l_arr[i]) > 0 else 0.5
        if not in_long and not in_short:
            if res_lvl is not None and c_bar > res_lvl + BRK_BUF * a_bar and pos >= STRONG_CLOSE:
                in_long = True
                long_fail = res_lvl - FAIL_BUF * a_bar
                long_trail = c_bar - TRAIL_MULT * a_bar
                if last_state != "LONG":
                    flip_bar = i
                    last_state = "LONG"
            elif sup_lvl is not None and c_bar < sup_lvl - BRK_BUF * a_bar and pos <= (1.0 - STRONG_CLOSE):
                in_short = True
                short_fail = sup_lvl + FAIL_BUF * a_bar
                short_trail = c_bar + TRAIL_MULT * a_bar
                if last_state != "SHORT":
                    flip_bar = i
                    last_state = "SHORT"
                    
    curr_state = "LONG" if in_long else ("SHORT" if in_short else "FLAT")
    fail_lvl = long_fail if in_long else (short_fail if in_short else None)
    trail_lvl = long_trail if in_long else (short_trail if in_short else None)
    
    return {
        "state": curr_state,
        "res_lvl": res_lvl,
        "sup_lvl": sup_lvl,
        "fail_level": fail_lvl,
        "trail_level": trail_lvl,
        "atr": round(atr_arr[-1], 2) if len(atr_arr) > 0 else 0.0,
        "flip_bars_ago": n - 1 - flip_bar
    }

def compute_alphatrend(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> Tuple[str, float]:
    n = len(closes)
    if n < period + 2:
        return "FLAT", closes[-1] if n > 0 else 0.0
    atr = compute_atr(highs, lows, closes, period)
    # Basic MFI proxy using close changes
    up_t = lows - atr * 1.0
    down_t = highs + atr * 1.0
    at_val = closes[0]
    for i in range(1, n):
        if closes[i] >= closes[i - 1]:
            at_val = max(at_val, up_t[i])
        else:
            at_val = min(at_val, down_t[i])
    dir_str = "LONG" if closes[-1] > at_val else ("SHORT" if closes[-1] < at_val else "FLAT")
    return dir_str, round(float(at_val), 2)

def compute_shonya_gravity(closes: np.ndarray, length: int = 20, mad_len: int = 14) -> Dict[str, float]:
    n = len(closes)
    if n < max(length, mad_len) + 2:
        return {"pull": 0.5, "upper": closes[-1], "lower": closes[-1], "pull_is_falling": False}
    s = pd.Series(closes)
    basis = s.ewm(span=length, adjust=False).mean()
    mean = s.rolling(window=mad_len).mean()
    mad = (s - mean).abs().rolling(window=mad_len).mean()
    
    velocity = basis - basis.shift(3)
    accel = velocity - velocity.shift(1)
    
    gravity = np.zeros(n)
    curr_grav = 0.0
    for i in range(1, n):
        m_val = mad.iloc[i] if not np.isnan(mad.iloc[i]) else 0.0
        a_val = accel.iloc[i] if not np.isnan(accel.iloc[i]) else 0.0
        norm_accel = abs(a_val) / m_val if m_val > 0 else 0.0
        if norm_accel > 0.01:
            curr_grav = min(norm_accel * 8.0, 2.0)
        else:
            curr_grav = curr_grav * 0.95
        gravity[i] = curr_grav
        
    pull_arr = np.minimum(gravity / 1.5, 1.0)
    trail_mult = 3.0 - (3.0 - 1.2) * pull_arr
    upper = basis + mad * trail_mult
    lower = basis - mad * trail_mult
    
    pull_curr = float(pull_arr[-1])
    pull_prev = float(pull_arr[-2]) if n > 1 else pull_curr
    
    return {
        "pull": round(pull_curr, 3),
        "upper": round(float(upper.iloc[-1]), 2),
        "lower": round(float(lower.iloc[-1]), 2),
        "pull_is_falling": pull_curr < pull_prev
    }

def compute_mapo_and_ema(closes: np.ndarray) -> Tuple[float, float, bool]:
    """Returns (mapo_per, ema_slope_deg, is_crossing_mid_wrong_way)"""
    n = len(closes)
    if n < 20:
        return 50.0, 0.0, False
    s = pd.Series(closes)
    ema5 = s.ewm(span=5, adjust=False).mean()
    ema20 = s.ewm(span=20, adjust=False).mean()
    
    # MAPO ribbon score: distance between 5 and 20 EMA normalized
    diff = (ema5.iloc[-1] - ema20.iloc[-1]) / (closes[-1] or 1.0) * 100.0
    mapo_per = float(np.clip(50.0 + diff * 50.0, 10.0, 90.0))
    
    # EMA slope in degrees approximation
    slope = (ema5.iloc[-1] - ema5.iloc[-3]) / 3.0
    angle = np.degrees(np.arctan(slope))
    
    # Crossing mid from wrong way:
    # If currently Bullish (>50) but just crossed from below, or Bearish (<50) but just crossed from above
    crossed_wrong = False
    if n > 2:
        diff_prev = (ema5.iloc[-2] - ema20.iloc[-2])
        if (diff > 0 and diff_prev <= 0) or (diff < 0 and diff_prev >= 0):
            crossed_wrong = True
            
    return round(mapo_per, 1), round(angle, 1), crossed_wrong

# ============================================================
# --- REGIME FILTER (must be TRUE) ---
# ============================================================
def is_trending_regime(bt_state: str, alphatrend_dir: str, mapo_per: float, shonya_pull: float, ema_slope: float, vwap_dist: float) -> bool:
    return (
        bt_state in ["LONG", "SHORT"] and
        alphatrend_dir == bt_state and
        abs(vwap_dist) >= MIN_ATR_MOVE and
        abs(ema_slope) > 15.0 and
        shonya_pull > 0.55 and
        (mapo_per > 62.0 or mapo_per < 38.0)
    )

print("PureBuyingBotV2 core logic defined successfully.")
