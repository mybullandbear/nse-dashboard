"""
SQLAlchemy ORM models for date-wise persistence:
- SmartMoneyShiftModel
- DailyMarketSnapshotModel
- SignalLifecycleModel
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, Index
from app.db.database import Base


class SmartMoneyShiftModel(Base):
    __tablename__ = "smart_money_shifts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    trade_date = Column(String(10), index=True)  # Format: YYYY-MM-DD
    timestamp = Column(String(30), index=True)   # ISO timestamp string
    symbol = Column(String(20), index=True)      # NIFTY, BANKNIFTY, etc.
    shift_text = Column(Text, nullable=False)    # Description of OI shift or Block Trade
    shift_type = Column(String(10), index=True)  # BULL, BEAR, NEUT
    strike_price = Column(Float, nullable=True)
    option_type = Column(String(5), nullable=True)  # CE or PE
    oi_change = Column(Integer, default=0)
    conviction_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class DailyMarketSnapshotModel(Base):
    __tablename__ = "daily_market_snapshots"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    trade_date = Column(String(10), index=True)  # YYYY-MM-DD
    timestamp = Column(String(30), index=True)
    symbol = Column(String(20), index=True)
    spot_price = Column(Float, default=0.0)
    atm_strike = Column(Float, default=0.0)
    pcr = Column(Float, default=0.0)
    vix = Column(Float, default=0.0)
    max_pain = Column(Float, default=0.0)
    call_writing_conviction = Column(Float, default=0.0)
    put_writing_conviction = Column(Float, default=0.0)
    expected_decay = Column(Float, default=0.0)
    total_ce_oi = Column(Float, default=0.0)
    total_pe_oi = Column(Float, default=0.0)
    total_ce_chg = Column(Float, default=0.0)
    total_pe_chg = Column(Float, default=0.0)
    data_source = Column(String(20), default="SIMULATED")
    created_at = Column(DateTime, default=datetime.utcnow)




class SignalLifecycleModel(Base):
    __tablename__ = "signal_lifecycle_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    signal_id = Column(String(50), unique=True, index=True)
    trade_date = Column(String(10), index=True)
    symbol = Column(String(20), index=True)
    strategy = Column(String(100), nullable=False)
    direction = Column(String(20), default="NEUTRAL")
    status = Column(String(20), default="GENERATED")  # GENERATED, CONFIRMING, ACTIVE, CLOSED
    entry_time = Column(String(30))
    entry_spot = Column(Float, default=0.0)
    entry_premium = Column(Float, default=0.0)
    target_premium = Column(Float, default=0.0)
    stop_loss = Column(Float, default=0.0)
    margin_required = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    exit_time = Column(String(30), nullable=True)
    exit_spot = Column(Float, nullable=True)
    exit_premium = Column(Float, nullable=True)
    exit_reason = Column(String(50), nullable=True)
    realized_pnl_pts = Column(Float, default=0.0)
    realized_pnl_rupees = Column(Float, default=0.0)
    realized_roi_pct = Column(Float, default=0.0)
    mfe_pts = Column(Float, default=0.0)
    mae_pts = Column(Float, default=0.0)
    is_win = Column(Boolean, nullable=True)
    
    # Phase 3 Timestamp Semantics
    signal_initiated_at = Column(String(50), nullable=True)
    signal_initiated_at_ist = Column(String(50), nullable=True)
    market_timestamp_at_initiation = Column(String(50), nullable=True)
    last_evaluated_at = Column(String(50), nullable=True)
    last_updated_at = Column(String(50), nullable=True)
    timestamp_status = Column(String(30), default="VERIFIED")
    confirming_started_at = Column(String(50), nullable=True)
    activated_at = Column(String(50), nullable=True)
    closed_at = Column(String(50), nullable=True)
    
    # Phase 4 Live vs Historical Signal Separation
    signal_category = Column(String(40), default="LIVE_SIGNAL")
    is_live = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)




class SignalOutcomeRecordModel(Base):
    __tablename__ = "vcc_signal_outcome_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    signal_id = Column(String(80), unique=True, index=True)
    trade_date = Column(String(10), index=True)
    timestamp = Column(String(30), index=True)
    symbol = Column(String(20), index=True)
    signal_type = Column(String(100), index=True)
    direction = Column(String(20), default="NEUTRAL")
    strength = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    positioning_score = Column(Float, default=0.0)
    price_score = Column(Float, default=0.0)
    confluence_score = Column(Float, default=0.0)
    spot_price = Column(Float, default=0.0)

    # Retrospective future outcomes
    spot_after_5m = Column(Float, nullable=True)
    spot_after_15m = Column(Float, nullable=True)
    spot_after_30m = Column(Float, nullable=True)

    return_5m = Column(Float, nullable=True)
    return_15m = Column(Float, nullable=True)
    return_30m = Column(Float, nullable=True)

    max_favorable_move = Column(Float, nullable=True)
    max_adverse_move = Column(Float, nullable=True)

    is_success_5m = Column(Boolean, nullable=True)
    is_success_15m = Column(Boolean, nullable=True)
    is_success_30m = Column(Boolean, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class VCCLiveSignalAuditModel(Base):
    __tablename__ = "vcc_live_signal_audits"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    snapshot_id = Column(String(100), unique=True, index=True)
    trade_date = Column(String(10), index=True)
    timestamp = Column(String(30), index=True)
    symbol = Column(String(20), index=True)
    session_slot = Column(String(20), index=True)

    spot_price = Column(Float, default=0.0)
    option_chain_timestamp = Column(String(30), nullable=True)
    spot_timestamp = Column(String(30), nullable=True)
    option_data_age_sec = Column(Float, default=0.0)
    spot_data_age_sec = Column(Float, default=0.0)
    data_quality_status = Column(String(30), default="DATA QUALITY GOOD") # DATA QUALITY GOOD, DATA QUALITY DEGRADED, DATA QUALITY INVALID

    positioning_score = Column(Float, default=0.0)
    price_confirmation_score = Column(Float, default=0.0)
    final_confluence_score = Column(Float, default=0.0)
    confluence_label = Column(String(50), default="MODERATE / TWO-SIDED")

    directional_flow_label = Column(String(50), default="NEUTRAL")
    net_flow_lakhs = Column(Float, default=0.0)
    pe_flow_lakhs = Column(Float, default=0.0)
    ce_flow_lakhs = Column(Float, default=0.0)
    total_activity_lakhs = Column(Float, default=0.0)
    pcr = Column(Float, default=0.0)
    atm_straddle_premium = Column(Float, default=0.0)

    support_wall = Column(Float, default=0.0)
    resistance_wall = Column(Float, default=0.0)
    wall_migration_direction = Column(String(30), default="STABLE")
    breakout_status = Column(String(50), default="NO BREAKOUT")
    range_compression_status = Column(String(50), default="NORMAL")
    atm_pressure_score = Column(Float, default=0.0)

    operational_state = Column(String(50), index=True)
    market_regime = Column(String(50), default="RANGE", index=True)
    signal_direction = Column(String(20), default="NEUTRAL", index=True)
    signal_lifecycle_stage = Column(String(30), default="CREATED")
    lifetime_sec = Column(Float, default=0.0)

    evidence_count = Column(Integer, default=0)
    conflict_count = Column(Integer, default=0)
    model_confidence = Column(Float, default=0.0)
    persistence_pct = Column(Float, default=0.0)
    historical_sample_size = Column(Integer, default=0)
    historical_reliability_pct = Column(Float, default=0.0)

    outcome_evaluated = Column(Boolean, default=False)
    spot_t5 = Column(Float, nullable=True)
    spot_t15 = Column(Float, nullable=True)
    spot_t30 = Column(Float, nullable=True)

    return_t5_pct = Column(Float, nullable=True)
    return_t15_pct = Column(Float, nullable=True)
    return_t30_pct = Column(Float, nullable=True)

    mfe_t30_pct = Column(Float, nullable=True)
    mae_t30_pct = Column(Float, nullable=True)

    directional_correctness_5m = Column(String(20), nullable=True)
    directional_correctness_15m = Column(String(20), nullable=True)
    directional_correctness_30m = Column(String(20), nullable=True)

    false_signal_category = Column(String(50), default="NONE", index=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class RawOptionChainObservationModel(Base):
    __tablename__ = "raw_option_chain_observations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    observed_at = Column(String(30), index=True, nullable=False)   # ISO timestamp string in IST
    trade_date = Column(String(10), index=True, nullable=False)    # YYYY-MM-DD
    symbol = Column(String(20), index=True, nullable=False)        # NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY
    expiry = Column(String(20), index=True, nullable=False)        # e.g., "08-Sep-2026"
    strike = Column(Float, index=True, nullable=False)             # Strike price
    option_type = Column(String(5), index=True, nullable=False)    # "CE" or "PE"
    
    spot = Column(Float, nullable=True)                            # Observed spot price
    ltp = Column(Float, nullable=True)                             # Last traded price (NULL if missing)
    oi = Column(Float, nullable=True)                              # Open interest (NULL if missing)
    oi_change = Column(Float, nullable=True)                       # Open interest change (NULL if missing)
    
    bid = Column(Float, nullable=True)                             # Bid price
    ask = Column(Float, nullable=True)                             # Ask price
    volume = Column(Float, nullable=True)                          # Volume
    iv = Column(Float, nullable=True)                              # Implied volatility
    
    underlying_timestamp = Column(String(30), nullable=True)
    provider_timestamp = Column(String(30), nullable=True)
    
    provider = Column(String(30), index=True, nullable=False, default="FYERS_LIVE")
    data_status = Column(String(30), nullable=False, default="REAL_LIVE")
    data_quality = Column(String(30), nullable=False, default="GOOD")
    session_state = Column(String(20), nullable=False, default="LIVE_MARKET")
    
    capture_run_id = Column(String(50), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_raw_opt_obs_sym_obs", "symbol", "observed_at"),
        Index("ix_raw_opt_obs_contract", "symbol", "expiry", "strike", "option_type", "observed_at"),
    )


class SignalProvenanceRecordModel(Base):
    __tablename__ = "signal_provenance_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    signal_id = Column(String(50), unique=True, index=True, nullable=False)
    symbol = Column(String(20), index=True, nullable=False)
    strategy = Column(String(100), nullable=False)
    direction = Column(String(20), nullable=False)

    # Time Provenance
    signal_initiated_at = Column(String(50), nullable=False)
    signal_initiated_at_ist = Column(String(50), nullable=False)
    market_timestamp_at_initiation = Column(String(50), nullable=False)
    provider_timestamp_at_initiation = Column(String(50), nullable=True)
    provenance_created_at = Column(DateTime, default=datetime.utcnow)

    # Source Ingestion Metadata
    provider = Column(String(30), nullable=False, default="FYERS_LIVE")
    data_status = Column(String(30), nullable=False, default="REAL_LIVE")
    data_quality = Column(String(30), nullable=False, default="GOOD")
    session_state = Column(String(20), nullable=False, default="LIVE_MARKET")
    capture_run_id = Column(String(50), index=True, nullable=True)

    # Market State at Initiation
    spot_at_initiation = Column(Float, nullable=True)
    expiry_at_initiation = Column(String(20), nullable=True)
    atm_at_initiation = Column(Float, nullable=True)

    # Option Analytics at Initiation
    pcr = Column(Float, nullable=True)
    atm_pcr = Column(Float, nullable=True)
    call_wall = Column(Float, nullable=True)
    put_wall = Column(Float, nullable=True)
    call_wall_oi = Column(Float, nullable=True)
    put_wall_oi = Column(Float, nullable=True)
    wall_velocity = Column(Float, nullable=True)
    wall_velocity_status = Column(String(30), nullable=True)

    # Smart Money at Initiation
    spos = Column(Float, nullable=True)
    sflow = Column(Float, nullable=True)
    put_conviction = Column(Float, nullable=True)
    call_conviction = Column(Float, nullable=True)
    net_bias = Column(String(20), nullable=True)
    smart_money_status = Column(String(30), nullable=True)

    # Signal Qualification Snapshot
    qualification_state = Column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_sig_prov_sym_init", "symbol", "signal_initiated_at"),
    )



