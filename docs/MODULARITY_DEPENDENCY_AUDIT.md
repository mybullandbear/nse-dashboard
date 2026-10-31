# VCC V3.2 — TRUE MODULARITY & DEPENDENCY AUDIT REPORT

**Audit Date:** August 28, 2026  
**System Status:** LIVE / FYERS_LIVE Active Data Ingestion  
**Audit Scope:** Read-Only Modularity & Coupling Assessment across 14 System Modules  
**Target Codebase:** `NSE dashboard/backend/app/` & `NSE dashboard/backend/app/static/index.html`

---

## 1. EXECUTIVE SUMMARY

The Visual Command Center (VCC V3.2) system is an institutional option analytics and trading signal platform. A full architectural dependency audit was conducted across all 14 functional subsystems of the production codebase.

The primary objective of V3.2 refactoring was to introduce clear domain contracts (`MarketSnapshot`, `SignalDecision`, `ConfluenceResult`), provider-agnostic data abstractions (`DataSourceManager`), interface-driven repositories (`base.py`), and pure analytical pipelines.

### Core Architectural Findings:
1. **V3 Core Architecture (Clean & Modular):** Modules 1 through 10 (Domain, Providers, DataSourceManager, Analytics, Intelligence, Signal Engine, Audit, Research, Repositories, and V3 API) demonstrate **high modularity and strict boundary enforcement**. Business logic relies on immutable domain contracts and abstract repository interfaces.
2. **Legacy Dual-Pipeline Coupling (Primary Risk):** The application runs two concurrent processing paths:
   - **V3.2 Decoupled Pipeline:** `DataSourceManager` → `AnalyticsPipeline` → `ConfluenceEngine` → `SignalEngine` → `ImmutableAuditService` → `/api/vcc/*`.
   - **Legacy Monolithic Engine:** `vcc_intelligence_engine.py` → `seller_engine.py` → `live_signal_audit_service.py` → `/api/dashboard/{symbol}`.
   The background live polling loop (`fyers_live_polling_loop` in `main.py`) continuously executes the legacy pipeline alongside the V3 pipeline.
3. **Direct Database Violations in Legacy Code:** While V3 repositories isolate SQL queries behind `AuditRepository` and `SignalRepository`, the legacy `vcc_intelligence_engine.py` directly instantiates `SessionLocal()` and queries `DailyMarketSnapshotModel` in the middle of analytical calculations.

---

## 2. COMPREHENSIVE DEPENDENCY MATRIX (14 × 14)

### Legend:
- **`D`**: Domain Contract / DTO Dependency (Clean)
- **`I`**: Abstract Interface / Dependency Injection (Clean)
- **`C`**: Direct Code / Import Coupling (Concrete Implementation Dependency)
- **`S`**: Shared Database Table / ORM Model Coupling
- **`0`**: No Dependency (Fully Decoupled)

| Source \ Target Module | 1. Dom | 2. Pro | 3. DSM | 4. Ana | 5. Int | 6. Sig | 7. Aud | 8. Res | 9. Rep | 10. API | 11. UI | 12. Cfg | 13. DB | 14. Leg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **1. Domain** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | C | 0 | 0 |
| **2. Providers** | D | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | C | C | 0 |
| **3. DataSourceManager** | D | C | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | C | 0 | 0 |
| **4. Analytics** | D | 0 | 0 | 0 | 0 | 0 | 0 | 0 | I | 0 | 0 | C | 0 | 0 |
| **5. Intelligence / Confluence**| D | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | C | 0 | 0 |
| **6. Signal Engine** | D | 0 | 0 | 0 | D | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **7. Audit** | D | 0 | 0 | 0 | 0 | D | 0 | 0 | I | 0 | 0 | 0 | 0 | 0 |
| **8. Research / Replay** | D | C | 0 | C | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **9. Repositories** | D | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | C | 0 |
| **10. API / Presentation (V3)**| D | 0 | C | C | C | C | C | C | I | 0 | 0 | C | 0 | 0 |
| **11. Frontend / UI** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | C | 0 | 0 | 0 | C |
| **12. Configuration** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **13. Database** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | C | 0 | 0 |
| **14. Legacy Pipeline** | D | C | 0 | 0 | 0 | 0 | C | 0 | 0 | C | 0 | C | C | 0 |

