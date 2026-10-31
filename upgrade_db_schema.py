"""
Database Schema Upgrade Script for VCCLiveSignalAuditModel.
Applies missing columns to SQLite database safely.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.db.database import engine, Base
from app.db.models import VCCLiveSignalAuditModel
from sqlalchemy import text

def upgrade_schema():
    print("Upgrading vcc_live_signal_audits schema...")
    with engine.connect() as conn:
        columns_to_add = [
            ("spot_timestamp", "VARCHAR(30)"),
            ("total_activity_lakhs", "FLOAT DEFAULT 0.0"),
            ("range_compression_status", "VARCHAR(50) DEFAULT 'NORMAL'"),
            ("atm_pressure_score", "FLOAT DEFAULT 0.0"),
            ("market_regime", "VARCHAR(50) DEFAULT 'RANGE'"),
            ("signal_direction", "VARCHAR(20) DEFAULT 'NEUTRAL'"),
            ("signal_lifecycle_stage", "VARCHAR(30) DEFAULT 'CREATED'"),
            ("lifetime_sec", "FLOAT DEFAULT 0.0"),
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                conn.execute(text(f"ALTER TABLE vcc_live_signal_audits ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                print(f"Added column {col_name}")
            except Exception as e:
                print(f"Column {col_name} already exists or error: {e}")

    # Re-create all tables if missing
    Base.metadata.create_all(bind=engine)
    print("Schema upgrade complete.")

if __name__ == "__main__":
    upgrade_schema()
