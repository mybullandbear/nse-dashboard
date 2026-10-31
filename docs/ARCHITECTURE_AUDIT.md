# VCC V3.2 ARCHITECTURE AUDIT & MODULARIZATION BLUEPRINT

**Document Version:** 1.0.0  
**Target System:** NSE Alpha-Sell Options Terminal & Visual Command Center (VCC V3.2)  
**Date:** August 28, 2026  
**Status:** Audit Complete — Baseline Blueprint  

---

## EXECUTIVE SUMMARY

This document provides a comprehensive, non-destructive codebase audit of the **NSE Alpha-Sell Options Terminal & Visual Command Center (VCC V3.2)**. The objective of this audit is to analyze the existing architecture, inventory all business logic, database structures, APIs, and frontend components, and propose a modular target architecture.

Per governance guidelines:
- **No working analytical logic, formulas, or thresholds are modified.**
- **No live trading signals or look-ahead audit rules are disrupted.**
- **This blueprint serves as a foundational roadmap for Phase 2 modularization.**

---

## 1. CURRENT ARCHITECTURE

The current application follows a hybrid monolithic architecture in FastAPI with background async polling tasks, a SQLite persistent storage engine, and a embedded single-file React 18 SPA frontend.

```
[External Sources]
  ├── Fyers Broker API v3 (fyers_apiv3)
  ├── NSE India Web Scraper (curl_cffi)
  ├── Yahoo Finance Sync Client
  └── Live Market Simulator (mock_engine.py)
         │
         ▼
[Ingestion & Polling Layer (main.py / market.py)]
  ├── fyers_live_polling_loop (1s-3s)
  ├── nse_slow_polling_loop (30s)
  ├── stock_polling_loop (60s)
  └── db_cleanup_loop (4h)
         │
         ▼
[Core Intelligence & Processing (engines/ & services/)]
  ├── VCCIntelligenceEngine (vcc_intelligence_engine.py)
  ├── LiveSignalAuditService (live_signal_audit_service.py)
  ├── SmartMoneyService (smart_money_service.py)
  ├── SellerEngine (seller_engine.py)
  └── SignalLifecycleEngine (signal_lifecycle.py)
         │
         ▼
[Storage & Cache Layer]
  ├── SQLite Database (nse_terminal.db via SQLAlchemy)
  └── In-Memory TTL Cache (cache/__init__.py)
         │
         ▼
[API & Delivery Layer (api/)]
  ├── /api/dashboard/{symbol} (REST)
  ├── /api/vcc/intelligence & /api/vcc/replay (REST)
  ├── /api/fyers/* (OAuth & Credentials)
  └── /ws (WebSocket Broadcast Manager)
         │
         ▼
[Presentation Layer]
  └── Single-File React 18 SPA (backend/app/static/index.html - 4498 lines)
```

---

## 2. CURRENT DATA FLOW

```
[Raw Broker Feed (Fyers v3)] / [NSE Scraper (curl_cffi)] / [Simulator Fallback]
                       │
                       ▼
           [market.py: get_dashboard(symbol)]
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
[parse_option_chain]       [get_indices() / VIX]
         │                           │
         └─────────────┬─────────────┘
                       ▼
   [vcc_intelligence_engine.compute_vcc_intelligence()]
    - Market Session Engine (09:15-15:30 IST)
    - PCR & ATM Strike Matrix (±25 strikes)
    - Support / Resistance Wall Detection & Velocity (pts/hr)
    - Institutional CE/PE Flow (₹ Lakhs) & Net Flow
    - Confluence Score (0-100) & Operational State
                       │
                       ▼
   [live_signal_audit_service.record_live_signal_snapshot()]
    - DB Insert: vcc_live_signal_audits (Immutable)
    - Composite Primary Key Deduplication
                       │
                       ▼
       [live_signal_audit_service.evaluate_pending_signal_outcomes()]
        - Look-ahead outcome evaluation (T+5m, T+15m, T+30m)
        - Forward window MFE / MAE calculations
        - Excludes non-directional signals (WATCH, SIGNAL CONFLICT)
                       │
                       ▼
           [FastAPI REST & WebSocket Broadcast]
                       │
                       ▼
          [React 18 SPA (index.html)]
```

