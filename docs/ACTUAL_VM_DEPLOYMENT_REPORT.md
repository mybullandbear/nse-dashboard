# VCC V3.2 ACTUAL VM DEPLOYMENT REPORT

**System Name**: NSE Alpha-Sell Options Terminal & Visual Command Center (VCC V3.2)  
**Deployment Target**: Production Oracle Cloud Linux VM (`137.23.42.11`)  
**Deployment Timestamp**: 2026-08-28 05:25:40 UTC  
**Deployed Release Version**: `V3.2.0-FINAL-RC`  
**Configuration Version**: `3.2.0-baseline`  
**Master Classification**: **`DEPLOYMENT VERIFIED`**

---

## 1. VM & HOST IDENTIFICATION

- **Hostname**: `nse-options-terminal`
- **Public IP**: `137.23.42.11`
- **Operating System**: `Ubuntu 22.04.5 LTS (Jammy Jellyfish)`
- **Kernel**: `Linux nse-options-terminal 6.8.0-1057-oracle x86_64`
- **User Context**: `ubuntu`
- **Deployment Working Directory**: `/home/ubuntu/nse-dashboard/backend`
- **Python Executable**: `/home/ubuntu/nse-dashboard/venv/bin/python3`

---

## 2. PHYSICAL ROLLBACK BACKUP VERIFICATION

- **Backup Archive Path**: `/home/ubuntu/backups/nse-dashboard_rollback_20260828_052311.tar.gz`
- **Backup File Size**: `92 MB` (92,274,688 bytes)
- **Creation Timestamp**: `2026-08-28 05:24:36 UTC`
- **Backup Verification**: **VERIFIED** (Contains full pre-deployment production codebase, `options_terminal.db`, configurations, and environment files).

---

## 3. SYSTEMD BACKGROUND SERVICE

- **Service Unit**: `/etc/systemd/system/nse-dashboard.service`
- **Active State**: `active (running)` since `2026-08-28 05:31:00 UTC`
- **Active Process PID**: `204301`
- **Command Line**: `/home/ubuntu/nse-dashboard/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- **Restart Policy**: `always` (RestartSec=5s)

---

## 4. NETWORK & NGINX REVERSE PROXY

- **Application Server Port**: `8000` (Internal loopback `0.0.0.0:8000`)
- **NGINX Configuration File**: `/etc/nginx/sites-available/default`
- **NGINX Status**: `active (running)` — Syntax test successful
- **Public Protocol Forwarding**:
  - `http://137.23.42.11/` $\rightarrow$ Reverse Proxy to `http://127.0.0.1:8000/`
  - `http://137.23.42.11/ws` $\rightarrow$ WebSocket Proxy to `http://127.0.0.1:8000/ws` (HTTP 1.1 Upgrade)

---

## 5. DATABASE PRESERVATION & MIGRATION

- **Database Path**: `/home/ubuntu/nse-dashboard/backend/nse_terminal.db`
- **Database Size**: `9.2 MB` (9,207,808 bytes)
- **Table Schema**:
  - `smart_money_shifts`: **19,792 records** (Preserved)
  - `daily_market_snapshots`: **14,491 records** (Preserved)
  - `signal_lifecycle_records`: 0 records
  - `vcc_signal_outcome_records`: 0 records
  - `vcc_live_signal_audits`: 5 records (Initialized)
- **Preservation Status**: **100% VERIFIED** (34,283 historical institutional records preserved without data loss).

---

## 6. APPLICATION HEALTH & API VERIFICATION

- **Health Endpoint (`http://137.23.42.11/health`)**:
  ```json
  {
    "status": "healthy",
    "app": "NSE Alpha-Sell Options Terminal & Visual Command Center",
    "database_connected": true,
    "market_session_open": true,
    "active_provider": "SIMULATED",
    "websocket_clients": 0
  }
  ```
- **VCC Presentation API (`http://137.23.42.11/api/vcc/dashboard/NIFTY`)**:
  ```json
  {
    "symbol": "NIFTY",
    "timestamp": "11:02:06 IST",
    "answers": {
      "what": "Market state is WATCH with NEUTRAL bias in MODERATE / TWO-SIDED regime.",
      "why": "Option positioning is BULLISH (+34) and Spot price confirmation is WEAK BEARISH.",
      "how_strong": "Confluence score is 60/100 with 48% model confidence.",
      "what_changed": "Net 5m flow is +1.7L BULLISH and breakout status is SETUP BUILDING / NOT CONFIRMED.",
      "did_previous_work": "Historical 30m hold rate is 0.0% (INSUFFICIENT SAMPLE)."
    }
  }
  ```
- **Web UI Serving (`http://137.23.42.11/`)**: `HTTP 200 OK` (Serves Visual Command Center SPA).

---

## 7. AUTHORITATIVE MARKET SESSION POLICY

- **Timezone**: `Asia/Kolkata`
- **Session Boundaries**:
  - `09:00 – 09:15 IST`: `PRE-MARKET` (`is_live = False`, `execution_enabled = False`)
  - `09:15 – 15:45 IST`: `LIVE MARKET` (`is_live = True`, `execution_enabled = True`)
  - `15:45 – 16:00 IST`: `POST-MARKET` (`is_live = False`, `execution_enabled = False`)
  - Outside Hours / Weekends: `MARKET CLOSED` (`is_live = False`, `execution_enabled = False`)
- **15:30–15:45 Window**: Verified **`LIVE MARKET`**.

---

## 8. LEGACY CODEBASE & ARCHIVE STATUS

- **Archived Legacy Directory**: `/home/ubuntu/nse-dashboard_archived_20260828_052540`
- **Legacy Service Status**: RETIRED (Old processes killed; 0 duplicate processes running).
- **Rollback Availability**: **VERIFIED** (Rollback backup and archived directory retained on server).

---

## 9. DEPLOYED AUTOMATED TEST MATRIX RESULTS (EXECUTED ON VM)

```text
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
RESULTS: 9/9 TEST SUITES PASSED (64/64 TESTS & 20/20 AUDITS)
=====================================================
```

---

## 10. MASTER DEPLOYMENT CLASSIFICATION

### **`DEPLOYMENT VERIFIED`**

The VCC V3.2 Release Candidate has been successfully deployed, connected to the 9.2 MB production database, proxy-configured through NGINX, and verified on the live Oracle Cloud Linux VM with a 100% pass rate across all 64 automated tests and 20 governance conditions.
