# VCC V3.2 — LEGACY DECOMMISSION & ARCHIVAL MASTER PLAN

**Plan Date:** August 28, 2026  
**System Target:** Production Visual Command Center (VCC V3.2)  
**Execution Phase:** Read-Only Planning & Blueprint (No code modified or moved in this phase)

---

## 1. COMPLETE LEGACY FILE INVENTORY

A complete audit of the repository identified 11 candidate legacy files across engines, services, and root utility scripts:

| File Path | Original Purpose | Current Production Status |
|---|---|---|
| `backend/app/engines/vcc_intelligence_engine.py` | Monolithic legacy intelligence engine | 🔴 Coupled (Invoked by `/api/dashboard/{symbol}`) |
| `backend/app/engines/seller_engine.py` | Option seller strategy recommendation engine | 🔴 Coupled (Invoked by `/api/dashboard/{symbol}`) |
| `backend/app/engines/trade_scorer.py` | Seller strategy win-rate probability matrix | 🔴 Coupled (Called by `seller_engine.py`) |
| `backend/app/engines/signal_lifecycle.py` | Legacy signal lifecycle state machine | 🔴 Coupled (Invoked by `/api/dashboard/{symbol}`) |
| `backend/app/engines/vcc_signal_lab.py` | CLI backtesting & historical simulation lab | 🟢 Standalone (Safe to archive) |
| `backend/app/services/live_signal_audit_service.py` | Legacy 20-Point Signal Audit Engine | 🔴 Coupled (Invoked by background polling loop) |
| `backend/app/services/smart_money_service.py` | Legacy institutional flow shift processor | 🟡 Coupled (Imported by `/api/smart-money/*`) |
| `backend/app/services/polling_service.py` | Unused background polling helper class | 🟢 Standalone (Safe to archive immediately) |
| `run_live_audit_report.py` | Legacy root CLI audit report runner | 🟢 Standalone (Safe to archive) |
| `test_live_audit_pipeline.py` | Legacy root test script for live audit service | 🟢 Standalone (Safe to archive) |
| `test_v32_20_conditions_audit.py` | Legacy root validation script for 20-condition engine | 🟢 Standalone (Safe to archive) |

---

## 2. DEPENDENCY GRAPH

The diagram below illustrates the exact coupling between production components and legacy vs. V3.2 pipelines:

```
                                [ CLIENT BROWSER (index.html) ]
                                               │
                   ┌───────────────────────────┴───────────────────────────┐
                   │ (Current Dual Fetch)                                  │ (Proposed Cutover)
                   ▼                                                       ▼
        GET /api/dashboard/{symbol}                             GET /api/vcc/dashboard/{symbol}
                   │                                                       │
         [ app/api/market.py ]                                     [ app/api/vcc.py ]
                   │                                                       │
   ┌───────────────┼───────────────┐                               ┌───────┴───────┐
   ▼               ▼               ▼                               ▼               ▼
[vcc_intel]  [seller_engine]  [live_audit]                  [DataSourceManager] [AnalyticsPipeline]
   │               │               │                               │               │
[SessionLocal] [trade_scorer]  [SessionLocal]                           ▼               ▼
   │                               │                       [MarketSnapshot] ──> [ConfluenceEngine]
   └───────────────┬───────────────┘                                               │
                   ▼                                                               ▼
        [ DailyMarketSnapshotModel ]                                        [SignalEngine]
        [ VCCLiveSignalAuditModel  ]                                               │
                                                                                   ▼
                                                                        [ImmutableAuditService]
                                                                                   │
                                                                                   ▼
                                                                          [AuditRepository]
```

---

## 3. FILES SAFE TO ARCHIVE IMMEDIATELY (GREEN)

The following files have **ZERO** runtime imports in the V3.2 production API path and can be moved to `archive/V3.1_LEGACY/` immediately:

