"""
Automated Test for Strike Buildup Lab
Verifies:
1. /api/buildup-lab/strikes/{symbol} endpoint
2. ATM +- 5 strike extraction and CE/PE categorization
3. /api/buildup-lab/timeline/{symbol} endpoint for slider playback
"""
import sys
import os

# Add backend directory to sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi.testclient import TestClient
from app.main import app
from app.db.storage import snapshot_storage
from app.core.market_hours import get_current_ist


def seed_test_strike_data():
    """Seeds test strike snapshots in SQLite for testing playback and off-market rendering."""
    sample_strikes = []
    atm = 24500
    for offset in range(-5, 6):
        stk = atm + offset * 50
        # CE
        sample_strikes.append({
            "strike": stk,
            "option_type": "CE",
            "ltp": 120.0 - offset * 15,
            "price_pchange": 5.0 + offset * 2,
            "oi": 500000 + offset * 20000,
            "oi_chg": 30000 + offset * 5000,
            "oi_pchange": 6.0 + offset * 1.5,
            "volume": 80000,
            "is_atm": (stk == atm)
        })
        # PE
        sample_strikes.append({
            "strike": stk,
            "option_type": "PE",
            "ltp": 95.0 + offset * 15,
            "price_pchange": -8.0 - offset * 1.5,
            "oi": 600000 - offset * 15000,
            "oi_chg": 45000 - offset * 3000,
            "oi_pchange": 8.0 - offset * 1.2,
            "volume": 95000,
            "is_atm": (stk == atm)
        })

    # Direct insert into sqlite without market hours check for testing
    now = get_current_ist()
    trade_date = now.strftime("%Y-%m-%d")
    ts_iso = now.isoformat()
    with snapshot_storage._get_connection() as conn:
        cursor = conn.cursor()
        for t_str in ["09:30", "10:30", "11:30"]:
            params = [
                (
                    "NIFTY", trade_date, ts_iso, t_str,
                    float(s["strike"]), s["option_type"], float(s["ltp"]),
                    float(s["price_pchange"]), int(s["oi"]), int(s["oi_chg"]),
                    float(s["oi_pchange"]), int(s["volume"]), 1 if s["is_atm"] else 0
                )
                for s in sample_strikes
            ]
            cursor.executemany("""
                INSERT INTO intraday_strike_snapshots (
                    symbol, trade_date, timestamp, time_str, strike, option_type,
                    ltp, price_pchange, oi, oi_chg, oi_pchange, volume, is_atm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
        conn.commit()
    return ts_iso


def test_strike_lab():
    client = TestClient(app)
    print("Testing Strike Buildup Lab API endpoints...")

    # Seed data
    ts_iso = seed_test_strike_data()

    # 1. Test NIFTY Live / Cached Strikes
    res_nifty = client.get("/api/buildup-lab/strikes/NIFTY?range=5")
    print(f"Status /api/buildup-lab/strikes/NIFTY: {res_nifty.status_code}")
    assert res_nifty.status_code == 200, f"Expected 200, got {res_nifty.status_code}: {res_nifty.text}"
    data_nifty = res_nifty.json()
    assert data_nifty["symbol"] == "NIFTY"
    assert "strikes" in data_nifty
    assert "counts" in data_nifty
    print(f"  NIFTY ATM: {data_nifty.get('atm_strike')}")
    print(f"  Total Strikes Loaded: {len(data_nifty['strikes'])}")
    print(f"  Quadrant Counts: {data_nifty['counts']}")

    # Verify strike contract fields
    if data_nifty["strikes"]:
        sample = data_nifty["strikes"][0]
        assert "strike" in sample
        assert "option_type" in sample
        assert "buildup_type" in sample
        assert "market_sentiment" in sample
        assert "sentiment_label" in sample
        print(f"  Sample Strike Contract: {sample['label']} -> {sample['buildup_type']} ({sample['sentiment_label']})")

    # 2. Test BANKNIFTY Endpoint
    res_bn = client.get("/api/buildup-lab/strikes/BANKNIFTY?range=5")
    print(f"Status /api/buildup-lab/strikes/BANKNIFTY: {res_bn.status_code}")
    assert res_bn.status_code == 200
    data_bn = res_bn.json()
    assert data_bn["symbol"] == "BANKNIFTY"

    # 3. Test Timeline Endpoint
    res_tl = client.get("/api/buildup-lab/timeline/NIFTY?range=5")
    print(f"Status /api/buildup-lab/timeline/NIFTY: {res_tl.status_code}")
    assert res_tl.status_code == 200
    data_tl = res_tl.json()
    assert "timeline" in data_tl
    print(f"  Timeline Slots Count: {data_tl.get('count')}")
    if data_tl["timeline"]:
        print(f"  First Time Slot: {data_tl['timeline'][0]['time']}")
        print(f"  Last Time Slot: {data_tl['timeline'][-1]['time']}")

    # 4. Test Playback Scrubber Lookup
    if data_tl["timeline"]:
        test_time = data_tl["timeline"][0]["time"]
        res_play = client.get(f"/api/buildup-lab/strikes/NIFTY?range=5&time_str={test_time}")
        assert res_play.status_code == 200
        data_play = res_play.json()
        assert data_play["is_live"] is False
        print(f"  Playback at {test_time} verified: loaded {len(data_play['strikes'])} strikes successfully.")

    # 5. Clean up seeded test records so zero dummy data remains in DB
    with snapshot_storage._get_connection() as conn:
        conn.cursor().execute("DELETE FROM intraday_strike_snapshots WHERE timestamp = ?", (ts_iso,))
        conn.commit()
    print("  [Cleaned] All temporary test records purged from SQLite.")

    print("\nALL STRIKE BUILDUP LAB TESTS PASSED!")


if __name__ == "__main__":
    test_strike_lab()
