# 🚀 VISUAL COMMAND CENTER (V3) — INSTITUTIONAL TERMINAL README

## 📌 Executive Overview
The **Visual Command Center (V3)** is a high-fidelity, validated analytical intelligence engine and graphical decision cockpit designed for index option sellers and intraday derivatives traders (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY). 

The V3 calibration transforms the terminal from heuristic visual cards into a **statistically rigorous, non-circular institutional intelligence platform**. It enforces strict separation between:
1. **Option Positioning** (OI, ΔOI, PCR dynamics across 1m, 5m, 15m, 30m, and session open).
2. **Deconstructed Price Confirmation** (Direction, Velocity, Acceleration, Spot Range, and Wall Interaction States).
3. **Weighted Confluence & Debounced Signal Lifecycles** (EARLY → CONFIRMED → MATURE → WEAKENING → INVALIDATED).

---

## 🎨 Visual Palette & Color Conventions

| Visual Cue | Color | Meaning |
| :--- | :--- | :--- |
| **Emerald Green** | `#10b981` / `#059669` | Put Support Floor / Institutional Put Writing / Bullish Accumulation |
| **Crimson Red** | `#ef4444` / `#dc2626` | Call Resistance Ceiling / Institutional Call Writing / Bearish Pressure |
| **Amber Gold** | `#f59e0b` / `#d97706` | Net Flow Crossover / Neutral Range / Signal Conflict Alert |
| **Cyan Blue** | `#06b6d4` / `#0284c7` | Live ATM Strike Cursor / Active Price Benchmark / Price Confirmation |
| **Bloomberg Dark** | `#080a0f` / `#0f172a` | Low-eyestrain dark background optimized for multi-monitor trading desks |

---

## 🧭 Master Dashboard Layout & V3 Analytical Hierarchy

The V3 engine follows a non-circular analytical pipeline:
```
RAW DATA → OBSERVATION → CLASSIFICATION → SIGNAL STRENGTH → PERSISTENCE → SIGNAL CONFIDENCE → CONFLUENCE → REGIME → HISTORICAL RELIABILITY
```

```
+-----------------------------------------------------------------------------------+
| 1. MASTER CONFLUENCE HEADER & 3 CORE BARS (POSITIONING, PRICE, CONFLUENCE)        |
+-----------------------------------------------------------------------------------+
| 2. COMPACT MARKET STATE STRIP (STRUCTURE, PRICE, BREAKOUT, REGIME, STATE)         |
+-----------------------------------------------------------------------------------+
| 3A. SMART MONEY SPEEDOMETER | 3B. FLOW MOMENTUM WAVE | 3C. MARKET REGIME ENGINE   |
+-----------------------------------------------------------------------------------+
| 4. REAL-TIME TELEMETRY STRIP (SPOT, PCR 5M/15M/OPEN, ATM STRADDLE, RANGE, FEED)   |
+-----------------------------------------------------------------------------------+
| 5A. SUPP/RES ZONES | 5B. MIGRATION (OSCILLATION FILTER) | 5C. DECAY DETECTOR | 5D. PRESSURE|
+-----------------------------------------------------------------------------------+
| 6A. BREAKOUT ENGINE | 6B. COMPRESSION | 6C. PERSISTENCE | 6D. STATISTICAL RELIABILITY |
+-----------------------------------------------------------------------------------+
| 7. CHRONOLOGICAL EVENT TIMELINE ("HOW DID WE GET HERE? HISTORICAL SNAPSHOTS")     |
+-----------------------------------------------------------------------------------+
| 8. CENTERPIECE: INSTITUTIONAL STRIKE DEFENSE WALL MATRIX (ATM ± 10 HEATMAP)       |
+-----------------------------------------------------------------------------------+
```

---

## 📊 Core V3 Analytical Components & How to Read Them

### 1. Master Confluence Header & 3 Core Bars
- **Option Positioning Bar (60% Weight)**: Evaluates option accumulation (`+82 BULLISH`).
- **Price Confirmation Bar (40% Weight)**: Deconstructed spot momentum (`+51 WEAK BULLISH`).
- **Final Confluence Score**: Weighted combination (`69/100`). If Positioning and Price diverge, the engine flags a **SIGNAL CONFLICT / UNCONFIRMED** banner and penalizes confidence by 20%.

### 2. Compact Market State Strip (5 Instant Telemetry Badges)
Located immediately below the header block:
- **OPTION STRUCTURE**: `BULLISH / MIXED` or `BULLISH`
- **PRICE ACTION**: `WEAK BEARISH` or `STRONG BULLISH`
- **BREAKOUT STATUS**: `SETUP BUILDING / NOT CONFIRMED` or `UPSIDE BREAKOUT CONFIRMED`
- **CONFLUENCE REGIME**: `SIGNAL CONFLICT` or `BULLISH CONFLUENCE`
- **OPERATIONAL STATE**: `WAIT / DEVELOPING SETUP` or `CONFIRMED ENTRY`

---

### 3. Deconstructed Price Confirmation Sub-Metrics
Price momentum is evaluated independently of Option OI to prevent circular logic:
- **Direction Score**: Intraday price change % relative to Session Open.
- **Velocity Score**: 15-minute price rate of change.
- **Acceleration Score**: Rate of velocity change (5m vs 15m).
- **Wall Interaction State**: Explicit position state (`APPROACHING RESISTANCE`, `TESTING RESISTANCE (CE)`, `ACCEPTED ABOVE RESISTANCE (BREAKOUT)`, `ACCEPTED BELOW SUPPORT (BREAKDOWN)`).

