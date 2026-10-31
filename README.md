# NSE Options Terminal & Visual Command Center V4 Pro

An institutional-grade, real-time decision support terminal and signal generation platform for NSE index option sellers. Features live Call vs Put Open Interest analytics, multi-factor confluence scoring, strike-level defense walls, and smart money order flow tracking.

---

## 🚀 Key Features

1. **Call vs Put Open Interest Visualizations (The Core Centerpiece)**:
   - **Dual-Axis Intraday Timeline (09:15 - 15:30 IST)**: Real-time tracking of Put OI (emerald) vs Call OI (coral red) with underlying Spot Price (gold dashed) on secondary axis. Supports `TOTAL OI`, `OI CHANGE`, and `NET DIFF (CE - PE)` modes.
   - **Strike-Wise Call vs Put Comparative Bar Chart**: Side-by-side distribution of Call OI vs Put OI for ATM ± 10 strikes, clearly marking the ATM strike, Support Wall, and Resistance Wall.
2. **Multi-Factor Confluence Engine (0 - 100)**:
   - Deterministic confluence weighting: Positioning (35%), Price Confirmation (30%), Wall Proximity (15%), Straddle Decay (20%).
   - Generates direction (`BULLISH`, `BEARISH`, `NEUTRAL`), operational state (`ENTRY READY`, `CONFIRMED BIAS`, `WATCH`), and actionable Option Seller Trade Guides (Credit Spreads, Stop Loss, Target).
3. **Smart Money Order Flow & Defense Walls**:
   - Institutional net capital flow tracking in ₹ Crores ($\text{PE Flow} - \text{CE Flow}$).
   - Conviction Speedometer ($0 - 100$).
   - ATM Straddle Combined Premium Decay & VWAP tracker.
4. **Prioritized Multi-Tier Data Ingestion**:
   - **Tier 1**: Fyers Broker API v3 (live quotes & option chains).
   - **Tier 2**: Official NSE India scraper with Chrome 120 TLS impersonation (`curl_cffi`).
   - **Tier 3**: High-fidelity Market Simulator for off-market local testing and development.
5. **Modern Modular Architecture**:
   - Clean separation of concerns (`core`, `services`, `api`, `db`, `static`).
   - Pure ES6 modular frontend with dark Bloomberg/TradingView terminal aesthetics.

---

## 📁 Project Directory Layout

```text
c:/Projects/NSE dashboard/
├── _archive/                      <-- Complete archive of legacy codebase & history
├── backend/
│   ├── app/
│   │   ├── api/                   <-- REST & WebSocket API endpoints
│   │   │   ├── auth.py            <-- Fyers OAuth v3 & token verification
│   │   │   ├── market.py          <-- Live indices, session info, option chain
│   │   │   ├── oi_analytics.py    <-- Call vs Put OI analytics & strike data
│   │   │   ├── signals.py         <-- Confluence radar & seller trade strategies
│   │   │   └── websocket.py       <-- High-frequency WebSocket streaming
│   │   ├── core/                  <-- Configuration & market timing
│   │   │   ├── config.py          <-- Pydantic application settings
│   │   │   └── market_hours.py    <-- IST timing & session state (09:15-15:30 IST)
│   │   ├── services/              <-- Business logic & data adapters
│   │   │   ├── fyers_service.py   <-- Fyers v3 API client & token sanitizer
│   │   │   ├── nse_fetcher.py     <-- NSE India scraper (curl_cffi Chrome TLS)
│   │   │   ├── simulator.py       <-- Realistic market simulation engine
│   │   │   ├── option_chain.py    <-- Option chain normalizer, Max Pain, PCR
│   │   │   ├── oi_analyzer.py     <-- Call vs Put OI timeline & wall detector
│   │   │   ├── signal_engine.py   <-- Confluence scoring & strategy generator
│   │   │   └── smart_money.py     <-- Institutional order flow (₹ Cr) & conviction
│   │   ├── db/                    <-- Persistence
│   │   │   └── storage.py         <-- SQLite snapshot & signal history store
│   │   ├── static/                <-- Ultra-modern terminal frontend
│   │   │   ├── index.html         <-- HTML5 entry point
│   │   │   ├── css/terminal.css   <-- Dark financial theme styling
│   │   │   └── js/                <-- Modular ES6 components
│   │   ├── fyers_config.json      <-- Saved broker credentials
│   │   └── main.py                <-- FastAPI entry point & poller
│   └── requirements.txt
├── run_terminal.bat               <-- One-click Windows runner
├── test_modular_system.py         <-- Comprehensive local test suite
└── setup_oracle.sh                <-- Automated Oracle Cloud VM deployment script
```