---

## 3. CURRENT MODULE RESPONSIBILITIES

| File Path | Current Primary Responsibility | Dependencies | Dependents | Identified Architectural Issues | Proposed Target Responsibility |
|---|---|---|---|---|---|
| `backend/app/main.py` | FastAPI application initialization, lifespans, background polling tasks, router mounting, static file hosting. | `api/*`, `services/*`, `db/*` | Server entry point | Contains polling loop business logic and database refresh triggers directly in main loop. | Pure application startup, middleware, and lifecycle manager. |
| `backend/app/api/market.py` | API routes for dashboard, indices, OI spurts, VCC intelligence, replay, plus polling helper functions. | `engines/*`, `services/*`, `cache` | Frontend, WebSocket | High coupling: handles routing, option chain parsing, fallback simulation, audit triggers, and caching in a single 1000+ line file. | Pure API Router delegating to Application Controllers / Use Cases. |
| `backend/app/api/auth.py` | Fyers OAuth v3 endpoints (`/status`, `/credentials`, `/login`, `/token`, `/callback`). | `services/fyers_fetcher`, `cache` | Frontend | Combines HTTP routing with connection testing logic. | Pure OAuth / Auth Router. |
| `backend/app/api/smart_money.py` | Smart money shifts REST endpoints. | `services/smart_money_service`, `db` | Frontend | Minimal issues; standard route handler. | Pure Smart Money Router. |
| `backend/app/api/stocks.py` | Stock gainers/losers intelligence endpoints. | `services/stock_*` | Frontend | Contains inline filtering and data assembly. | Stock Intelligence Router. |
| `backend/app/api/websocket.py` | WebSocket manager and broadcast loop. | `cache`, `api/market` | Frontend | Directly imports `get_dashboard` from `api/market`. | Dedicated Real-time Push Gateway. |
| `backend/app/config.py` | Environment variable loader & settings container. | `pydantic_settings` | Entire backend | Contains hardcoded default fallbacks. | Central Configuration Service. |
| `backend/app/db/database.py` | SQLAlchemy Engine, SessionLocal factory, SQLite PRAGMA execution, table init. | `sqlalchemy` | Models & Services | Direct DB session creation scattered across services. | Database Infrastructure Provider. |
| `backend/app/db/models.py` | SQLAlchemy ORM Models (5 tables). | `sqlalchemy` | DB & Services | Database schema mixed with domain default values. | Pure Persistence Domain Models. |
| `backend/app/engines/vcc_intelligence_engine.py` | Core VCC V3.2 Intelligence Engine (Session engine, confluence, walls, migration, flow, regime, state). | `schemas`, `services/market_hours` | `api/market`, `live_signal_audit_service` | Single 1300+ line engine carrying out multiple distinct analytical sub-tasks. | Pure Domain Analytical Engine / Domain Service. |
| `backend/app/engines/seller_engine.py` | Seller option strategy recommendations (straddles, condors, directional). | `schemas` | `api/market` | Contains hardcoded strategy delta/premium rules. | Option Strategy Engine. |
| `backend/app/engines/signal_lifecycle.py` | Signal state transitions (`GENERATED` -> `CLOSED`), trade management. | `db`, `schemas` | `api/market` | Stateful singleton managing intraday memory & DB. | Signal Lifecycle Domain Engine. |
| `backend/app/engines/trade_scorer.py` | Win-rate probability scoring. | `schemas` | `seller_engine` | Hardcoded weight matrices. | Trade Scoring Engine. |
| `backend/app/engines/vcc_signal_lab.py` | Backtester and historical signal simulation lab. | `db`, `vcc_intelligence_engine` | Standalone / CLI | Queries DB directly with raw SQL/ORM loops. | Historical Backtesting Service. |
| `backend/app/services/fyers_fetcher.py` | Fyers API v3 client, OAuth token sanitization, live quote fetching. | `fyers_apiv3` | `api/market`, `auth` | Directly modifies local JSON config file (`fyers_config.json`). | Broker Data Source Gateway. |
| `backend/app/services/nse_fetcher.py` | Scrapes NSE India web option chains via `curl_cffi`. | `curl_cffi`, `bs4` | `api/market` | Web scraping logic tightly coupled to custom HTTP headers. | Exchange Scraper Data Source Gateway. |
| `backend/app/services/live_signal_audit_service.py` | 20-Point Governance Audit Engine, pending outcome evaluation, MFE/MAE. | `db`, `schemas`, `vcc_intelligence_engine` | `api/market` | Handles DB writes, look-ahead calculations, and stats aggregation in one module. | Governance & Audit Domain Service. |
| `backend/app/services/smart_money_service.py` | Institutional flow analysis & block trade shift detection. | `db`, `schemas` | `api/market` | Direct database writes inside processing functions. | Smart Money Analytical Service. |
| `backend/app/services/mock_engine.py` | Synthetic option chain and index tick generator for fallback. | `schemas`, `db` | `api/market` | Queries DB for baseline when fallback is active. | Simulation Data Source Gateway. |
| `backend/app/services/market_hours.py` | IST session boundary validator. | `datetime`, `pytz` | Entire backend | Utility function imported in multiple places. | Domain Session Policy Service. |
| `backend/app/services/option_chain.py` | Option chain parsing, Greeks calculation, PCR computation. | `schemas` | `api/market` | Intertwined with delta/theta estimation routines. | Option Math & Normalization Service. |
| `backend/app/static/index.html` | Embedded single-file React 18 SPA (4498 lines). | CDN React, Tailwind, Lucide | End-User Browser | Contains inline CSS, state management, API polling, WebSocket listener, and straddle decay math. | Presentation Layer (SPA). |

