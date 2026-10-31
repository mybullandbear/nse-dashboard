# Institutional Rules for Trade (Spot-Anchored Trend Following)

> **Document Version**: 2.0  
> **Core Engine**: Shonya Bot & DhanVarsha Execution Engine  
> **Primary Structural Indicator**: **PineScript Breakout Tracker (BRK-TRK)** + **AlphaTrend (AT)** + **Spot VWAP** + **Proximity MAPO**  
> **Asset Class**: NSE Index Options (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY)  
> **Core Philosophy**: Options are non-linear derivatives subject to theta decay and spread noise. All market regimes, entries, initial stop-losses, and structural trailing levels **MUST BE ANCHORED EXCLUSIVELY TO UNDERLYING SPOT STRUCTURE**. Zero arbitrary option premium tick stops.

---

## 1. The Core Flaw in Legacy Bot vs Institutional Model

| Dimension | Legacy Trading Bot (Flawed) | Institutional Spot-Anchored Model (Correct) |
|---|---|---|
| **Stop Loss** | Fixed $-15\%$ on option premium ticks. | Anchored to **Spot Breakout Tracker Invalidation (`fail_level`)** or **Confirmed Pivot High/Low**. |
| **Trailing Stop** | Clamped to Entry $+2\%$ (Breakeven suffocation). | Ratchets dynamically using **Breakout Tracker Trailing (`trail_level`)** and **AlphaTrend**. |
| **Market Noise** | 1-sec option tick wicks / spread widening trigger exits. | Position held through premium fluctuations until **Spot 5M candle structurally breaks**. |
| **Asset Allocation** | Enters 4 indices simultaneously (synthetic 4x correlated leverage). | **Single Index Leader Rule**: Only 1 active trade at a time in the highest-confluence index. |
| **Consolidation** | Over-trades and flips (PE $\rightarrow$ CE $\rightarrow$ PE) in sideways chop. | **Regime Filter (VWAP + 5/20 EMA Ribbon + Breakout Tracker State)** pauses execution during compression. |

---

## 2. The Institutional Indicator Composite: Breakout Tracker (BRK-TRK) & AlphaTrend

The structural backbone of this trading system is powered by the **PineScript Breakout Tracker (`BRK-TRK`)** integrated with **AlphaTrend**, **VWAP**, and **Proximity MAPO**:

```
                              ┌────────────────────────────────────────┐
                              │     BREAKOUT TRACKER (BRK-TRK)         │
                              │  • Confirmed Pivots (pivL=10, pivR=3)  │
                              │  • Breakout Level (resLvl / supLvl)    │
                              │  • Structural Invalidation (fail_level)│
                              │  • Dynamic ATR Ratchet (trail_level)   │
                              └───────────────────┬────────────────────┘
                                                  │
                                                  ▼
                              ┌────────────────────────────────────────┐
                              │          SPOT 5M ALPHATREND            │
                              │   (Volume MFI Stepped Trend Filter)    │
                              └───────────────────┬────────────────────┘
                                                  │
                                                  ▼
                              ┌────────────────────────────────────────┐
                              │               SPOT VWAP                │
                              │   (Institutional Value & Macro Bias)   │
                              └───────────────────┬────────────────────┘
                                                  │
                                                  ▼
                              ┌────────────────────────────────────────┐
                              │     PROXIMITY MA STACK (5/20 EMA)      │
                              │  (Micro-Momentum & Ribbon Exhaustion)  │
                              └────────────────────────────────────────┘
```

### Why Breakout Tracker is the Core Structural Engine:
1. **Zero Repainting Confirmed Pivots**:
   * Uses `ta.pivothigh(high, 10, 3)` and `ta.pivotlow(low, 10, 3)`.
   * A pivot is locked only after a 3-bar confirmation delay (`pivR=3`).
2. **Breakout Expansion Filter**:
   * Long Breakout requires: $\text{Close} > \text{resLvl} + 0.10 \times \text{ATR}_{14}$ with strong candle close ($\text{pos} \ge 0.60$) and volume expansion ($\text{Vol} > 1.2 \times \text{VolMA}_{20}$).
   * Short Breakdown requires: $\text{Close} < \text{supLvl} - 0.10 \times \text{ATR}_{14}$ with strong candle close ($\text{pos} \le 0.40$) and volume expansion.