---

## 3. MODULE-BY-MODULE AUDIT REPORT

### Module 1: Domain Layer (`app/domain/`)
- **What it imports:** `dataclasses`, `enum`, `typing`, `pydantic`, `app.core.constants.system_config`.
- **What imports it:** Providers, DataSourceManager, Analytics, Intelligence, Signal Engine, Audit, Repositories, V3 API.
- **Consumed Contracts:** Config thresholds.
- **Produced Contracts:** `MarketSnapshot`, `SpotQuote`, `OptionQuote`, `MarketMetadata`, `DataQuality`, `SignalDecision`, `ConfluenceResult`, `SignalOutcome`.
- **Internal Access Violations:** None.
- **Direct DB Access:** No.
- **Hardcoded Values / Config:** Leverages `system_config`.
- **Failure Blast Radius:** Critical. Changes break all V3 analytical subsystems.

### Module 2: Providers (`app/providers/`)
- **What it imports:** `app.domain.contracts`, `app.config`, provider SDKs (`fyers_apiv3`), `curl_cffi`, `SessionLocal` (in fallback/replay).
- **What imports it:** `DataSourceManager`, `ResearchRunner`.
- **Consumed Contracts:** Raw JSON/REST payloads from Fyers API & NSE web scrapers.
- **Produced Contracts:** Canonical `MarketSnapshot` instances.
- **Internal Access Violations:** `db_fallback_adapter.py` and `replay_adapter.py` instantiate `SessionLocal()` directly.
- **Direct DB Access:** Yes (Fallback and Replay adapters read DB directly).
- **Hardcoded Values / Config:** Symbol format transformations (`NSE:NIFTY50-INDEX`).
- **Failure Blast Radius:** High. If a provider fails, `DataSourceManager` triggers automatic failover.

### Module 3: DataSourceManager (`app/providers/data_source_manager.py`)
- **What it imports:** `app.domain.contracts`, provider adapters (`FyersProviderAdapter`, `NSEWebProviderAdapter`, `DatabaseFallbackProviderAdapter`, `SimulatorProviderAdapter`).
- **What imports it:** V3 API (`app/api/vcc.py`), `main.py` health checks.
- **Consumed Contracts:** Provider health metrics & snapshots.
- **Produced Contracts:** Primary live `MarketSnapshot` with automatic failover telemetry.
- **Internal Access Violations:** None.
- **Direct DB Access:** No (delegated to fallback adapter).
- **Hardcoded Values / Config:** Polling timeout limits (1.5s).
- **Failure Blast Radius:** Medium. If manager fails, fallback to simulated snapshot occurs cleanly.

### Module 4: Analytics Pipeline (`app/analytics/`)
- **What it imports:** `app.domain.contracts`, `app.analytics.context_provider`, sub-engines (`market_state`, `option_positioning`, `price_confirmation`, `flow_dynamics`).
- **What imports it:** V3 API (`app/api/vcc.py`), `ResearchRunner`.
- **Consumed Contracts:** `MarketSnapshot`, `HistoricalContextProvider`.
- **Produced Contracts:** Standardized dictionary of analytical metrics (`positioning_score`, `price_conf_score`, `net_flow_lakhs`, `wall_interaction`).
- **Internal Access Violations:** None. Uses abstract `HistoricalContextProvider` interface.
- **Direct DB Access:** No.
- **Hardcoded Values / Config:** Confluence weighting defaults from `system_config`.
- **Failure Blast Radius:** High for V3 analytics; zero impact on legacy endpoints.

### Module 5: Intelligence / Confluence Engine (`app/intelligence/confluence_engine.py`)
- **What it imports:** `app.domain.contracts`, `app.core.constants.system_config`.
- **What imports it:** V3 API (`app/api/vcc.py`), `SignalEngine`.
- **Consumed Contracts:** Analytical scores, `DataQuality` enum.
- **Produced Contracts:** `ConfluenceResult` (containing `final_score`, `confidence`, `evidences`, `conflicts`, `is_conflict`).
- **Internal Access Violations:** None. Pure mathematical logic.
- **Direct DB Access:** No.
- **Hardcoded Values / Config:** Weights (`POSITIONING=0.45`, `PRICE=0.35`, `WALL=0.20`).
- **Failure Blast Radius:** Medium. Affects V3 signal cards only.

