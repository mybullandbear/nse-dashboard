"""
Mock & Live Fallback Data Generator for Indian Options Market.
Generates institutional-grade live option chain, index ticks, OI spurts,
and signals when NSE India server is closed or rate-limited.
"""
import random
import math
from datetime import datetime, timedelta
from app.schemas import (
    OptionChainResponse, OptionStrikeData, OptionGreeks, PCRData,
    SupportResistance, SellerRecommendation, VIXData, MarketBreadth, IndexData
)

class LiveMarketSimulator:
    def __init__(self):
        self.spots = {
            "NIFTY": 24520.50,
            "BANKNIFTY": 52140.25,
            "FINNIFTY": 23410.80,
            "MIDCPNIFTY": 13120.10,
            "SENSEX": 80450.00
        }
        self.step_map = {
            "NIFTY": 50,
            "BANKNIFTY": 100,
            "FINNIFTY": 50,
            "MIDCPNIFTY": 25,
            "SENSEX": 100
        }

    def _get_persisted_baseline(self, symbol: str) -> tuple[float, float, float, float]:
        """Fetch the last real stored market snapshot parameters (spot, atm, pcr, vix) from SQLite database."""
        try:
            from app.db.database import SessionLocal
            from app.db.models import DailyMarketSnapshotModel
            db = SessionLocal()
            try:
                snap = db.query(DailyMarketSnapshotModel).filter(
                    DailyMarketSnapshotModel.symbol == symbol.upper()
                ).order_by(DailyMarketSnapshotModel.id.desc()).first()
                if snap and snap.spot_price > 0:
                    step = self.step_map.get(symbol.upper(), 50)
                    atm = snap.atm_strike if snap.atm_strike > 0 else round(snap.spot_price / step) * step
                    return snap.spot_price, atm, snap.pcr or 1.05, snap.vix or 13.50
            finally:
                db.close()
        except Exception:
            pass

        base_spot = self.spots.get(symbol.upper(), 24520.50)
        step = self.step_map.get(symbol.upper(), 50)
        atm = round(base_spot / step) * step
        return base_spot, atm, 1.05, 13.45

    def get_indices(self) -> dict:
        indices = []
        vix_val = 13.45
        t_sec = datetime.now().timestamp()
        for symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]:
            base_spot, _, _, db_vix = self._get_persisted_baseline(symbol)
            if db_vix > 0:
                vix_val = db_vix
            # Add subtle dynamic tick jitter for fallback simulation
            jitter = math.sin(t_sec / 4.0 + len(symbol)) * (base_spot * 0.0003) + random.uniform(-0.4, 0.4)
            current = round(base_spot + jitter, 2)
            change = round(current - base_spot, 2)
            pct = round((change / max(1.0, base_spot)) * 100, 2)
            indices.append({
                "symbol": symbol,
                "name": f"NIFTY {symbol}" if symbol != "SENSEX" else "SENSEX",
                "last": current,
                "change": change,
                "pctChange": pct,
                "open": round(base_spot * 0.998, 2),
                "high": round(base_spot * 1.004, 2),
                "low": round(base_spot * 0.996, 2),
                "prevClose": base_spot,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            })

        vix_data = {
            "current": vix_val,
            "change": 0.0,
            "pct_change": 0.0,
            "high": round(vix_val * 1.05, 2),
            "low": round(vix_val * 0.95, 2),
            "prev_close": vix_val,
            "trend": "stable"
        }

        breadth = {
            "advances": 32,
            "declines": 18,
            "unchanged": 0,
            "adr": 1.78
        }

        return {
            "indices": indices,
            "vix": vix_data,
            "breadth": breadth,
            "timestamp": datetime.now().isoformat()
        }

    def get_option_chain(self, symbol: str = "NIFTY") -> OptionChainResponse:
        symbol = symbol.upper()
        spot, atm, pcr_val, vix_val = self._get_persisted_baseline(symbol)
        t_sec = datetime.now().timestamp()
        jitter = math.sin(t_sec / 4.0 + len(symbol)) * (spot * 0.0003) + random.uniform(-0.4, 0.4)
        spot = round(spot + jitter, 2)
        step = self.step_map.get(symbol, 50)
        atm = round(spot / step) * step

        strikes = []
        days_ahead = (1 - datetime.now().weekday()) % 7
        expiry = (datetime.now() + timedelta(days=days_ahead)).strftime("%d-%b-%Y")
        
        # Build 25 strikes above and below ATM (51 total strikes)
        for i in range(-25, 26):
            strike = atm + (i * step)
            dist = (strike - spot) / spot

            # Approximate Black-Scholes IV & Deltas
            ce_iv = round(vix_val + abs(dist) * 12, 2)
            pe_iv = round(vix_val + 0.7 + abs(dist) * 14, 2)

            ce_delta = max(0.01, min(0.99, round(0.5 - dist * 15, 3)))
            pe_delta = max(-0.99, min(-0.01, round(-0.5 - dist * 15, 3)))

            # Intrinsic + Time value estimation
            ce_ltp = max(0, spot - strike) + max(2.0, (1 - abs(dist)*10) * (spot * 0.012))
            pe_ltp = max(0, strike - spot) + max(2.0, (1 - abs(dist)*10) * (spot * 0.012))
            
            ce_ltp = round(ce_ltp, 2)
            pe_ltp = round(pe_ltp, 2)

            # Institutional OI Distribution
            ce_oi = int(max(1000, (150000 - abs(strike - (spot + step*2)) * 120)))
            pe_oi = int(max(1000, (180000 - abs(strike - (spot - step*2)) * 130)))

            ce_oi_chg = int(ce_oi * (0.08 if strike > spot else -0.04))
            pe_oi_chg = int(pe_oi * (0.11 if strike < spot else -0.02))

            ce_vol = int(ce_oi * 0.35)
            pe_vol = int(pe_oi * 0.40)

            strikes.append(OptionStrikeData(
                strike_price=strike,
                expiry=expiry,
                ce_ltp=ce_ltp,
                ce_oi=ce_oi,
                ce_oi_change=ce_oi_chg,
                ce_volume=ce_vol,
                ce_iv=ce_iv,
                ce_bid=round(ce_ltp * 0.99, 2),
                ce_ask=round(ce_ltp * 1.01, 2),
                ce_greeks=OptionGreeks(delta=ce_delta, theta=round(-14.5 + abs(dist)*20, 2), gamma=0.0004, vega=12.1, iv=ce_iv),
                pe_ltp=pe_ltp,
                pe_oi=pe_oi,
                pe_oi_change=pe_oi_chg,
                pe_volume=pe_vol,
                pe_iv=pe_iv,
                pe_bid=round(pe_ltp * 0.99, 2),
                pe_ask=round(pe_ltp * 1.01, 2),
                pe_greeks=OptionGreeks(delta=pe_delta, theta=round(-14.2 + abs(dist)*20, 2), gamma=0.0004, vega=11.9, iv=pe_iv),
                oi_interpretation_ce="Fresh Short" if ce_oi_chg > 0 else "Long Unwinding",
                oi_interpretation_pe="Fresh Short" if pe_oi_chg > 0 else "Short Covering"
            ))

        total_ce_oi = sum(s.ce_oi for s in strikes)
        total_pe_oi = sum(s.pe_oi for s in strikes)
        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else pcr_val

        return OptionChainResponse(
            symbol=symbol,
            expiry=expiry,
            spot_price=spot,
            atm_strike=atm,
            strikes=strikes,
            pcr=pcr,
            max_pain=atm,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            expiry_list=[expiry]
        )

simulator = LiveMarketSimulator()
