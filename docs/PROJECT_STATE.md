# Project State: MyBullAndBear Institutional NSE Terminal

Status: ACTIVE — Unified Neumorphic Dark Architecture
Last verified: 2026-11-01
Branch / inspected HEAD: origin/main & origin/improvement/one-screen-dashboard-20261101 (028d650)
Remote VM Target: `ubuntu@137.23.63.209` (Service: `nse-dashboard.service` on port 8000)

## Purpose and User Requirements
A centralized, institutional-grade decision support and algorithmic options trading terminal for Indian National Stock Exchange (NSE) index derivatives (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX).
Primary User Demands:
1. **One Unified Neumorphic Dark Theme**: Cohesive tactile aesthetics (extruded cards, recessed wells, embossed buttons, dual light-shadow lighting, glowing LED directives).
2. **Feature Consolidation**: Integrate Decision Board, Sensibull Option Chain Matrix with ATM+-3 Sparklines, Confluence Engine, Strategy Workspace, OI Flow, and Shonya Bot.
3. **Strict Zero-Regression Guarantee**: Preserve all solved issues from the last 2 months (broker authentication callback, strict mode ES6, scroll stability, credentials preservation).
4. **Project Continuity**: Persistent Project Memory Agent integration.

## Architecture and Important Paths
- **Backend Entry Point**: [backend/app/main.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/main.py) (FastAPI app, lifespan poller, access protection, mounted routers).
- **API Routers**:
  - Decision Board: [backend/app/api/decision_board.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/api/decision_board.py) (`/api/dashboard/board`)
  - Market & Option Chain: [backend/app/api/market.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/api/market.py) (`/api/market/option-chain/{symbol}`)
  - Broker Auth & Callback: [backend/app/api/auth.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/api/auth.py) (`/api/fyers/login`, `/api/fyers/callback`, `/api/fyers/exchange`)
  - Strategy Workspace: [backend/app/api/strategy_workspace.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/api/strategy_workspace.py)
  - Shonya Bot & Orders: [backend/app/api/shonya_api.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/api/shonya_api.py)
  - Unified Historical Replay: [backend/app/services/unified_replay_service.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/services/unified_replay_service.py)
- **Data & Storage**:
  - SQLite Snapshots: [backend/app/db/storage.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/db/storage.py) (`intraday_strike_snapshots`, `intraday_snapshots`, 814k+ recorded points).
  - Credentials: [backend/app/core/credentials.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/core/credentials.py) (Fyers client/secret, Shonya user/keys - STRICTLY READ-ONLY).
- **Frontend Architecture**:
  - App Shell: [backend/app/static/index.html](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/index.html)
  - Master Orchestrator: [backend/app/static/js/app.js](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/js/app.js)
  - Terminal Shell Controls: [backend/app/static/js/terminal-shell.js](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/js/terminal-shell.js)
  - Design Systems:
    - Master Neumorphic Theme: `backend/app/static/css/neumorphism.css`
    - Shared Terminal Layout: [backend/app/static/css/modern-terminal.css](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/css/modern-terminal.css)
    - Decision Board Surfaces: [backend/app/static/css/decision-board.css](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/css/decision-board.css)
    - Sensibull Matrix: [backend/app/static/css/terminal.css](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/css/terminal.css)
  - Core Components:
    - `decision_board.js`: Multi-index 5m closed-candle decision table with live sparklines.
    - `chain_table.js`: 13-column Sensibull matrix with ATM+-3 price and OI sparklines.
    - `option_confluence.js`: Quantitative corridor matrix (AlphaTrend, Hull, OTT, Shonya).
    - `shonya_terminal.js`: Algorithmic trading bot terminal with trailing stops and risk gates.
    - `oi_charts.js`: Institutional Call vs Put OI distribution.
    - `master_replay_bar.js`: Time-travel historical replay scrubber.

## Verified Anti-Regression Safeguards
1. **Credentials Preservation**: Credentials in `credentials.py` / `credentials.json` are preserved verbatim.
2. **Dynamic Host Resolution**: Auth redirect URIs dynamically resolve host from `request.headers.get("host")`.
3. **Strict Mode Safety**: `access_gate.js` strictly declares `let unlocked = true;` to avoid runtime `ReferenceError`.
4. **Scroll Stability**: Matrix polling preserves `persistentTableScrollLeft` and `persistentTableScrollTop`.
5. **Mobile Gesture Protection**: Polling pauses DOM modifications during active user touches.
6. **Concurrent DB Safety**: SQLite uses busy timeout handling to avoid database locks during recording.

## Current Task & Status
- **Goal**: Full Neumorphism design system implementation across all modules, unifying the entire application into a single cohesive, tactile, dark-mode terminal.
- **Next Exact Action**: Create `backend/app/static/css/neumorphism.css`, link it into `index.html`, and style all headers, toolbars, tables, and tabs to match.
