# 🚀 NSE Alpha-Sell Options Terminal & Institutional Smart Money Tracker
### Complete Operational, Architectural, and Deployment Manual

---

## 📌 1. Project Overview
The **NSE Alpha-Sell Options Terminal** is a high-performance, institutional-grade options trading analytics dashboard built for Indian Index Option Sellers (**Nifty**, **BankNifty**, **FinNifty**, **MidCapNifty**).

It tracks real-time **Institutional Smart Money Flow**, **Strike Wall Support/Resistance Ceilings**, **Intraday OI Trends**, and **Derivatives Buildup Classification** to enable rapid, high-conviction trading decisions.

---

## 🌐 2. Cloud Server & Live Deployment Info

* **Hosting Infrastructure:** Oracle Cloud Infrastructure (OCI) Free Tier VM (Ubuntu 22.04 LTS)
* **Public Server IP:** `137.23.42.11`
* **Port:** `8000` (FastAPI + Uvicorn)
* **Live Web URL:** 👉 **[http://137.23.42.11:8000](http://137.23.42.11:8000)**
* **SSH Access Command:**
  ```powershell
  ssh -i "ssh-key-2026-07-30.key" ubuntu@137.23.42.11
  ```
* **Remote Application Path:** `/home/ubuntu/nse-dashboard/`
* **Linux Systemd Service:** `nse-dashboard.service`

---

## 🔐 3. Telegram & Broker Credentials

### 📱 Telegram Lockscreen Push Alerts
* **Bot Token:** `8392685097:AAFnCGdGMcyjOlMScfqKLS6um9kY2wO7arA`
* **Chat ID:** `562973750`
* **Alert Mechanism:** Automatically triggers 24/7 push notifications to your mobile phone lockscreen whenever large institutional block trades or OI shifts occur.

### 🔑 Broker Integration (Fyers API)
* Supports direct live feed via Fyers API.
* Credentials and OAuth tokens are configurable in the UI via the **🔑 BROKER** modal.
* **Fallback Engine:** If Fyers API token expires, system smoothly falls back to the automated resilient NSE API fetcher.

---

## 📊 4. Core Features & Module Architecture

### 1. 🏛️ Smart Money Tracker (Default Landing Page)
* **Smart Money Score (0-100):** Multi-factor institutional conviction score.
* **Support (Put Defense) & Resistance (Call Ceiling):** Dynamic strike levels.
* **Persisted Smart Money OI Shifts Log:** Live SQLite database-backed log of large block trades and wall shifts.
* **Real-Time OI Spectrum:** Centered ATM bar chart displaying CE vs PE accumulation.

### 2. 📈 Intraday OI Trends (3 Stacked Dual-Axis Charts)
* **TOTAL OI vs Spot Price:** Tracks total CE & PE open interest curve against index price.
* **CHANGE IN OI vs Spot Price:** Intraday OI additions/reductions curve.
* **DIFFERENCE IN OI (CE - PE) vs Spot Price:** Net institutional bias delta line.
* **Data Retention:** Retains full market day snapshots (`09:15 AM - 03:30 PM IST`) in SQLite.

### 3. 🎯 Data Interpretation & Buildup Matrix
* **4-Quadrant Derivatives Color Codes:**
  * 🟢 **LONG BUILDUP (LB):** `OI ↑ | Price ↑` — Buyers Accumulating / Put Sellers Active *(Bullish)*.
  * 🔴 **SHORT BUILDUP (SB):** `OI ↑ | Price ↓` — Aggressive Shorting / Writing *(Bearish)*.
  * 🟡 **SHORT COVERING (SC):** `OI ↓ | Price ↑` — Sellers Closing Shorts *(Relief Rally)*.
  * 🔵 **LONG UNWINDING (LU):** `OI ↓ | Price ↓` — Longs Exiting *(Profit Booking)*.
* **Full Matrix Table:** Displays `CALL OI`, `CE BUILDUP`, `CE OI CHG`, `CE LTP`, `STRIKE`, `PE LTP`, `PE OI CHG`, `PUT BUILDUP`, and `PUT OI`.

### 4. 🛡️ Strike Wall Heatmap (2D Concept Grid)
* **2D Intensity Heat Grid:** Visual cards for ATM ± 5 strikes.
* **Color Saturation:** Emerald cards for Put floors, Crimson cards for Call ceilings, Gold for ATM.
* **PE/CE Dominance Micro-Bars:** Percentage split meter inside each strike card.

### 5. 📊 Option Chain Table
* Interactive tabular view with strike-wise IV, LTP, OI, and micro Buildup Badges (`[LB]`, `[SB]`, `[SC]`, `[LU]`).

### 6. ⚡ Strategy Backtest & Analytics
* Performance analytics for signal win rate, profit factor, average win points, and total P&L.

---

## 📁 5. Directory & Codebase Structure

```
c:\Projects\NSE dashboard\
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI application entry point & CORS
│   │   ├── config.py                   # Environment settings & defaults
│   │   ├── api/
│   │   │   └── market.py               # REST API endpoints & websocket handlers
│   │   ├── services/
│   │   │   ├── option_chain.py         # NSE/Fyers chain parser & Greeks calculator
│   │   │   ├── smart_money_service.py  # SQLite shift persistence & intraday timeline
│   │   │   └── telegram_alert_service.py # Telegram bot integration
│   │   ├── db/
│   │   │   ├── database.py             # SQLite database connection & cleanup (4-day retention)
│   │   │   └── models.py               # SQLAlchemy ORM models (Snapshots, Shifts, Signals)
│   │   ├── engines/
│   │   │   └── seller_engine.py        # Option selling strategy generator
│   │   └── static/
│   │       └── index.html              # Complete Single-Page Application (React + Tailwind)
└── setup_oracle.sh                     # Oracle VM auto-setup script
```

---

## 🛠️ 6. Maintenance & Deployment Cheat Sheet

### Deploy Updated Files to Oracle Cloud Server:
```powershell
# Upload static frontend (index.html)
scp -i "ssh-key-2026-07-30.key" "c:\Projects\NSE dashboard\backend\app\static\index.html" ubuntu@137.23.42.11:~/nse-dashboard/backend/app/static/index.html

# Upload entire backend
scp -r -i "ssh-key-2026-07-30.key" "c:\Projects\NSE dashboard\backend\app" ubuntu@137.23.42.11:~/nse-dashboard/backend/
```

### Restart Server Service:
```powershell
ssh -i "ssh-key-2026-07-30.key" ubuntu@137.23.42.11 "sudo systemctl restart nse-dashboard"
```

### View Live Logs:
```powershell
ssh -i "ssh-key-2026-07-30.key" ubuntu@137.23.42.11 "journalctl -u nse-dashboard -f"
```

---
*Created on 2026-08-03 | All Rights Reserved for Alpha-Sell Terminal.*