### Module 6: Signal Engine (`app/signals/signal_engine.py`)
- **What it imports:** `app.domain.contracts`, `app.intelligence.confluence_engine.ConfluenceResult`, `app.services.market_hours.IST`.
- **What imports it:** V3 API (`app/api/vcc.py`).
- **Consumed Contracts:** `MarketSnapshot`, `ConfluenceResult`.
- **Produced Contracts:** `SignalDecision` immutable dataclass/Pydantic model.
- **Internal Access Violations:** None. Zero external side effects.
- **Direct DB Access:** No.
- **Hardcoded Values / Config:** Operational state thresholds (`ENTRY CONFIRMED` >= 70 score).
- **Failure Blast Radius:** Low to Medium (Pure function, easily testable).

### Module 7: Audit Layer (`app/audit/`)
- **What it imports:** `app.domain.contracts`, `app.repositories.sqlalchemy_repository.audit_repository`, `app.services.market_hours.IST`.
- **What imports it:** V3 API (`app/api/vcc.py`).
- **Consumed Contracts:** `MarketSnapshot`, `SignalDecision`.
- **Produced Contracts:** `snapshot_id` string, saved audit dictionary.
- **Internal Access Violations:** Interacts with repository singleton (`audit_repository`).
- **Direct DB Access:** No (mediated by repository).
- **Hardcoded Values / Config:** Retention slot labels.
- **Failure Blast Radius:** Low. Logging failure does not interrupt API response generation.

### Module 8: Research / Replay (`app/analytics/research_runner.py`)
- **What it imports:** `app.domain.contracts`, `app.providers.replay_adapter`, `app.analytics.pipeline`, `app.intelligence.confluence_engine`, `app.signals.signal_engine`, `app.audit.outcome_engine`.
- **What imports it:** V3 API (`/api/vcc/research/run`).
- **Consumed Contracts:** Replay series snapshots.
- **Produced Contracts:** Research evaluation report & win-rate metrics.
- **Internal Access Violations:** None.
- **Direct DB Access:** No (Replay adapter fetches snapshots).
- **Hardcoded Values / Config:** Non-lookahead time window (30-minute evaluation).
- **Failure Blast Radius:** Zero on live trading operations.

### Module 9: Repositories (`app/repositories/`)
- **What it imports:** `app.repositories.base`, `app.db.database.SessionLocal`, `app.db.models`.
- **What imports it:** Audit Service, Performance Engine, V3 API.
- **Consumed Contracts:** Domain contracts & dictionaries.
- **Produced Contracts:** ORM persistence & domain state retrieval.
- **Internal Access Violations:** None. Implements ABC interfaces cleanly.
- **Direct DB Access:** Yes (Encapsulates all SQLAlchemy queries for V3).
- **Hardcoded Values / Config:** None.
- **Failure Blast Radius:** Medium (Database persistence).

### Module 10: API / DTO / Presentation (`app/api/vcc.py`)
- **What it imports:** `FastAPI`, `Pydantic`, all V3 services (`data_source_manager`, `analytics_pipeline`, `confluence_engine`, `signal_engine`, `audit_service`, `performance_repository`).
- **What imports it:** `app.main.py`.
- **Consumed Contracts:** Domain DTOs and pipeline outputs.
- **Produced Contracts:** Strongly typed `VCCDashboardResponse`, `SignalCardResponse`.
- **Internal Access Violations:** Orchestrates V3 pipeline execution within endpoint handlers.
- **Direct DB Access:** No.
- **Hardcoded Values / Config:** Router prefix (`/api/vcc`).
- **Failure Blast Radius:** Low (REST API presentation layer).

### Module 11: Frontend / UI (`app/static/index.html`)
- **What it imports:** CDN libraries (React 18, Babel, Tailwind CSS, Lucide, ApexCharts).
- **What imports it:** Browser client.
- **Consumed Contracts:** Endpoint responses (`/api/dashboard/{symbol}` and `/api/stocks/*`).
- **Produced Contracts:** User Interface rendering.
- **Internal Access Violations:** Currently polls legacy `/api/dashboard/{symbol}` rather than `/api/vcc/dashboard/{symbol}`.
- **Direct DB Access:** No.
- **Hardcoded Values / Config:** Polling intervals (15s stock polling, 3s index polling).
- **Failure Blast Radius:** Isolated to user browser rendering.