---

## 4. COUPLING ANALYSIS

```
[api/market.py] ──TIGHTLY COUPLED TO──> [fyers_fetcher.py]
[api/market.py] ──TIGHTLY COUPLED TO──> [nse_fetcher.py]
[api/market.py] ──TIGHTLY COUPLED TO──> [mock_engine.py]
[api/market.py] ──TIGHTLY COUPLED TO──> [vcc_intelligence_engine.py]
[api/market.py] ──TIGHTLY COUPLED TO──> [live_signal_audit_service.py]
[api/market.py] ──TIGHTLY COUPLED TO──> [smart_money_service.py]
[api/market.py] ──TIGHTLY COUPLED TO──> [seller_engine.py]
[api/market.py] ──TIGHTLY COUPLED TO──> [signal_lifecycle.py]
[api/market.py] ──TIGHTLY COUPLED TO──> [cache/__init__.py]
[websocket.py]  ──TIGHTLY COUPLED TO──> [api/market.py]
```

### Critical Architectural Tight-Couplings
1. **API Layer Impregnated with Business & Orchestration Logic**: `api/market.py` is serving as API router, ingestion orchestrator, caching layer, fallback manager, and response formatter simultaneously.
2. **Direct Cross-Service Database Access**: `live_signal_audit_service.py`, `smart_money_service.py`, `signal_lifecycle.py`, and `mock_engine.py` each manage their own raw SQLAlchemy `SessionLocal()` transactions.
3. **Data Source Leakage**: `api/market.py` directly handles Fyers responses, NSE scrapers, and simulator fallbacks inline.

---

## 5. BUSINESS LOGIC INVENTORY

All core analytical formulas and business logic are inventory-cataloged below and **must be strictly preserved without modification**:

