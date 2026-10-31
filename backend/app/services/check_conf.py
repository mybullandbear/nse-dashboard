import sqlite3

conn = sqlite3.connect("/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db")
c = conn.cursor()
c.execute("""
    SELECT trade_date, symbol, MIN(confluence), AVG(confluence), MAX(confluence), COUNT(*)
    FROM intraday_snapshots
    GROUP BY trade_date, symbol
""")
for r in c.fetchall():
    print(f"Date: {r[0]} | Sym: {r[1]:10s} | Min: {r[2]} | Avg: {r[3]:.1f} | Max: {r[4]} | Count: {r[5]}")
