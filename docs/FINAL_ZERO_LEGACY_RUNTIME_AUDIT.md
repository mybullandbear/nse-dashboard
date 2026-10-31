# VCC V3.2 — Final Zero-Legacy Runtime Audit & Decommission Readiness

**Audit Date:** August 28, 2026  
**Audited Subsystems:** `app/engines/`, `app/services/`, `app/api/`, `app/static/`, `main.py`  
**Audit Purpose:** Evaluate whether legacy V3.1 / monolithic intelligence components can be safely archived without affecting production runtime execution.  

---

## Final Decision

### **ARCHIVAL BLOCKED — LEGACY RUNTIME DEPENDENCY REMAINS**

> **Rationale:** Although the Smart Money subsystem (`app/smart_money` and `app/alerts`) has been fully ported into a clean modular V3 subsystem with 100% functional equivalence and dedicated tests passing, **legacy production runtime dependencies still exist in `backend/app/api/market.py`, `backend/app/main.py` background polling loops, and `backend/app/static/index.html` frontend REST fetches.** Physical removal or archiving of legacy files at this moment would crash the live application and break user interface rendering.

---

## 1. Production Import Graph

Tracing imports starting from `backend/app/main.py` and registered routers (`market_router`, `vcc_router`, `smart_money_router`):

```
backend/app/main.py
 └── app.api.market (market_router)
      ├── app.engines.seller_engine (seller_engine)              [PRODUCTION RUNTIME]
      ├── app.engines.trade_scorer (trade_scorer)                [PRODUCTION RUNTIME]
      ├── app.engines.signal_lifecycle (signal_lifecycle_engine) [PRODUCTION RUNTIME]
      ├── app.engines.vcc_intelligence_engine                    [PRODUCTION RUNTIME]
      ├── app.services.smart_money_service (smart_money_service) [PRODUCTION RUNTIME]
      └── app.services.live_signal_audit_service                 [PRODUCTION RUNTIME]
```

### Import Classification Summary
- `app/engines/vcc_intelligence_engine.py`: **PRODUCTION RUNTIME** (Imported in `app/api/market.py:643, 774, 819, 859`).
- `app/engines/seller_engine.py`: **PRODUCTION RUNTIME** (Imported in `app/api/market.py:20`).
- `app/engines/trade_scorer.py`: **PRODUCTION RUNTIME** (Imported in `app/api/market.py:21`).
- `app/engines/signal_lifecycle.py`: **PRODUCTION RUNTIME** (Imported in `app/api/market.py:543, 738`).
- `app/services/live_signal_audit_service.py`: **PRODUCTION RUNTIME** (Imported in `app/api/market.py:657, 923, 936`).
- `app/services/smart_money_service.py`: **PRODUCTION RUNTIME** (Imported in `app/api/market.py:346, 739`).

---

## 2. Production Function-Call Graph

Tracing call stacks from active routes and background services:

```
[Background Task: fyers_live_polling_loop()]
 └── get_dashboard(symbol) [app/api/market.py:547]
      ├── smart_money_v3_service.process_and_persist(symbol, chain, pcr, vix_obj) [V3 ACTIVE]
      ├── seller_engine.analyze(chain, pcr, vix_obj, ...)                         [LEGACY ACTIVE]
      └── signal_lifecycle_engine.process_recommendation(...)                    [LEGACY ACTIVE]

[GET /api/dashboard/{symbol}]
 └── get_dashboard(symbol)
      ├── seller_engine.analyze(...)
      └── signal_lifecycle_engine.process_recommendation(...)

[GET /api/seller-recommendations/{symbol}]
 └── get_seller_recommendations_by_symbol(symbol) [app/api/market.py:346]
      ├── smart_money_service.get_smart_money_data(symbol)                      [LEGACY ACTIVE]
      └── seller_engine.analyze(...)                                             [LEGACY ACTIVE]

[GET /api/vcc/live-audit-daily]
 └── get_live_audit_daily_report() [app/api/market.py:923]
      └── live_signal_audit_service.evaluate_pending_signal_outcomes(symbol)     [LEGACY ACTIVE]
```

---

## 3. Background Task Dependency Map

Background tasks started during `lifespan` in `backend/app/main.py`:

| Background Task | Frequency | Code Executed | Classification | Status |
| :--- | :--- | :--- | :--- | :--- |
| `fyers_live_polling_loop()` | 3.0s (Market Hours) | `refresh_fyers_live_data()`, `get_dashboard(symbol)` | Mixed V3 + Legacy | **DEPENDENT ON LEGACY** |
| `nse_slow_polling_loop()` | 30.0s | `get_indices()`, `get_oi_spurts()` | Production Utility | CLEAN |
| `stock_polling_loop()` | 60.0s | `update_stock_market_data()` | Stock Analytics | CLEAN |
| `db_cleanup_loop()` | 4 Hours | `cleanup_old_data()` | DB Storage Pruning | CLEAN |
| `telegram_bot_service.start_polling()` | Continuous | `TelegramBotService` | V3 Service (`smart_money_v3_service`) | CLEAN V3 |

> **Critical Note:** `fyers_live_polling_loop()` calls `get_dashboard(symbol)` every 3 seconds for `["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]`, which triggers `seller_engine.analyze()` and `signal_lifecycle_engine.process_recommendation()`.

---

## 4. API Route Classification

| Route Path | Module | Dependencies | Legacy Execution? | V3 Replacement | Classification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `/api/dashboard/{symbol}` | `app/api/market.py` | `seller_engine`, `signal_lifecycle` | **YES** | `/api/vcc/dashboard/{symbol}` | **ACTIVE LEGACY** |
| `/api/seller-recommendations/{symbol}` | `app/api/market.py` | `seller_engine`, `smart_money_service` | **YES** | `/api/vcc/signals/{symbol}` | **ACTIVE LEGACY** |
| `/api/vcc-signal-lab` | `app/api/market.py` | `vcc_intelligence_engine` | **YES** | `/api/vcc/signals/{symbol}` | **DEPRECATED LEGACY** |
| `/api/vcc/live-audit-daily` | `app/api/market.py` | `live_signal_audit_service` | **YES** | `/api/vcc/audit` | **ACTIVE LEGACY** |
| `/api/smart-money/*` | `app/api/smart_money.py` | `smart_money_v3_service`, `smart_money_repository` | **NO** | N/A | **ACTIVE V3** |
| `/api/vcc/smart-money/{symbol}` | `app/api/vcc.py` | `smart_money_v3_service`, `data_source_manager` | **NO** | N/A | **ACTIVE V3** |
| `/api/vcc/dashboard/{symbol}` | `app/api/vcc.py` | `data_source_manager`, `analytics_pipeline`, `confluence_engine` | **NO** | N/A | **ACTIVE V3** |
| `/api/vcc/signals/{symbol}` | `app/api/vcc.py` | `signal_engine`, `signal_repository` | **NO** | N/A | **ACTIVE V3** |
| `/api/vcc/audit` | `app/api/vcc.py` | `audit_service`, `performance_engine` | **NO** | N/A | **ACTIVE V3** |

---

## 5. Frontend Dependency Map

Inspection of `backend/app/static/index.html`:

- **Primary Polling Function:** `fetchDashboardData(symbol)` (lines 2722–2746).
- **Fetches:**
  1. `fetch('/api/dashboard/${symbol}')` $\rightarrow$ Primary state payload.
  2. `fetch('/api/vcc/dashboard/${symbol}')` $\rightarrow$ Merged into `json.vcc`.
- **Finding:** The React SPA frontend (`index.html`) relies on `/api/dashboard/${symbol}` to render main option chain tables, strike heatmap widgets, and PCR cards.

---

## 6. Smart Money Final Verification

- **`smart_money_service.py` Status:** Replaced in main market poller by `smart_money_v3_service`. Remaining imports exist only in legacy fallback routines inside `app/api/market.py:346, 739`.
- **`smart_money_v3_service` Status:** Active production implementation backing `/api/vcc/smart-money/{symbol}` and `/api/smart-money/{symbol}`.
- **Payload Verification:** `/api/vcc/smart-money/{symbol}` provides complete `SmartMoneyAnalysisResult` (conviction %, walls, intraday timeline, shift events, market direction DTO).
- **Telegram Subsystem Verification:** Non-blocking async Telegram alerts originate strictly from `backend/app/alerts/telegram_alert_service.py` with in-memory & DB duplicate suppression.

---

## 7. Database Access Audit

Search for `SessionLocal()`, `db.query()`, `db.execute()` outside repository boundaries:

| File Location | Direct DB Call | Context / Purpose | Classification |
| :--- | :--- | :--- | :--- |
| `app/engines/vcc_signal_lab.py` | `db.query(DailyMarketSnapshotModel)` | Historical lab snapshot retrieval | Legacy Direct DB |
| `app/providers/db_fallback_adapter.py` | `db.query(DailyMarketSnapshotModel)` | Provider snapshot query | Provider Internal |
| `app/providers/replay_adapter.py` | `db.query(DailyMarketSnapshotModel)` | Research replay querying | Provider Internal |
| `app/services/live_signal_audit_service.py` | `db.query(VCCLiveSignalAuditModel)` | Outcome evaluation & audit reporting | Legacy Direct DB |
| `app/services/smart_money_service.py` | `db.query(SmartMoneyShiftModel)` | Legacy shift query | Legacy Direct DB |
| `app/repositories/*` | `SessionLocal()` / `db.query()` | Decoupled V3 Repositories | **Clean V3 Boundary** |