---

## 💻 Local Testing & Execution

### 1. Run Automated Test Suite
Verify that all 8 core subsystems pass with zero errors:
```bash
python test_modular_system.py
```

### 2. Launch Local Server
Double-click `run_terminal.bat` or run:
```bash
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser at **`http://localhost:8000`**.

---

## ☁️ Deploying to Oracle Cloud VM

To upload and deploy to your remote Ubuntu Linux server:

1. Upload or clone the repository to the server at `/home/ubuntu/nse-dashboard`.
2. Make the automated deployment script executable:
   ```bash
   chmod +x setup_oracle.sh
   ```
3. Run the deployment script:
   ```bash
   ./setup_oracle.sh
   ```
This automatically configures Python venv, installs dependencies, creates a 2GB swap file, configures systemd background service `nse-dashboard.service`, and opens ports 80 and 8000.

---

## 🤖 AI Trading Intelligence & Momentum Buyer Architecture

### 1. Two-Tier Hybrid Architecture
```text
┌────────────────────────────────────────────────────────────────────────┐
│             TIER 1: DETERMINISTIC VM ENGINE (0ms Latency)             │
│  • Computes Real-time Greeks, Delta, Hull Moving Average, Supertrend   │
│  • Monitors Open Interest shifts, Institutional Wall capitulations    │
│  • Clamps Strike Selection strictly to ATM (Delta ~ 0.50)              │
│  • Manages Micro-Stop Loss & Trailing Targets in Real Time            │
└───────────────────────────────────▲────────────────────────────────────┘
                                    │ Instant Signal Trigger
┌───────────────────────────────────▼────────────────────────────────────┐
│      TIER 2: AI COGNITIVE REASONING (Groq LPU / Gemini Fallback)       │
│  • Sub-300ms inference on Groq LPU (qwen/qwen3.8-27b / llama3-70b)     │
│  • Automatic Fallback to Google Gemini Flash Free Tier                 │
│  • Filters out Trap breakouts, fake pumps, and dead chop consolidation │
│  • Validates Risk-to-Reward and confirms high-conviction scalps        │
└───────────────────────────────────▲────────────────────────────────────┘
                                    │ Verified Order Approval
┌───────────────────────────────────▼────────────────────────────────────┐
│       BROKER EXECUTION (Fyers API v3 / Zerodha Auto-Order Gateway)     │
│  • Places Multi-Leg Bracket / Regular Orders                           │
│  • Enforces Statutory Cost Recovery before trade exit                  │
└────────────────────────────────────────────────────────────────────────┘
```

### 2. Option Buyer & Scalper Protection Engine
- **Strict ATM Strike Selection**: No far OTM lotteries. Every trade recommendation selects the **strictly ATM strike** (Delta 0.50 - 0.55) for maximum responsiveness and high gamma expansion.
- **Commission & Fee Guarantee**: 
  - Standard round-trip option trading costs in India = **₹75** (₹40 Fyers brokerage [₹20 Buy + ₹20 Sell] + ~₹35 STT, GST, Stamp Duty & Exchange Turnover charges).
  - Target 1 is automatically clamped to **gross profit $\ge$ ₹200/lot**, guaranteeing **at least +₹125 to +₹600 net profit directly into your pocket per order**. You will never trade just to pay broker commissions from your pocket.
