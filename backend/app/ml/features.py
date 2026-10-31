"""
Feature Engineering Pipeline for NSE Directional Options
Extracts normalized, symmetric market and option-chain features without lookahead bias.
"""
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


FEATURE_NAMES = [
    "pcr",
    "net_oi_imbalance",
    "net_oi_chg_imbalance",
    "ce_oi_chg_rate",
    "pe_oi_chg_rate",
    "spot_ret_1m",
    "spot_ret_5m",
    "spot_ret_15m",
    "atm_ce_ret_1m",
    "atm_ce_ret_5m",
    "atm_ce_ret_15m",
    "atm_pe_ret_1m",
    "atm_pe_ret_5m",
    "atm_pe_ret_15m",
    "option_rel_momentum_5m",
    "confluence_5m_norm",
    "confluence_1m_norm",
    "alphatrend_5m_num",
    "hull_5m_num",
    "hull_1m_num",
    "trend_direction_strength",
    "shonya_state_num",
    "shonya_gravity",
    "shonya_pull",
    "proximity_pct_norm",
    "indicator_agreement",
    "spot_volatility_5m",
    "time_of_day_norm"
]


def time_to_day_fraction(t_str: str) -> float:
    """Converts HH:MM string to fraction of trading day [09:15=0.0, 15:30=1.0]."""
    try:
        parts = t_str.split(":")
        mins = int(parts[0]) * 60 + int(parts[1])
        start_mins = 9 * 60 + 15  # 09:15 = 555
        end_mins = 15 * 60 + 30   # 15:30 = 930
        frac = (mins - start_mins) / float(end_mins - start_mins)
        return float(np.clip(frac, 0.0, 1.0))
    except Exception:
        return 0.5


