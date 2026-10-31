# Walkthrough: Simultaneous Dual-Pair NSE Options Terminal V4 Pro

We have upgraded the terminal to support **simultaneous dual-pair live market views**:
1. **Default View**: **NIFTY & BANKNIFTY** displayed side-by-side simultaneously.
2. **Secondary View**: **FINNIFTY & MIDCAP NIFTY** displayed side-by-side simultaneously.
3. **Seamless Toggling**: One-click pair selector in the navigation header with automatic synchronization across ticker cards, open interest charts, confluence signal radars, and smart money flow.

---

## Key Dual-View Architecture Highlights

### 1. Default Simultaneous View: NIFTY & BANKNIFTY Side-by-Side
When loading `http://localhost:8000`, the terminal defaults to the **NIFTY & BANKNIFTY** dual view:
- **Parallel Real-Time Ingestion**: The backend and frontend fetch and poll live data for both `NIFTY` and `BANKNIFTY` simultaneously in parallel (`Promise.all`), updating every 3 seconds.
- **Side-by-Side 2-Column Responsive Layout**:
  - **Column 1 (Left - NIFTY 50)**: Live Spot (`23,226.0`), PCR (`1.02 BALANCED`), Writer Pressure (`54.4% PE : 45.6% CE`), Support Wall (`23200 PE` with 120.9 L contracts), Resistance Wall (`24000 CE` with 86.4 L contracts), Intraday OI Timeline, and ATM ± 10 Strike Bar Chart.
  - **Column 2 (Right - BANK NIFTY)**: Live Spot (`56,136.9`), PCR (`0.83 BEARISH BIAS`), Writer Pressure (`54.6% PE : 45.4% CE`), Support Wall (`56000 PE` with 9.1 L contracts), Resistance Wall (`57500 CE` with 22.3 L contracts), Intraday OI Timeline, and ATM ± 10 Strike Bar Chart.

![Default Simultaneous View: NIFTY & BANKNIFTY](C:/Users/resea/.gemini/antigravity-ide/brain/22b1ac81-0931-4c3a-9bf8-1c2a910bbcf8/dual_view_nifty_banknifty.png)

---

### 2. Strike-Wise Call vs Put Comparative Bar Charts (ATM ± 10 Strikes)
Full comparative strike distribution showing call writing (red) versus put writing (green) side-by-side for both indices:

![Scrolled Strike Bar Charts](C:/Users/resea/.gemini/antigravity-ide/brain/22b1ac81-0931-4c3a-9bf8-1c2a910bbcf8/dual_view_strike_bars_scrolled.png)

---

### 3. Secondary Simultaneous View: FINNIFTY & MIDCAP NIFTY
Clicking `[⚡ FINNIFTY & MIDCAP]` in the header instantly re-configures the terminal to stream and display FINNIFTY and MIDCPNIFTY side-by-side:
- **Column 1 (Left - FIN NIFTY)**: Live Spot (`25,191.55`), PCR (`0.65 BEARISH BIAS`), Support Wall (`25200 PE`), Resistance Wall (`26500 CE`), and Intraday OI Timeline.
- **Column 2 (Right - MIDCAP NIFTY)**: Live Spot (`14,259.55`), PCR (`0.90 BALANCED`), Writer Pressure (`63.2% PE : 36.8% CE - Put Support Floor`), Support Wall (`14000 PE`), Resistance Wall (`15000 CE`), and Intraday OI Timeline.

![Secondary Simultaneous View: FINNIFTY & MIDCAP](C:/Users/resea/.gemini/antigravity-ide/brain/22b1ac81-0931-4c3a-9bf8-1c2a910bbcf8/dual_view_finnifty_midcap.png)

---

### Walkthrough - Mobile Strike Center Lock, Option Chain Auto-Alignment & Blank Screen Fix

## 1. Issues Addressed
1. **Option Chain Auto-Alignment on Mobile**:
   - The view previously reset or automatically snapped back to Call data during the 3-second live polling ticks, preventing traders from viewing Put buildup signals and data.
2. **Mobile Strikes Center-Locked Architecture**:
   - The user requested strike prices to remain centered, with both Call and Put data clearly aligned and relating directly to each strike without jumping around.
3. **Blank Screen on Deployment (`http://137.23.42.11:8000`)**:
   - Tabs loaded, but content mount, tickers, and header remained blank due to an ES module parsing failure caused by a syntax error (`timeToMinutes` function missing closing brace `}`) in `oi_charts.js`.

---

## 2. Root Cause Analysis & Fixes

