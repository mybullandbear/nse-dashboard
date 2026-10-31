# ALPHA-SELL / VISUAL COMMAND CENTER (VCC) V3.2 — MASTER ARCHITECTURE & SPECIFICATION PROMPT

> **LLM DEPLOYMENT PROMPT INSTRUCTION:**  
> This file is a complete, self-contained architecture blueprint and code specification for the **NSE Alpha-Sell Options Terminal & Visual Command Center (VCC V3.2)**. Any LLM reading this document can reconstruct, debug, deploy, or upload the complete application to a remote server (e.g., Oracle Cloud VM, AWS, DigitalOcean, or local machine) and make it operational without requiring additional context.

---

## 1. 🎯 PROJECT OBJECTIVE & EXECUTIVE OVERVIEW

The **NSE Alpha-Sell Options Terminal & Visual Command Center (VCC V3.2)** is an institutional-grade, real-time index options intelligence system for the National Stock Exchange of India (NSE). It tracks real-time option chains, institutional order flows, strike-level open interest (OI) defense walls, straddle decay, and market regime transitions for **NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY**.

### Core Operational Principles
1. **Real-Time Data Ingestion**: Primary ingestion via **Fyers Broker API v3**, with secondary fallback to **NSE India web scrapers** (`curl_cffi`), and tertiary fallback to Yahoo Finance / synthetic market simulation (`OptionChainSimulator`).
2. **Deterministic Intelligence Engine**: Multi-factor confluence scoring ($0–100$), directional flow analysis in ₹ Lakhs/Crores, support/resistance wall migration velocity ($\text{pts/hr}$), straddle decay metrics, and breakout compression state.
3. **Strict Market Session Boundaries**: Execution signals and persistent snapshot recordings are strictly restricted to regular NSE derivative market hours (**09:15 to 15:30 IST**). Outside market hours, operational state is locked to `MARKET CLOSED` with execution disabled.
4. **20-Point Governance & Look-Ahead Audit Engine**: Signals and performance metrics are audited via immutable database snapshots (`vcc_live_signal_audits`), with forward outcomes ($T+5\text{m}, T+15\text{m}, T+30\text{m}$ MFE/MAE) calculated exclusively from snapshots recorded *after* signal generation time $T$. Non-directional signals (`WATCH`, `SIGNAL CONFLICT`) are strictly excluded from directional accuracy metrics.

---

## 2. 🔌 DATA INGESTION & BROKER INTEGRATION

### A. Fyers Broker API v3 OAuth Integration (`backend/app/services/fyers_fetcher.py`)
- **API Version**: Fyers v3 API (`fyers-apiv3`).
- **Authentication Flow**:
  1. `POST /api/fyers/credentials` saves `client_id`, `secret_key`, and `redirect_uri` to `backend/app/fyers_config.json`.
  2. `GET /api/fyers/login` redirects user to Fyers OAuth login page (`generate_auth_code()`).
  3. Fyers redirects to `GET /api/fyers/callback?auth_code=...`.
  4. Backend exchanges `auth_code` for `access_token` via `SessionModel.generate_token()`.
  5. `clean_token()` sanitizes token by stripping quotes, whitespace, `Bearer ` prefix, and prepended `client_id:`.
  6. `validate_connection()` tests the token against live Fyers servers by requesting a quote (`NSE:NIFTY50-INDEX`).
- **Intercepting Invalid/Expired Tokens**:
  - `_handle_api_response()` inspects Fyers API responses.
  - If Fyers returns error codes (`-14, -15, -16, -17, -99, 401, 403`) or error text containing `token`, `invalid`, `expired`, `unauthorized`, or `session`, session is invalidated (`access_token = None`), error is saved to `last_error`, and `is_configured()` returns `False`.

### B. Fallback Hierarchy & Polling Loop (`backend/app/main.py` & `backend/app/api/market.py`)
1. **Fyers Live Broker Feed**: `fyers_service.get_option_chain(symbol)` (returns `FYERS_LIVE`).
2. **NSE Web Scraper**: `nse.get_option_chain(symbol)` using `curl_cffi` HTTP client (returns `NSE_LIVE`).
3. **Historical DB Baseline**: Pulls latest real snapshot from SQLite database.
4. **Simulator Fallback**: `OptionChainSimulator.get_option_chain(symbol)` generates synthetic strikes and option ticks (returns `SIMULATED` or `MOCK`).