3. **Exact Structural Failure Level (`fail_level`)**:
   * Long Failure: $\text{fail\_level} = \text{resLvl} - 0.50 \times \text{ATR}_{14}$
   * Short Failure: $\text{fail\_level} = \text{supLvl} + 0.50 \times \text{ATR}_{14}$
4. **Dynamic Trailing Ratchet (`trail_level`)**:
   * Long Trail: $\text{longTrail} = \max(\text{longTrail}, \text{Close} - 3.0 \times \text{ATR}_{14})$
   * Short Trail: $\text{shortTrail} = \min(\text{shortTrail}, \text{Close} + 3.0 \times \text{ATR}_{14})$
   * The trailing line **can never move against the position**—it only ratchets in favor of the trade!

---

## 3. How "Lower High" and "Higher Low" are Mathematically Determined

In technical analysis, manual traders guess where swing points lie. The **Breakout Tracker PineScript algorithmically extracts Lower Highs and Higher Lows** through two mathematical layers:

### Layer A: Mathematical Pivot High/Low ($N$-Bar Window)
At every closed bar $i$, the engine evaluates a left window of $L=10$ bars and a right confirmation window of $R=3$ bars:

$$\text{Bar } p = (i - 3) \text{ is a confirmed Swing High if:}$$
$$\text{High}_p > \max(\text{High}_{p-10 \dots p-1}) \quad \text{AND} \quad \text{High}_p > \max(\text{High}_{p+1 \dots p+3})$$

* **Lower High (LH) Determination for PE (Shorts)**:
  1. Let the previous confirmed pivot high be $\text{resLvl}_{\text{prev}}$.
  2. When a new pivot high forms at bar $p$, let it be $\text{resLvl}_{\text{new}}$.
  3. **Mathematical Condition**:
     $$\text{resLvl}_{\text{new}} < \text{resLvl}_{\text{prev}} \implies \mathbf{Confirmed\ Lower\ High\ (LH)}$$
  4. The engine ratchets the structural resistance to this new level.
  5. The stop is violated **ONLY if Spot closes a 5-minute bar above this Lower High $+ (0.2 \times \text{ATR})$**.

### Layer B: Dynamic Ratcheting via Breakout Tracker `shortTrail`
While waiting for a new 10-bar pivot to form, the engine uses the continuous **Breakout Tracker ATR Trailing Stop**:
$$\text{shortTrail}_t = \min(\text{shortTrail}_{t-1}, \text{Close}_t + 3.0 \times \text{ATR}_{14})$$
* Because of the $\min()$ operator, as Spot falls and prints lower closes, `shortTrail` continuously steps downward.
* Each horizontal shelf on the `shortTrail` line represents the **mathematical volatility ceiling of that swing leg**.
* **Exit Condition for PE**: Spot closes a bar with $\text{Spot Close} > \text{shortTrail}$.

---

## 4. Complete Operational Rules for Live Trading

### RULE 1: Regime Identification (Trending vs Consolidation)

The engine prevents choppy whipsaw days (like Oct 16) by classifying the market before entering:

1. **TRENDING REGIME (Execution Enabled)**:
   * **Breakout Tracker State**: Confirmed `LONG` or `SHORT` (not `FLAT`).
   * **VWAP Separation**: Spot is outside VWAP by at least $0.10\%$.
   * **EMA Slope**: 5 EMA and 20 EMA are clearly separated with expanding slope ($\text{Angle} > 20^\circ$).
   * **OI Confirmation**: PCR aligns ($< 0.85$ for Bearish, $> 1.15$ for Bullish) and Call/Put OI difference is widening in favor of the trade.
   * $\rightarrow$ **Breakout entries ACTIVE.**

2. **CONSOLIDATION REGIME (Execution Paused)**:
   * Breakout Tracker State is `FLAT` (inside corridor between `resLvl` and `supLvl`).
   * Spot oscillates within $\pm 0.08\%$ of VWAP.
   * 5 EMA and 20 EMA are tangled (frequent crosses).
   * PCR is neutral ($0.90$ to $1.05$) with no institutional buildup.
   * $\rightarrow$ **ZERO entries allowed.** Bot waits for structural expansion.

