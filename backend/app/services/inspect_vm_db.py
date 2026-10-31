import sqlite3

db_path = "/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

print("Tables:", [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])

for table in ["intraday_snapshots", "intraday_strike_snapshots", "signal_history"]:
    try:
        c.execute(f"SELECT trade_date, COUNT(*), MIN(time_str), MAX(time_str) FROM {table} GROUP BY trade_date")
        rows = c.fetchall()
        print(f"\n--- {table} ---")
        for r in rows:
            print(f"Date: {r[0]} | Count: {r[1]} | Min Time: {r[2]} | Max Time: {r[3]}")
    except Exception as e:
        print(f"Error reading {table}: {e}")
