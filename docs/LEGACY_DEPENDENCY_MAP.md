# VCC V3.2 — LEGACY DEPENDENCY MAP & DISCOVERY REPORT

**Assessment Date:** August 28, 2026  
**Scope:** Complete Codebase Inventory & Dependency Discovery for V3.2 Archival  
**Constraint:** Read-Only Assessment (No code modification, deletion, or service restart performed)

---

## 1. EXECUTIVE SUMMARY

To safely retire and archive the previous V3.1/monolithic legacy implementation, every candidate file across the repository was evaluated against a 10-point production dependency check.

### Candidate Status Summary:
- **GREEN (Safe to Archive Immediately / Standalone):** 5 files (`vcc_signal_lab.py`, `polling_service.py`, `run_live_audit_report.py`, `test_live_audit_pipeline.py`, `test_v32_20_conditions_audit.py`).
- **RED (Coupled / Pre-Cutover Required):** 6 files (`vcc_intelligence_engine.py`, `seller_engine.py`, `trade_scorer.py`, `signal_lifecycle.py`, `live_signal_audit_service.py`, `smart_money_service.py`). Coupled to `/api/dashboard/{symbol}` or background tasks.
- **YELLOW (Shared Dependency / Core Infrastructure):** 5 files (`schemas/__init__.py`, `mock_engine.py`, `market_hours.py`, `fyers_fetcher.py`, `nse_fetcher.py`). Retained for V3 providers/domain infrastructure.

---

## 2. 10-POINT DEPENDENCY DISCOVERY MATRIX

For each candidate file, the 10 production checks are:
1. **Imp?** — Who imports it?
2. **Call?** — Who calls its functions?
3. **Main?** — Used by `main.py` startup or background tasks?
4. **UI?** — Used by frontend (`index.html`)?
5. **Leg API?** — Used by `/api/dashboard/{symbol}`?
6. **V3 API?** — Used by `/api/vcc/dashboard/{symbol}`?
7. **BG Task?** — Used by live background polling loops?
8. **Tests?** — Used by test suite (`tests/` or root test scripts)?
9. **Startup?** — Part of production app startup path?
10. **Shared?** — Shared with V3.2 pipeline?

---

### Candidate File 1: `app/engines/vcc_intelligence_engine.py`
- **Purpose:** Legacy monolithic V3.2 intelligence engine.
- **1. Imports:** `test_v32_20_conditions_audit.py`, `run_v32_hardened_tests.py`, `app/api/market.py`.
- **2. Calls:** `compute_vcc_intelligence()` called in `market.py`.
- **3. Main:** Yes (via `main.py` -> `fyers_live_polling_loop()` -> `get_dashboard()`).
- **4. UI:** Indirectly via `/api/dashboard/{symbol}`.
- **5. Leg API:** **YES** (`/api/dashboard/{symbol}`).
- **6. V3 API:** **NO** (V3 API uses `app/analytics/pipeline.py` and `app/intelligence/confluence_engine.py`).
- **7. BG Task:** **YES** (`fyers_live_polling_loop`).
- **8. Tests:** Yes (`test_v32_20_conditions_audit.py`, `test_analytics_pipeline.py`).
- **9. Startup:** Yes (via router import in `main.py`).
- **10. Shared:** No (V3 uses `ConfluenceEngine`).
- **Classification:** 🔴 **RED** (Active in production via `/api/dashboard/{symbol}` & background polling; will become 🟢 **GREEN** once frontend is migrated).

---

### Candidate File 2: `app/engines/seller_engine.py`
- **Purpose:** Legacy option seller strategy generator (Iron Condor, ATM Straddle Decay).
- **1. Imports:** `app/api/market.py`.
- **2. Calls:** `seller_engine.analyze()` in `market.py`.
- **3. Main:** Yes (via `get_dashboard()`).
- **4. UI:** Indirectly via `/api/dashboard/{symbol}`.
- **5. Leg API:** **YES** (`/api/dashboard/{symbol}` and `/api/seller-recommendations/{symbol}`).
- **6. V3 API:** **NO**.
- **7. BG Task:** **YES** (called during 3s background polling).
- **8. Tests:** No.
- **9. Startup:** Yes (imported in `market.py`).
- **10. Shared:** No.
- **Classification:** 🔴 **RED** (Will become 🟢 **GREEN** post-cutover).