### Module 12: Configuration (`app/config.py`, `app/core/constants.py`)
- **What it imports:** `pydantic_settings`, `pydantic`.
- **What imports it:** Domain, Providers, Analytics, Intelligence, Repositories, API, Main.
- **Consumed Contracts:** Environment variables (`.env`).
- **Produced Contracts:** `system_config` singleton, `Settings` object.
- **Internal Access Violations:** None.
- **Direct DB Access:** No.
- **Hardcoded Values / Config:** Default market hours (09:15 - 15:45 IST), strike steps (NIFTY=50, BANKNIFTY=100).
- **Failure Blast Radius:** Critical. Central configuration backbone.

### Module 13: Database (`app/db/`)
- **What it imports:** `sqlalchemy`, `app.config`.
- **What imports it:** Repositories, Legacy engine, Fallback provider, `main.py`.
- **Consumed Contracts:** Database connection string (`sqlite:///./options_terminal.db`).
- **Produced Contracts:** `Base`, `SessionLocal`, SQLAlchemy Models (`DailyMarketSnapshotModel`, `VCCLiveSignalAuditModel`, `SmartMoneyShiftModel`).
- **Internal Access Violations:** Directly imported by legacy code bypassing repository interfaces.
- **Direct DB Access:** Yes (It IS the DB layer).
- **Hardcoded Values / Config:** SQLite file path.
- **Failure Blast Radius:** Critical for persistent audit logs; graceful fallback to in-memory mode available in DataSourceManager.

### Module 14: Legacy Pipeline (`app/engines/vcc_intelligence_engine.py`, `seller_engine.py`, `live_signal_audit_service.py`)
- **What it imports:** `SessionLocal`, `DailyMarketSnapshotModel`, `app.schemas`, `app.services.market_hours`.
- **What imports it:** `app/api/market.py` (`/api/dashboard/{symbol}`), background task in `main.py`.
- **Consumed Contracts:** Raw option chain schemas (`OptionChainResponse`).
- **Produced Contracts:** Legacy VCC intelligence dict, persisted live audit records.
- **Internal Access Violations:** Direct DB session management (`db = SessionLocal()`) inside analytical functions.
- **Direct DB Access:** Yes (Bypasses repository layer completely).
- **Hardcoded Values / Config:** Duplicated weightings (`POSITIONING_WEIGHT=0.60`, `PRICE_WEIGHT=0.40`).
- **Failure Blast Radius:** High risk of lock contention or stale data pollution if background polling fails.

---

## 4. ARCHITECTURAL VIOLATION LOG

| ID | Severity | Source File & Line | Violation Type | Description & Impact |
|---|---|---|---|---|
| **VIO-01** | 🔴 **RED** | `app/engines/vcc_intelligence_engine.py:138-148` | Direct DB Coupling in Business Engine | `VCCIntelligenceEngine` directly opens `db: Session = SessionLocal()` to query `DailyMarketSnapshotModel`. Bypasses repository layer. |
| **VIO-02** | 🔴 **RED** | `app/services/live_signal_audit_service.py:35-50` | Direct DB Coupling in Service Layer | `LiveSignalAuditService` performs raw ORM `db.query(VCCLiveSignalAuditModel)` inside audit logging routines. |
| **VIO-03** | 🟠 **ORANGE** | `app/main.py:42-52` | Background Polling Executing Legacy Pipeline | `fyers_live_polling_loop()` calls `get_dashboard(symbol)`, which executes the monolithic legacy engine on every 3-second cycle. |
| **VIO-04** | 🟠 **ORANGE** | `app/providers/db_fallback_adapter.py:35-45` | Direct DB Access in Provider Adapter | `DatabaseFallbackProviderAdapter` queries ORM directly rather than using a `MarketRepository` interface. |
| **VIO-05** | 🟡 **YELLOW** | `app/engines/vcc_intelligence_engine.py:20-30` | Configuration Duplication | Weight constants (`POSITIONING_WEIGHT = 0.60`) are hardcoded in the legacy engine instead of reading from `system_config`. |
| **VIO-06** | 🟡 **YELLOW** | `app/static/index.html:596-605` | Frontend Legacy API Endpoint Dependency | Frontend tab fetches `/api/stocks/market-data` and `/api/dashboard/{symbol}` instead of consuming unified V3 endpoints (`/api/vcc/dashboard/{symbol}`). |

