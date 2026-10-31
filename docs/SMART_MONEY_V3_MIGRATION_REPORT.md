# VCC V3.2 — Smart Money Subsystem Migration & Decoupling Report

**Status:** COMPLETE & FULLY VERIFIED  
**Architecture Version:** VCC V3.2 Modular Enterprise Architecture  
**Primary Subsystem:** `backend/app/smart_money`  
**Alert Subsystem:** `backend/app/alerts`  
**Legacy Status:** Decoupled from production runtime execution  

---

## 1. Executive Summary

The legacy `smart_money_service.py` module contained tight coupling between market data parsing, institution single-strike shift detection, market bias scoring, database persistence, Telegram HTTP network calls, and dashboard UI aggregation.

Under **VCC V3.2 Modular Architecture**, the Smart Money subsystem has been completely ported into a clean, modular subsystem with strict separation of concerns:

- **Pure Business & Analytical Logic:** Encapsulated in `detector.py`, `scoring.py`, and `timeline.py` with **zero side effects** (no DB, no network, no Telegram).
- **Non-Blocking Alert System:** Encapsulated in `backend/app/alerts/telegram_alert_service.py` with asynchronous non-blocking task execution and in-memory/DB duplicate suppression.
- **Repository Persistence:** Delegated to `SmartMoneyRepository` and `MarketRepository` for all database interactions (zero inline SQL queries in business modules).
- **Service Orchestration:** Centralized in `app/smart_money/service.py` (`smart_money_v3_service`).

---

## 2. Subsystem Architecture & Dependency Map

```
                          ┌─────────────────────────────┐
                          │   MarketSnapshot Contract   │
                          └──────────────┬──────────────┘
                                         │
                                         ▼
                   ┌───────────────────────────────────────────┐
                   │    backend/app/smart_money/service.py     │
                   │         (smart_money_v3_service)          │
                   └──────┬──────────────┬──────────────┬──────┘
                          │              │              │
        ┌─────────────────┘              │              └──────────────────┐
        ▼                                ▼                                 ▼
┌─────────────────────────┐  ┌───────────────────────┐   ┌───────────────────────────┐
│       detector.py       │  │      scoring.py       │   │        timeline.py        │
│   Pure Detection Logic  │  │  Pure Scoring Engine  │   │ Intraday Timeline Manager │
└─────────────────────────┘  └───────────────────────┘   └───────────────────────────┘
        │                                │                                 │
        └─────────────────┬──────────────┴──────────────┬──────────────────┘
                          │                             │
                          ▼                             ▼
            ┌───────────────────────────┐  ┌───────────────────────────┐
            │   SmartMoneyRepository    │  │   TelegramAlertService    │
            │   MarketRepository        │  │ (app/alerts) Non-Blocking │
            └───────────────────────────┘  └───────────────────────────┘
```

---

## 3. Detailed Component Specifications

### 3.1 `backend/app/smart_money/detector.py`
- **Functionality:** Identifies institutional block trade shifts, aggressive OI buildup, and call/put unwinding.
- **Symbol Thresholds:**
  - `NIFTY` / `FINNIFTY`: Shift threshold $\ge 35,000$ contracts change.
  - `BANKNIFTY`: Shift threshold $\ge 25,000$ contracts change.
  - Default / Stock: Shift threshold $\ge 20,000$ contracts change.
- **Unwinding Detection:**
  - Call Unwinding: OI Change $\le -25,000$ contracts on Call side $\rightarrow$ `BULL` shift.
  - Put Unwinding: OI Change $\le -25,000$ contracts on Put side $\rightarrow$ `BEAR` shift.

### 3.2 `backend/app/smart_money/scoring.py`
- **Functionality:** Calculates `sm_bias_5` (ATM $\pm 5$ strikes directional change), net institutional bias, conviction scores, expected decay, and actionable Trade Guide recommendations.
- **`sm_bias_5` Calculation:**
  $$\text{Net 5-Strike Diff} = \sum_{\text{ATM}-5}^{\text{ATM}+5} \Delta \text{PE\_OI} - \sum_{\text{ATM}-5}^{\text{ATM}+5} \Delta \text{CE\_OI}$$
  - $\text{Diff} \ge +50,000 \rightarrow$ `BULLISH`
  - $\text{Diff} \le -50,000 \rightarrow$ `BEARISH`
  - Else $\rightarrow$ `NEUTRAL`
