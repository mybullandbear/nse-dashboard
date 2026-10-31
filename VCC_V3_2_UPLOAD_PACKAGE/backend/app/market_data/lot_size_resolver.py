"""
Authoritative Symbol + Expiry Lot Size Resolver for VCC V3.2.
Resolves exact contract lot size using LotSizeMaster.
Enforces strict zero-guessing rules: Never defaults to 500, 1, or arbitrary values.
"""
import re
import logging
from datetime import datetime
from typing import Optional, Dict

from app.market_data.lot_size_master import lot_size_master, LotSizeMaster

logger = logging.getLogger(__name__)

MONTH_NAME_MAP = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
}


class LotSizeResolver:

    def __init__(self, master: Optional[LotSizeMaster] = None):
        self.master = master or lot_size_master

    def normalize_symbol(self, symbol: str) -> str:
        if not symbol:
            return ""
        return symbol.strip().upper()

    def normalize_expiry_to_month_key(self, expiry: Optional[str]) -> Optional[str]:
        """
        Normalizes expiry input into master month key format (e.g. 'Sep 2026', 'Oct 2026', 'Nov 2026').
        Supports ISO dates ('2026-09-24'), month format ('2026-09'), or direct strings ('Sep 2026').
        """
        if not expiry:
            return None

        exp_str = str(expiry).strip()

        # Direct match check
        if exp_str in ("Sep 2026", "Oct 2026", "Nov 2026"):
            return exp_str

        # Match YYYY-MM-DD or YYYY-MM
        m = re.match(r"^(\d{4})-(\d{2})(?:-\d{2})?", exp_str)
        if m:
            year = int(m.group(1))
            month_num = int(m.group(2))
            if 1 <= month_num <= 12:
                month_name = MONTH_NAME_MAP[month_num]
                return f"{month_name} {year}"

        # Match DD-MMM-YYYY or MMM-YYYY
        m2 = re.search(r"([A-Za-z]{3})[-_\s]*(\d{4})", exp_str)
        if m2:
            m_name = m2.group(1).capitalize()
            yr = m2.group(2)
            return f"{m_name} {yr}"

        return None

    def get_lot_size(self, symbol: str, expiry: Optional[str] = None) -> Optional[int]:
        """
        Resolves authoritative contract lot size for symbol and optional expiry.
        Returns:
            int: Authoritative lot size (> 0)
            None: If symbol unknown, expiry unresolvable, or lot size unavailable in master.
        Strict Rules:
            - Never fallback to 500 or 1.
            - Never guess.
        """
        sym = self.normalize_symbol(symbol)
        if not sym or not self.master.is_symbol_supported(sym):
            return None

        all_month_sizes = self.master.get_all_symbol_lot_sizes(sym)
        if not all_month_sizes:
            return None

        month_key = self.normalize_expiry_to_month_key(expiry)

        if month_key:
            # Explicit expiry requested
            val = all_month_sizes.get(month_key)
            if val is not None and val > 0:
                return val
            # Expiry explicitly unavailable in master for this month
            return None

        # Expiry omitted: Check if all non-None values in master are identical
        valid_vals = [v for v in all_month_sizes.values() if v is not None and v > 0]
        if valid_vals and len(set(valid_vals)) == 1:
            return valid_vals[0]

        # Differing values across expiries or all None -> return None
        return None


# Global Singleton Instance
lot_size_resolver = LotSizeResolver()