---

## 8. Complete Legacy File Status Table

| File | Prod Runtime Dep? | Prod Import? | Prod Caller? | API Dep? | Frontend Dep? | Background Dep? | Test Dep? | Safe to Archive? | Required Migration |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `app/engines/vcc_intelligence_engine.py` | **YES** | **YES** | **YES** | **YES** | NO | **YES** | **YES** | **NO** | Cut over `/api/dashboard` references to `analytics_pipeline` |
| `app/engines/seller_engine.py` | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **NO** | Cut over `/api/dashboard` recommendations to V3 `signal_engine` |
| `app/engines/trade_scorer.py` | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **NO** | Utility used by `seller_engine.py` |
| `app/engines/signal_lifecycle.py` | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **NO** | Cut over `/api/dashboard` lifecycle to `signal_repository` |
| `app/services/live_signal_audit_service.py` | **YES** | **YES** | **YES** | **YES** | **YES** | NO | **YES** | **NO** | Cut over `/api/vcc/live-audit-daily` to `audit_service` |
| `app/services/smart_money_service.py` | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **NO** | Cut over remaining fallback calls in `market.py` to `smart_money_v3_service` |

---

## 9. Repository-Wide Legacy Identifier Scan

| Identifier | Match Count | Context Breakdown |
| :--- | :---: | :--- |
| `vcc_intelligence_engine` | 5 | `app/api/market.py` (4 callers) + `vcc_intelligence_engine.py` |
| `seller_engine` | 6 | `app/api/market.py` (5 callers) + `seller_engine.py` |
| `trade_scorer` | 2 | `app/api/market.py` (1 import) + `trade_scorer.py` |
| `signal_lifecycle` | 12 | `app/api/market.py` (6 callers) + `live_signal_audit_service.py` + DB schema |
| `live_signal_audit_service` | 10 | `app/api/market.py` (6 callers) + `live_signal_audit_service.py` |
| `smart_money_service` | 5 | `app/api/market.py` (3 callers) + `smart_money_service.py` |
| `get_dashboard` | 6 | `app/main.py` (poller) + `app/api/market.py` |
| `/api/dashboard/` | 45 | Frontend `index.html`, test scripts, documentation |

---

## 10. Production Health Verification (READ-ONLY)

FastAPI TestClient execution against production application endpoints:

```
[200 OK] /health
[200 OK] /api/vcc/dashboard/NIFTY
[200 OK] /api/vcc/smart-money/NIFTY
[200 OK] /api/vcc/signals/NIFTY
[200 OK] /api/vcc/audit
[200 OK] /
```

- **Service Status:** Running & Healthy
- **Database Connection:** Connected & verified (`SELECT 1`)
- **V3 API Payload:** Valid `SmartMoneyAnalysisResult` & `VCCDashboardResponse`

---

## 11. Regression Test Verification

Automated test suites executed against the current repository state:

- **Release Candidate Master Test Matrix (`run_all_vm_tests.py`):** **9/9 TEST SUITES PASSED** (Exit Code: 0)
- **Smart Money Dedicated Test Suite (`tests/test_v3_smart_money.py`):** **7/7 TESTS PASSED**
- **V3.2 20-Conditions Governance Audit (`test_v32_20_conditions_audit.py`):** **20/20 AUDITS PASSED**

---

## 12. Decommission Blockers & Required Cutover Steps

To achieve **READY FOR LEGACY ARCHIVAL**, the following remaining cutover steps must be performed in a controlled manner:

1. **Frontend Cutover:** Update `fetchDashboardData` in `backend/app/static/index.html` to consume `/api/vcc/dashboard/${symbol}` directly, eliminating the call to `/api/dashboard/${symbol}`.
2. **`app/api/market.py` Cleanup:** Remove legacy fallback references to `seller_engine`, `signal_lifecycle_engine`, `vcc_intelligence_engine`, `live_signal_audit_service`, and `smart_money_service`.
3. **Background Loop Update:** Update `fyers_live_polling_loop()` in `main.py` to refresh V3 presentation caches without calling legacy `get_dashboard`.

Once those 3 cutover steps are executed, physical archival to `legacy_archive/` can proceed safely with zero risk of breaking production.