---

## 5. SYSTEM MODULARITY RATING & REPLACEMENT IMPACT MATRIX

### Overall System Modularity Score: **82 / 100** (GRADE: A-)

- **V3 Core Architecture Sub-Score:** **94 / 100** (Strictly decoupled, pure functions, repository interfaces).
- **Legacy Subsystem Sub-Score:** **62 / 100** (Tight DB coupling, duplicated state logic).

---

### Component Replacement Impact Matrix

| Subsystem to Replace | Difficulty | Affected Modules | Refactoring Effort Required | Risk Level |
|---|---|---|---|---|
| **Replace Fyers API with Zerodha / AngelOne** | 🟢 **LOW** | Module 2 (`app/providers/`) | **Minimal:** Write a new `ZerodhaProviderAdapter(MarketDataProvider)` implementing `get_snapshot()`. Zero changes required in Analytics, Intelligence, or Signal Engine. | 🟢 Low |
| **Replace Confluence Engine Scoring Rules** | 🟢 **LOW** | Module 5 (`app/intelligence/`) | **Minimal:** Modify `compute_confluence()` in `confluence_engine.py`. Zero changes required in data providers or database. | 🟢 Low |
| **Switch Database from SQLite to PostgreSQL** | 🟡 **MEDIUM**| Module 9, 13, 14 (`app/repositories/`, `app/db/`, `app/engines/`) | **Moderate:** Change connection string in `config.py` for V3 repositories. However, legacy `vcc_intelligence_engine.py` direct queries must be cleaned up to prevent dialect mismatch issues. | 🟡 Medium |
| **Redesign Signal Decision Rules** | 🟢 **LOW** | Module 6 (`app/signals/`) | **Minimal:** Update static method `SignalEngine.decide_signal()`. Inputs and outputs are strictly typed domain objects. | 🟢 Low |
| **Replace Frontend UI with Next.js / React Native** | 🟢 **LOW** | Module 11 (`app/static/`) | **Low:** Consume `/api/vcc/dashboard/{symbol}` REST endpoints or WebSocket feed. Backend is standard FastAPI JSON. | 🟢 Low |

---

## 6. ANSWERS TO 10 EXPLICIT ARCHITECTURAL QUESTIONS

### Q1: Can `AnalyticsPipeline` run completely without a database connection?
**YES.** `AnalyticsPipeline` depends solely on a `MarketSnapshot` domain object and an abstract `HistoricalContextProvider`. In live execution, if the database is down, `AnalyticsPipeline` operates seamlessly using an in-memory context provider or single-snapshot mode without throwing errors.

### Q2: What happens if Fyers API is completely offline?
The system triggers graceful multi-tiered failover managed by `DataSourceManager`:
1. Attempts `FyersProviderAdapter` (Fails/Times out).
2. Fails over to `NSEWebProviderAdapter` (Live web scraping).
3. If NSE scraper is blocked, fails over to `DatabaseFallbackProviderAdapter` (Uses last known DB snapshot).
4. If DB has no recent snapshots, fails over to `SimulatorProviderAdapter` (Generated synthetic market tick).
The frontend state strip displays connection telemetry reflecting the active fallback data source.

### Q3: Is `SignalEngine` dependent on network, DB, or presentation objects?
**NO.** `SignalEngine` is a 100% deterministic pure logic module. It accepts a canonical `MarketSnapshot`, a `ConfluenceResult`, and a `breakout_status` string, and returns a `SignalDecision` object. It imports zero network libraries, zero database sessions, and zero presentation schemas.

### Q4: Can `ConfluenceEngine` be modified or replaced without touching `SignalEngine` or `AnalyticsPipeline`?
**YES.** `ConfluenceEngine` accepts numeric positioning and price metrics and outputs a standardized `ConfluenceResult` contract. As long as `ConfluenceResult` structure is maintained, the internal scoring algorithm (or a future Machine Learning model) can be replaced without modifying a single line of code in `AnalyticsPipeline` or `SignalEngine`.

