"""
Database connection and session initialization module.
Supports SQLite out-of-the-box or PostgreSQL via DATABASE_URL setting.
"""
import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

db_url = settings.DATABASE_URL
if db_url.startswith("sqlite:///./") or db_url == "sqlite:///nse_terminal.db":
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    db_file = "nse_terminal.db"
    abs_db_path = os.path.join(backend_dir, db_file)
    db_url = f"sqlite:///{abs_db_path}"

if db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(db_url, connect_args=connect_args, echo=False)
else:
    engine = create_engine(db_url, echo=False, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Create all tables in the database if they do not exist and perform storage cleanup/schema migration."""
    try:
        from app.db import models  # ensure models are imported
        from sqlalchemy import text
        Base.metadata.create_all(bind=engine)
        
        # Auto-migrate SQLite schema for missing columns
        if engine.url.drivername.startswith("sqlite"):
            with engine.connect() as conn:
                cols_to_add = [
                    ("daily_market_snapshots", "call_writing_conviction", "FLOAT DEFAULT 0.0"),
                    ("daily_market_snapshots", "put_writing_conviction", "FLOAT DEFAULT 0.0"),
                    ("daily_market_snapshots", "expected_decay", "FLOAT DEFAULT 0.0"),
                    ("daily_market_snapshots", "total_ce_oi", "FLOAT DEFAULT 0.0"),
                    ("daily_market_snapshots", "total_pe_oi", "FLOAT DEFAULT 0.0"),
                    ("daily_market_snapshots", "total_ce_chg", "FLOAT DEFAULT 0.0"),
                    ("daily_market_snapshots", "total_pe_chg", "FLOAT DEFAULT 0.0"),
                    ("signal_lifecycle_records", "signal_initiated_at", "VARCHAR(50)"),
                    ("signal_lifecycle_records", "signal_initiated_at_ist", "VARCHAR(50)"),
                    ("signal_lifecycle_records", "market_timestamp_at_initiation", "VARCHAR(50)"),
                    ("signal_lifecycle_records", "last_evaluated_at", "VARCHAR(50)"),
                    ("signal_lifecycle_records", "last_updated_at", "VARCHAR(50)"),
                    ("signal_lifecycle_records", "timestamp_status", "VARCHAR(30) DEFAULT 'VERIFIED'"),
                    ("signal_lifecycle_records", "confirming_started_at", "VARCHAR(50)"),
                    ("signal_lifecycle_records", "activated_at", "VARCHAR(50)"),
                    ("signal_lifecycle_records", "closed_at", "VARCHAR(50)"),
                    ("signal_lifecycle_records", "signal_category", "VARCHAR(40) DEFAULT 'LIVE_SIGNAL'"),
                    ("signal_lifecycle_records", "is_live", "BOOLEAN DEFAULT 0")
                ]
                for tbl_name, col_name, col_type in cols_to_add:
                    try:
                        conn.execute(text(f"ALTER TABLE {tbl_name} ADD COLUMN {col_name} {col_type};"))
                        conn.commit()
                        logger.info(f"Migrated column {col_name} into {tbl_name}")
                    except Exception:
                        pass # column already exists
                        
        logger.info(f"Database initialized successfully with URL: {db_url}")
        cleanup_old_data(market_days_to_keep=7, signal_days_to_keep=30)
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")



def cleanup_old_data(market_days_to_keep: int = 7, signal_days_to_keep: int = 30, raw_days_to_keep: int = 3):
    """
    Purge database records:
    - Raw option chain observations (RawOptionChainObservationModel) older than 3 days.
    - Market data (DailyMarketSnapshotModel, SmartMoneyShiftModel) older than 7 days.
    - Signal lifecycle records (SignalLifecycleModel) older than 30 days.
    - Truncate large log files (>5MB) to keep system fast and fluent.
    - Run VACUUM on SQLite to release unneeded disk space.
    """
    try:
        from datetime import datetime, timedelta
        from sqlalchemy import text
        from app.db.models import SmartMoneyShiftModel, DailyMarketSnapshotModel, SignalLifecycleModel, RawOptionChainObservationModel
        from app.services.market_hours import get_ist_now

        now_ist = get_ist_now()
        raw_cutoff_date = (now_ist.date() - timedelta(days=raw_days_to_keep)).strftime("%Y-%m-%d")
        raw_cutoff_ts = (now_ist - timedelta(days=raw_days_to_keep)).isoformat()

        market_cutoff = datetime.utcnow() - timedelta(days=market_days_to_keep)
        market_cutoff_str = market_cutoff.strftime("%Y-%m-%d")

        signal_cutoff = datetime.utcnow() - timedelta(days=signal_days_to_keep)
        signal_cutoff_str = signal_cutoff.strftime("%Y-%m-%d")

        db = SessionLocal()
        try:
            # Delete raw option chain observations older than 3 days
            del_raw = db.query(RawOptionChainObservationModel).filter(
                (RawOptionChainObservationModel.trade_date < raw_cutoff_date) | 
                (RawOptionChainObservationModel.observed_at < raw_cutoff_ts)
            ).delete(synchronize_session=False)

            # Delete market data older than 7 days
            del_shifts = db.query(SmartMoneyShiftModel).filter(
                (SmartMoneyShiftModel.created_at < market_cutoff) | (SmartMoneyShiftModel.trade_date < market_cutoff_str)
            ).delete(synchronize_session=False)

            del_snaps = db.query(DailyMarketSnapshotModel).filter(
                (DailyMarketSnapshotModel.created_at < market_cutoff) | (DailyMarketSnapshotModel.trade_date < market_cutoff_str)
            ).delete(synchronize_session=False)

            # Delete signals older than 30 days (preserve ACTIVE signals)
            del_sigs = db.query(SignalLifecycleModel).filter(
                SignalLifecycleModel.status != "ACTIVE",
                ((SignalLifecycleModel.created_at < signal_cutoff) | (SignalLifecycleModel.trade_date < signal_cutoff_str))
            ).delete(synchronize_session=False)

            db.commit()

            if engine.url.drivername.startswith("sqlite"):
                with engine.connect() as conn:
                    conn.execute(text("VACUUM;"))

            logger.info(
                f"[Storage Retention] Purged raw observations older than {raw_days_to_keep} days ({del_raw} rows), "
                f"market data older than {market_days_to_keep} days ({del_shifts} shifts, {del_snaps} snaps), "
                f"and signals older than {signal_days_to_keep} days ({del_sigs} signals removed)."
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Error executing DB cleanup: {e}")
        finally:
            db.close()

        # Log maintenance: truncate oversized log files in backend directory
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for log_file in ["fyersApi.log", "fyersRequests.log"]:
            log_path = os.path.join(backend_dir, log_file)
            if os.path.exists(log_path) and os.path.getsize(log_path) > 5 * 1024 * 1024:  # > 5MB
                try:
                    with open(log_path, "w") as f:
                        f.write(f"[{datetime.utcnow().isoformat()}] Log file auto-truncated for performance optimization.\n")
                    logger.info(f"Auto-truncated large log file: {log_file}")
                except Exception as log_ex:
                    logger.warning(f"Could not truncate log file {log_file}: {log_ex}")

    except Exception as ex:
        logger.error(f"Failed to run storage cleanup: {ex}")


def get_db():
    """Dependency generator for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

