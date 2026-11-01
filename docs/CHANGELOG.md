# Project Changelog

All notable changes, milestone implementations, and verified bug resolutions are documented in this file.

## [2026-11-01] - ATM+-3 Option Chain Sparklines & Neumorphic Architecture Initialization
- **Feature (Option Chain Sparklines)**:
  - Added `get_atm3_strike_sparklines()` to [backend/app/db/storage.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/db/storage.py) querying `intraday_strike_snapshots` for 7 focus strikes (14 contracts: CE & PE).
  - Enriched `/api/market/option-chain/{symbol}` in [backend/app/api/market.py](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/api/market.py).
  - Infused SVG sparklines for price movement (LTP trend: green/red) and OI accumulation (sky blue/amber) in [backend/app/static/js/components/chain_table.js](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/js/components/chain_table.js).
  - Added `.atm3-corridor-row` highlighting and column labels `OI & Trend (ATM±3)` and `LTP & Trend (ATM±3)`.
  - Deployed to live VM at `137.23.63.209` and empirically verified with both NIFTY and BANKNIFTY.
- **Continuity (Project Memory Agent)**:
  - Installed root `AGENTS.md`, `.github/copilot-instructions.md`, `.github/agents/project-memory.agent.md`.
  - Initialized verified project memory: `docs/PROJECT_STATE.md`, `docs/CHANGELOG.md`, `docs/DECISIONS.md`.
- **Bug Fix (Blank Canvas & Layout Regression)**:
  - Fixed `ReferenceError: _isUnlocked is not defined` in `access_gate.js` in ES6 strict mode.
  - Restored single-screen decision board layout and unified shell from `028d650`.
- **Bug Fix (Fyers Redirect & Auto-Login)**:
  - Added dynamic host inference to `/api/fyers/login` and `/api/fyers/callback`.
  - Added automatic query parameter interception (`?auth_code=...`) on root `/` and `app.js` boot.
- **Security Check**:
  - Verified user credentials in `backend/app/core/credentials.py` are preserved intact.

## [2026-10-31] - Closed-Candle Multi-Indicator Confluence & Signal Research
- Implemented 5-minute closed candle confirmation gate in `candle_color_breakout_engine.py` and `decision_board.py`.
- Verified indicator unison across Hull Suite (EHMA 34), AlphaTrend, Optimized Trend Tracker (OTT), and Shonya Bot.
- Added historical replay time-travel synchronization across Option Chain, Ticker Bar, and Confluence Matrix.
