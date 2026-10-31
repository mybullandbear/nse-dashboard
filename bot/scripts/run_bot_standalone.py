"""
Standalone Runner Example
Demonstrates how to run SmartTrackerBot in any external Python script or project.
"""
import sys
import os

# Add parent directory to path so bot can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from bot import SmartTrackerBot, tracker_storage
from bot.engine.models import ParsedOptionChain, StrikeRow, StrikeContract


def run_demo():
    print("==================================================================")
    print("  INSTITUTIONAL SMART OPTIONS BOT - STANDALONE RUNNER DEMO")
    print("==================================================================")

    bot = SmartTrackerBot()
    print(f"Bot Active: {bot.is_bot_active()}")

    # 1. Warm up indicator candles with simulated NIFTY 1-minute ticks
    base_price = 25000.0
    for i in range(15):
        hour = 9 + (30 + i) // 60
        minute = (30 + i) % 60
        t_str = f"{hour:02d}:{minute:02d}"
        spot = base_price + (i * 12.0)  # Upward trending momentum
        bot.feed_candle_history("NIFTY", [{
            "time_str": t_str,
            "open": spot - 5,
            "high": spot + 10,
            "low": spot - 8,
            "close": spot
        }])

    tech = bot.get_technical_state("NIFTY")
    print("\n[PineScript Indicators Warmup]")
    print(f"  NIFTY OTT State : {tech.get('ott_state')}")
    print(f"  NIFTY ADX       : {tech.get('adx')}")
    print(f"  NIFTY +DI / -DI : {tech.get('plus_di')} / {tech.get('minus_di')}")

    # 2. Build mock ParsedOptionChain at current spot
    current_spot = 25180.0
    atm = 25200.0
    chain = ParsedOptionChain(
        symbol="NIFTY",
        spot_price=current_spot,
        atm_strike=atm,
        expiry="2026-10-01",
        pcr=1.25,
        pcr_atm_5=1.30,
        strikes=[
            StrikeRow(
                strikePrice=25200.0,
                CE=StrikeContract(strikePrice=25200.0, lastPrice=110.0, openInterest=120000, totalTradedVolume=80000),
                PE=StrikeContract(strikePrice=25200.0, lastPrice=95.0, openInterest=95000, totalTradedVolume=60000)
            ),
            StrikeRow(
                strikePrice=25150.0,
                CE=StrikeContract(strikePrice=25150.0, lastPrice=145.0, openInterest=110000, totalTradedVolume=75000),
                PE=StrikeContract(strikePrice=25150.0, lastPrice=70.0, openInterest=80000, totalTradedVolume=50000)
            )
        ]
    )

    # 3. Simulate high-conviction breakout signal (Buyer Regime)
    signal = {
        "active_regime": "BUYER_REGIME",
        "confluence_score": 76.5,
        "top_recommendation": {
            "role": "BUYER",
            "strategy": {
                "name": "NIFTY Momentum CE Breakout",
                "type": "MOMENTUM_BUY",
                "buy_strike": 25200.0,
                "option_type": "CE",
                "ltp": 110.0
            }
        }
    }

    print("\n[Processing Tick 1 - Persistence Test]")
    bot.process_tick("NIFTY", chain, signal)
    print("  Open trades after tick 1:", len(tracker_storage.get_open_trades()), "(Awaiting confirmation)")

    print("\n[Processing Tick 2 - Confirmation Test]")
    bot.process_tick("NIFTY", chain, signal)
    open_trades = tracker_storage.get_open_trades()
    print("  Open trades after tick 2:", len(open_trades))
    if open_trades:
        tr = open_trades[0]
        print(f"  --> Executed: {tr['symbol']} {tr['strategy_type']} | Entry: ₹{tr['entry_net_price']} | TQS: {tr['tqs_score']}")

    # 4. View dashboard summary
    summary = tracker_storage.get_category_pnl_summary()
    print("\n[Dashboard Summary]")
    print(f"  Active Positions: {summary.get('open_trades_count')}")
    print(f"  Realized Net P&L: Rs. {summary.get('total_net_realized_pnl_inr')}")
    print("  Note: Live entry gates enforce 09:30 - 15:25 IST market hours.")
    print("==================================================================")


if __name__ == "__main__":
    run_demo()