---

### RULE 2: Morning Session Execution (09:18 – 09:45 AM)

Do not artificially ban morning trading; explosive moves occur here. Instead, apply strict structural validation:

1. **Opening 3-Minute Baseline (09:15–09:18)**:
   * Record the High and Low of the opening 3-minute bar.
2. **Breakout Trigger**:
   * If Spot breaks below 3-min Low + Breakout Tracker confirms `SHORT` + Spot is below VWAP + Call OI Writing $>$ Put OI Writing by $1.4\times$:
     * $\rightarrow$ Enter 1-ITM / ATM PE.
3. **Initial Stop**:
   * Anchor Stop Loss to the **Opening 3-minute High** on Spot (or Breakout Tracker `shortFail`).
   * **Zero option percentage stop-loss**.

---

### RULE 3: Single Index Leader Rule (Zero Correlated Multi-Entries)

* The engine monitors NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY.
* At any given minute, **ONLY ONE INDEX CAN BE TRADED**.
* When a directional trigger fires across multiple indices:
  * Rank them by **Confluence / Relative Strength Score**:
    $$\text{Score} = (\text{Distance from VWAP}) \times 0.35 + (\text{OI Divergence Ratio}) \times 0.35 + (\text{Breakout Tracker ATR PnL}) \times 0.30$$
  * Execute **ONLY on the #1 highest-ranked index**.
  * Keep all other indices idle. This eliminates 4x correlated losses during minor pullbacks.

---

### RULE 4: Spot-Anchored Stop-Loss Protocol

* **For PE Positions**:
  * Initial SL = Breakout Tracker `shortFail` ($\text{supLvl} + 0.5 \times \text{ATR}$).
  * Option is held through all premium fluctuations.
  * Exit Order is dispatched **ONLY when Spot Close $\ge$ `shortFail`**.
* **For CE Positions**:
  * Initial SL = Breakout Tracker `longFail` ($\text{resLvl} - 0.5 \times \text{ATR}$).
  * Exit Order is dispatched **ONLY when Spot Close $\le$ `longFail`**.

---

### RULE 5: Multi-Lot Asymmetric Payoff & Trailing

Trade in **2 Lots** (or multiples of 2):

1. **Lot 1 (Guaranteed Cash Bank)**:
   * Exits automatically when Spot moves $1.5\times$ ATR in favor, or Option Premium reaches $+18\%$ to $+20\%$.
   * This locks in realized bank profit immediately.
2. **Lot 2 (Structural Trend Runner)**:
   * As soon as Lot 1 exits, Lot 2's Stop-Loss moves to **Spot Entry Level** (Risk-Free).
   * Lot 2 trails behind the **Breakout Tracker `trail_level` (and Spot 5M AlphaTrend)**:
     * As Spot drops and forms Lower Highs, `trail_level` steps downward.
     * Exit Lot 2 **ONLY when Spot closes a 5-minute bar above `trail_level` (for PE) or below `trail_level` (for CE)**.
   * This allows Lot 2 to capture $+100\%$ to $+200\%$ on massive trending days.

---

### RULE 6: Strict Anti-Whipsaw & Reversal Rule

Never flip from PE to CE (or vice versa) on a single green candle:

* To flip direction, the following **3 conditions must ALL be met**:
  1. Breakout Tracker state must confirm a new opposite breakout (`LONG` for CE, `SHORT` for PE).
  2. Spot must close a 5-minute candle across **VWAP**.
  3. PCR must show **institutional unwinding** ($\Delta \text{PCR} \ge +0.20$ within 15 minutes).
* If these 3 conditions are not met, any bounce while in a PE trade is treated as a **pullback to add/hold**, NOT an entry for CE.

---

### RULE 7: Strict 5-Minute Candle Close Exit Requirement (No Intra-Candle Whipsaw Exits)

> **CORE PRINCIPLE**: Entry can be executed immediately when breakout criteria are fulfilled. However, **ALL EXITS MUST ONLY BE EVALUATED AT THE CLOSE OF THE 5-MINUTE CANDLE**.

