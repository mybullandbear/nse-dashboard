# VCC V3.2 READ-ONLY PRODUCTION CUTOVER VERIFICATION

**System Name**: NSE Alpha-Sell Options Terminal & Visual Command Center (VCC V3.2)  
**Verification Mode**: READ-ONLY Evidence Inspection  
**Verification Date**: 2026-08-28  

---

## 1. RUNNING APPLICATION PROCESS INSPECTION

- **PID**: None (Process not currently running on host port 8000)
- **Executable**: `N/A`
- **Command Line**: `N/A`
- **Working Directory**: `c:\Projects\NSE dashboard` (Local workspace)
- **User**: `resea`
- **Python Executable**: `C:\Users\resea\AppData\Local\Programs\Python\Python311\python.exe`
- **Verification Result**: No active Uvicorn server process was detected bound to port 8000 (`ConnectionRefusedError`). The runtime process on `/home/ubuntu/nse-dashboard/` could not be verified on the local host.

---

## 2. SYSTEMD SERVICE VERIFICATION

- **Command Attempted**: `sudo systemctl status nse-dashboard --no-pager`
- **Status**: `NOT APPLICABLE / UNAVAILABLE` (Operating System is Windows; `systemctl` service manager is not present).
- **Service File Template**: Located at `setup_oracle.sh` and documented in `GO_LIVE_REPORT.md`.
- **Verification Result**: Systemd runtime state cannot be verified from local Windows environment.

---

## 3. VM FILE SYSTEM & ARCHITECTURE STRUCTURE

- **Workspace Path**: `c:\Projects\NSE dashboard`
- **Modular Architecture Verification**:
  - `backend/app/domain/` — **PRESENT** (`contracts.py`)
  - `backend/app/providers/` — **PRESENT** (`data_source_manager.py`, `fyers_adapter.py`, `nse_adapter.py`, `simulator_adapter.py`, `replay_adapter.py`)
  - `backend/app/analytics/` — **PRESENT** (`pipeline.py`, `research_runner.py`)
  - `backend/app/intelligence/` — **PRESENT** (`confluence_engine.py`)
  - `backend/app/signals/` — **PRESENT** (`signal_engine.py`)
  - `backend/app/audit/` — **PRESENT** (`audit_service.py`, `outcome_engine.py`)
  - `backend/app/repositories/` — **PRESENT** (`market_repository.py`, `signal_repository.py`, `audit_repository.py`)
  - `backend/app/api/` — **PRESENT** (`vcc.py`)

- **Core Module Verification**:
  - `backend/app/analytics/pipeline.py`: **EXISTS**
  - `backend/app/intelligence/confluence_engine.py`: **EXISTS**
  - `backend/app/signals/signal_engine.py`: **EXISTS**
  - `backend/app/analytics/research_runner.py`: **EXISTS**

---

## 4. LEGACY VS NEW PIPELINE ROUTING STATUS

- **Endpoint Routing Analysis (`backend/app/main.py`)**:
  - `/api/dashboard/{symbol}`: Served by `market_router` (`MarketDataFetcher` / `VCCIntelligenceEngine`)
  - `/api/vcc/dashboard/{symbol}`: Served by `vcc_router` (`VCC Presentation API` DTOs)

- **Routing Status**:
  - `/api/dashboard/{symbol}`: **LEGACY ACTIVE**
  - `/api/vcc/dashboard/{symbol}`: **NEW PIPELINE ACTIVE**
  - **Combined Endpoint Status**: **BOTH ACTIVE**

---

## 5. DATABASE FILE & SCHEMA INSPECTION

- **Database Path**: `c:\Projects\NSE dashboard\nse_terminal.db`
- **Database Size**: `147,456 bytes` (144 KB)
- **Table Schema & Record Counts**:
  - `smart_money_shifts`: 0 records
  - `daily_market_snapshots`: 0 records
  - `signal_lifecycle_records`: 0 records
  - `vcc_signal_outcome_records`: 0 records
  - `vcc_live_signal_audits`: 5 records
- **Verification Result**: Database schema is initialized with audit tables, but historical market snapshot and signal records are minimal (5 audit records).

---

## 6. ENVIRONMENT & SECRET PROTECTION

- **DATABASE_URL**: `sqlite:///./nse_terminal.db` — **CONFIGURED**
- **Fyers API Configuration**: **CONFIGURED**
- **HOST**: `0.0.0.0` — **CONFIGURED**
- **PORT**: `8000` — **CONFIGURED**
- **LOG_LEVEL**: `INFO` — **CONFIGURED**
- **DEBUG**: `False` — **CONFIGURED**
- **Secret Values**: All API keys and secrets remain protected in `.env` and were not exposed.

---

## 7. NGINX & UPSTREAM FORWARDING

- **NGINX Status**: `UNAVAILABLE` (Local Windows OS).
- **Configuration Status**: NGINX reverse proxy configuration script present in `setup_oracle.sh`, but no active NGINX process is running locally.

---

## 8. ACTUAL HTTP RESPONSE TESTING

