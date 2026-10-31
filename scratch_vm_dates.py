import sqlite3

c = sqlite3.connect('/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db').cursor()
print(c.execute("SELECT trade_date, COUNT(*), MIN(time_str), MAX(time_str) FROM intraday_snapshots GROUP BY trade_date").fetchall())
