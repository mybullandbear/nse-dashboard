import sqlite3

db_path = '/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("DELETE FROM intraday_snapshots WHERE trade_date='2026-09-17' AND time_str < '09:15'")
deleted = c.rowcount
conn.commit()
print(f"Purged {deleted} pre-market snapshots from 2026-09-17.")

c.execute("SELECT MIN(time_str), MAX(time_str), COUNT(id) FROM intraday_snapshots WHERE trade_date='2026-09-17' AND symbol='NIFTY'")
row = c.fetchone()
print(f"NIFTY today range: min={row[0]}, max={row[1]}, count={row[2]}")

c.execute("SELECT MIN(time_str), MAX(time_str), COUNT(id) FROM intraday_snapshots WHERE trade_date='2026-09-17' AND symbol='BANKNIFTY'")
row = c.fetchone()
print(f"BANKNIFTY today range: min={row[0]}, max={row[1]}, count={row[2]}")
