# VCC V3.2 — Pre-Archival Production Cutover Report

**Cutover Date:** August 28, 2026  
**Audited Subsystems:** `app/engines/`, `app/services/`, `app/api/`, `app/static/`, `main.py`  
**Execution Purpose:** Validate completed production cutover from legacy monolithic pipeline to VCC V3.2 modular architecture prior to physical archival.

---

## Final Classification

### **READY FOR LEGACY ARCHIVAL**

> **Validation Summary:** All 3 legacy production cutover blockers identified in the prior audit have been completely resolved. The frontend (`index.html`), background poller (`main.py`), and market REST router (`market.py`) now operate **100% on the VCC V3.2 modular architecture**. Zero production execution paths depend on legacy engines (`vcc_intelligence_engine`, `seller_engine`, `trade_scorer`, `signal_lifecycle`, `live_signal_audit_service`, `smart_money_service`). All 9/9 release candidate test suites, 7/7 Smart Money tests, 20/20 governance audits, and production health endpoints return 100% pass rates.

---

## 1. Files Changed

| File Path | Description of Changes |
| :--- | :--- |
| `backend/app/static/index.html` | Updated `fetchDashboardData` to consume `/api/vcc/dashboard/${symbol}` directly as its primary state payload. |
| `backend/app/api/vcc.py` | Enhanced `VCCDashboardResponse` and `get_vcc_dashboard` to include all presentation-layer DTOs (`option_chain`, `pcr`, `vix`, `smart_money`, `straddle_tracker`, `strike_wall_heatmap`, `sellers`, `active_signal`). |
| `backend/app/api/market.py` | Completely removed all production imports and execution calls to legacy engines/services (`seller_engine`, `trade_scorer`, `signal_lifecycle`, `vcc_intelligence_engine`, `live_signal_audit_service`, `smart_money_service`). Cut over routes to V3 services and repositories. |
| `backend/app/main.py` | Updated `fyers_live_polling_loop()` to call `refresh_v3_market_data()` from `v3_background_poller.py` instead of `get_dashboard()`. Removed `app.api.market` dependency from background execution. |
| `backend/app/api/websocket.py` | Cut over initial fallback dashboard fetch from `get_dashboard` to `get_vcc_dashboard`. |

---

## 2. Files Added

| File Path | Purpose / Description |
| :--- | :--- |
| `backend/app/services/v3_background_poller.py` | V3-native background market processor. Orchestrates `DataSourceManager` $\rightarrow$ `AnalyticsPipeline` $\rightarrow$ `ConfluenceEngine` $\rightarrow$ `SignalEngine` $\rightarrow$ `SmartMoneyV3Service` $\rightarrow$ `AuditService` $\rightarrow$ `MarketRepository` without invoking API endpoints or legacy engines. |

---

## 3. Legacy Dependencies Removed

The following 6 legacy monolithic components have been **100% disconnected from production runtime execution**:

1. `backend/app/engines/vcc_intelligence_engine.py` (0 production imports / 0 callers)
2. `backend/app/engines/seller_engine.py` (0 production imports / 0 callers)
3. `backend/app/engines/trade_scorer.py` (0 production imports / 0 callers)
4. `backend/app/engines/signal_lifecycle.py` (0 production imports / 0 callers)
5. `backend/app/services/live_signal_audit_service.py` (0 production imports / 0 callers)
6. `backend/app/services/smart_money_service.py` (0 production imports / 0 callers)

---

## 4. API Route Migration

| Route Path | Legacy Provider | V3 Replacement Subsystem | Status |
| :--- | :--- | :--- | :---: |
| `/api/dashboard/{symbol}` | Monolithic `get_dashboard` | `data_source_manager`, `analytics_pipeline`, `smart_money_v3_service`, `signal_engine` | **CUT OVER (V3 Thin Adapter)** |
| `/api/seller-recommendations/{symbol}` | `seller_engine`, `smart_money_service` | `signal_engine`, `smart_money_v3_service` | **CUT OVER (V3 Thin Adapter)** |
| `/api/vcc/live-audit-daily` | `live_signal_audit_service` | `performance_repository`, `audit_repository` | **CUT OVER (V3 Native)** |
| `/api/vcc/live-audit-summary` | `live_signal_audit_service` | `performance_repository` | **CUT OVER (V3 Native)** |
| `/api/vcc/replay` | `vcc_intelligence_engine` | `data_source_manager`, `analytics_pipeline` | **CUT OVER (V3 Native)** |
| `/api/vcc/signal-lab` | `vcc_signal_lab_engine` | `research_runner` | **CUT OVER (V3 Native)** |
| `/api/vcc/dashboard/{symbol}` | N/A | V3 Primary Cockpit Endpoint (`VCCDashboardResponse`) | **ACTIVE V3 PRIMARY** |
| `/api/vcc/smart-money/{symbol}` | N/A | `smart_money_v3_service` | **ACTIVE V3 PRIMARY** |
| `/api/vcc/signals/{symbol}` | N/A | `signal_engine` | **ACTIVE V3 PRIMARY** |
| `/api/vcc/audit` | N/A | `audit_service`, `audit_repository` | **ACTIVE V3 PRIMARY** |

---

## 5. Frontend Migration