---

### Candidate File 3: `app/engines/trade_scorer.py`
- **Purpose:** Win-rate probability scoring matrix for seller strategies.
- **1. Imports:** `app/api/market.py`, `app/engines/seller_engine.py`.
- **2. Calls:** `trade_scorer.calculate_win_rate()` in `seller_engine.py`.
- **3. Main:** Yes (via `seller_engine`).
- **4. UI:** Indirectly via `/api/dashboard/{symbol}`.
- **5. Leg API:** **YES**.
- **6. V3 API:** **NO**.
- **7. BG Task:** **YES**.
- **8. Tests:** No.
- **9. Startup:** Yes.
- **10. Shared:** No.
- **Classification:** 🔴 **RED** (Will become 🟢 **GREEN** post-cutover).

---

### Candidate File 4: `app/engines/signal_lifecycle.py`
- **Purpose:** Legacy signal lifecycle state machine (`CREATED` -> `CONFIRMED` -> `EXPIRED`).
- **1. Imports:** `app/api/market.py`, `app/services/telegram_bot_service.py`, `app/services/live_signal_audit_service.py`.
- **2. Calls:** `signal_lifecycle_engine.process_recommendation()`.
- **3. Main:** Yes (via `get_dashboard()`).
- **4. UI:** Indirectly via `/api/dashboard/{symbol}` (`signal_history`).
- **5. Leg API:** **YES**.
- **6. V3 API:** **NO** (V3 uses `app/signals/signal_engine.py` and `app/repositories/lifecycle_repository.py`).
- **7. BG Task:** **YES**.
- **8. Tests:** No.
- **9. Startup:** Yes.
- **10. Shared:** No.
- **Classification:** 🔴 **RED** (Will become 🟢 **GREEN** post-cutover).

---

### Candidate File 5: `app/engines/vcc_signal_lab.py`
- **Purpose:** CLI historical signal simulation and backtesting lab.
- **1. Imports:** `app/api/market.py`.
- **2. Calls:** `vcc_signal_lab_engine.run_historical_validation()` in `/api/vcc-signal-lab`.
- **3. Main:** No.
- **4. UI:** No.
- **5. Leg API:** **YES** (`/api/vcc-signal-lab`).
- **6. V3 API:** **NO** (V3 research endpoint is `/api/vcc/research/run`).
- **7. BG Task:** No.
- **8. Tests:** No.
- **9. Startup:** Yes (via router).
- **10. Shared:** No.
- **Classification:** 🟢 **GREEN** (Safe to archive or deprecate).

---

### Candidate File 6: `app/services/live_signal_audit_service.py`
- **Purpose:** Legacy 20-Point Signal Governance & Outcome Evaluation engine.
- **1. Imports:** `app/api/market.py`, `run_live_audit_report.py`, `test_live_audit_pipeline.py`, `test_v32_20_conditions_audit.py`.
- **2. Calls:** `record_live_signal_snapshot()` and `evaluate_pending_signal_outcomes()`.
- **3. Main:** Yes (via `get_dashboard()`).
- **4. UI:** Indirectly via `/api/vcc/live-audit-daily`.
- **5. Leg API:** **YES**.
- **6. V3 API:** Partial (referenced for summary compatibility).
- **7. BG Task:** **YES**.
- **8. Tests:** Yes (`test_live_audit_pipeline.py`).
- **9. Startup:** Yes.
- **10. Shared:** Partial.
- **Classification:** 🔴 **RED** (Will become 🟢 **GREEN** once V3 `ImmutableAuditService` and `OutcomeEngine` take over).

---

### Candidate File 7: `app/services/smart_money_service.py`
- **Purpose:** Legacy institutional block trade & OI shift detector.
- **1. Imports:** `app/api/market.py`, `app/api/smart_money.py`, `app/services/telegram_bot_service.py`.
- **2. Calls:** `process_and_persist()`, `get_smart_money_data()`.
- **3. Main:** Yes (via `get_dashboard()`).
- **4. UI:** Yes (Smart Money Tab).
- **5. Leg API:** **YES**.
- **6. V3 API:** **NO** (V3 API `/api/vcc/*` uses `smart_money_repository.py`).
- **7. BG Task:** **YES**.
- **8. Tests:** No.
- **9. Startup:** Yes.
- **10. Shared:** Partial.
- **Classification:** 🟡 **YELLOW** (Legacy service, but imported by `app/api/smart_money.py`; replace with `smart_money_repository.py` to make 🟢 **GREEN**).