| Analytical Component | Location in Codebase | Formula / Operational Logic | Governance Rule |
|---|---|---|---|
| **Market Session State** | `vcc_intelligence_engine.py` (lines 370-410) | `09:00-09:15`: `PRE-MARKET`<br>`09:15-15:30`: `LIVE MARKET`<br>`15:30-16:00`: `POST-MARKET`<br>Else: `MARKET CLOSED` | Execution `DISABLED` outside 09:15-15:30 IST. |
| **ATM Strike Calculation** | `option_chain.py` & `vcc_intelligence_engine.py` | $\text{ATM} = \text{round}(\text{Spot} / \text{Step}) \times \text{Step}$ | Step: 50 for NIFTY/FINNIFTY/MIDCPNIFTY; 100 for BANKNIFTY/SENSEX. |
| **PCR Variants** | `option_chain.py` (lines 110-145) | Overall PCR: $\sum \text{Put OI} / \sum \text{Call OI}$<br>ATM $\pm 5$ PCR: Put/Call OI ratio restricted to 5 strikes around ATM | Zero-division guarded with `max(1, Call OI)`. |
| **Support / Resistance Walls** | `vcc_intelligence_engine.py` (lines 450-520) | Support Wall: Strike below ATM with max Put OI.<br>Resistance Wall: Strike above ATM with max Call OI. | Evaluated across ATM $\pm 10$ strike matrix. |
| **Wall Migration Velocity** | `vcc_intelligence_engine.py` (lines 530-580) | $\text{Velocity} = \frac{\text{Current Wall} - \text{Wall}_{T-1\text{h}}}{1.0\text{ hr}}$ | `UPWARD` if $> +25\text{ pts/hr}$; `DOWNWARD` if $< -25\text{ pts/hr}$. |
| **Institutional Flow (₹ Lakhs)** | `vcc_intelligence_engine.py` (lines 590-640) | $\text{CE Flow} = \sum (\Delta \text{CE OI} \times \text{CE LTP}) / 100,000$<br>$\text{Net Flow} = \text{PE Flow} - \text{CE Flow}$ | Weighted by option premium. |
| **Confluence Score (0-100)** | `vcc_intelligence_engine.py` (lines 650-710) | $\text{Confluence} = 0.35 \times \text{Positioning} + 0.30 \times \text{Price} + 0.15 \times \text{Wall} + 0.20 \times \text{Decay}$ | Weighted multi-factor model. |
| **20-Condition Outcome Audit** | `live_signal_audit_service.py` (lines 200-350) | Evaluates $T+5\text{m}, T+15\text{m}, T+30\text{m}$ outcomes post-signal timestamp $T$. | Excludes non-directional signals (`WATCH`, `SIGNAL CONFLICT`). Enforces $N \ge 30$ sample size governance. |

---

## 6. CONFIGURATION INVENTORY

The following parameters are currently hardcoded across backend modules:

```python
# Hardcoded Symbols
SUPPORTED_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]

# Hardcoded Strike Steps
STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "SENSEX": 100
}

# Confluence Score Weights
WEIGHT_POSITIONING = 0.35
WEIGHT_PRICE_CONFIRMATION = 0.30
WEIGHT_WALL_PROXIMITY = 0.15
WEIGHT_STRADDLE_DECAY = 0.20

# Session Time Boundaries (IST)
PRE_MARKET_START = "09:00"
LIVE_MARKET_START = "09:15"
LIVE_MARKET_END = "15:30"
POST_MARKET_END = "16:00"

# Governance Audit Parameters
MIN_SAMPLE_SIZE = 30
OUTCOME_WINDOW_5M = 300   # seconds
OUTCOME_WINDOW_15M = 900  # seconds
OUTCOME_WINDOW_30M = 1800 # seconds
MIN_WIN_POINTS = 10.0     # index points
```

---

## 7. DATABASE INVENTORY

| Table Name | Description | Key Columns | Write Trigger | Read Trigger |
|---|---|---|---|---|
| `vcc_live_signal_audits` | Primary 20-condition audit telemetry store. | `snapshot_id` (PK, Unique), `trade_date`, `timestamp`, `symbol`, `session_slot`, `spot_price`, `final_confluence_score`, `operational_state`, `spot_t5`, `spot_t15`, `spot_t30`, `directional_correctness_30m`. | `live_signal_audit_service.record_live_signal_snapshot` | Outcome evaluator, live audit report runner. |
| `daily_market_snapshots` | Intraday snapshot time series. | `id` (PK), `trade_date`, `timestamp`, `symbol`, `spot_price`, `atm_strike`, `pcr`, `vix`. | Background polling loop (`main.py`) during market hours. | Flow wave charts, baseline fallbacks. |
| `signal_lifecycle_records` | Trade lifecycle records. | `signal_id` (PK, Unique), `trade_date`, `symbol`, `strategy`, `status`, `entry_spot`, `exit_spot`, `realized_pnl_pts`. | `signal_lifecycle.py` on signal state change. | Signal history API, terminal UI. |
| `smart_money_shifts` | Institutional block trades / OI shifts. | `id` (PK), `trade_date`, `timestamp`, `symbol`, `shift_text`, `conviction_score`. | `smart_money_service.py` on shift detection. | Smart money API, UI timeline. |
| `vcc_signal_outcome_records` | Retrospective signal outcomes. | `signal_id` (PK, Unique), `trade_date`, `symbol`, `return_5m`, `is_success_30m`. | Legacy signal outcome recorder. | Historical analysis. |