- **Trade Guide Rule Matrix:**
  - `STRONG BULLISH` ($\ge 75\%$) $\rightarrow$ Bull Put Spread (Sell PE, Buy OTM PE)
  - `BULLISH` ($60\% - 74\%$) $\rightarrow$ Bull Put Spread / Put Credit Spread
  - `BEARISH` / `STRONG BEARISH` $\rightarrow$ Bear Call Spread (Sell CE, Buy OTM CE)
  - `NEUTRAL / SIDEWAYS` $\rightarrow$ Iron Condor / Short Straddle

### 3.3 `backend/app/smart_money/timeline.py`
- **Functionality:** Normalizes snapshot timestamps to Indian Standard Time (IST) and builds a clean 1-minute deduplicated timeline.
- **Market Session Restriction:** Strictly filters records within **09:15 to 15:45 IST** (minutes 555 to 945).
- **Deduplication:** Keeps only the latest snapshot per minute (`HH:MM`).

### 3.4 `backend/app/alerts/telegram_alert_service.py`
- **Fail-Safe Design:** Non-blocking async HTTP dispatch (`httpx.AsyncClient`). Dispatched inside isolated try-except blocks so network or API token errors **never crash** market data processing.
- **Duplicate Suppression:** Maintains an in-memory set and queries database records for `(symbol, shift_text, trade_date)` to prevent spamming users.

---

## 4. Presentation API Endpoints

The presentation API endpoints consume the modular `smart_money_v3_service` and `smart_money_repository` without touching legacy code:

| Endpoint | Method | Response Model | Description |
| :--- | :--- | :--- | :--- |
| `/api/vcc/smart-money/{symbol}` | `GET` | `SmartMoneyAnalysisResult` | Complete V3 institutional Smart Money analysis, events, timeline, and market direction. |
| `/api/smart-money/{symbol}` | `GET` | `SmartMoneyAnalysisResult` | REST endpoint for UI frontend and historical comparison. |
| `/api/smart-money/dates` | `GET` | `{"dates": List[str]}` | Returns distinct historical dates stored in the repository. |

---

## 5. Verification & Test Matrix Results

All test suites were executed against the modular codebase:

### 5.1 New Dedicated Smart Money Test Suite (`tests/test_v3_smart_money.py`)
- **`test_nifty_threshold_exact_and_below`**: PASSED (NIFTY 35k exact vs 34.99k below)
- **`test_banknifty_threshold_exact_and_below`**: PASSED (BANKNIFTY 25k exact vs 24.99k below)
- **`test_call_and_put_unwinding`**: PASSED (Unwinding $\le -25k$)
- **`test_sm_bias_5_calculation`**: PASSED (ATM $\pm 5$ strike directional scoring)
- **`test_timeline_session_boundary_and_deduplication`**: PASSED (09:15-15:45 IST partition & 1-min deduplication)
- **`test_telegram_duplicate_alert_suppression`**: PASSED (In-memory & DB duplicate suppression)
- **`test_service_process_and_persist_flow`**: PASSED (Full orchestration pipeline execution)

### 5.2 Release Candidate Master Test Matrix (`run_all_vm_tests.py`)
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
RESULTS: 9/9 TEST SUITES PASSED (Exit Code: 0)
=====================================================
```

---

## 6. Conclusion

The Smart Money engine porting and legacy decoupling is **100% complete**. All business logic for single-strike block trades, market direction scoring (`sm_bias_5`), intraday timeline deduplication, and non-blocking Telegram alerting now runs exclusively through `app/smart_money` and `app/alerts`.

`smart_money_service.py` is no longer participating in production runtime execution.