### C. Background Polling Architecture
- **`fyers_live_polling_loop` (1s – 3s frequency)**: Refreshes live quotes and option chains during market hours (09:00 – 15:45 IST). During off-market hours, polls live indices every 15 seconds without persisting DB snapshots.
- **`nse_slow_polling_loop` (30s frequency)**: Scrapes official web index data.
- **`stock_polling_loop` (60s frequency)**: Fetches top stock gainers/losers and sector breadth.
- **`db_cleanup_loop` (4h frequency)**: Purges market data older than 7 days and audit signals older than 30 days.

---

## 3. 💾 BACKEND DATA PERSISTENCE & DATABASE SCHEMA

Database layer built using **SQLAlchemy ORM** over **SQLite** (`backend/app/db/database.py`, SQLite file: `nse_terminal.db`).

### Key Database Tables (`backend/app/db/models.py`)

#### 1. `vcc_live_signal_audits` (Primary Audit Table)
Stores immutable snapshot telemetry for every state change / signal during live trading:
- **`snapshot_id`** (String, Unique Primary Key): `AUDIT_{symbol}_{timestamp}`.
- **`trade_date`** (String): `YYYY-MM-DD`.
- **`timestamp`** (String): ISO timestamp string.
- **`symbol`** (String): `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`.
- **`session_slot`** (String): `09:15-09:30`, `09:30-11:30`, `11:30-14:00`, `14:00-15:30`, `OFF_MARKET`.
- **`spot_price`**, **`option_chain_timestamp`**, **`spot_timestamp`**, **`option_data_age_sec`**, **`spot_data_age_sec`**.
- **`data_quality_status`**: `DATA QUALITY GOOD`, `DATA QUALITY DEGRADED`, `DATA QUALITY INVALID`.
- **`positioning_score`**, **`price_confirmation_score`**, **`final_confluence_score`** ($0–100$).
- **`confluence_label`**, **`directional_flow_label`**, **`net_flow_lakhs`**, **`pe_flow_lakhs`**, **`ce_flow_lakhs`**, **`total_activity_lakhs`**.
- **`pcr`**, **`atm_straddle_premium`**, **`support_wall`**, **`resistance_wall`**, **`wall_migration_direction`**, **`breakout_status`**, **`range_compression_status`**, **`atm_pressure_score`**.
- **`operational_state`**: `PRE-MARKET`, `LIVE MARKET`, `POST-MARKET`, `MARKET CLOSED`, `ENTRY CONFIRMED`, `ENTRY READY`.
- **`market_regime`**: `RANGE`, `BREAKOUT`, `TRENDING`, `HIGH VOLATILITY`.
- **`signal_direction`**: `BULLISH`, `BEARISH`, `NEUTRAL`.
- **`signal_lifecycle_stage`**: `CREATED`, `CONFIRMED`, `EXPIRED`, `SUPERSEDED`.
- **`model_confidence`**, **`persistence_pct`**, **`historical_sample_size`**, **`historical_reliability_pct`**.
- **Retrospective Forward Outcomes**: `outcome_evaluated` (Boolean), `spot_t5`, `spot_t15`, `spot_t30`, `return_t5_pct`, `return_t15_pct`, `return_t30_pct`, `mfe_t30_pct`, `mae_t30_pct`, `directional_correctness_5m`, `directional_correctness_15m`, `directional_correctness_30m`, `false_signal_category`.

#### 2. `daily_market_snapshots`
Intraday snapshots recorded every 3 seconds for charting intraday flow wave and spot price time series.

#### 3. `signal_lifecycle_records`
Tracks trade execution lifecycle (entry spot, target premium, stop loss, margin, P&L, MFE/MAE).

#### 4. `smart_money_shifts`
Logs block trade anomalies, massive OI additions/unwinding, and smart money conviction shifts.