---

## 8. API INVENTORY

| Method | Endpoint Path | Description | Data Source |
|---|---|---|---|
| `GET` | `/api/dashboard/{symbol}` | Complete dashboard payload (Indices, PCR, Walls, Signal, VCC Intel). | Redis/Memory Cache -> Fyers / Scraper / Simulator |
| `GET` | `/api/indices` | Live indices quotes, VIX, and market breadth. | Fyers / Scraper / Yahoo |
| `GET` | `/api/oi-spurts` | Top OI gainers and spurts. | NSE Scraper |
| `GET` | `/api/vcc/intelligence` | Unified VCC V3.2 Intelligence Payload. | VCC Intelligence Engine |
| `GET` | `/api/vcc/replay` | Historical Minute Market Replay. | SQLite DB snapshots |
| `GET` | `/api/fyers/status` | Broker configuration and access token status. | `fyers_service` |
| `POST` | `/api/fyers/credentials` | Save Client ID & Secret Key; return Auth URL. | `fyers_service` |
| `GET` | `/api/fyers/login` | Redirect to Fyers OAuth Page. | Fyers OAuth |
| `POST` | `/api/fyers/token` | Save and validate access token directly. | `fyers_service.validate_connection` |
| `GET` | `/api/fyers/callback` | OAuth redirect callback handler. | Fyers OAuth |
| `GET` | `/api/smart-money/shifts` | Recent institutional shift logs. | `SmartMoneyShiftModel` |
| `GET` | `/api/stocks/movers` | Top stock movers and EMS opportunities. | Stock Scraper |
| `WS` | `/ws` | Real-time WebSocket tick broadcast. | ConnectionManager broadcast loop |

---

## 9. FRONTEND INVENTORY (`backend/app/static/index.html`)

The frontend is a single-file React 18 SPA (4498 lines).

### Key UI Components
1. **Top Market Header**: Session badge, data source badge (`● BROKER`, `● NSE`, `● SIMULATED`), mode switcher (**Visual Cockpit** vs **Terminal**), Broker Modal trigger.
2. **Smart Money Conviction Speedometer & Flow Wave**: Real-time gauge and SVG intraday flow vs spot price line chart.
3. **ATM Strike Defense Heatmap & Straddle Decay Tracker**: CE/PE writer pressure, straddle VWAP bias, decay speed.
4. **Visual Command Center (VCC) Intelligence Strip**: Confluence radar, positioning score, price confirmation score, persistence %, and operational state.
5. **Options Strike Matrix**: ATM $\pm 10$ strike table showing LTP, $\Delta\text{LTP}$, OI, $\Delta\text{OI}$, and action labels.

### Business Logic Embedded in Frontend (To Be Preserved & Cleaned)
- Memoized straddle decay calculation fallback (`open_premium`, `low_premium`, `decay_pct`).
- Heatmap pressure ratio calculations (`call_writer_pressure`, `put_writer_pressure`).
- Spot price and ATM strike synchronization helpers.

---

## 10. TESTING INVENTORY

### Existing Test Suite
- `test_v32_20_conditions_audit.py`: 20/20 Passing integration tests covering snapshot immutability, look-ahead protection, data quality invalid filtering, session state enforcement, and deduplication.
- `test_live_audit_pipeline.py`: Pipeline execution test for pending signal evaluations.
- `test_live_vcc_api.py`: REST endpoint response structure tests.
- `run_v32_hardened_tests.py`: Comprehensive test runner.

### Missing Test Coverage
- Unit tests for individual data source fallbacks (Fyers timeout -> Scraper -> DB -> Simulator).
- Unit tests for WebSocket broadcast disconnect / reconnection logic.
- Automated API mock tests for off-market hours state transitions.

---

## 11. PROPOSED TARGET ARCHITECTURE

The target architecture introduces clear separation of concerns across 15 conceptual layers while preserving every existing file and function:

