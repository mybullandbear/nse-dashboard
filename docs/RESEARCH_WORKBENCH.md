# Closed five-minute research workbench

Open `/research` after signing in. Choose an index, recorded session, IST cutoff,
indicator and exit parameters. Press **Load research**. Use the candle scrubber to
inspect evidence, the visible-window selector to zoom, and the option strike/side
controls to inspect historical premiums. **Compare recorded indices** applies the
loaded session and parameters to all configured indices. CSV export contains the
selected indicator's index research ledger.

## Shared calculation path

`research_workbench.closed_bars` anchors five-minute buckets at 09:15 IST,
excludes the active bucket and observations at/after the cutoff, and orders by
observation timestamp/id. The 09:15–15:40 derivatives session has **77** buckets.
OHLC is sampled from snapshots, not exchange-complete candle history. Missing
observed minutes are flagged. Native Hull, AlphaTrend, Shonya and OTT Python
implementations are reused unchanged; conservative warmup masks suppress immature
states. AlphaTrend uses RSI when underlying volume is unavailable. No index VWAP
or synthetic volume is invented. Indicators may warm from up to eight recorded
index sessions; historical options reset daily because expiry is unverified.

The strategy desk and forward shadow observations now use this same closed-bar
builder. Their EMA/OI family feature function accepts an explicit five-minute
interval; its original one-minute research default is retained for reproducibility.
The desk therefore requires 30 five-minute warmup bars, rather than silently treating
30 minutes as 30 five-minute bars. Forward decisions have a `-5m` version suffix.
Unsafe-data transitions can be recorded within a five-minute decision interval.
The legacy ShonyaBot OI/Hull selection remains separately labeled; it is not the
workbench policy and is not promoted to live execution by this change.

## Research execution assumptions

The selected native indicator's completed-bar directional state creates a pending
entry for the next observed candle open. Optional OI alignment requires matching
put-minus-call OI change. Entries stop at 15:00; open research positions close at
the completed 15:35 candle. Exits can use an ATR trailing stop, signal flip, or both.
A previously decided signal flip fills at next open before that candle's intrabar
range. A stop uses the previous ratchet, including the initial stop in the entry
candle; gaps through a stop use the opening price. Ratchets use only closed-candle
values and never widen. Missing buckets or incomplete observations make a position
unresolved and halt subsequent ledger entries. An intraday cutoff can leave a
position open, excluded from realized metrics.

Results are **gross index points**, not executable option P&L. Fees, slippage,
liquidity, option Greeks and expiry are not represented by those points. Win rate
is the observed fraction of positive closed research outcomes, not calibrated
signal accuracy. Index point values must not be compared as currency across indices.
Option charts expose actual recorded premiums but do not claim verified fills or
option returns. The supplied archive lacks historical expiry/bid/ask/fills.
No indicator is automatically promoted or called best from this exploratory table.

## Redundancy and compatibility audit

| Path | Change / status |
| --- | --- |
| Research chart, historical indicator comparisons | One read-only repository and closed-candle builder; bounded 16-response cache with copy isolation, five-second TTL and DB/WAL metadata invalidation |
| Strategy desk and new forward policies | Shared five-minute builder; distinct version, existing formulas preserved |
| Legacy option chart GET | Removed invented ATM prices, repeated chain fetching and tick recording; central poller owns ingestion; developing bars excluded from indicator/signal calculations |
| Main dashboard / confluence / option matrix | Existing calculation contracts retained; not silently replaced with research assumptions |
| Legacy option candle cache | Still separate from historical research for API compatibility; its broader expiry/warmup behavior needs a future contract-aware migration |
| Pine-to-Python parity | Existing implementations reused; exact TradingView parity still needs matching reference candles and exported Pine output |

## Validation

Tests cover cutoff boundaries, ordering, incomplete buckets, indicator prefix
invariance (no future-candle repaint), warmup, next-open entries, entry-bar stops,
flip precedence, unresolved gaps, read-only SQLite, cache isolation, authenticated
API validation, and real controller/SVG behavior in a DOM VM. The test process denies
outbound network/DNS and mocks notifications. VM checks do not verify browser pixels,
mobile touch behavior or device installation.

```
python -m pytest -q
python check_syntax.py
find backend/app/static/js -name '*.js' -print0 | xargs -0 -n1 node --check
PYTHONPATH=backend python scripts/benchmark_research.py --database /path/history.db --date 2026-10-14
```

The benchmark reads the supplied DB in SQLite read-only mode and prints only timing
and coverage. Raw private data is not committed. Live order mutations remain hard
disabled. No deployment is included.