---

## 4. 🧠 INTELLIGENCE ENGINE & ANALYTICAL LOGIC

The VCC V3.2 Intelligence Engine (`backend/app/engines/vcc_intelligence_engine.py`) computes all market parameters deterministically:

### A. Market Session Engine
```python
IST Time Range       Session State       Execution Status
09:00 - 09:15 IST -> PRE-MARKET       -> DISABLED
09:15 - 15:30 IST -> LIVE MARKET      -> ENABLED (IF CONFLUENCE MET)
15:30 - 16:00 IST -> POST-MARKET      -> DISABLED
Other Times       -> MARKET CLOSED    -> DISABLED
```

### B. Option Chain & PCR Analysis
- **ATM Strike Calculation**:
  $$\text{ATM} = \text{round}\left(\frac{\text{Spot Price}}{\text{Strike Step}}\right) \times \text{Strike Step}$$
  *(Strike Step: 50 for NIFTY/FINNIFTY/MIDCPNIFTY, 100 for BANKNIFTY/SENSEX)*.
- **PCR Variants**:
  - Overall PCR: $\sum \text{Put OI} / \sum \text{Call OI}$.
  - ATM $\pm 5$ PCR: Put OI vs Call OI restricted to 5 strikes around ATM.

### C. Strike-Level Wall Detection & Migration Velocity
- **Support Wall**: Strike below ATM with maximum Put Open Interest.
- **Resistance Wall**: Strike above ATM with maximum Call Open Interest.
- **Wall Migration Velocity**:
  $$\text{Velocity (pts/hr)} = \frac{\text{Current Wall Strike} - \text{Wall Strike 1 Hour Ago}}{1.0\text{ Hour}}$$
- **Wall Migration Direction**:
  - `UPWARD_MIGRATION` (Velocity $> +25\text{ pts/hr}$)
  - `DOWNWARD_MIGRATION` (Velocity $< -25\text{ pts/hr}$)
  - `STABLE` / `OSCILLATING` (Velocity within $\pm 25\text{ pts/hr}$)

### D. Institutional Flow & Confluence Scoring
- **CE Flow (₹ Lakhs)**: $\sum (\Delta \text{CE OI} \times \text{CE LTP}) / 100,000$.
- **PE Flow (₹ Lakhs)**: $\sum (\Delta \text{PE OI} \times \text{PE LTP}) / 100,000$.
- **Net Directional Flow**: $\text{PE Flow} - \text{CE Flow}$.
- **Confluence Score ($0 – 100$)**:
  $$\text{Confluence} = 0.35 \times \text{Positioning} + 0.30 \times \text{Price Confirmation} + 0.15 \times \text{Wall Proximity} + 0.20 \times \text{Straddle Decay}$$

### E. Look-Ahead Protection & Performance Governance (`backend/app/services/live_signal_audit_service.py`)
1. **Outcome Evaluation Trigger**: Outcomes at $T+5\text{m}, T+15\text{m}, T+30\text{m}$ are calculated **only when a snapshot exists at or after $T + \Delta t$**.
2. **Directional Correctness Evaluation**:
   - `BULLISH` Signal: WIN if $\text{Spot}_{T+\Delta t} - \text{Spot}_T \ge +10.0\text{ pts}$, LOSS if $\le -10.0\text{ pts}$.
   - `BEARISH` Signal: WIN if $\text{Spot}_T - \text{Spot}_{T+\Delta t} \ge +10.0\text{ pts}$, LOSS if $\le -10.0\text{ pts}$.
   - `WATCH`, `NO SIGNAL`, `SIGNAL CONFLICT`: Classified as `NEUTRAL`, excluded from win/loss accuracy totals.
3. **Statistical Validity Governance**: Any signal filter or confidence bucket with fewer than 30 completed samples ($N < 30$) is tagged as `INSUFFICIENT SAMPLE`.

---

## 5. 🎨 FRONTEND PRESENTATION & USER INTERFACE

The visual interface is delivered as a single-file React 18 SPA embedded inside `backend/app/static/index.html` via FastAPI static file mounting:

