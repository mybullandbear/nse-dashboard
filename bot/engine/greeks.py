"""
Pure Python Black-Scholes Greeks Calculator
Computes Delta, Theta, Gamma, Vega using standard library math.
"""
import math
from typing import Dict, Any


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


def calculate_greeks(
    spot: float,
    strike: float,
    iv_pct: float,
    dte_days: float = 2.0,
    is_call: bool = True
) -> Dict[str, float]:
    """
    Computes Black-Scholes Greeks (Delta, Theta per day in points, Gamma, Vega).
    Clamps inputs to prevent divide-by-zero or math domain errors.
    """
    if spot <= 0 or strike <= 0:
        return {"delta": 0.5 if is_call else -0.5, "theta": -5.0, "gamma": 0.001, "vega": 1.0}

    # Normalize parameters
    sigma = max(0.06, min(1.20, (iv_pct or 14.0) / 100.0))
    t_years = max(0.25 / 365.0, (dte_days or 2.0) / 365.0)
    r = 0.07  # Benchmark risk-free rate approx 7%

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    pdf_d1 = _norm_pdf(d1)
    cdf_d1 = _norm_cdf(d1)
    cdf_d2 = _norm_cdf(d2)

    gamma = pdf_d1 / (spot * sigma * sqrt_t)
    vega = (spot * sqrt_t * pdf_d1) / 100.0  # per 1% vol change

    if is_call:
        delta = cdf_d1
        annual_theta = -(spot * pdf_d1 * sigma) / (2.0 * sqrt_t) - (r * strike * math.exp(-r * t_years) * cdf_d2)
    else:
        delta = cdf_d1 - 1.0
        annual_theta = -(spot * pdf_d1 * sigma) / (2.0 * sqrt_t) + (r * strike * math.exp(-r * t_years) * (1.0 - cdf_d2))

    daily_theta = annual_theta / 365.0

    return {
        "delta": round(delta, 3),
        "theta": round(daily_theta, 2),  # negative points per day
        "gamma": round(gamma, 5),
        "vega": round(vega, 2)
    }