---

### 4. Multi-Timeframe ΔOI & Strike Classification Engine
Option actions are classified per strike over 5-minute rolling windows:
- **LONG BUILDUP**: ΔOI > 0, ΔLTP > 0
- **PUT / CALL WRITING**: ΔOI > 0, ΔLTP < 0 (Smart Money position accumulation)
- **SHORT COVERING**: ΔOI < 0, ΔLTP > 0
- **LONG UNWINDING**: ΔOI < 0, ΔLTP < 0
- **Battle Status**: Comparative PE strength vs CE strength at the same strike (`BALANCED BATTLE`, `PE DOMINANT`, `CE DOMINANT`).

---

### 5. Wall Migration & Oscillation Filter
- **UPWARD MIGRATION**: Floor moving continuously higher (`23,850 → 23,950 → 24,000`).
- **DOWNWARD MIGRATION**: Ceiling pressing continuously lower (`24,300 → 24,250 → 24,200`).
- **OSCILLATING / STABLE**: If walls bounce back and forth within a range without net displacement, velocity is set to `0.0 pts/hr` and tagged as `OSCILLATING (±50 pts)`.

---

### 6. Signal Confidence vs Statistical Historical Reliability
- **SIGNAL CONFIDENCE**: Current data freshness and signal integrity (e.g. 91%). Penalized by data lag, sparse snapshots, or signal conflict.
- **HISTORICAL RELIABILITY**: Backtested wall hold/fail rates calculated from recorded database snapshots. If snapshot samples < 10, explicitly marked as `DATA UNAVAILABLE (REQUIRING >10 SAMPLES)`.

---

### 7. Historical Market Replay Engine (`/api/vcc/replay`)
Allows traders and backtesters to pass `?date_str=2026-08-19&timestamp_str=10:30:00` to reconstruct the exact VCC intelligence payload for any historical minute of any session.

---

---

## 🛠️ V3.1 Analytical Correction & Temporal Consistency Patch

The V3.1 patch addresses temporal drift, signal state persistence, and visual chart scaling without modifying the institutional UI design:

### 1. Signal Lifecycle & IST Session Age Normalization
- **Cross-Day State Reset**: Signal persistence counters and start timestamps (`started_dt`) are automatically reset on trading date transitions, eliminating multi-day age drift (e.g., 71h bug).
- **Session Clamping**: All duration metrics are clamped strictly to current trading session hours (`09:15:00 IST` to current time), formatted as `Xh Ym Zs` or `Xm`.

### 2. Wall Change Detector & Narrow Y-Axis Auto-Scaling
- **Intraday Market Hours Scale**: The X-axis renders timestamp nodes sampled across full market hours (`09:15` to current IST) for strikes within `ATM ± 500`.
- **Tight Y-Axis Scale**: SVG viewboxes apply narrow, dynamic lower/upper bounds (`y_min`, `y_max`) tailored around actual intraday strength min/max values (e.g., 50–95), ensuring subtle wall decay is visually distinct.

### 3. ATM Pressure, Breakout Pressure & Range Compression Engines
- **ATM Pressure**: Calculates CE pressure, PE pressure, and net balance (`+18 PE` Support Floor vs `-12 CE` Overhead Resistance) alongside 5m/15m historical momentum deltas.
- **Breakout & Range Compression Engines**: Dynamic setup start times (`STARTED: 10:52 IST`), age, directional bias (`UPSIDE PRESSURE`), statistical reliability %, and live data-driven checklists.

### 4. Master Signal Confidence & Lifecycle Trajectory
- **Dual-Line Trajectory**: Renders intraday points for Confluence Strength vs Statistical Reliability over time.
- **Stage Definitions & Guidance**: Explicit trader guidance for each lifecycle phase (`EARLY`, `CONFIRMED`, `MATURE`, `WEAKENING`, `INVALIDATED`).

---

## ⚡ Institutional Trader Decision Playbook

### 🟢 Bullish Setup (Dip Buying / Put Selling)
1. **Market State Strip**: `OPTION STRUCTURE: BULLISH`, `CONFLUENCE: BULLISH CONFLUENCE`, `STATE: CONFIRMED ENTRY`.
2. **Breakout Engine**: `BREAKOUT STATUS: UPSIDE BREAKOUT CONFIRMED` (Price > CE Wall with +40 Price Confirmation).
3. **Action**: Sell OTM Put Options or Buy Call Spreads on pullbacks to PE Support.

### ⚠️ Conflict Setup (No-Trade / Stand Aside)
1. **Header Banner**: `SIGNAL CONFLICT / UNCONFIRMED` (Option positioning bullish, spot momentum bearish).
2. **Market State Strip**: `STATE: WAIT / DEVELOPING SETUP`.
3. **Action**: DO NOT enter directional trades until price confirmation aligns with option positioning.

---

## 🌐 Access & VM Deployment
- **Local Terminal**: `http://localhost:8000`
- **Oracle Cloud VM IP**: `http://137.23.42.11:8000`

