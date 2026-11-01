# Project Changelog

All notable changes, milestone implementations, and verified bug resolutions are documented in this file.

## [2026-11-01] - MNC High-Density Zero-Scroll Workstation Redesign & Layout Overhaul
- **Layout Architecture (Strict 100vh Full-Screen Discipline)**:
  - Enforced `overflow: hidden` on `html`, `body`, and `.app-container`, completely eliminating document-level scrolling and dual scrollbars.
  - Consolidated bulky `workspace-toolbar` (~90px) and `connection-line` (~40px) into a sleek 26px `micro-toolbar`, saving 124px of vertical height.
  - Compacted top header to a razor-sharp 40px institutional bar with streamlined pair switches and telemetry badges.
  - Re-positioned desktop module tabs into a sleek 32px tactile tab strip directly under the header.
- **Option Chain Matrix (Sensibull 13-Column High-Density)**:
  - Enforced double-sticky headers (`thead tr th`) pinned to top: 0 and top: 24px so column headers never scroll out of view.
  - Scaled inline SVG sparklines to 60px x 14px to prevent row height bloat.
  - Added full-height flex container (`#content-mount > .glass-panel`, `.chain-table-container`) allowing smooth internal scrolling across all 100 strikes.
- **Bug Fix (DOM Structure)**:
  - Fixed HTML nesting syntax bug in `dashboard_view.js` (premature closing div) and adjusted parameter matrix table and bottom analytics grid to flex-fit the viewport.
- **Design System (`neumorphism.css`)**:
  - Overhauled master neumorphic theme with refined dual shadows, compact padding (4px-8px), tabular typography (`JetBrains Mono`), and tactile embossed controls.

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
