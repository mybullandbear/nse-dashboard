# Institutional Smart Options Trading Bot Package

A production-grade, self-contained **Options Trading & Signal Execution Engine** designed specifically for Indian index options (`NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`).

This package contains everything required to deploy the bot into **any external project**, run paper trading, connect to live broker APIs (Zerodha Kite, Fyers, Dhan, Angel One), or run multi-day backtest simulations.

---

## 📁 Package Directory Structure

```text
bot/
├── README.md                      # Complete Integration & Developer Manual (this file)
├── __init__.py                    # High-level package exports
├── engine/
│   ├── __init__.py
│   ├── tracker_bot.py             # Core trading engine (TQS, OTT/ADX filters, trailing stops, concurrency)
│   ├── technical_indicators.py    # Pure Python PineScript OTT (Chande VAR), ADX, DMI, Wilder RMA, RSI
│   ├── greeks.py                  # Pure Python Black-Scholes Delta, Theta, Gamma, Vega calculator
│   ├── market_hours.py            # IST timezone utilities & NSE market timing rules (09:15 - 15:40 IST)
│   └── models.py                  # Pydantic data schemas (ParsedOptionChain, StrikeRow, TradeSignal)
├── storage/
│   ├── __init__.py
│   └── tracker_storage.py         # Thread-safe SQLite persistence (Trades, MFE/MAE, Circuit Breaker, Learning)
├── api/
│   ├── __init__.py
│   └── tracker_api.py             # FastAPI REST router (/dashboard, /history, /toggle, /squareoff)
├── ui/
│   ├── trade_tracker.js           # Modern Vanilla JS dashboard component (Real-time MTM, Badges, Journal)
│   └── trade_tracker.css          # Sleek high-contrast dark theme stylesheet
├── scripts/
│   ├── run_bot_standalone.py      # Standalone runner demonstrating tick processing and signal execution
│   └── backtest_simulation.py     # Multi-day historical backtesting and parameter tuning harness
└── docs/
    └── bot.md                     # Quantitative formulas, PineScript logic & 4-day backtest audit report
```

---

## ⚡ Key Features & Edge

1. **Prioritization of Option Buying with PineScript Filters**:
   - **OTT (Optimized Trend Tracker)**: Enforces directional alignment before buying (Call buys only permitted in Bullish OTT channel; Put buys only permitted in Bearish OTT channel).
   - **ADX Trend Velocity Gate**: Blocks all option buying when $\text{ADX} < 18.0$, eliminating capital loss during low-volatility theta drag.
2. **Institutional Strike Selection**:
   - Strictly selects **ATM** or **1-step ITM** contracts ($\Delta \approx 0.48 - 0.58$) for Option Buying.
   - Rejects low-premium junk contracts (NIFTY < ₹45, BANKNIFTY < ₹75, FINNIFTY < ₹40, MIDCPNIFTY < ₹25).
3. **5-Pillar Trade Quality Score (TQS: 0 to 100 Points)**:
   - Evaluates Signal Confluence, Strike Delta, Liquidity/Spread, Momentum Alignment, and Risk/Reward before firing.
4. **Fast 3-Stage Dynamic Breakeven Ladder**:
   - $\ge +20\%$ gain $\implies$ Trail SL immediately to Entry Price (**Zero-Risk Breakeven Lock**).
   - $\ge +35\%$ gain $\implies$ Lock in $+15\%$ profit minimum.
   - $\ge +60\%$ gain $\implies$ Lock in $+35\%$ profit.
5. **Strict Concurrency & Risk Limits**:
   - **1 trade per symbol simultaneously** (up to 4 concurrent trades across NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY).
   - Daily loss circuit breaker at **-₹3,500**.
   - Mandatory cooldown after consecutive losses.
   - Unconditional EOD market squareoff at **15:35:00 IST**.
6. **Realistic Accounting**:
   - Deducts **flat ₹100/lot round-trip brokerage** (₹50 entry + ₹50 exit) from every single trade.

---

## 🚀 How to Use in Another Project

### 1. Installation & Requirements
The engine is written in **pure standard Python 3.8+**. It requires only `pydantic` for schema validation and `fastapi` if using the REST API:

```bash
pip install pydantic fastapi uvicorn
```

*(No heavy NumPy, Pandas, or PyTorch dependencies required; all mathematics are pure Python standard library).*

---

### 2. Standalone Python Usage (Direct Script Integration)

Copy the `bot/` folder into your new project. You can now instantiate and run the bot directly:

```python
from bot import SmartTrackerBot, tracker_storage
from bot.engine.models import ParsedOptionChain, StrikeRow, StrikeContract

# 1. Initialize Bot
bot = SmartTrackerBot()

# 2. Warm up PineScript candles with live spot prices
bot.feed_candle_history("NIFTY", [
    {"time_str": "09:30", "open": 25100, "high": 25120, "low": 25095, "close": 25115},
    {"time_str": "09:31", "open": 25115, "high": 25140, "low": 25110, "close": 25135},
    # ... feed at least 5-10 bars
])

# 3. Create Option Chain object from your broker data
chain = ParsedOptionChain(
    symbol="NIFTY",
    spot_price=25150.0,
    atm_strike=25150.0,
    pcr=1.25,
    strikes=[
        StrikeRow(
            strikePrice=25150.0,
            CE=StrikeContract(strikePrice=25150.0, lastPrice=115.0, openInterest=150000, totalTradedVolume=90000),
            PE=StrikeContract(strikePrice=25150.0, lastPrice=80.0, openInterest=80000, totalTradedVolume=40000)
        )
    ]
)

# 4. Formulate signal decision (from your custom strategy or indicator)
signal = {
    "active_regime": "BUYER_REGIME",
    "confluence_score": 75.0,
    "top_recommendation": {
        "role": "BUYER",
        "strategy": {
            "name": "NIFTY Momentum CE Breakout",
            "type": "MOMENTUM_BUY",
            "buy_strike": 25150.0,
            "option_type": "CE",
            "ltp": 115.0
        }
    }
}

# 5. Process Tick (evaluates persistence, TQS score, OTT/ADX gating, and exits)
bot.process_tick("NIFTY", chain, signal)

# 6. Check Active Trades & Performance
open_positions = tracker_storage.get_open_trades()
summary = tracker_storage.get_category_pnl_summary()

print("Active Trades:", len(open_positions))
print(f"Net Realized P&L: ₹{summary['total_net_realized_pnl_inr']}")
```

---

### 3. FastAPI REST Service Integration

If your project uses FastAPI, mount the bot's REST router in one line:

```python
from fastapi import FastAPI
from bot.api import tracker_router

app = FastAPI(title="My Trading System")

# Mount the Bot API endpoints
app.include_router(tracker_router)

# Available Endpoints:
# GET  /api/tracker/dashboard    -> Real-time positions, category P&L, indicator states
# GET  /api/tracker/history      -> Closed trade journal with MFE/MAE
# POST /api/tracker/toggle       -> Pause or resume trading bot
# POST /api/tracker/squareoff/{id} -> Manual squareoff for a specific trade
# POST /api/tracker/squareoff_all  -> Emergency squareoff all active positions
```

---

### 4. Frontend UI Dashboard Integration

To display the bot's live marked-to-market performance, active trades, PineScript badges, and trade journal in your web frontend:

1. Include `bot/ui/trade_tracker.css` in your HTML:
```html
<link rel="stylesheet" href="/static/css/trade_tracker.css">
```

2. Render the tracker component inside any container `<div>`:
```html
<div id="bot-dashboard-container"></div>

<script type="module">
  import { renderTradeTracker } from '/static/js/trade_tracker.js';

  const container = document.getElementById('bot-dashboard-container');
  renderTradeTracker(container);

  // Auto-refresh every 3 seconds
  setInterval(() => renderTradeTracker(container), 3000);
</script>
```

---

### 5. Connecting to Real Brokers (Fyers / Zerodha / Dhan)

To transition from paper trading to live execution:
1. In `bot/engine/tracker_bot.py`, locate the order placement triggers:
   - Line ~763 for Buyer Entry: `tid = self.storage.insert_trade(trade_payload)`
   - Line ~853 for Seller Entry: `tid = self.storage.insert_trade(trade_payload)`
   - Line ~584 for Exit: `self._execute_close(...)`
2. Simply call your broker's order placement SDK (e.g., `kite.place_order(...)` or `fyers.place_order(...)`) right before or after recording the trade in `storage`.

---

## 📊 Backtest Verification & Simulation

To test the bot against historical multi-day market data:

```bash
python bot/scripts/backtest_simulation.py
```

This will run the simulation across all recorded tick snapshots and output detailed trade-by-trade analytics, MFE/MAE excursions, and Gross vs Net P&L.

---

## 🛠️ Configuration & Customization Parameters

You can customize parameters directly when instantiating `SmartTrackerBot`:

```python
bot = SmartTrackerBot(
    strike_steps={"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25},
    lot_sizes={"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}
)
```

Adaptive thresholds can be modified at runtime via `tracker_storage.save_learning_params(...)`:
- `buyer_min_tqs`: Minimum TQS to enter a Buyer trade (Default: `70.0`).
- `seller_min_tqs`: Minimum TQS to enter a Seller trade (Default: `66.0`).
- `daily_loss_limit_inr`: Daily circuit breaker in ₹ (Default: `3500.0`).
- `cooldown_minutes`: Post-consecutive-loss cooldown window (Default: `45` mins).