1. `backend/app/engines/vcc_signal_lab.py` (Superseded by `/api/vcc/research/run`).
2. `backend/app/services/polling_service.py` (Orphaned helper class).
3. `run_live_audit_report.py` (Standalone root script).
4. `test_live_audit_pipeline.py` (Standalone root test script).
5. `test_v32_20_conditions_audit.py` (Standalone root test script).

---

## 4. FILES STILL COUPLED TO PRODUCTION (RED / YELLOW)

The following files are **STILL COUPLED** to production operations and MUST NOT be moved until the cutover steps in Section 5 are executed:

1. `app/engines/vcc_intelligence_engine.py` (Coupled via `/api/dashboard/{symbol}`).
2. `app/engines/seller_engine.py` (Coupled via `/api/dashboard/{symbol}`).
3. `app/engines/trade_scorer.py` (Coupled via `seller_engine.py`).
4. `app/engines/signal_lifecycle.py` (Coupled via `/api/dashboard/{symbol}`).
5. `app/services/live_signal_audit_service.py` (Coupled via `main.py` background polling).
6. `app/services/smart_money_service.py` (Coupled via `/api/smart-money/*`).

---

## 5. REQUIRED V3 MIGRATION STEPS (PRE-ARCHIVAL CUTOVER)

To safely decouple production from legacy files, execute these 3 migration steps in order:

### Step 1: Update Frontend REST Fetch in `backend/app/static/index.html`
- **Location:** Line ~2725 in `fetchDashboardData()`.
- **Change:** Replace dual fetch (`/api/dashboard/${symbol}` then `/api/vcc/dashboard/${symbol}`) with a single direct call to `/api/vcc/dashboard/${symbol}`.
- **Payload Mapping:** Ensure `/api/vcc/dashboard/{symbol}` returns `option_chain`, `smart_money`, `pcr_data`, and `vcc` blocks required by React components.

### Step 2: Refactor Background Polling Loop in `backend/app/main.py`
- **Location:** `fyers_live_polling_loop()` in `main.py`.
- **Change:** Replace `await get_dashboard(symbol)` (which executes legacy engine) with `await data_source_manager.get_snapshot(symbol)` and `await vcc_service.refresh_cache(symbol)`.

### Step 3: Update `app/api/smart_money.py` Router
- **Location:** `app/api/smart_money.py`.
- **Change:** Replace `from app.services.smart_money_service import smart_money_service` with `from app.repositories.smart_money_repository import smart_money_repository`.

---

## 6. DATABASE DEPENDENCIES & REPOSITORY REPLACEMENT

All database operations currently performed via raw `SessionLocal()` in legacy engines must be routed through V3 repositories:

| Model / Table | Legacy Direct Access Location | V3 Repository Replacement |
|---|---|---|
| `DailyMarketSnapshotModel` | `vcc_intelligence_engine.py:138`, `live_signal_audit_service.py:238`, `smart_money_service.py:195` | `app/repositories/market_repository.py` (`MarketRepository`) |
| `VCCLiveSignalAuditModel` | `live_signal_audit_service.py:156`, `live_signal_audit_service.py:222` | `app/repositories/audit_repository.py` (`AuditRepository`) |
| `SmartMoneyShiftModel` | `smart_money_service.py:124`, `smart_money_service.py:262` | `app/repositories/smart_money_repository.py` (`SmartMoneyRepository`) |

---

## 7. FRONTEND DEPENDENCIES & VERIFICATION

Currently, `index.html` relies on:
1. `/api/dashboard/{symbol}` for `option_chain`, `spot_price`, `pcr`, and `seller_recommendations`.
2. `/api/vcc/dashboard/{symbol}` for `confluence_engine`, `signal_card`, `wall_matrix`, and `flow_engine`.

**Cutover Requirement:**  
Once `/api/vcc/dashboard/{symbol}` provides all option chain metrics alongside V3 intelligence, `index.html` can discontinue fetching `/api/dashboard/{symbol}` entirely.

---

## 8. BACKGROUND-TASK DEPENDENCIES

