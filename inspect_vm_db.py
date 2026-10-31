import sqlite3
import os

db_path = "/home/ubuntu/nse-dashboard/backend/nse_terminal.db"
if not os.path.exists(db_path):
    print(f"DB File {db_path} not found!")
else:
    print(f"DB Path: {db_path}, Size: {os.path.getsize(db_path)} bytes")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print("Tables found:", tables)
    counts = {}
    for t in tables:
        try:
            counts[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception as e:
            counts[t] = f"Error: {e}"
    print("Record counts:", counts)