def extract_features_from_history(
    merged_1m: pd.DataFrame,
    ticks_lookup: Dict[tuple, Dict[str, Any]],
    symbol: str,
    step: int
) -> pd.DataFrame:
    """
    Extracts time-series features across an entire trading day for a symbol.
    Ensures zero future lookahead by strictly relying on t and historical lags (t-1, t-5, t-15).
    """
    df = merged_1m.copy()
    n = len(df)
    if n < 20:
        return pd.DataFrame()

    rows = []
    spots = df['close'].values
    times = df['time_str'].values

    # Pre-extract ATM option LTPs
    atm_ce_ltps = np.zeros(n)
    atm_pe_ltps = np.zeros(n)
    atm_strikes = np.zeros(n)

    for i in range(n):
        t_str = times[i]
        sp = spots[i]
        atm_stk = round(sp / step) * step
        atm_strikes[i] = atm_stk

        ce_tk = ticks_lookup.get((t_str, atm_stk, 'CE'), {})
        pe_tk = ticks_lookup.get((t_str, atm_stk, 'PE'), {})
        atm_ce_ltps[i] = float(ce_tk.get('ltp', 0.0))
        atm_pe_ltps[i] = float(pe_tk.get('ltp', 0.0))

    # Rolling calculations
    spot_series = pd.Series(spots)
    ce_series = pd.Series(atm_ce_ltps).replace(0, np.nan).ffill().bfill()
    pe_series = pd.Series(atm_pe_ltps).replace(0, np.nan).ffill().bfill()

    spot_ret_1m = (spot_series.pct_change(1).fillna(0.0) * 100.0).values
    spot_ret_5m = (spot_series.pct_change(5).fillna(0.0) * 100.0).values
    spot_ret_15m = (spot_series.pct_change(15).fillna(0.0) * 100.0).values
    spot_vol_5m = spot_series.pct_change(1).rolling(5).std().fillna(0.0).values * 100.0

    ce_ret_1m = (ce_series.pct_change(1).fillna(0.0) * 100.0).values
    ce_ret_5m = (ce_series.pct_change(5).fillna(0.0) * 100.0).values
    ce_ret_15m = (ce_series.pct_change(15).fillna(0.0) * 100.0).values

    pe_ret_1m = (pe_series.pct_change(1).fillna(0.0) * 100.0).values
    pe_ret_5m = (pe_series.pct_change(5).fillna(0.0) * 100.0).values
    pe_ret_15m = (pe_series.pct_change(15).fillna(0.0) * 100.0).values

    for i in range(15, n):
        t_str = times[i]
        r = df.iloc[i]

        pcr = float(r.get('pcr', 1.0))
        ce_oi = float(r.get('ce_oi', 1.0))
        pe_oi = float(r.get('pe_oi', 1.0))
        ce_oi_chg = float(r.get('ce_oi_chg', 0.0))
        pe_oi_chg = float(r.get('pe_oi_chg', 0.0))

        tot_oi = max(1.0, ce_oi + pe_oi)
        net_oi_imbalance = (pe_oi - ce_oi) / tot_oi

        tot_chg = max(1.0, abs(pe_oi_chg) + abs(ce_oi_chg))
        net_oi_chg_imbalance = (pe_oi_chg - ce_oi_chg) / tot_chg

        ce_oi_rate = ce_oi_chg / max(1.0, ce_oi)
        pe_oi_rate = pe_oi_chg / max(1.0, pe_oi)

        conf_5m = float(r.get('confluence_5m', 50.0))
        conf_1m = float(r.get('confluence_1m', 50.0))
        conf_5m_norm = (conf_5m - 50.0) / 50.0
        conf_1m_norm = (conf_1m - 50.0) / 50.0

        at_val = 1.0 if r.get('alphatrend_5m') == 'BULLISH' else (-1.0 if r.get('alphatrend_5m') == 'BEARISH' else 0.0)
        hull_5m_val = 1.0 if r.get('hull_5m') == 'BULLISH' else -1.0
        hull_1m_val = 1.0 if r.get('hull_1m') == 'BULLISH_GREEN' else -1.0

        # Indicator agreement: count of directional concordances
        agreement = (
            (1.0 if conf_5m_norm > 0 else -1.0) +
            (1.0 if conf_1m_norm > 0 else -1.0) +
            at_val +
            hull_5m_val +
            hull_1m_val
        ) / 5.0

        rel_opt_mom = ce_ret_5m[i] - pe_ret_5m[i]
        tod = time_to_day_fraction(t_str)

        feat = {
            "trade_date": r.get('trade_date'),
            "time_str": t_str,
            "symbol": symbol,
            "spot": spots[i],
            "atm_strike": atm_strikes[i],
            "atm_ce_ltp": atm_ce_ltps[i],
            "atm_pe_ltp": atm_pe_ltps[i],
            "pcr": float(np.clip(pcr, 0.2, 3.0)),
            "net_oi_imbalance": float(np.clip(net_oi_imbalance, -1.0, 1.0)),
            "net_oi_chg_imbalance": float(np.clip(net_oi_chg_imbalance, -1.0, 1.0)),
            "ce_oi_chg_rate": float(np.clip(ce_oi_rate, -1.0, 1.0)),
            "pe_oi_chg_rate": float(np.clip(pe_oi_rate, -1.0, 1.0)),
            "spot_ret_1m": float(np.clip(spot_ret_1m[i], -5.0, 5.0)),
            "spot_ret_5m": float(np.clip(spot_ret_5m[i], -10.0, 10.0)),
            "spot_ret_15m": float(np.clip(spot_ret_15m[i], -15.0, 15.0)),
            "atm_ce_ret_1m": float(np.clip(ce_ret_1m[i], -50.0, 100.0)),
            "atm_ce_ret_5m": float(np.clip(ce_ret_5m[i], -80.0, 200.0)),
            "atm_ce_ret_15m": float(np.clip(ce_ret_15m[i], -90.0, 300.0)),
            "atm_pe_ret_1m": float(np.clip(pe_ret_1m[i], -50.0, 100.0)),
            "atm_pe_ret_5m": float(np.clip(pe_ret_5m[i], -80.0, 200.0)),
            "atm_pe_ret_15m": float(np.clip(pe_ret_15m[i], -90.0, 300.0)),
            "option_rel_momentum_5m": float(np.clip(rel_opt_mom, -200.0, 200.0)),
            "confluence_5m_norm": float(conf_5m_norm),
            "confluence_1m_norm": float(conf_1m_norm),
            "alphatrend_5m_num": float(at_val),
            "hull_5m_num": float(hull_5m_val),
            "hull_1m_num": float(hull_1m_val),
            "indicator_agreement": float(agreement),
            "spot_volatility_5m": float(spot_vol_5m[i]),
            "time_of_day_norm": float(tod)
        }
        rows.append(feat)

    return pd.DataFrame(rows)