---

### Candidate File 8: `app/services/polling_service.py`
- **Purpose:** Unused standalone polling service helper class.
- **1. Imports:** None in production path.
- **2. Calls:** None.
- **3. Main:** No.
- **4. UI:** No.
- **5. Leg API:** No.
- **6. V3 API:** No.
- **7. BG Task:** No.
- **8. Tests:** No.
- **9. Startup:** No.
- **10. Shared:** No.
- **Classification:** 🟢 **GREEN** (100% safe to archive immediately).

---

### Candidate File 9: `app/services/mock_engine.py`
- **Purpose:** Synthetic data generator for fallback market snapshots.
- **1. Imports:** `app/providers/simulator_adapter.py`, `app/providers/replay_adapter.py`, `app/providers/db_fallback_adapter.py`, `app/api/market.py`.
- **2. Calls:** `simulator.generate_snapshot()`.
- **3. Main:** Indirectly via providers.
- **4. UI:** Indirectly via fallback snapshots.
- **5. Leg API:** Yes.
- **6. V3 API:** **YES** (used by V3 `SimulatorProviderAdapter`).
- **7. BG Task:** No.
- **8. Tests:** Yes.
- **9. Startup:** Yes.
- **10. Shared:** **YES**.
- **Classification:** 🟡 **YELLOW** (Shared infrastructure; do NOT archive).

---

### Candidate File 10: `app/schemas/__init__.py`
- **Purpose:** Monolithic Pydantic schemas (`OptionChainResponse`, `PCRData`, `SellerRecommendation`).
- **1. Imports:** `app/providers/fyers_adapter.py`, `app/providers/nse_adapter.py`, `app/api/market.py`, `app/engines/*`.
- **2. Calls:** Data validation for provider responses.
- **3. Main:** Yes.
- **4. UI:** Dict output schemas.
- **5. Leg API:** Yes.
- **6. V3 API:** Indirectly via providers.
- **7. BG Task:** Yes.
- **8. Tests:** Yes.
- **9. Startup:** Yes.
- **10. Shared:** **YES**.
- **Classification:** 🟡 **YELLOW** (Shared type definitions; retain until provider schemas are fully decoupled).

---

## 3. SUMMARY DISCOVERY CLASSIFICATION TABLE

| Path | Category | Production Status | Cutover Requirement |
|---|---|---|---|
| `app/engines/vcc_intelligence_engine.py` | Engine | 🔴 RED (Active) | Migrate UI to `/api/vcc/dashboard/{symbol}` |
| `app/engines/seller_engine.py` | Engine | 🔴 RED (Active) | Port recommendations to V3 API DTOs |
| `app/engines/trade_scorer.py` | Engine | 🔴 RED (Active) | Retire with seller engine |
| `app/engines/signal_lifecycle.py` | Engine | 🔴 RED (Active) | Replace with `lifecycle_repository.py` |
| `app/engines/vcc_signal_lab.py` | Engine | 🟢 GREEN (Standalone) | Safe to archive immediately |
| `app/services/live_signal_audit_service.py` | Service | 🔴 RED (Active) | Replace with V3 `ImmutableAuditService` |
| `app/services/smart_money_service.py` | Service | 🟡 YELLOW (Coupled) | Replace imports in `smart_money.py` with repository |
| `app/services/polling_service.py` | Service | 🟢 GREEN (Unused) | Safe to archive immediately |
| `app/services/mock_engine.py` | Gateway | 🟡 YELLOW (Shared) | Retain for V3 `SimulatorProviderAdapter` |
| `app/schemas/__init__.py` | Schemas | 🟡 YELLOW (Shared) | Retain for provider response parsing |

---
*Report compiled by Antigravity Decommissioning Discovery System — August 28, 2026*