### Core UI Modules
1. **Header & Navigation Strip**:
   - Live Session Indicator (`● LIVE MARKET`, `● MARKET CLOSED`).
   - Data Source Badge (`● BROKER` [Green], `● NSE` [Blue], `● SIMULATED` [Rose]).
   - Primary Mode Switcher: **Visual Cockpit** vs **Numerical Terminal**.
   - Broker Authentication Modal button (`⚡ FYERS` / `🔑 FYERS LOGIN`).
2. **Smart Money Conviction Speedometer & Flow Wave**:
   - Gauge displaying Smart Money Conviction Score ($0–100$).
   - Real-time intraday line chart showing Net Institutional Flow vs Spot Price.
3. **ATM Defense Wall Heatmap & Straddle Decay Tracker**:
   - Visual heatmap showing CE Writers vs PE Writers at ATM $\pm 10$ strikes.
   - Combined ATM Straddle Decay metric, VWAP bias, and decay speed (`FAST DECAY` / `STABLE`).
4. **VCC Intelligence Strip & Signal Radar**:
   - Confluence gauge, positioning score, price confirmation score, directional flow, persistence %, and operational state.

---

## 6. 🔑 CREDENTIALS, TOKENS & ENVIRONMENT VARIABLES

To run live market data feed from Fyers Broker API, the following credentials are configured in `backend/app/fyers_config.json` or environment variables:

| Credential | Variable Name | Purpose / Source | Example Value |
|---|---|---|---|
| **Client ID** | `FYERS_CLIENT_ID` | Obtained from Fyers API Dashboard | `` |
| **Secret Key** | `FYERS_SECRET_KEY` | Obtained from Fyers App Config | `` |
| **Redirect URI** | `FYERS_REDIRECT_URI` | Configured in Fyers App Settings | `http://137.23.42.11:8000/api/fyers/callback` |
| **Access Token** | `FYERS_ACCESS_TOKEN` | Generated daily via OAuth or pasted in UI | `eyJhbGciOiJIUzI1Ni...` |

*(Note: Fyers access tokens expire daily at midnight IST per Indian broker security regulations).*

---

## 7. 📦 DEPENDENCIES & PROJECT FILE STRUCTURE

### Project Directory Layout
```text
NSE dashboard/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── auth.py             <-- Fyers OAuth v3 endpoints & token validation
│   │   │   ├── market.py           <-- Dashboard endpoints & live polling
│   │   │   ├── smart_money.py      <-- Smart Money tracker API
│   │   │   ├── stocks.py           <-- Stock market intelligence API
│   │   │   └── websocket.py        <-- High-frequency WebSocket manager
│   │   ├── db/
│   │   │   ├── database.py         <-- SQLAlchemy engine & SessionLocal
│   │   │   └── models.py           <-- Database ORM models
│   │   ├── engines/
│   │   │   ├── vcc_intelligence_engine.py <-- Core VCC V3.2 Intelligence Engine
│   │   │   ├── seller_engine.py    <-- Seller recommendation engine
│   │   │   └── signal_lifecycle.py <-- Lifecycle state manager
│   │   ├── services/
│   │   │   ├── fyers_fetcher.py    <-- Fyers API v3 client & auto-auth
│   │   │   ├── nse_fetcher.py      <-- NSE web scraper client (curl_cffi)
│   │   │   ├── live_signal_audit_service.py <-- 20-Point Audit Engine
│   │   │   ├── smart_money_service.py <-- Institutional flow processor
│   │   │   └── mock_engine.py     <-- Live market fallback simulator
│   │   ├── static/
│   │   │   └── index.html          <-- Single-file React 18 SPA Frontend
│   │   ├── config.py               <-- Settings & Environment loader
│   │   ├── fyers_config.json       <-- Saved broker credentials & token
│   │   └── main.py                 <-- FastAPI app entry point & polling loops
│   └── requirements.txt
├── test_v32_20_conditions_audit.py <-- 20-Point Governance Integrity Test Suite
├── setup_oracle.sh                 <-- Automated Ubuntu VM Deployment Script
└── Logic.md                        <-- Master Specification Document
```

