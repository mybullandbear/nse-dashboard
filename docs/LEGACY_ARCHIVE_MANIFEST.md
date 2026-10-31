# VCC V3.1 LEGACY ARCHIVE MANIFEST

**Archive Name:** `V3.1_LEGACY`  
**Archive Creation Date:** 2026-08-28  
**Architecture Target:** VCC V3.2 Decoupled Modular Architecture  
**Execution State:** STAGING MANIFEST (Read-Only Planning Phase — Files pending physical relocation)

---

## 1. ARCHIVE PURPOSE & SCOPE

This manifest establishes the formal audit trail for all legacy subsystems, engines, and services designated for retirement. Moving these components to `archive/V3.1_LEGACY/` ensures that the active `backend/app/` workspace contains ONLY clean, decoupled V3.2 modules without orphaned or legacy code clutter.

---

## 2. COMPREHENSIVE ARCHIVE INVENTORY

| # | Original Path | Subsystem Purpose | V3.2 Replacement Module | Dependency Status | Primary Archive Reason |
|---|---|---|---|---|---|
| 1 | `app/engines/vcc_intelligence_engine.py` | Monolithic legacy V3.2 intelligence engine combining wall detection, positioning, and flow calculations. | `app/analytics/pipeline.py` & `app/intelligence/confluence_engine.py` | 🔴 Coupled (Pending UI Cutover) | Replaced by pure analytical pipeline and provider-agnostic domain contracts (`MarketSnapshot`). |
| 2 | `app/engines/seller_engine.py` | Legacy option selling strategy generator (Straddles, Iron Condors). | `app/analytics/option_positioning.py` & V3 Strategy DTOs | 🔴 Coupled (Pending UI Cutover) | Embedded hardcoded weights and raw dict payloads; replaced by V3 option positioning engine. |
| 3 | `app/engines/trade_scorer.py` | Legacy win-rate probability scoring matrix. | `app/intelligence/confluence_engine.py` | 🔴 Coupled (Called by seller_engine) | Hardcoded scoring rules consolidated into `ConfluenceEngine`. |
| 4 | `app/engines/signal_lifecycle.py` | Legacy signal lifecycle state machine (`CREATED` -> `CONFIRMED` -> `EXPIRED`). | `app/signals/signal_engine.py` & `app/repositories/lifecycle_repository.py` | 🔴 Coupled (Called by `market.py`) | Managed in-memory and raw DB states; replaced by pure `SignalEngine` and repository pattern. |
| 5 | `app/engines/vcc_signal_lab.py` | CLI backtester and historical signal simulation lab. | `app/analytics/research_runner.py` & `app/providers/replay_adapter.py` | 🟢 Standalone | Superseded by anti-lookahead `ResearchRunner` and `/api/vcc/research/run`. |
| 6 | `app/services/live_signal_audit_service.py` | Legacy 20-Point Governance Audit Engine. | `app/audit/audit_service.py` & `app/repositories/audit_repository.py` | 🔴 Coupled (Called by `get_dashboard`) | Contained direct ORM queries (`SessionLocal()`); replaced by `ImmutableAuditService`. |
| 7 | `app/services/smart_money_service.py` | Legacy institutional flow & block trade shift detector. | `app/repositories/smart_money_repository.py` | 🟡 Coupled (Imported by `smart_money.py`) | Direct DB session handling replaced by interface-driven `SmartMoneyRepository`. |
| 8 | `app/services/polling_service.py` | Unused standalone polling helper class. | `app/providers/data_source_manager.py` | 🟢 Standalone | Orphaned class; background orchestration handled by `DataSourceManager`. |
| 9 | `run_live_audit_report.py` | Root CLI script for running legacy audit reports. | `/api/vcc/research/run` & `app/audit/performance_engine.py` | 🟢 Standalone | Legacy CLI script replaced by standard REST endpoints. |
| 10 | `test_live_audit_pipeline.py` | Root test script for legacy audit service. | `tests/test_audit_governance_anti_lookahead.py` | 🟢 Standalone | Legacy test suite replaced by V3 `pytest` suite. |
| 11 | `test_v32_20_conditions_audit.py` | Root validation script for 20-condition legacy engine. | `tests/test_signal_decision_engine.py` | 🟢 Standalone | Replaced by V3 unit test suite. |

---

## 3. SHARED INFRASTRUCTURE RETAINED IN PRODUCTION

The following components were analyzed during discovery and determined to be **REQUIRED** by active V3.2 operations. They are **EXCLUDED** from archival:

1. **`app/services/mock_engine.py`**: Retained as the underlying synthetic generator for `SimulatorProviderAdapter` (`app/providers/simulator_adapter.py`).
2. **`app/services/market_hours.py`**: Retained as the canonical IST market session time manager used by `domain/quality.py`, `SignalEngine`, and `vcc.py`.
3. **`app/services/fyers_fetcher.py`**: Retained as the network REST client for `FyersProviderAdapter` (`app/providers/fyers_adapter.py`).
4. **`app/services/nse_fetcher.py`**: Retained as the scraper for `NSEWebProviderAdapter` (`app/providers/nse_adapter.py`).
5. **`app/schemas/__init__.py`**: Retained for provider raw response parsing until schemas are fully refactored into `domain/contracts.py`.

---

## 4. ARCHIVAL TARGET DIRECTORY STRUCTURE

Upon execution of Phase 7 (Post-Cutover), archived files will be moved to the following target paths:

```
NSE dashboard/
├── archive/
│   └── V3.1_LEGACY/
│       ├── engines/
│       │   ├── vcc_intelligence_engine.py
│       │   ├── seller_engine.py
│       │   ├── trade_scorer.py
│       │   ├── signal_lifecycle.py
│       │   └── vcc_signal_lab.py
│       ├── services/
│       │   ├── live_signal_audit_service.py
│       │   ├── smart_money_service.py
│       │   └── polling_service.py
│       └── scripts/
│           ├── run_live_audit_report.py
│           ├── test_live_audit_pipeline.py
│           └── test_v32_20_conditions_audit.py
```

---
*Manifest approved by Antigravity Archival Verification System — August 28, 2026*