1. **The Rationale**:
   * Intra-candle noise (1-second tick pullbacks, momentary bid-ask spread widening, or 3-minute wicks) routinely touches stop levels without breaking the market structure.
   * Exiting mid-candle suffocated our winning trades on Monday Oct 19 (+92% Nifty PE exited at breakeven due to an intra-candle wick).
2. **The Execution Rule**:
   * While a 5-minute candle is forming (e.g. from 09:25:00 to 09:29:59), the bot **DOES NOT EXIT** on temporary wicks.
   * **Only at bar close (XX:X0 or XX:X5)**: The completed candle's `Close` is compared against `fail_level` or `trail_level`.
   * If $\text{Close} \le \text{trail\_level}$ (for CE) or $\text{Close} \ge \text{trail\_level}$ (for PE), the exit is dispatched immediately.
   * If the candle wicks past the level but closes back in favor $\rightarrow$ **The trade remains OPEN**.

---

## 5. Summary Flowchart for Execution Engine

```
[09:15 AM Market Open]
         │
         ▼
[Check Regime: Breakout Tracker State + VWAP + 5/20 EMA Slope]
         │
    ┌────┴────────────────────────┐
    ▼                             ▼
[CHOP / CONSOLIDATION]        [TRENDING BREAKOUT]
State: FLAT                   State: LONG or SHORT
Pause Trading.                Identify Leading Index (#1 Confluence).
Wait for corridor breakout.               │
                                          ▼
                              [Execute 2 Lots ATM/ITM Option]
                              Set SL on Spot Breakout Tracker `fail_level`.
                                          │
                        ┌─────────────────┴─────────────────┐
                        ▼                                   ▼
                [LOT 1: Cash-In]                   [LOT 2: Trend Runner]
         Exit at +18-20% Option Gain.       Trail with Breakout Tracker `trail_level`.
         Move Lot 2 SL to Spot Entry.       Exit ONLY when Spot closes across `trail_level`.
```

---

## 6. Regulatory Indices Specifications: Lot Sizes & Expiry Schedule (SEBI / Exchange Framework)

| Index Symbol | Underlying Name | Exchange | Strike Step | Lot Size (Qty) | Contract Expiry Schedule | Characteristics & Regulatory Status |
|---|---|---|---|---|---|---|
| **NIFTY** | Nifty 50 | NSE | 50 pts | **65** | **Weekly & Monthly: Every Tuesday** | Benchmark National Index, Weekly & Monthly liquidity |
| **BANKNIFTY** | Nifty Bank | NSE | 100 pts | **30** | **Monthly Only: Last Tuesday of the month** | High-beta banking index (Single weekly contract rationalization) |
| **FINNIFTY** | Nifty Financial Services | NSE | 50 pts | **60** | **Monthly Only: Last Tuesday of the month** | Financial services & NBFC sectoral exposure |
| **MIDCPNIFTY** | Nifty Midcap Select | NSE | 25 pts | **120** | **Monthly Only: Last Tuesday of the month** | High-growth midcap segment |
| **SENSEX** | BSE S&P Sensex | BSE | 100 pts | **20** | **Weekly & Monthly: Every Thursday** | Bombay Stock Exchange benchmark index |

> [!IMPORTANT]
> **Key Regulatory Expiry & Sizing Mandates**:
> 1. **NIFTY 50**: Lot size is **65**. Weekly & monthly contracts expire every **Tuesday**.
> 2. **BANKNIFTY**: Lot size is **30**. Trades **only in monthly contracts** expiring on the **last Tuesday of the month**.
> 3. **FINNIFTY**: Lot size is **60**. Trades **only in monthly contracts** expiring on the **last Tuesday of the month**.
> 4. **MIDCPNIFTY**: Lot size is **120**. Trades **only in monthly contracts** expiring on the **last Tuesday of the month**.
> 5. **BSE SENSEX**: Lot size is **20**. Weekly & monthly contracts expire every **Thursday**.
> 6. All backend margin calculations, strike risk models, shadow sizing, and matrix dashboards strictly adhere to these exchange parameters.


