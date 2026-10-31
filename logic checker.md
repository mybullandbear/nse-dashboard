# 🧮 MASTER LOGIC CHECKER & CALCULATION SPECIFICATION
## Active Production Rules for Oracle VM Deployment (VCC V3.2)

> **IMPORTANT:** This document details the exact mathematical formulas, scoring models, threshold matrices, decision trees, and governance rules running on the active Oracle Cloud VM instance (`backend/app`). Archived or deprecated legacy logic (e.g. V3.1) has been completely excluded.

---

# Table of Contents
1. [System Architecture & Market Boundaries](#1-system-architecture--market-boundaries)
2. [Option Chain & Primary Market Analytics](#2-option-chain--primary-market-analytics)
3. [Smart Money Tracker Engine](#3-smart-money-tracker-engine)
4. [VCC V3.2 Confluence Engine & Decision Matrix](#4-vcc-v32-confluence-engine--decision-matrix)
5. [AI Trade Recommendation & Option Selling Engine](#5-ai-trade-recommendation--option-selling-engine)
6. [Signal Lifecycle & Hysteresis Noise Filter](#6-signal-lifecycle--hysteresis-noise-filter)
7. [Stock Early Movement Detection Engine (EMS v2)](#7-stock-early-movement-detection-engine-ems-v2)
8. [20-Point Governance & Look-Ahead Audit Engine](#8-20-point-governance--look-ahead-audit-engine)

---

# 1. System Architecture & Market Boundaries

### 1.1 Active System Scope
- **Production Backend Path**: `backend/app/`
- **Supported Index Derivatives**:
  - `NIFTY`
  - `BANKNIFTY`
  - `FINNIFTY`
  - `MIDCPNIFTY`
- **Data Ingestion Feeds**:
  1. **Primary Feed**: Fyers Broker API v3 (`fyers-apiv3`)
  2. **Secondary Feed**: NSE Web Scraper (`curl_cffi` HTTP client)
  3. **Tertiary Feed**: Real-time DB snapshot fallback & `OptionChainSimulator`

### 1.2 Market Session State Machine
Signal generation and snapshot persistence are governed by strict regular NSE derivative trading hours (IST = UTC + 5:30):

$$\text{Operational State} = \begin{cases} 
\text{"PRE-MARKET"}, & \text{if } 09:00 \le t < 09:15 \text{ IST (Execution Disabled)} \\ 
\text{"LIVE MARKET"}, & \text{if } 09:15 \le t \le 15:15 \text{ IST (Execution Enabled)} \\ 
\text{"POST-MARKET"}, & \text{if } 15:15 < t \le 15:40 \text{ IST (Execution Disabled)} \\ 
\text{"MARKET CLOSED"}, & \text{otherwise (Execution Disabled)} 
\end{cases}$$

### 1.3 Authoritative Hard Real-Data Gate & Data Quality Rules
Every market data snapshot contains structured metadata (`DataSourceMetadata`) with mandatory status tracking:

$$\text{DataStatus} \in \{\text{REAL\_LIVE}, \, \text{REAL\_RECENT}, \, \text{REAL\_STALE}, \, \text{INVALID}, \, \text{MISSING}, \, \text{SYNTHETIC}, \, \text{UNKNOWN}\}$$

#### Mandatory Snapshot Telemetry Contract
- `symbol`: Equity/Index symbol (e.g. `NIFTY`)
- `exchange`: Exchange identifier (`NSE`)
- `provider`: Active provider name (`FYERS_LIVE`, `NSE_LIVE`, `PERSISTED_DB`, `SIMULATED`, `UNAVAILABLE`)
- `provider_timestamp`: ISO 8601 timestamp reported by upstream provider
- `received_timestamp`: Local IST time when snapshot was ingested
- `market_timestamp`: True market timestamp of underlying quote/chain
- `data_age_seconds`: Maximum age between spot and option chain timestamps relative to current IST time
- `data_status`: One of the 7 DataStatus states
- `is_real_data`: Boolean flag (`True` ONLY for `FYERS_LIVE`, `NSE_LIVE`, `PERSISTED_DB`)
- `is_stale`: Boolean flag (`True` if `data_age_seconds` $> 30.0$ seconds or data is synthetic)
- `completeness_status`: Completeness check (`COMPLETE`, `MISSING_SPOT`, `EMPTY_STRIKES`, `SYNTHETIC`, `MISSING`)
- `validation_status`: Gate validation code (`REAL_DATA_LIVE`, `REAL_DATA_RECENT`, `REAL_DATA_STALE`, `SYNTHETIC_DATA_PROHIBITED`, `INVALID_SPOT_PRICE`, `INVALID_OPTION_CHAIN`)
- `quality`: Canonical quality level (`GOOD`, `DEGRADED`, `INVALID`)

#### Hard Real-Data Signal Eligibility Gate Matrix
Signals are generated **ONLY** when market data passes the authoritative `DataQualityEvaluator.is_signal_eligible()` gate:

| DataStatus State | Real Data? | Stale? | Operational State Returned | Signal Eligible? |
| :--- | :---: | :---: | :---: | :---: |
| **REAL_LIVE** ($\le 5\text{s}$) | `True` | `False` | Active Signal Engine State | **YES** (100% Valid) |
| **REAL_RECENT** ($5\text{s} - 30\text{s}$) | `True` | `False` | Active Signal Engine State | **YES** (Recent Feed) |
| **REAL_STALE** ($> 30\text{s}$) | `True` | `True` | `WATCH` | **NO** (Stale Feed Prohibited) |
| **INVALID** | `False` | `True` | `WATCH` | **NO** (Malformed Structure) |
| **MISSING** | `False` | `True` | `DATA_UNAVAILABLE` | **NO** (Missing Required Data) |
| **SYNTHETIC** | `False` | `True` | `NO_VALID_DATA` / `WATCH` | **NO** (Synthetic Prohibited) |
| **UNKNOWN** | `False` | `True` | `WATCH` | **NO** (Unknown Status) |

#### Contamination Prevention & Persistence Rules
1. **Zero Synthetic Signals**: `DatabaseFallbackProviderAdapter` and emergency fallbacks must NEVER generate synthetic option chain strikes or relabel historical timestamps as live.
2. **Read-Only API Decoupling**: HTTP GET requests (`/api/vcc/signals/{symbol}`, `/api/vcc/dashboard/{symbol}`) are strictly read-only and must NEVER trigger side-effect writes to `vcc_live_signal_audits`.
3. **Controlled Audit Persistence**: Immutable signal audit records are written ONLY by `V3BackgroundPoller` during live market hours for validated `REAL_LIVE` or `REAL_RECENT` snapshots.

---

# 2. Option Chain & Primary Market Analytics

### 2.1 Strike Parameters & At-The-Money (ATM) Formula

$$\text{ATM Strike} = \text{round}\left(\frac{\text{Spot Price}}{\text{Strike Step}}\right) \times \text{Strike Step}$$

| Symbol | Default Strike Step | ATM ± 5 Band Width | Strangle Fallback Step |
| :--- | :---: | :---: | :---: |
| **NIFTY** | 50 pts | 250 pts | 150 pts |
| **BANKNIFTY** | 100 pts | 500 pts | 300 pts |
| **FINNIFTY** | 50 pts | 250 pts | 150 pts |
| **MIDCPNIFTY** | 50 pts | 250 pts | 75 pts |

### 2.2 Put-Call Ratio (PCR) Calculations

1. **Overall Market PCR**:
   $$\text{PCR}_{\text{Overall}} = \frac{\sum_{s \in \text{Chain}} \text{Put OI}_s}{\sum_{s \in \text{Chain}} \text{Call OI}_s}$$

2. **ATM ± 5 Band PCR**:
   $$\text{PCR}_{\text{ATM}\pm5} = \frac{\sum_{s \in [\text{ATM}-5\text{Step}, \text{ATM}+5\text{Step}]} \text{Put OI}_s}{\sum_{s \in [\text{ATM}-5\text{Step}, \text{ATM}+5\text{Step}]} \text{Call OI}_s}$$

### 2.3 Strike-Level Defense Walls & Migration Velocity

- **Call Wall Strike (Resistance Ceiling)**:
  $$\text{Call Wall Strike} = \arg\max_{s \ge \text{ATM}} (\text{CE OI}_s)$$
  *(Constrained strictly to strikes at or above ATM)*.

- **Put Wall Strike (Support Floor)**:
  $$\text{Put Wall Strike} = \arg\max_{s \le \text{ATM}} (\text{PE OI}_s)$$
  *(Constrained strictly to strikes at or below ATM)*.

- **Wall Migration Velocity ($\text{pts/hr}$)**:
  $$\text{Velocity} = \frac{\text{Wall Strike}_{t} - \text{Wall Strike}_{t - 1\text{h}}}{1.0 \text{ Hour}}$$

- **Migration Direction Classification**:
  $$\text{Wall Direction} = \begin{cases} 
  \text{"UPWARD\_MIGRATION"}, & \text{if } \text{Velocity} > +25\text{ pts/hr} \\ 
  \text{"DOWNWARD\_MIGRATION"}, & \text{if } \text{Velocity} < -25\text{ pts/hr} \\ 
  \text{"STABLE"}, & \text{otherwise} 
  \end{cases}$$

### 2.4 Expected EOD Theta Decay

$$\text{ATM Premium} = \text{LTP}_{\text{CE}}(\text{ATM}) + \text{LTP}_{\text{PE}}(\text{ATM})$$

$$\text{Expected EOD Decay} = \text{round}\left(\text{ATM Premium} \times 0.45, \, 2\right)$$

---

# 3. Smart Money Tracker Engine

Implemented in `backend/app/smart_money/scoring.py` and `backend/app/services/smart_money_service.py`.

### 3.1 Put Writing Conviction (Bullish Floor Score, 20% – 99%)

$$\text{Put Conviction} = \text{clamp}_{20.0}^{99.0} \left( \text{round}\left( \frac{\text{Total PE OI}_{\text{ATM}\pm10}}{\max(1.0, \text{Total CE OI}_{\text{ATM}\pm10})} \times 50.0 + \frac{\text{Total PE OI Change}_{\text{ATM}\pm10}}{100,000.0}, \, 1 \right) \right)$$

### 3.2 Call Writing Conviction (Bearish Ceiling Score, 20% – 99%)

$$\text{Call Conviction} = \text{clamp}_{20.0}^{99.0} \left( \text{round}\left( \frac{\text{Total CE OI}_{\text{ATM}\pm10}}{\max(1.0, \text{Total PE OI}_{\text{ATM}\pm10})} \times 50.0 + \frac{\text{Total CE OI Change}_{\text{ATM}\pm10}}{100,000.0}, \, 1 \right) \right)$$

### 3.3 Net Institutional Bias Classification

$$\text{Net Institutional Bias} = \begin{cases} 
\text{"BULLISH FLOOR BUILDING"}, & \text{if } \text{PE OI Change}_{\text{ATM}\pm5} > \text{CE OI Change}_{\text{ATM}\pm5} + 30,000 \\ 
\text{"BEARISH CEILING BUILDING"}, & \text{if } \text{CE OI Change}_{\text{ATM}\pm5} > \text{PE OI Change}_{\text{ATM}\pm5} + 30,000 \\ 
\text{"RANGE-BOUND ACCUMULATION"}, & \text{otherwise} 
\end{cases}$$

### 3.4 High-Conviction Smart Money Score (50 – 98)

$$\text{Ratio}_5 = \frac{\Delta\text{PE OI}_{\text{ATM}\pm5} - \Delta\text{CE OI}_{\text{ATM}\pm5}}{\max(1.0, |\Delta\text{PE OI}_{\text{ATM}\pm5}| + |\Delta\text{CE OI}_{\text{ATM}\pm5}|)}$$

$$\text{Smart Money Score} = \begin{cases} 
\min\left(98, \max(75, \lfloor 50 + (\text{Ratio}_5 \times 48) \rfloor)\right), & \text{if } \text{Ratio}_5 \ge +0.15 \\ 
\min\left(98, \max(75, \lfloor 50 + (|\text{Ratio}_5| \times 48) \rfloor)\right), & \text{if } \text{Ratio}_5 \le -0.15 \\ 
\max\left(50, \min(65, \lfloor 50 + (|\text{Ratio}_5| \times 35) \rfloor)\right), & \text{otherwise} 
\end{cases}$$

### 3.5 Market Direction Decision Score (5 – 99)

$$\text{Base Direction Score} = 50$$

1. **Bias Adjustment**: $+25$ if `sm_bias_5 == "BULLISH"`, $-25$ if `sm_bias_5 == "BEARISH"`.
2. **PCR Adjustment**: $+15$ if $\text{PCR} \ge 1.15$, $-15$ if $\text{PCR} \le 0.85$.
3. **Spot vs ATM Adjustment**: $+10$ if $\text{Spot} \ge \text{ATM}$, $-10$ if $\text{Spot} < \text{ATM}$.

$$\text{Direction Score} = \text{clamp}_{5}^{99}(\text{Base Score})$$

- **Score $\ge 65$**: `🟢 BULLISH TREND (BUY DIPS / SELL PE)`
- **Score $\le 35$**: `🔴 BEARISH TREND (SELL RALLIES / SELL CE)`
- **36 – 64**: `🟡 SIDEWAYS / RANGEBOUND (STRADDLE DECAY)`

### 3.6 Institutional Shift Detection Thresholds

| Symbol | Min OI Shift Addition Threshold | Min Unwinding Threshold | Shift Type |
| :--- | :---: | :---: | :---: |
| **NIFTY** | $\ge +35,000$ contracts | $\le -25,000$ contracts | `BULL` (PE Add) / `BEAR` (CE Add) |
| **BANKNIFTY** | $\ge +25,000$ contracts | $\le -20,000$ contracts | `BULL` (PE Add) / `BEAR` (CE Add) |
| **FINNIFTY** | $\ge +20,000$ contracts | $\le -15,000$ contracts | `BULL` (PE Add) / `BEAR` (CE Add) |
| **MIDCPNIFTY** | $\ge +15,000$ contracts | $\le -10,000$ contracts | `BULL` (PE Add) / `BEAR` (CE Add) |

---

# 4. VCC V3.2 Confluence Engine & Decision Matrix

Implemented in `backend/app/analytics/pipeline.py` and `backend/app/signals/signal_engine.py`.

### 4.1 4-Factor Weighted Confluence Score

$$\text{Weighted Signal} = 0.60 \times \text{Positioning Score} + 0.40 \times \text{Price Confirmation Score}$$

$$\text{Raw Confluence Score} = \text{clamp}_{5}^{99} \left( 50 + \text{round}\left( \frac{\text{Weighted Signal}}{2.0} \right) \right)$$

### 4.2 Positioning vs Price Conflict Guard

A conflict is flagged if option position building opposes underlying spot momentum:

```python
if positioning_score >= 20 and price_confirmation_score <= -15:
    is_conflict = True
    conflict_type = "POSITIONING vs PRICE CONFLICT"
elif positioning_score <= -20 and price_confirmation_score >= 15:
    is_conflict = True
    conflict_type = "POSITIONING vs PRICE CONFLICT"
```

$$\text{Final Confluence Score} = \begin{cases} 
\text{clamp}_{20}^{55}(\text{Raw Confluence} - 25), & \text{if } \text{is\_conflict is True} \\ 
\text{Raw Confluence}, & \text{otherwise} 
\end{cases}$$

### 4.3 Operational State Decision Matrix

| Confluence Score | Price Confirmation Score | Breakout Status | Operational State | Reason Codes |
| :---: | :---: | :--- | :--- | :--- |
| **Data Invalid** | Any | Any | `WATCH` | `DATA_QUALITY_INVALID` |
| **Conflict True** | Any | Any | `SIGNAL CONFLICT` | `POSITIONING_PRICE_MISMATCH` |
| **$< 35$** | Any | Any | `NO SIGNAL` | `LOW_CONFLUENCE_SCORE` |
| **$35 - 49$** | Any | Any | `WATCH` | `WAITING_FOR_CONFLUENCE` |
| **$50 - 59$** | Any | Any | `SETUP DEVELOPING` | `CONFLUENCE_BUILDING` |
| **$60 - 69$** | Any | Any | `CONFIRMED BIAS` | `STRONG_DIRECTIONAL_BIAS` |
| **$\ge 70$** | $\ge 50$ | `BREAKOUT CONFIRMED` | `ENTRY CONFIRMED` | `HIGH_CONFLUENCE`, `BREAKOUT_VALIDATED` |
| **$\ge 70$** | $\ge 50$ | Other | `ENTRY READY` | `HIGH_CONFLUENCE`, `PRICE_CONFIRMED` |
| **$\ge 70$** | $< 50$ | Other | `CONFIRMED BIAS` | `AWAITING_PRICE_CONFIRMATION` |

---

# 5. AI Trade Recommendation & Option Selling Engine

Implemented in `backend/app/engines/trade_scorer.py` and `backend/app/engines/seller_engine.py`.

### 5.1 Multi-Factor Scoring Model (100-Point Scale)

$$\text{Total Score} = S_{\text{momentum}} + S_{\text{volume}} + S_{\text{oi}} + S_{\text{pcr}} + S_{\text{iv}} + S_{\text{sector}} + S_{\text{trend}} + S_{\text{risk}}$$

| Scoring Factor | Max Points | Formula / Logic |
| :--- | :---: | :--- |
| **1. Momentum / Distance** | 20 | $\min\left(20.0, \, \frac{|\text{Strike} - \text{Spot}|}{\text{Spot}} \times 400.0\right)$ |
| **2. Volume / Liquidity** | 15 | $\frac{\text{Volume}_{\text{strike}}}{\text{Max Volume}} \times 15.0$ |
| **3. Open Interest Defense** | 20 | $\frac{\text{OI}_{\text{strike}}}{\text{Max OI}} \times 15.0 + (\text{if } \Delta\text{OI} > 0 \text{ then } 5.0 \text{ else } 0.0)$ |
| **4. PCR Alignment** | 10 | CE: $\min(10.0, (\text{PCR}-0.5) \times 10.0)$ if $\text{PCR}>1.0$; PE: $\min(10.0, (1.5-\text{PCR}) \times 10.0)$ if $\text{PCR}<1.0$ |
| **5. Implied Volatility Zone** | 10 | $15\% \le \text{IV} \le 30\% \rightarrow 10$ pts; $30\% < \text{IV} \le 50\% \rightarrow 7$ pts; $\text{IV} > 50\% \rightarrow 3$ pts; $\text{IV} < 15\% \rightarrow 5$ pts |
| **6. Sector Confirmation** | 10 | $10.0$ pts if sector flow aligns with trade (e.g. Bearish sector $>60\%$ for CE sell) |
| **7. Trend & OI Interpretation**| 10 | Fresh Short $= 10$ pts (CE), Fresh Long $= 10$ pts (PE) |
| **8. Gamma Risk** | 5 | $|\gamma| < 0.0003 \rightarrow 5.0$ pts; $0.0003 \le |\gamma| < 0.0008 \rightarrow 3.0$ pts; $|\gamma| \ge 0.0008 \rightarrow 1.0$ pt |

### 5.2 Short-Term Momentum Filter (`pctChange`)

- **Bullish Momentum (`pctChange > +0.20%`)**:
  - CE Selling: Penalized by **$-18.0$ to $-25.0$ pts** (suppressed if $> +0.40\%$).
  - PE Selling: Boosted by **$+5.0$ pts**.
- **Bearish Momentum (`pctChange < -0.20%`)**:
  - PE Selling: Penalized by **$-18.0$ to $-25.0$ pts** (suppressed if $< -0.40\%$).
  - CE Selling: Boosted by **$+5.0$ pts**.

### 5.3 Smart Money Confluence Adjustments

1. **Wall Defense Alignment (+14 pts)**: Strike $\le 100$ pts from Call Wall (for CE) or Put Wall (for PE).
2. **Far-Wall Penalty (-12 pts)**: Strike $> 150$ pts past Wall (unprotected OTM premium).
3. **High Conviction Boost (+5 pts)**: Call or Put conviction $\ge 70\%$.
4. **Range-Bound Prioritization (+15 pts)**: Short Strangle and Iron Condor boosted by $+15.0$ pts in range-bound markets.

### 5.4 Strategy Execution Formulas

1. **Single Naked Option (Sell CE / Sell PE)**:
   - **Probability of Profit (POP)**: $\text{POP} = \text{round}((1 - |\Delta|) \times 100, \, 1)$
   - **Stop Loss**: $2.0 \times \text{Entry Premium}$
   - **Margin**: $\text{Spot Price} \times \text{Lot Size} \times 0.12$ ($\approx 12\%$ SPAN margin)

2. **Short Strangle**:
   - **Total Premium**: $\text{Premium}_{\text{CE}} + \text{Premium}_{\text{PE}}$
   - **POP**: $\max\left(0.0, \, \text{POP}_{\text{CE}} + \text{POP}_{\text{PE}} - 100.0\right)$
   - **Margin**: $\text{Spot Price} \times \text{Lot Size} \times 0.15$ ($\approx 15\%$ SPAN margin)

3. **Short Straddle (ATM)**:
   - **Total Premium**: $\text{LTP}_{\text{CE}}(\text{ATM}) + \text{LTP}_{\text{PE}}(\text{ATM})$
   - **Daily Volatility**: $\sigma_{\text{daily}} = \frac{\text{Average IV}}{100 \times \sqrt{252}}$
   - **Standard Score $Z$**: $Z = \frac{\text{Total Premium} / \text{Spot}}{\sigma_{\text{daily}}}$
   - **POP**: $\text{clamp}_{20.0}^{75.0}\left( \left( 2 \cdot \Phi(Z) - 1 \right) \times 100 \right)$ where $\Phi(Z)$ is the standard normal CDF.

4. **Iron Condor (4-Leg Hedged Spread)**:
   - **Net Credit**: $(\text{LTP}_{\text{Sell CE}} - \text{LTP}_{\text{Buy CE}}) + (\text{LTP}_{\text{Sell PE}} - \text{LTP}_{\text{Buy PE}})$
   - **Max Risk per Lot**: $(\text{Strike Step} - \text{Net Credit}) \times \text{Lot Size}$
   - **Margin**: $\text{Strike Step} \times \text{Lot Size}$

### 5.5 Safety Circuit Breakers
- **India VIX Breaker**: If $\text{VIX} > 22.0$, all trade recommendation scores drop to $0$ and return `MARKET ALERT: VIX TOO HIGH (AVOID SELLING)`.

---

# 6. Signal Lifecycle & Hysteresis Noise Filter

Implemented in `backend/app/engines/signal_lifecycle.py`.

```
[ SCAN DETECTS TRADE ] ──> GENERATED
                               │
                               ▼
                         CONFIRMING  <── (Must persist >= 4 consecutive scans)
                               │
                               ▼
                            ACTIVE  <── (Requires Candidate Score >= Active Score + 18.0 pts)
                               │
                               ▼
                            CLOSED  <── (Target 80% decay captured OR SL 2x OR VIX > 22)
```

### 6.1 Noise Suppression Rules
1. **Confirmation Buffer**: Trade candidate must remain valid across **4 consecutive 3-second market scans** before promotion to `ACTIVE`.
2. **Score Hysteresis Guard**: Candidate strategy must outperform active signal by at least **$+18.0$ points**:
   $$\text{Score}_{\text{Candidate}} \ge \text{Score}_{\text{Active}} + 18.0$$
3. **Minimum Holding Period**: Active signal locked for at least **450 seconds (7.5 minutes)** before termination, shielding positions against transient intraday tick spikes.

### 6.2 Real-Time MFE & MAE Tracking

$$\text{Unrealized P\&L (pts)} = \text{Entry Premium} - \text{Current Premium}$$

$$\text{MFE}_{\text{pts}} = \max\left(\text{MFE}_{\text{pts}}, \, \text{Unrealized P\&L}\right)$$

$$\text{MAE}_{\text{pts}} = \min\left(\text{MAE}_{\text{pts}}, \, \text{Unrealized P\&L}\right) \quad (\text{Drawdown is negative})$$

### 6.3 Phase 3 Immutable Signal Timestamp Integrity & Deduplication Architecture

Implemented in `backend/app/signals/signal_engine.py` (`SignalLifecycleTracker`), `backend/app/repositories/signal_repository.py`, `backend/app/db/models.py`, and `backend/app/domain/contracts.py`.

#### Mandatory Lifecycle Telemetry Fields
Every VCC decision output (`SignalDecision`, `SignalCardResponse`, `SignalLifecycleModel`) carries strict, immutable initiation telemetry:

| Telemetry Field | Type | Immutability | Description |
| :--- | :---: | :---: | :--- |
| `signal_id` | `str` | **IMMUTABLE** | Canonical identifier formatted as `SIG_{SYMBOL}_{YYYYMMDD_HHMMSS}` based on true market observation timestamp |
| `signal_initiated_at` | `str` | **IMMUTABLE** | Exact ISO timestamp of the first market snapshot observation that triggered active signal criteria |
| `signal_initiated_at_ist` | `str` | **IMMUTABLE** | Human-readable IST string (e.g., `2026-09-02 09:15:00 IST`) |
| `market_timestamp_at_initiation` | `str` | **IMMUTABLE** | Provider market timestamp captured at signal initiation |
| `last_evaluated_at` | `str` | DYNAMIC | ISO timestamp of the current market scan / evaluation cycle |
| `last_updated_at` | `str` | DYNAMIC | ISO timestamp when signal score or operational state last changed |
| `timestamp_status` | `str` | DYNAMIC | `VERIFIED` for live/real data observations; `TIMESTAMP_UNVERIFIED` for synthetic/fallback data |
| `confirming_started_at` | `Optional[str]` | IMMUTABLE ONCE SET | Timestamp when signal entered `CONFIRMED BIAS` |
| `activated_at` | `Optional[str]` | IMMUTABLE ONCE SET | Timestamp when signal entered `ENTRY READY` or `ENTRY CONFIRMED` |
| `closed_at` | `Optional[str]` | IMMUTABLE ONCE SET | Timestamp when signal transitioned to an inactive state (`WATCH`, `NO SIGNAL`, etc.) |

#### Deduplication & Recalculation Governance Rules
1. **Initiation Freeze**: When a signal transitions from inactive to an active directional setup (`BULLISH` or `BEARISH` with state in `SETUP DEVELOPING`, `CONFIRMED BIAS`, `ENTRY READY`, `ENTRY CONFIRMED`), `signal_initiated_at`, `signal_initiated_at_ist`, `market_timestamp_at_initiation`, and `signal_id` are permanently assigned and **FROZEN**.
2. **Polling & Refresh Protection**: Repeated API requests (`GET /api/vcc/signals/{symbol}`) or background poller cycles while the active direction persists MUST NOT recreate the signal or reset `signal_initiated_at`.
3. **Score & State Recalculation**: Sub-scans that update `confluence_score` (e.g. $72.0 \rightarrow 85.0$) or transition operational state update `last_evaluated_at` and `last_updated_at`, while `signal_initiated_at` remains unchanged.
4. **State Closure**: If an active signal transitions to an inactive state (`WATCH`, `DATA_UNAVAILABLE`, `NO_VALID_DATA`, `SIGNAL CONFLICT`, `NO SIGNAL`, `NEUTRAL`), the record is closed with `closed_at = market_timestamp` and removed from active memory.
5. **Persistence Recovery**: On server restart, `SignalLifecycleTracker` restores unclosed active signals from `SignalLifecycleModel` DB table, ensuring original initiation timestamps and `signal_id`s survive process restarts.

---

# 7. Stock Early Movement Detection Engine (EMS v2)

Implemented in `backend/app/services/stock_detection_engine.py`.

### 7.1 Dynamic Weights & Session Alpha

$$\alpha = \min\left(1.0, \, \max\left(0.0, \, \frac{\text{Elapsed Seconds}}{6.25 \times 3600}\right)\right)$$

| Feature Key | Weight Formula | Description |
| :--- | :--- | :--- |
| `rank_a` | $0.14 \times (1 + 0.5(1 - \alpha))$ | Rank acceleration (higher weight early morning) |
| `vda` | $0.13$ | VWAP Distance Acceleration |
| `vsp` | $0.12 \times (1 + 0.3\alpha)$ | VWAP Support Persistence (higher weight afternoon) |
| `pa` | $0.11$ | Price Acceleration |
| `vs_trans` | $0.09 \times (1 + 0.5(1 - \alpha))$ | Volume Shocker Transition |
| `dp` | $0.09 \times (1 + 0.4\alpha)$ | Directional Price Persistence |
| `list_entry` | $0.07 \times (1 + 0.6(1 - \alpha))$ | Fresh Gainer/Loser List Entry |
| `hwf` | $0.06$ | High-Water Mark Persistence |
| `rpv` | $0.06$ | Range Position Velocity |
| `srs` | $0.05 \times (1 + 0.3\alpha)$ | Relative Strength Score ($\text{pChange} - 2.0$) |
| `vdr` | $0.05$ | VWAP Distance Ratio |
| `lp` | $0.03$ | Multi-List Presence Score |

$$\text{EMS}_{\text{raw}} = \frac{\sum (S_k \times W_k)}{\sum W_k} \times 100$$

### 7.2 Signal Age & VWAP Distance Penalties

$$\text{Age Penalty} = \begin{cases} 
0.0, & \text{if } \text{Age} \le 10\text{ mins} \\ 
(\text{Age} - 10) \times 0.3, & \text{if } 10 < \text{Age} \le 20\text{ mins} \\ 
\min(15.0, \, (\text{Age} - 20) \times 0.5), & \text{if } \text{Age} > 20\text{ mins} 
\end{cases}$$

$$\text{VWAP Distance Penalty} = \begin{cases} 
0.0, & \text{if } |\text{VWAP Dist \%}| \le 1.2\% \\ 
\min(10.0, \, (|\text{VWAP Dist \%}| - 1.2) \times 5.0), & \text{if } |\text{VWAP Dist \%}| > 1.2\% 
\end{cases}$$

$$\text{EMS Final} = \text{clamp}_{0}^{100}(\text{EMS}_{\text{raw}} - \text{Age Penalty} - \text{VWAP Penalty} - \text{Range Penalty})$$

### 7.3 Signal Quality Classification

- **`Valid / Fresh` (🟢)**: Fresh entry, tight VWAP distance, high volume shock. Action: **Buy**
- **`Extended` (🟡)**: VWAP distance extended ($>1.2\%$) or late age. Action: **Caution**
- **`Watch` (🟠)**: Mixed multi-timeframe alignment or aging signal. Action: **Wait**
- **`Exhaustion Risk` (🔴)**: Exhaustion score $>0.6$ or range $>90\%$. Action: **Avoid**
- **`Invalid` (⚫)**: Confidence $<30\%$ or trend conflict. Action: **Avoid**

---

# 8. 20-Point Governance & Look-Ahead Audit Engine

Implemented in `backend/app/services/live_signal_audit_service.py` and `backend/app/engines/vcc_signal_lab.py`.

### 8.1 Immutable Audit Snapshot Table (`vcc_live_signal_audits`)
Every live signal change persists telemetry including `snapshot_id`, `trade_date`, `timestamp`, `symbol`, `spot_price`, `confluence_score`, `pcr`, `operational_state`, and forward outcomes (`spot_t5`, `spot_t15`, `spot_t30`, `mfe_t30_pct`, `mae_t30_pct`, `directional_correctness_30m`).

### 8.2 Anti-Lookahead Guarantee Rule
To guarantee 100% statistical integrity and prevent data leakage:
> **Forward outcomes at $T+5\text{m}, T+15\text{m}, T+30\text{m}$ are calculated EXCLUSIVELY using snapshots whose timestamp $t > T$.**

### 8.3 Directional Win/Loss Evaluation Rules

$$\text{Return}_{T+\Delta t} = \frac{\text{Spot}_{T+\Delta t} - \text{Spot}_T}{\text{Spot}_T}$$

- **`BULLISH` Signal**:
  - **WIN (100% Success)**: If $\text{Return}_{T+\Delta t} \ge +0.0010$ (or $+10.0$ pts)
  - **LOSS (0% Success)**: If $\text{Return}_{T+\Delta t} \le -0.0010$
- **`BEARISH` Signal**:
  - **WIN (100% Success)**: If $\text{Return}_{T+\Delta t} \le -0.0010$ (or $-10.0$ pts)
  - **LOSS (0% Success)**: If $\text{Return}_{T+\Delta t} \ge +0.0010$
- **Non-Directional Signals (`WATCH`, `NO SIGNAL`, `SIGNAL CONFLICT`, `NEUTRAL`)**:
  - Classified as `EXCLUDED_NON_DIRECTIONAL` and strictly removed from win/loss accuracy totals.

### 8.4 Statistical Sample Quality Classification

$$\text{Sample Quality} = \begin{cases} 
\text{"INSUFFICIENT SAMPLE"}, & \text{if } N < 30 \text{ (Statistical claims unverified)} \\ 
\text{"LOW SAMPLE"}, & \text{if } 30 \le N \le 99 \\ 
\text{"MODERATE SAMPLE"}, & \text{if } 100 \le N \le 299 \\ 
\text{"HIGHER SAMPLE"}, & \text{if } N \ge 300 
\end{cases}$$

---

## 14. PHASE 5 — AUTHORITATIVE MARKET SESSION ENGINE

### 14.1 Authoritative Session Definitions (Asia/Kolkata IST)

| Session State | Time Window (IST) | `is_live` | `signal_generation_allowed` | `data_collection_allowed` | Description |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **`PRE_MARKET`** | `09:00:00` to `09:15:00` | `False` | `False` | `True` | Data collection/preparation permitted. No live actionable entry signals. |
| **`LIVE_MARKET`** | `09:15:00` to `15:15:00` | `True` | `True` | `True` | Real-time signal generation permitted. |
| **`POST_MARKET`** | `15:15:00` to `15:40:00` | `False` | `False` | `True` | Post-market analysis, batch audit, and summary calculations permitted. No new entry signals. |
| **`MARKET_CLOSED`** | `< 09:00:00`, `>= 15:40:00`, Weekends, Holidays | `False` | `False` | `False` | Market closed. No live signal evaluation or data collection. |

---

### 14.2 Exact Time Boundary Matrix

$$\text{Session State}(t) = \begin{cases} 
\text{"MARKET\_CLOSED"}, & t < 09:00:00 \text{ IST} \\ 
\text{"PRE\_MARKET"}, & 09:00:00 \le t < 09:15:00 \text{ IST} \\ 
\text{"LIVE\_MARKET"}, & 09:15:00 \le t < 15:15:00 \text{ IST} \\ 
\text{"POST\_MARKET"}, & 15:15:00 \le t < 15:40:00 \text{ IST} \\ 
\text{"MARKET\_CLOSED"}, & t \ge 15:40:00 \text{ IST} \text{ or Weekend / Holiday} 
\end{cases}$$

| Timestamp | Evaluated Session State | Live Signal Eligible? |
| :--- | :--- | :---: |
| `08:59:59` | `MARKET_CLOSED` | ❌ No |
| `09:00:00` | `PRE_MARKET` | ❌ No |
| `09:14:59` | `PRE_MARKET` | ❌ No |
| `09:15:00` | `LIVE_MARKET` | ✅ Yes |
| `15:14:59` | `LIVE_MARKET` | ✅ Yes |
| `15:15:00` | `POST_MARKET` | ❌ No |
| `15:39:59` | `POST_MARKET` | ❌ No |
| `15:40:00` | `MARKET_CLOSED` | ❌ No |

---

### 14.3 Distinct Operating Windows

1. **`BUSINESS SESSION`**: Active operating window from `09:00:00` to `15:40:00 IST` (encompassing `PRE_MARKET`, `LIVE_MARKET`, `POST_MARKET`).
2. **`DATA COLLECTION WINDOW`**: `09:00:00` to `15:40:00 IST`.
3. **`PROVIDER AVAILABILITY WINDOW`**: `09:00:00` to `15:40:00 IST`.
4. **`SIGNAL GENERATION WINDOW`**: Strictly `09:15:00` to `15:15:00 IST` (`LIVE_MARKET`).
5. **`AUDIT WINDOW`**: `15:15:00` to `15:40:00 IST` (`POST_MARKET`).

---

## 15. PHASE 6 — OPTION CHAIN & ATM CALCULATION HARDENING

### 15.1 Authoritative ATM Strike Selection Engine

Let $S = [s_1, s_2, \dots, s_n]$ be the sorted list of valid, available strike prices present in the option chain.

$$\text{ATM Strike}(P_{\text{spot}}, S) = \begin{cases} 
s_i, & \text{if } \exists \, s_i \in S \text{ such that } P_{\text{spot}} = s_i \text{ (Exact Match)} \\ 
s_{k+1}, & \text{if } s_k < P_{\text{spot}} < s_{k+1} \text{ and } (P_{\text{spot}} - s_k) = (s_{k+1} - P_{\text{spot}}) \text{ (Equidistant Midpoint Half-Up)} \\ 
s_k, & \text{if } s_k < P_{\text{spot}} < s_{k+1} \text{ and } (P_{\text{spot}} - s_k) < (s_{k+1} - P_{\text{spot}}) \text{ (Nearest Available)} \\ 
s_{k+1}, & \text{if } s_k < P_{\text{spot}} < s_{k+1} \text{ and } (P_{\text{spot}} - s_k) > (s_{k+1} - P_{\text{spot}}) \text{ (Nearest Available)} \\ 
s_1, & \text{if } P_{\text{spot}} < s_1 \text{ (Out of Bounds Low)} \\ 
s_n, & \text{if } P_{\text{spot}} > s_n \text{ (Out of Bounds High)} \\ 
\left\lfloor \frac{P_{\text{spot}}}{W} + 0.5 \right\rfloor \times W, & \text{if } S = \emptyset \text{ (Theoretical Grid Fallback with step } W \text{)} 
\end{cases}$$

---

### 15.2 Before vs. After Behavior Matrix

| Dimension | Legacy / Audit Behavior (Before) | Hardened Engine Behavior (After) |
| :--- | :--- | :--- |
| **Midpoint Rounding** | Used Python `round(spot / step) * step` (banker's round-to-even: `round(24025/50)*50 = 24000`, `round(24075/50)*50 = 24100`). | Deterministic half-up upper strike preference: $24025.0 \to 24050.0$ and $24075.0 \to 24100.0$. |
| **Missing Strike in Chain** | Assumed theoretical grid point (even if strike did NOT exist in actual contract matrix). | Prefers nearest **VALID AVAILABLE STRIKE** directly from option chain matrix. |
| **Stock Strike Intervals** | Assumed index step (e.g., 50/100) for stock option chains. | Dynamically derives strike step directly from option chain ($\min(s_{i+1} - s_i)$ e.g., RELIANCE = 10). |
| **Missing LTP / OI** | Defaulted missing LTP or OI to zero or fabricated dummy values. | Strict validation: returns `NO_VALID_DATA`. No zero substitution or value fabrication. |
| **Incomplete Chain Handling** | Evaluated guessed ATM and partial data. | Rejects snapshot with `validation_status = "NO_VALID_DATA"` and `DataQuality = INVALID`. |
| **Calculation Telemetry** | Preserved only `atm_strike`. | Preserves `spot`, `spot_timestamp`, `atm_strike`, `atm_source`, `strike_step`, `strike_step_source`, `validation_status`. |

---

### 15.3 Strict Data Validation Rules (`NO_VALID_DATA`)

Option chain validation fails with `NO_VALID_DATA` if ANY of the following occur:
1. `spot_price` is missing, `None`, non-numeric, or $\le 0.0$.
2. `spot_timestamp` is missing or empty string.
3. `strikes` list is empty or `None`.
4. Contracts in chain have missing/invalid LTP (`None`, string `"N/A"`, or negative).
5. Contracts in chain have missing/invalid OI (`None` or negative).

---
*Master Calculation Specification — NSE Alpha-Sell Options Terminal & VCC V3.2.*
