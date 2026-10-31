"""
Smart Money Shift & Block Trade Event Detector for VCC V3.2.
Detects institutional block trades, single-strike OI shifts, and call/put unwinding events.
Pure analytical module independent of database or network calls.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from app.domain.contracts import MarketSnapshot
from app.smart_money.models import SmartMoneyShiftEvent

from app.market_data.lot_size_resolver import lot_size_resolver

IST = timezone(timedelta(hours=5, minutes=30))


class SmartMoneyDetector:

    @staticmethod
    def get_thresholds(symbol: str, expiry: Optional[str] = None) -> tuple[Optional[int], Optional[int]]:
        sym_upper = symbol.upper()
        if "BANK" in sym_upper:
            return 25000, -20000
        elif "FIN" in sym_upper:
            return 20000, -15000
        elif "MID" in sym_upper:
            return 15000, -10000
        elif "NIFTY" in sym_upper:
            return 35000, -25000
        else:  # F&O Stock Options lot-size resolved threshold
            lot_size = lot_size_resolver.get_lot_size(symbol, expiry)
            if lot_size is None or lot_size <= 0:
                return None, None
            return max(200 * lot_size, 5000), -max(150 * lot_size, 3500)

    def detect_shifts(
        self,
        symbol: str,
        snapshot: MarketSnapshot,
        trade_date: Optional[str] = None,
        now_iso: Optional[str] = None,
        put_conviction: float = 89.0,
        call_conviction: float = 78.0
    ) -> List[SmartMoneyShiftEvent]:
        """
        Scans option chain for institutional block trades, OI additions, and unwinding.
        Returns canonical SmartMoneyShiftEvent list.
        """
        if not snapshot or not snapshot.option_chain or not snapshot.option_chain.strikes:
            return []

        now_dt = datetime.now(IST)
        t_date = trade_date or now_dt.strftime("%Y-%m-%d")
        iso_str = now_iso or now_dt.isoformat()

        expiry = getattr(snapshot.option_chain, 'expiry', None) or getattr(snapshot, 'expiry', None)
        min_shift_oi, min_unwind_oi = self.get_thresholds(symbol, expiry)

        if min_shift_oi is None or min_unwind_oi is None:
            return []

        chain = snapshot.option_chain
        step = 100 if "BANK" in symbol.upper() else (25 if "MID" in symbol.upper() else 50)
        band_min = chain.atm_strike - (10 * step)
        band_max = chain.atm_strike + (10 * step)

        detected_events: List[SmartMoneyShiftEvent] = []

        for s in chain.strikes:
            strike_price = float(s.strike_price)
            if strike_price < band_min or strike_price > band_max:
                continue

            pe_oi_chg = float(getattr(s, 'pe_oi_change', getattr(getattr(s, 'pe_tick', None), 'oi_change', 0)))
            ce_oi_chg = float(getattr(s, 'ce_oi_change', getattr(getattr(s, 'ce_tick', None), 'oi_change', 0)))

            # 1. Put writing shift (Bullish Floor)
            if pe_oi_chg >= min_shift_oi:
                text = f"Smart Money added +{(pe_oi_chg / 100000.0):.1f}L PE OI at {int(strike_price)} PE (Strong Floor)"
                detected_events.append(SmartMoneyShiftEvent(
                    symbol=symbol.upper(),
                    trade_date=t_date,
                    timestamp=iso_str,
                    shift_text=text,
                    shift_type="BULL",
                    strike_price=strike_price,
                    option_type="PE",
                    oi_change=pe_oi_chg,
                    conviction_score=put_conviction
                ))

            # 2. Call writing shift (Bearish Resistance)
            elif ce_oi_chg >= min_shift_oi:
                text = f"Smart Money added +{(ce_oi_chg / 100000.0):.1f}L CE OI at {int(strike_price)} CE (Resistance Ceiling)"
                detected_events.append(SmartMoneyShiftEvent(
                    symbol=symbol.upper(),
                    trade_date=t_date,
                    timestamp=iso_str,
                    shift_text=text,
                    shift_type="BEAR",
                    strike_price=strike_price,
                    option_type="CE",
                    oi_change=ce_oi_chg,
                    conviction_score=call_conviction
                ))

            # 3. Call unwinding (Bullish)
            elif ce_oi_chg <= min_unwind_oi:
                text = f"Call Unwinding observed at {int(strike_price)} CE ({(ce_oi_chg / 1000.0):.0f}K OI)"
                detected_events.append(SmartMoneyShiftEvent(
                    symbol=symbol.upper(),
                    trade_date=t_date,
                    timestamp=iso_str,
                    shift_text=text,
                    shift_type="BULL",
                    strike_price=strike_price,
                    option_type="CE",
                    oi_change=ce_oi_chg,
                    conviction_score=put_conviction
                ))

            # 4. Put unwinding (Bearish)
            elif pe_oi_chg <= min_unwind_oi:
                text = f"Put Unwinding observed at {int(strike_price)} PE ({(pe_oi_chg / 1000.0):.0f}K OI)"
                detected_events.append(SmartMoneyShiftEvent(
                    symbol=symbol.upper(),
                    trade_date=t_date,
                    timestamp=iso_str,
                    shift_text=text,
                    shift_type="BEAR",
                    strike_price=strike_price,
                    option_type="PE",
                    oi_change=pe_oi_chg,
                    conviction_score=call_conviction
                ))

        return detected_events


smart_money_detector = SmartMoneyDetector()
