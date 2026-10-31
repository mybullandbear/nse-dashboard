import sqlite3

conn = sqlite3.connect("/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db")
c = conn.cursor()
for table in ["signal_history", "intraday_snapshots", "intraday_strike_snapshots"]:
    c.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in c.fetchall()]
    print(f"\nTable: {table}\nColumns: {cols}")

c.execute("SELECT COUNT(*) FROM signal_history")
print("\nsignal_history row count:", c.fetchone()[0])
c.execute("SELECT * FROM signal_history LIMIT 3")
for r in c.fetchall():
    print(r)