```text
backend/app/
├── core/                       <-- Layer 14 & 15: Configuration & Infrastructure
│   ├── config.py
│   ├── constants.py            <-- Hardcoded symbols, steps, session boundaries
│   ├── logging.py
│   └── telemetry.py
├── domain/                     <-- Layer 4, 5, 6, 7, 8, 9 & 10: Pure Domain Logic
│   ├── models/                 <-- Domain Entities (Pydantic / Dataclasses)
│   ├── session/                <-- Market Session Policy (09:15-15:30 IST)
│   ├── analytics/              <-- Confluence, Walls, Flow, Straddle Engines
│   ├── signal/                 <-- Signal Lifecycle & State Machine
│   └── audit/                  <-- 20-Point Governance & Look-Ahead Audit Engine
├── data/                       <-- Layer 1, 2, 3 & 11: Data Sources & Persistence
│   ├── sources/                <-- Fyers, NSE Scraper, Yahoo, Simulator Gateways
│   ├── normalization/          <-- Option Chain Normalizer & Greeks Calculators
│   └── repositories/           <-- SQLAlchemy Repositories (Audits, Snapshots, Signals)
├── application/                <-- Use Cases & Application Orchestration Services
│   ├── market_service.py
│   ├── audit_service.py
│   └── auth_service.py
├── api/                        <-- Layer 12: Pure API & Delivery
│   ├── v1/
│   │   ├── market_router.py
│   │   ├── auth_router.py
│   │   └── ws_router.py
│   └── dependencies.py
└── static/                     <-- Layer 13: Presentation Layer (React SPA)
    └── index.html
```

---

## 12. MIGRATION MAP

| Current File | New Target Module | Responsibility |
|---|---|---|
| `backend/app/config.py` | `core/config.py` & `core/constants.py` | Environment loading, constants, and thresholds. |
| `backend/app/services/market_hours.py` | `domain/session/session_policy.py` | IST Session state determination policy. |
| `backend/app/services/fyers_fetcher.py` | `data/sources/fyers_gateway.py` | Fyers API v3 client gateway & OAuth handling. |
| `backend/app/services/nse_fetcher.py` | `data/sources/nse_scraper_gateway.py` | NSE India web scraper gateway. |
| `backend/app/services/mock_engine.py` | `data/sources/simulator_gateway.py` | Synthetic market simulator gateway. |
| `backend/app/services/option_chain.py` | `data/normalization/option_normalizer.py` | Normalizes option chains & calculates Greeks/PCR. |
| `backend/app/engines/vcc_intelligence_engine.py` | `domain/analytics/vcc_engine.py` | Core VCC V3.2 Intelligence calculation engine. |
| `backend/app/engines/seller_engine.py` | `domain/analytics/seller_strategy_engine.py` | Option seller strategy recommendation engine. |
| `backend/app/engines/signal_lifecycle.py` | `domain/signal/signal_lifecycle.py` | Signal lifecycle state machine. |
| `backend/app/services/live_signal_audit_service.py` | `domain/audit/audit_governance_engine.py` & `data/repositories/audit_repository.py` | 20-Point Governance engine & DB repository. |
| `backend/app/services/smart_money_service.py` | `domain/analytics/smart_money_engine.py` & `data/repositories/smart_money_repository.py` | Smart Money shift analytical engine & repository. |
| `backend/app/db/models.py` | `data/repositories/models.py` | SQLAlchemy ORM persistence models. |
| `backend/app/api/market.py` | `application/market_service.py` & `api/v1/market_router.py` | Split into application orchestrator and pure API router. |
| `backend/app/api/auth.py` | `api/v1/auth_router.py` | Pure auth router delegating to `fyers_gateway`. |

---

## 13. RISK ASSESSMENT