### Python Dependencies (`backend/requirements.txt`)
```text
fastapi==0.115.0
uvicorn[standard]==0.30.6
websockets==12.0
httpx==0.27.2
redis==5.0.8
sqlalchemy==2.0.35
psycopg2-binary==2.9.9
alembic==1.13.2
apscheduler==3.10.4
pydantic==2.9.2
pydantic-settings==2.5.2
python-dotenv==1.0.1
numpy==1.26.4
scipy==1.14.1
pandas==2.2.2
beautifulsoup4==4.12.3
lxml==5.3.0
fyers-apiv3>=3.0.0
curl_cffi>=0.7.0
```

---

## 8. 🚀 SERVER DEPLOYMENT & EXECUTION BLUEPRINT

To upload and run this project on any Linux Cloud VM (Ubuntu 22.04 LTS / Oracle Cloud Free Tier / AWS EC2):

### Step 1: Connect to Server & Clone/Upload Project
```bash
ssh -i "path/to/ssh-key.key" ubuntu@<SERVER-IP>
git clone <YOUR-REPOSITORY-URL> nse-dashboard
cd nse-dashboard
```

### Step 2: Execute Automated Deployment Script (`setup_oracle.sh`)
```bash
chmod +x setup_oracle.sh
./setup_oracle.sh
```

### What `setup_oracle.sh` Executes Automatically:
1. System package update & installation (`python3-pip`, `python3-venv`, `nginx`, `ufw`).
2. Creates a 2GB Swap file to prevent out-of-memory errors during build.
3. Installs Python virtual environment and installs `requirements.txt`.
4. Creates systemd background service `/etc/systemd/system/nse-dashboard.service`:
   ```ini
   [Unit]
   Description=NSE Options Terminal FastAPI Server
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/nse-dashboard/backend
   ExecStart=/home/ubuntu/nse-dashboard/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
5. Opens ports 80, 443, and 8000 in `iptables` / firewall rules.

---

## 9. 🤖 ONE-SHOT MASTER LLM DEPLOYMENT PROMPT

> **Copy and paste the prompt below into any AI assistant (ChatGPT, Gemini, Claude) to build, configure, or upload this system to a remote server:**

```text
You are an expert full-stack python developer and cloud DevOps engineer.

I want you to deploy the "NSE Alpha-Sell Options Terminal & Visual Command Center (VCC V3.2)" onto my Ubuntu Linux server.

Here are the project requirements based on Logic.md:
1. TECH STACK: FastAPI (Backend), SQLAlchemy + SQLite (Persistence), Fyers API v3 (Broker Feed), curl_cffi (NSE Fallback Scraper), Single-File React 18 SPA (Frontend in backend/app/static/index.html).
2. SERVER REPO: Clone/upload the workspace files.
3. VIRTUALENV SETUP: Create python3 venv in the project directory, upgrade pip, and install all dependencies from backend/requirements.txt including fyers-apiv3 and curl_cffi.
4. FYERS CONFIGURATION: Check backend/app/fyers_config.json. Ensure credentials (client_id, secret_key, redirect_uri) are saved properly and token cleaning via clean_token() is enabled.
5. DATABASE INITIALIZATION: Ensure SQLite database nse_terminal.db is created with all ORM models (vcc_live_signal_audits, daily_market_snapshots, signal_lifecycle_records, smart_money_shifts).
6. SYSTEMD SERVICE: Create and enable /etc/systemd/system/nse-dashboard.service to run uvicorn app.main:app --host 0.0.0.0 --port 8000 under systemd restart management.
7. FIREWALL & NETWORK: Open port 8000 and port 80 in iptables/ufw.
8. AUDIT TEST VERIFICATION: Run 'python test_v32_20_conditions_audit.py' to confirm that all 20 audit governance conditions pass with zero errors.

Execute all necessary terminal commands autonomously, verify server startup via HTTP status check, and return the server access URL once operational.
```

---

*Master Architecture Specification Document — VCC V3.2 Final Release.*
