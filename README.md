# MyBullAndBear — Institutional NSE Derivative & Signal Terminal

[![Terminal Theme](https://img.shields.io/badge/Theme-Neumorphic%20Dark-38bdf8?style=flat-square)](#neumorphic-design-system)
[![Architecture](https://img.shields.io/badge/Architecture-FastAPI%20%2B%20Modular%20ES6-10b981?style=flat-square)](#system-architecture)
[![Data Engine](https://img.shields.io/badge/Market%20Data-Fyers%20%7C%20Shonya%20%7C%20Simulator-f59e0b?style=flat-square)](#broker--market-data-hub)
[![Memory Continuity](https://img.shields.io/badge/Memory-Project%20Memory%20Agent-8b5cf6?style=flat-square)](docs/PROJECT_STATE.md)

A centralized, real-time decision support and automated execution terminal for Indian National Stock Exchange (NSE) index derivatives (**NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, and BSE SENSEX**). Built for institutional and active intraday traders with a unified tactile **Neumorphic Dark Theme**, multi-indicator closed-candle signal unison, and deep strike-level analytics.

---

## 🌟 Core Features & Modules

### 1. 📊 5-Index Market Decision Board
- Multi-index 5-minute closed-candle decision table across NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, and SENSEX.
- Shows current spot, 5m session price sparklines, Call OI, Put OI, Net $\Delta\text{OI}$ flow, PCR, Opening Range breakout state, and actionable playbook guidance.
- Quantitative indicator consensus combining **Hull Suite (EHMA 34)**, **AlphaTrend**, **Optimized Trend Tracker (OTT)**, and **Shonya Confluence**.

### 2. ⛓️ Sensibull Option Chain Matrix with ATM $\pm$ 3 Sparklines
- 13-column matrix with Call & Put Hull trend badges, institutional buildup labels (Long Buildup, Short Covering, Short Buildup, Long Unwinding), volume heatmaps, and relative OI gauges.
- **ATM $\pm$ 3 Focus Corridor**: The 7 strikes centered at ATM ($\text{ATM}-3$ to $\text{ATM}+3$) infuse real-time SVG sparklines for:
  - **LTP Trajectory**: Green for premium surge, red for decay.
  - **$\Delta\text{OI}$ Accumulation**: Sky blue for open interest addition, amber for unwinding.
- Full mobile support with **Center-Locked Strike Architecture** and dedicated **Puts Focus** and **Calls Focus** modes.

### 3. 🎯 Quantitative Option Confluence
- Multi-timeframe corridor matrix tracking institutional positioning, support/resistance corridors, and automated trade entry validation gates.
- Anti-falling knife protection with 30-second premium confirmation gate.

### 4. 🤖 ShonyaBot Execution Terminal
- Algorithmic execution engine for paper and live order routing via Finvasia Shonya API.
- Configurable risk limits (max daily loss, trailing stop loss, position size rules).
- Real-time trade log, order status updates, and P&L tracking.

### 5. 🌊 Call vs Put OI Flow & Analytics
- Visual strike distribution of Open Interest and Day's Change in OI.
- Multi-strike accumulation vs distribution tracker.

### 6. ⏱️ Whole-Day Master Replay & Time-Travel Controller
- Frame-by-frame historical session playback scrubbing through recorded SQLite strike snapshots.
- Synchronizes the entire terminal (Ticker Bar, Directional Weightage Bar, Decision Board, and Option Chain) to the selected historical timestamp.

---

## 🎨 Neumorphic Design System

The terminal is designed around a single, cohesive **Dark Neumorphism (Soft UI)** design system:
- **Extruded Tactile Surfaces (`.nm-card`, `.nm-raised`)**: Subtle dual-shadow lighting (top-left specular highlight + bottom-right deep shadow) giving cards and panels a physical, sculpted appearance.
- **Recessed Wells (`.nm-well`, `.nm-inset`)**: Inset wells for high-density tabular matrixes, TradingView charts, and live terminal logs.
- **Haptic Controls (`.nm-btn`, `.nm-tab`)**: Buttons and navigation pills that smoothly depress from extruded states to indented active wells when selected.
- **Cybernetic Glowing Directives**: Clean, uncluttered LED status indicators for Bullish (`#10b981`), Bearish (`#ef4444`), Neutral (`#f59e0b`), and Active (`#38bdf8`) market conditions.

---

## 🏗️ System Architecture

```mermaid
graph TD
    subgraph Data Sources
        Fyers[Fyers API v3 Live Quotes]
        Shonya[Finvasia Shonya API]
        Sim[Built-in Market Simulator]
        DB[(SQLite Snapshots DB)]
    end

    subgraph Backend FastAPI
        Main[main.py Lifespan Poller]
        AuthRouter[/api/fyers/login & callback]
        BoardRouter[/api/dashboard/board]
        MarketRouter[/api/market/option-chain]
        ShonyaRouter[/api/shonya]
        ReplayEngine[unified_replay_service.py]
    end

    subgraph Frontend Neumorphic UI
        Shell[terminal-shell.js & index.html]
        NMTheme[neumorphism.css Master Theme]
        BoardView[decision_board.js]
        ChainView[chain_table.js with ATM±3 Sparklines]
        ConfluenceView[option_confluence.js]
        BotView[shonya_terminal.js]
    end

    Fyers --> Main
    Shonya --> Main
    Sim --> Main
    Main --> DB
    Main --> BoardRouter
    Main --> MarketRouter
    Main --> ShonyaRouter
    DB --> ReplayEngine
    BoardRouter --> BoardView
    MarketRouter --> ChainView
    NMTheme --> Shell
    Shell --> BoardView
    Shell --> ChainView
    Shell --> ConfluenceView
    Shell --> BotView
```

---

## 🚀 Running and Operating

### Local Development
```bash
# 1. Activate Python virtual environment
python -m venv venv
venv\Scripts\activate

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Run FastAPI backend
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

### Remote VM Deployment
The production service runs on Ubuntu under systemd:
```bash
# Check service status
ssh -i <ssh_key> ubuntu@137.23.63.209 "systemctl status nse-dashboard"

# Restart service after updates
ssh -i <ssh_key> ubuntu@137.23.63.209 "sudo systemctl restart nse-dashboard"

# View live service logs
ssh -i <ssh_key> ubuntu@137.23.63.209 "journalctl -u nse-dashboard -n 50 -f"
```
Production URL: [http://137.23.63.209:8000/](http://137.23.63.209:8000/)

---

## 🛡️ Anti-Regression Safeguards

All agents and contributors must preserve the following architectural invariants:
1. **Never edit or print credentials**: Broker keys in `backend/app/core/credentials.py` are strictly read-only.
2. **Dynamic Host OAuth**: Auth redirect URIs must dynamically infer the host header (`request.headers.get("host")`).
3. **Strict Mode Safety**: All ES6 modules must avoid undeclared variable assignments (`let unlocked = true`).
4. **Scroll Position Memory**: Polling updates must never reset user scroll positions in table matrices.
5. **Continuous Project Memory**: Update `docs/PROJECT_STATE.md`, `docs/CHANGELOG.md`, and `docs/DECISIONS.md` on every major change.

---

## 📚 Project Memory Links
- **[docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)**: Current checkpoint, verified components, and next tasks.
- **[docs/CHANGELOG.md](docs/CHANGELOG.md)**: Chronological record of completed work and validations.
- **[docs/DECISIONS.md](docs/DECISIONS.md)**: Architectural decisions and design trade-offs.
- **[AGENTS.md](AGENTS.md)**: Project continuity contract and implementation rules.