- **Primary Polling Function:** `fetchDashboardData(symbol)` in `backend/app/static/index.html`.
- **Target Endpoint:** `/api/vcc/dashboard/${symbol}` (Primary REST source).
- **Compatibility Preservation:** The returned `VCCDashboardResponse` contains all top-level keys (`option_chain`, `pcr`, `vix`, `smart_money`, `straddle_tracker`, `strike_wall_heatmap`, `active_signal`, `sellers`, `vcc`).
- **UI Integrity:** Verified that option chains, PCR meters, Smart Money speedometers, strike heatmaps, and signal decision cards render seamlessly without UI console errors or missing property exceptions.

---

## 6. Background Loop Migration

- **Previous Loop (`main.py`):** `fyers_live_polling_loop()` $\rightarrow$ `get_dashboard(symbol)` (API route wrapper invoking legacy engines).
- **V3 Native Loop (`main.py`):** `fyers_live_polling_loop()` $\rightarrow$ `refresh_v3_market_data(symbol)` (`v3_background_poller.py`).
- **Architecture Validation:** API routes are no longer called by background processes. Background processes interact directly with V3 application services and repositories.

---

## 7. Functional Equivalence

- **Option Chain & PCR:** 100% calculated via `OptionAnalyticsEngine` & canonical `MarketSnapshot`.
- **Spot Price Confirmation & Heatmap:** Calculated via `PriceAnalyticsEngine` & `OptionAnalyticsEngine`.
- **Confluence Scoring:** Calculated via `ConfluenceEngine` using immutable system weights.
- **Signal Decision & Cards:** Generated by `SignalEngine` answering WHAT, WHY, and HOW STRONG.
- **Smart Money Subsystem:** 100% executed via `smart_money_v3_service` with 5-strike directional scoring (`sm_bias_5`), threshold detection, and non-blocking Telegram alerts (`TelegramAlertService`).
- **Market Hours Policy:** Strictly preserved at 09:15–15:45 IST (`Asia/Kolkata`).

---

## 8. Test Results

Executed automated test matrix prior to production cutover validation:

```
=====================================================
  EXECUTING DEPLOYED RELEASE CANDIDATE TEST MATRIX   
=====================================================
[PASS] tests/test_domain_contracts.py
[PASS] tests/test_data_source_manager.py
[PASS] tests/test_analytics_pipeline.py
[PASS] tests/test_signal_decision_engine.py
[PASS] tests/test_audit_governance_anti_lookahead.py
[PASS] tests/test_persistence_repositories.py
[PASS] tests/test_vcc_api_presentation.py
[PASS] tests/test_replay_research_engine.py
[PASS] test_v32_20_conditions_audit.py
=====================================================
RESULTS: 9/9 TEST SUITES PASSED
=====================================================

[PASS] tests/test_v3_smart_money.py (7/7 tests PASSED)
[PASS] test_v32_20_conditions_audit.py (20/20 audits PASSED)
[PASS] run_v32_hardened_tests.py (6/6 tests PASSED)
```

---

## 9. Production Health Verification

HTTP health checks executed against active FastAPI application instance:

```
/health                        --> 200 OK
/api/vcc/dashboard/NIFTY       --> 200 OK
/api/vcc/smart-money/NIFTY     --> 200 OK
/api/vcc/signals/NIFTY         --> 200 OK
/api/vcc/audit                 --> 200 OK
/                              --> 200 OK
/api/vcc/dashboard/BANKNIFTY   --> 200 OK
/api/vcc/dashboard/FINNIFTY    --> 200 OK
/api/vcc/dashboard/MIDCPNIFTY  --> 200 OK
```

---

## 10. Rollback Archive Path

- **Rollback Directory:** `legacy_archive/pre_decommission_backup_20260828/`
- **Current State:** Repository contains zero active runtime references to legacy files.

---

## 11. Final Legacy Dependency Scan

Repository-wide static scan for legacy engine identifiers across `backend/app`:

| Identifier | Production Runtime Imports | Production Callers | Classification |
| :--- | :---: | :---: | :--- |
| `vcc_intelligence_engine` | **0** | **0** | Safe for Physical Archival |
| `seller_engine` | **0** | **0** | Safe for Physical Archival |
| `trade_scorer` | **0** | **0** | Safe for Physical Archival |
| `signal_lifecycle` | **0** | **0** | Safe for Physical Archival |
| `live_signal_audit_service` | **0** | **0** | Safe for Physical Archival |
| `smart_money_service` | **0** | **0** | Safe for Physical Archival |

*(Note: Schema strings such as column name `signal_lifecycle_stage` in `models.py` remain preserved for database backward compatibility).*

---

## 12. Remaining Risks

- **Stale Browser Caches:** Users with active browser tabs open may need to refresh once to ensure the client JS fetches `/api/vcc/dashboard/` instead of legacy cached endpoints.
- **Risk Mitigation:** Legacy `/api/dashboard/{symbol}` endpoint is maintained as a thin, non-breaking V3 adapter so legacy client sessions will continue to operate smoothly without errors.

---

## 13. Exact Files Now Safe to Archive

The following 6 files may now be safely moved to `legacy_archive/` in a subsequent archival task:

1. `backend/app/engines/vcc_intelligence_engine.py`
2. `backend/app/engines/seller_engine.py`
3. `backend/app/engines/trade_scorer.py`
4. `backend/app/engines/signal_lifecycle.py`
5. `backend/app/services/live_signal_audit_service.py`
6. `backend/app/services/smart_money_service.py`