- **Chop Gate (Capital Preservation)**: When market confluence is flat or range-bound (47% - 53%), the engine enters `STANDBY` mode. No option buying is permitted during consolidation to protect against theta decay.

### 3. Total Fund Management & Dynamic Position Sizing
* **Configured Capital**: Set to **₹50,000 by default** (customizable & saveable via the UI or `POST /api/signals/fund`).
* **Standard Exchange Lot Sizes**:
  * **NIFTY**: **65 Qty**
  * **BANKNIFTY**: **30 Qty**
  * **FINNIFTY**: **60 Qty**
  * **MIDCPNIFTY**: **120 Qty**
* **Dynamic Sizing & Risk Management**:
  * **1-Lot Margin Required**: $\text{LTP} \times \text{Lot Size}$
  * **Recommended Lots**: Safely sizes position up to ~50% of available capital for maximum safety buffer.
  * **Risk Exposure**: Real-time Stop Loss risk calculation as a percentage of total fund ($\le 2\% - 4\%$).
  * **Remaining Buffer**: Live display of undeployed account cash.

---


## 🔑 Credentials Management & Security

Credentials are centrally loaded via `backend/app/core/credentials.py` with multi-tier fallback (environment variables $\to$ `credentials.json` $\to$ `backend/app/credentials.json`).

### File Locations
- **Project Root**: `credentials.json`
- **Backend App**: `backend/app/credentials.json`
- **Environment**: `backend/.env`

### Stored Credentials Schema
```json
{
  "groq": {
    "api_key": "gsk_...",
    "model": "qwen/qwen3.8-27b"
  },
  "gemini": {
    "api_key": "AQ....",
    "model": "gemini-flash-latest"
  },
  "fyers": {
    "app_id": "...",
    "secret_key": "...",
    "redirect_uri": "http://127.0.0.1:8000/api/auth/fyers/callback",
    "access_token": "..."
  },
  "vm": {
    "host": "137.23.42.11",
    "user": "ubuntu",
    "ssh_key_path": "_archive/ssh-key-2026-07-30.key"
  }
}
```

### Where to Obtain & Manage Free API Keys
1. **Groq LPU API Key (Primary AI Brain)**:
   - Visit: [console.groq.com](https://console.groq.com/)
   - Sign up / Log in (Completely Free).
   - Go to **API Keys** $\to$ **Create API Key**.
   - Copy key (starts with `gsk_`) and paste into `credentials.json`.
   - *Free Tier Quota*: 30 requests/minute, 14,400 requests/day. Ultra-low latency (~200ms).

2. **Google Gemini Free Tier Key (Backup AI Brain)**:
   - Visit: [aistudio.google.com](https://aistudio.google.com/)
   - Sign up / Log in with Google Account (Completely Free).
   - Click **Get API key** $\to$ **Create API key in new project**.
   - Copy key and paste into `credentials.json`.
   - *Free Tier Quota*: 15 requests/minute, 1,500 requests/day.

3. **Fyers Broker Trading API Key**:
   - Visit: [myapi.fyers.in](https://myapi.fyers.in/)
   - Create App with Redirect URL: `http://127.0.0.1:8000/api/auth/fyers/callback`.
   - Copy `app_id` and `secret_key` into `credentials.json` or `fyers_config.json`.

---

## 🛠️ Remote VM Maintenance Commands

- **Connect via SSH**:
  ```bash
  ssh -i "_archive/ssh-key-2026-07-30.key" ubuntu@137.23.42.11
  ```
- **Restart Terminal Service**:
  ```bash
  sudo systemctl restart nse-dashboard.service
  ```
- **View Live Logs**:
  ```bash
  journalctl -u nse-dashboard.service -f
  ```
- **Live Terminal Access**:
  Open `http://137.23.42.11:8000` in any web browser.

