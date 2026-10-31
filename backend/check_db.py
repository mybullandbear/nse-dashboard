import sqlite3

conn = sqlite3.connect('_archive/backend/nse_terminal.db')
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables in archive db:", cur.fetchall())

print("\n--- intraday_snapshots ---")
cur.execute("SELECT trade_date, COUNT(*), MIN(time_str), MAX(time_str) FROM intraday_snapshots GROUP BY trade_date ORDER BY trade_date DESC LIMIT 10")
for r in cur.fetchall():
    print(r)

print("\n--- signal_history ---")
cur.execute("SELECT trade_date, COUNT(*) FROM signal_history GROUP BY trade_date ORDER BY trade_date DESC LIMIT 10")
for r in cur.fetchall():
    print(r)

print("\n--- intraday_strike_snapshots ---")
cur.execute("SELECT trade_date, COUNT(*), MIN(time_str), MAX(time_str) FROM intraday_strike_snapshots GROUP BY trade_date ORDER BY trade_date DESC LIMIT 10")
for r in cur.fetchall():
    print(r)

print("\n--- Columns in intraday_snapshots ---")
cur.execute("PRAGMA table_info(intraday_snapshots)")
for col in cur.fetchall():
    print(col)