### A. Blank Screen Resolved
- **Root Cause**: In [oi_charts.js](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/js/components/oi_charts.js#L32-L41), the helper function `timeToMinutes` was missing its closing brace `}`. When ES6 modular imports were evaluated by the browser in `app.js`, the syntax error threw an uncaught `SyntaxError: Unexpected token 'export'`, halting script execution before `mountHeader()`, `mountTicker()`, or `mountContent()` could run.
- **Fix**:
  - Restored closing brace `}` to `timeToMinutes` in `oi_charts.js`.
  - Bumped cache busters across [index.html](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/index.html) and [app.js](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/js/app.js) to `v=4.0.14` to ensure clients receive the clean, updated scripts without browser caching conflicts.

### B. Mobile Option Chain Center-Lock & Put Signals Lock
- **Scroll Position Memory**: Captured `scrollLeft` and `scrollTop` prior to polling redraws in [chain_table.js](file:///c:/Ritesh%20Workspace/Projects/NSE%20dashboard/backend/app/static/js/components/chain_table.js) and re-applied them immediately, completely eliminating automatic reorientation to Call data.
- **Side Focus Bar**: Added `[⚡ BOTH DUAL]`, `[🔴 PUTS FOCUS]`, and `[🟢 CALLS FOCUS]` filters. Activating `PUTS FOCUS` locks the screen to the center strike and Put signals/data exclusively.
- **Metric Quick Pills**: Added one-tap metric filters (`[🎯 SIGNALS]`, `[📊 OI]`, `[⚡ PRICE]`, `[📈 OI CHG]`, `[🌊 VOLUME]`, `[⚖️ DUAL]`) and horizontal swipe navigation.
- **Quick-Jump Buttons**: Provided `[‹ Calls]`, `[• Strike •]`, and `[Puts & Signals ›]` in full table mode.

---

## 3. Deployment & Live Verification
- **Target**: Oracle Cloud VM (`ubuntu@137.23.42.11`).
- **Safety**: Packaged and deployed only `app/static/` via `v22_deploy.tar.gz`. The live `fyers_config.json` access token and database files were preserved untouched.
- **Service Status**: `systemctl restart nse-dashboard` succeeded (`Active: active (running)` on port 8000).
- **HTTP Verification**:
  - `GET /` -> HTTP 200 with `<script type="module" src="/static/js/app.js?v=4.0.14"></script>`.
  - `GET /static/js/app.js?v=4.0.14` -> HTTP 200 OK.
  - `GET /static/js/components/oi_charts.js?v=4.0.14` -> HTTP 200 OK (syntax verified).
  - `GET /static/js/components/chain_table.js?v=4.0.14` -> HTTP 200 OK.

---

### 4. Dual Confluence Signal Radar & Option Seller Trade Guide
In the **Signal Radar** tab, both symbols in the active pair are compared side-by-side:
- Confluence score radial dials ($0 - 100$).
- Real-time market state (`WATCH`, `EXECUTE`, `DEFEND`).
- 4-Factor breakdown (Positioning 35%, Price Action 30%, Wall Proximity 15%, Straddle Decay 20%).
- Specific option seller trade setups (e.g. Short Iron Condor strike recommendations, stop loss spot, and profit target).

![Dual Signal Radar](C:/Users/resea/.gemini/antigravity-ide/brain/22b1ac81-0931-4c3a-9bf8-1c2a910bbcf8/dual_view_signals.png)

---

### 5. Dual Institutional Smart Money & Defense Walls
In the **Smart Money & Walls** tab, institutional order flow for both active symbols is displayed simultaneously:
- Speedometer conviction score.
- Net capital flow across ATM ± 5 strikes in ₹ Crores (PE writing flow vs CE writing flow).
- Defense walls (Put Support Floor & Call Resistance Ceiling).
- ATM straddle combined premium and intraday decay percentage.

![Dual Smart Money](C:/Users/resea/.gemini/antigravity-ide/brain/22b1ac81-0931-4c3a-9bf8-1c2a910bbcf8/dual_view_smart_money.png)

---

### 6. Full Option Chain Matrix with Instant Active Pair Switcher
In the **Option Chain Matrix** tab, full 11-column option chain data is accessible for both active symbols with 1 click:

![Dual Option Chain Matrix](C:/Users/resea/.gemini/antigravity-ide/brain/22b1ac81-0931-4c3a-9bf8-1c2a910bbcf8/dual_view_option_chain.png)

---

## Verification Summary
- **Zero Browser / Backend Errors**: Tested via headless Chrome automation with zero severe console errors.
- **100% Real Live Market Data**: Directly streaming live quotes and option chains from Fyers API (`FYERS_LIVE`).
- **Live Local URL**: **`http://localhost:8000`** is currently active and serving the live dashboard.
