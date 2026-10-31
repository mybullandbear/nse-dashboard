import sqlite3

conn = sqlite3.connect("/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db")
c = conn.cursor()
c.execute("""
    SELECT symbol, MIN(pcr), AVG(pcr), MAX(pcr)
    FROM intraday_snapshots
    GROUP BY symbol
""")
for r in c.fetchall():
    print(f"Symbol: {r[0]:12s} | Min PCR: {r[1]:.2f} | Avg PCR: {r[2]:.2f} | Max PCR: {r[3]:.2f}")