- **`http://127.0.0.1:8000/health`**: `FAILED` (`ConnectionRefusedError: No connection could be made because target machine actively refused it`)
- **`http://127.0.0.1:8000/api/vcc/dashboard/NIFTY`**: `FAILED` (`ConnectionRefused`)
- **`http://127.0.0.1:8000/`**: `FAILED` (`ConnectionRefused`)
- **Verification Result**: Port 8000 is inactive on the local host.

---

## 9. PROCESS → CODE → DATABASE CHAIN

- **Running PID**: `None`
- **Python Executable**: `C:\Users\resea\AppData\Local\Programs\Python\Python311\python.exe`
- **Working Directory**: `c:\Projects\NSE dashboard`
- **Application Code**: `backend/app/main.py`
- **Database Path**: `c:\Projects\NSE dashboard\nse_terminal.db`
- **Chain Integrity**: Codebase and database exist locally, but active runtime process chain is broken due to server being stopped.

---

## 10. MARKET SESSION POLICY VERIFICATION

- **Source Code Verification (`backend/app/services/market_hours.py` & `constants.py`)**:
  - `09:00 – 09:15 IST`: `PRE-MARKET` (`is_live = False`, `execution_enabled = False`)
  - `09:15 – 15:45 IST`: `LIVE MARKET` (`is_live = True`, `execution_enabled = True`)
  - `15:45 – 16:00 IST`: `POST-MARKET` (`is_live = False`, `execution_enabled = False`)
  - Outside / Weekends: `MARKET CLOSED` (`is_live = False`, `execution_enabled = False`)

- **Specific Timestamp Test Verification**:
  - `15:30:00 IST`: **`LIVE MARKET`** (`is_live = True`, `execution_enabled = True`) — **VERIFIED (PASS)**
  - `15:44:59 IST`: **`LIVE MARKET`** (`is_live = True`, `execution_enabled = True`) — **VERIFIED (PASS)**
  - `15:45:00 IST`: **`POST-MARKET`** (`is_live = False`, `execution_enabled = False`) — **VERIFIED (PASS)**
- **Test Result**: `13/13` deterministic unit tests in `tests/test_domain_contracts.py` **PASSED**.

---

## 11. ROLLBACK BACKUP ARCHIVE VERIFICATION

- **Actual Backup File Path**: `None`
- **Actual File Size**: `N/A`
- **Creation Timestamp**: `N/A`
- **Verification Result**: **BACKUP NOT CREATED** (Backup procedure was documented, but no physical `.tar.gz` archive was generated on disk).

---

## 12. OLD PROJECT STATE

- **State**: The legacy codebase remains mixed alongside the new modular release candidate within `c:\Projects\NSE dashboard`. It has not been moved to a separate `/home/ubuntu/nse-dashboard.old` archive.

---

## 13. DUPLICATE PROCESSES

- **Running Processes**: `0` Python processes bound to port 8000.
- **Verification Result**: **NONE** (No duplicate processes found).

---

## 14. APPLICATION LOGS

- **Systemd Journal**: `UNAVAILABLE` (`journalctl` not present on Windows).
- **Test Suite Logs**: All 64 unit/audit tests executed cleanly with zero unhandled exceptions.

---

## 15. FINAL CLASSIFICATION REPORT

### PRODUCTION CUTOVER STATUS
```text
NOT VERIFIED
```
*(Reason: The server process is not actively running on port 8000, systemd/NGINX cannot be inspected on Windows, and no physical backup archive file exists on disk.)*

---

### Component Sub-Ratings

- **Application**: **WARNING** *(Code is 100% test-passed (64/64), but server process is currently stopped)*
- **Systemd**: **FAIL** *(Service not active/running on target system)*
- **Database**: **WARNING** *(Database file exists, but contains only 5 audit records)*
- **NGINX**: **FAIL** *(Proxy not running or listening on port 80/443)*
- **WebSocket**: **WARNING** *(WebSocket endpoint configured in code, but process is offline)*
- **Market Session**: **PASS** *(09:15–15:45 IST session engine & 13 boundary tests 100% verified)*
- **New Modular Pipeline**: **PASS** *(All modular components implemented, integrated, and 100% test-verified)*
- **Legacy Pipeline**: **BOTH** *(Both legacy `/api/dashboard/` and new `/api/vcc/dashboard/` routers are mounted in `main.py`)*
- **Rollback Backup**: **NOT VERIFIED** *(Physical tarball backup file does not exist)*
- **Duplicate Processes**: **NONE**
- **Public Endpoint**: **FAIL** *(Port 8000 HTTP request returned connection refused)*

---

**AUDIT CONCLUSION**:  
The release candidate code (`V3.2.0-FINAL-RC`) has passed all 64/64 automated tests and 20/20 governance audits locally. However, strictly adhering to the **READ-ONLY live production cutover rules**, the runtime process on port 8000 is stopped, systemd/NGINX services are not active, and no rollback archive file exists. Therefore, the production cutover status is classified as **`NOT VERIFIED`**.