| High-Risk Component | Operational Risk | Safeguard / Protection Requirement |
|---|---|---|
| **VCC Intelligence Engine Formulas** | Modifying confluence weights, directional flow, or wall formulas will distort live market signals. | **STRICT FREEZE**: Formulas must be moved verbatim without altering a single weight or math calculation. |
| **Look-Ahead Audit Protection** | Evaluated pending outcomes must not access data prior to or at signal timestamp $T$. | **STRICT GOVERNANCE**: Retain exact timestamp delay checks ($T + 300\text{s}$, $T + 900\text{s}$, $T + 1800\text{s}$). |
| **Snapshot Primary Key Constraints** | Duplicate `snapshot_id` inserts will cause DB integrity errors during system restarts. | **STRICT DB POLICY**: Retain `UNIQUE` constraint on `snapshot_id` and handle `IntegrityError` gracefully. |
| **Market Session Enforcement** | Signals generated outside 09:15-15:30 IST pollute historical performance statistics. | **SESSION LOCK**: Ensure `MARKET CLOSED` state is strictly enforced outside market hours. |
| **Non-Directional Signal Exclusion** | Including `WATCH` or `SIGNAL CONFLICT` in accuracy calculations skews win/loss percentages. | **NEUTRAL EXCLUSION**: `WATCH` and `SIGNAL CONFLICT` signals must return `NEUTRAL` correctness. |

---

## 14. MIGRATION SEQUENCE

Phase-by-phase execution plan for future refactoring:

```text
[Phase 1: Blueprint & Constants] (CURRENT STEP - COMPLETED)
  └── Create docs/ARCHITECTURE_AUDIT.md and extract central constants.

[Phase 2: Data Sources & Normalization Abstraction]
  └── Isolate FyersGateway, NSEScraperGateway, and SimulatorGateway behind a unified DataRepository.

[Phase 3: Domain Engine Decoupling]
  └── Isolate VCCEngine, AuditGovernanceEngine, and SessionPolicy into pure domain modules.

[Phase 4: Persistence Repository Layer]
  └── Encapsulate all database queries (Audits, Snapshots, Signals) into dedicated Repositories.

[Phase 5: Application Service Layer Orchestration]
  └── Create Application Use-Case Services (MarketService, AuditService) to decouple API routes.

[Phase 6: API Router Refactoring & Test Verification]
  └── Refactor REST routes to thin handlers and run test_v32_20_conditions_audit.py to verify 100% compliance.
```

---

## AUDIT SUMMARY & STEP 1 VERIFICATION

### 1. AUDIT COMPLETE
The complete repository analysis for VCC V3.2 is finalized.

### 2. Files Inspected
- `backend/app/main.py`
- `backend/app/api/market.py`
- `backend/app/api/auth.py`
- `backend/app/api/smart_money.py`
- `backend/app/api/stocks.py`
- `backend/app/api/websocket.py`
- `backend/app/db/database.py`
- `backend/app/db/models.py`
- `backend/app/engines/vcc_intelligence_engine.py`
- `backend/app/engines/seller_engine.py`
- `backend/app/engines/signal_lifecycle.py`
- `backend/app/engines/trade_scorer.py`
- `backend/app/engines/vcc_signal_lab.py`
- `backend/app/services/fyers_fetcher.py`
- `backend/app/services/nse_fetcher.py`
- `backend/app/services/live_signal_audit_service.py`
- `backend/app/services/smart_money_service.py`
- `backend/app/services/mock_engine.py`
- `backend/app/services/market_hours.py`
- `backend/app/services/option_chain.py`
- `backend/app/config.py`
- `backend/app/static/index.html`
- `requirements.txt`
- `test_v32_20_conditions_audit.py`
- `setup_oracle.sh`
- `Logic.md`

### 3. Files That Need Modification (in Phase 2+)
- `backend/app/api/market.py` (Split into Service + Thin Router)
- `backend/app/main.py` (Decouple polling loops from business logic)
- `backend/app/config.py` (Extract hardcoded constants)

### 4. Proposed Architecture
Modular 15-layer architecture separating Core, Domain, Data, Application, API, and Presentation layers.

### 5. Migration Risks
Risk of breaking live VCC confluence calculation or look-ahead audit protection during refactoring. Mitigated by running `test_v32_20_conditions_audit.py` at every milestone.

### 6. Exact Recommended Order for Next Implementation Steps
1. **Stop at Step 1** (as instructed).
2. Wait for user instruction to begin **Step 2 (Phase 2 Data Source & Constants Abstraction)**.

---
*End of Blueprint Document — docs/ARCHITECTURE_AUDIT.md*