`fyers_live_polling_loop()` in `main.py` runs every 3 seconds during market hours (09:00 - 15:45 IST).
- **Current Execution Path:** `fyers_live_polling_loop` -> `get_dashboard(symbol)` -> `vcc_intelligence_engine` -> `live_signal_audit_service.record_live_signal_snapshot()`.
- **Target V3 Execution Path:** `fyers_live_polling_loop` -> `data_source_manager.get_snapshot(symbol)` -> `analytics_pipeline.execute()` -> `audit_service.record_signal_snapshot()`.

---

## 9. ROLLBACK BACKUP PROCEDURE

Before performing any physical file relocation or code edit, execute the following powershell command to generate a full, immutable system archive:

```powershell
tar -czvf VCC_V3.2_PRE_ARCHIVE_2026-08-28.tar.gz `
  --exclude="*.env" `
  --exclude="__pycache__" `
  --exclude=".git" `
  --exclude="node_modules" `
  backend/ tests/ docs/ README.md config.py requirements.txt
```

> [!IMPORTANT]
> Do NOT include `.env` or API secret files in the `.tar.gz` archive. `fyers_config.json` and `.env` containing live broker keys must be backed up separately via secure encrypted vault storage.

---

## 10. PROPOSED FINAL PROJECT STRUCTURE

After cutover and archival execution, the project directory structure will reflect complete modularity:

```
NSE dashboard/
├── archive/
│   └── V3.1_LEGACY/                  <-- ALL RETIRED LEGACY FILES HERE
│       ├── engines/
│       │   ├── vcc_intelligence_engine.py
│       │   ├── seller_engine.py
│       │   ├── trade_scorer.py
│       │   ├── signal_lifecycle.py
│       │   └── vcc_signal_lab.py
│       ├── services/
│       │   ├── live_signal_audit_service.py
│       │   └── smart_money_service.py
│       └── scripts/
│           ├── run_live_audit_report.py
│           ├── test_live_audit_pipeline.py
│           └── test_v32_20_conditions_audit.py
├── backend/
│   └── app/
│       ├── analytics/               <-- Sub-engines & Analytics Pipeline
│       ├── api/
│       │   └── vcc.py               <-- Unified V3 Presentation REST API
│       ├── audit/                   <-- Immutable Audit & Outcome Engines
│       ├── core/                    <-- System Config & Thresholds
│       ├── db/                      <-- ORM Models & Session Factory
│       ├── domain/                  <-- Canonical Contracts (MarketSnapshot)
│       ├── intelligence/            <-- Confluence Scoring Engine
│       ├── providers/               <-- DataSourceManager & Adapters
│       ├── repositories/            <-- Interface-Driven Persistence
│       ├── signals/                 <-- Pure Deterministic Signal Engine
│       └── main.py                  <-- Decoupled FastAPI Application Entry
├── docs/                            <-- Architecture & Audit Documentation
└── tests/                           <-- Pytest Test Suite
```

---

## 11. VERIFICATION PROCEDURE AFTER ARCHIVAL

After moving files to `archive/V3.1_LEGACY/`, verify system integrity using the following checklist:

1. **Syntax & Import Check:**
   ```powershell
   python -m py_compile backend/app/main.py
   python -m py_compile backend/app/api/vcc.py
   ```
2. **Pytest Test Suite Execution:**
   ```powershell
   pytest tests/ -v
   ```
   *Expectation:* 100% passing across domain contracts, provider failover, analytics pipeline, confluence engine, signal engine, and audit repositories.
3. **Live Endpoint Health Checks:**
   ```powershell
   curl -s http://localhost:8000/api/vcc/dashboard/NIFTY | jq .
   curl -s http://localhost:8000/api/vcc/signal/NIFTY | jq .
   ```
4. **Frontend Interface Validation:**
   Open browser at `http://localhost:8000` and verify that the Visual Cockpit speedometer, wall matrix, and intraday timeline render without browser console errors.

---
*Decommissioning Plan compiled by Antigravity Systems Architecture Team — August 28, 2026*
