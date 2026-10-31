import sqlite3
import os

db_path = os.path.expanduser('~/nse-dashboard/backend/app/db/terminal_snapshots.db')
if not os.path.exists(db_path):
    db_path = 'app/db/terminal_snapshots.db'

conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("--- Snapshots by symbol on 2026-09-18 ---")
cur.execute("""
    SELECT symbol, min(spot), max(spot), min(time_str), max(time_str), count(*) 
    FROM intraday_snapshots 
    WHERE trade_date='2026-09-18' 
    GROUP BY symbol
""")
for r in cur.fetchall():
    print(r)

print("\n--- Snapshots by symbol on 2026-09-19 ---")
cur.execute("""
    SELECT symbol, min(spot), max(spot), min(time_str), max(time_str), count(*) 
    FROM intraday_snapshots 
    WHERE trade_date='2026-09-19' 
    GROUP BY symbol
""")
for r in cur.fetchall():
    print(r)
