import sqlite3

conn = sqlite3.connect("/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db")
c = conn.cursor()
c.execute("""
    SELECT time_str, spot, confluence, pcr 
    FROM intraday_snapshots 
    WHERE trade_date='2026-09-24' AND symbol='MIDCPNIFTY' AND time_str BETWEEN '13:50' AND '13:55'
    ORDER BY timestamp ASC
""")
rows = c.fetchall()
print(f"Rows found: {len(rows)}")
for r in rows:
    print(r)