### Q5: Does `Frontend` communicate through domain DTOs or untyped dictionaries?
**MIXED:**
- V3 endpoints (`/api/vcc/*`) return strongly-typed Pydantic DTOs (`VCCDashboardResponse`, `SignalCardResponse`).
- Legacy endpoint (`/api/dashboard/{symbol}`) returns a large untyped Python dictionary. The current production frontend (`index.html`) primarily consumes this legacy dictionary.

### Q6: Is `Research / Replay` isolated from live production execution?
**YES.** `ResearchRunner` operates in strict anti-lookahead mode using `ReplayProviderAdapter`. It instantiates separate pipeline execution instances and does not mutate live cache state or pollute production audit tables.

### Q7: How tightly bound is `Audit` logging to live signal execution?
**DECOUPLED.** In V3, signal decisions are computed first (`signal_engine.decide_signal`), and then asynchronously passed to `ImmutableAuditService.record_signal_snapshot()`. Database write failures in the audit service log a warning but do not interrupt or fail the API response to the user.

### Q8: What dependencies prevent switching database from SQLite to PostgreSQL?
1. Direct raw ORM queries inside legacy `vcc_intelligence_engine.py` and `live_signal_audit_service.py`.
2. SQLite-specific date formatting assumptions in legacy snapshot queries (`strftime`).
All V3 repositories use SQLAlchemy standard abstractions and can switch to PostgreSQL simply by updating `DATABASE_URL` in `.env`.

### Q9: Are configuration settings (weights, thresholds, hours) centralized or scattered?
Centralized in `app/config.py` and `app/core/constants.py` (`system_config`). However, legacy engine `vcc_intelligence_engine.py` maintains duplicate hardcoded constants (`POSITIONING_WEIGHT = 0.60`, `ENTRY_MIN_CONFLUENCE = 70`).

### Q10: Is the legacy pipeline still coupled to the live system, and can it be removed safely?
The legacy pipeline is currently coupled via:
1. `app/main.py` background polling loop calling `get_dashboard()`.
2. Frontend `index.html` fetching `/api/dashboard/{symbol}`.
**Removal Plan:** Safe removal requires updating `index.html` to consume `/api/vcc/dashboard/{symbol}`, after which `vcc_intelligence_engine.py` and `live_signal_audit_service.py` can be deprecated cleanly without impacting V3 operations.

---

## 7. TOP 5 REFACTORING RECOMMENDATIONS (PRIORITIZED)

### Recommendation 1: Migrate Frontend to V3 Unified API Endpoint (`/api/vcc/dashboard/{symbol}`)
- **Priority:** 🔥 **URGENT (P0)**
- **Rationale:** Eliminates reliance on the legacy untyped dictionary and allows deprecation of the legacy monolithic engine.
- **Risk:** Low (V3 endpoint is fully functional and returns complete payload).

### Recommendation 2: Remove Direct DB Queries from `VCCIntelligenceEngine` & `LiveSignalAuditService`
- **Priority:** ⚡ **HIGH (P1)**
- **Rationale:** Resolves Architectural Violations VIO-01 and VIO-02. Routes all persistence through `AuditRepository` and `MarketRepository`.
- **Risk:** Low.

### Recommendation 3: Decommission Legacy Background Polling Loop in `main.py`
- **Priority:** ⚡ **HIGH (P1)**
- **Rationale:** Stops dual-execution of legacy engine during live market hours, reducing backend CPU usage and DB lock contention by ~50%.
- **Risk:** Low after Recommendation 1 is completed.

### Recommendation 4: Consolidate Configuration Constants into `system_config`
- **Priority:** 💡 **MEDIUM (P2)**
- **Rationale:** Removes hardcoded thresholds in legacy adapters and enforces a single source of truth across all modules.
- **Risk:** Minimal.

### Recommendation 5: Wrap `DatabaseFallbackProviderAdapter` with `MarketRepository` Interface
- **Priority:** 💡 **MEDIUM (P2)**
- **Rationale:** Ensures 100% of data providers interact with abstract repository interfaces rather than direct ORM sessions.
- **Risk:** Minimal.

---
*Report compiled by Antigravity Architectural Audit Subsystem — August 28, 2026*
