"""
Modular NSE F&O Lot Size Master Data Module.
Loads, validates, and indexes authoritative lot sizes from backend/config/nse_fno_lot_sizes.csv.
Pure configuration data component independent of Smart Money trading logic.
"""
import os
import csv
import logging
from typing import Dict, Optional, Tuple, Set

logger = logging.getLogger(__name__)

# Column names in source CSV
COL_SYMBOL = "Symbol"
COL_COMPANY = "All Companies"
COL_SCREENER = "Screener"
MONTH_COLUMNS = {
    "Sep 2026": "Lot Size (Sep 2026)",
    "Oct 2026": "Lot Size (Oct 2026)",
    "Nov 2026": "Lot Size (Nov 2026)"
}


class LotSizeMaster:

    def __init__(self, csv_path: Optional[str] = None):
        if not csv_path:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            csv_path = os.path.join(base_dir, "config", "nse_fno_lot_sizes.csv")

        self.csv_path = csv_path
        # Map of (symbol_upper, month_str) -> Optional[int]
        self._lot_sizes: Dict[Tuple[str, str], Optional[int]] = {}
        # Map of symbol_upper -> set of valid month keys
        self._symbol_months: Dict[str, Set[str]] = {}
        # Metadata map symbol_upper -> company_name
        self._company_names: Dict[str, str] = {}

        self._load_and_validate()

    def _load_and_validate(self):
        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"Authoritative Lot Size Master CSV not found at: {self.csv_path}")

        with open(self.csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []

            if COL_SYMBOL not in headers:
                raise ValueError(f"Invalid Lot Size Master CSV: Missing '{COL_SYMBOL}' header.")

            row_index = 1
            for row in reader:
                row_index += 1
                raw_sym = row.get(COL_SYMBOL, "").strip()
                if not raw_sym:
                    raise ValueError(f"Invalid Lot Size Master record at line {row_index}: Symbol cannot be blank.")

                sym_upper = raw_sym.upper()
                company_name = row.get(COL_COMPANY, "").strip()
                self._company_names[sym_upper] = company_name

                if sym_upper not in self._symbol_months:
                    self._symbol_months[sym_upper] = set()

                for month_key, col_name in MONTH_COLUMNS.items():
                    if col_name not in headers:
                        continue

                    raw_val = row.get(col_name, "").strip()
                    val: Optional[int] = None

                    if raw_val and raw_val not in ("-", "None", "NULL", "N/A"):
                        try:
                            parsed = int(raw_val)
                            if parsed <= 0:
                                raise ValueError(f"Invalid lot size {parsed} for {sym_upper} ({month_key}) at line {row_index}.")
                            val = parsed
                        except ValueError as e:
                            raise ValueError(f"Non-numeric lot size '{raw_val}' for {sym_upper} ({month_key}) at line {row_index}.") from e

                    key = (sym_upper, month_key)
                    if key in self._lot_sizes:
                        raise ValueError(f"Duplicate symbol + month record in master: {key}")

                    self._lot_sizes[key] = val
                    self._symbol_months[sym_upper].add(month_key)

        logger.info("LotSizeMaster loaded successfully: %d symbols indexed from %s", len(self._symbol_months), self.csv_path)

    def get_raw_lot_size(self, symbol: str, month_key: str) -> Optional[int]:
        """Returns authoritative lot size for (symbol, month_key) or None if unavailable/unknown."""
        return self._lot_sizes.get((symbol.strip().upper(), month_key))

    def get_all_symbol_lot_sizes(self, symbol: str) -> Dict[str, Optional[int]]:
        """Returns dict of month_key -> lot_size for given symbol."""
        sym_upper = symbol.strip().upper()
        res = {}
        for m_key in self._symbol_months.get(sym_upper, []):
            res[m_key] = self._lot_sizes.get((sym_upper, m_key))
        return res

    def is_symbol_supported(self, symbol: str) -> bool:
        return symbol.strip().upper() in self._symbol_months


# Global Singleton Instance
lot_size_master = LotSizeMaster()
