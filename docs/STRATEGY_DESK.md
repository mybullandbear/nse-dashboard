# Entry/exit policy and strategy desk milestone

Stacked on the signal-quality PR. No production merge/deployment or live-order activation is included. New opening-range and pullback policies are **unvalidated shadow/paper-preview models**. The existing OI/Hull paper engine remains separate and now shares stronger service-boundary risk checks.

## Session and quantity

Normal NSE equity-derivatives session: 09:15–15:40 IST, confirmed against https://www.nseindia.com/static/market-data/market-timings on 2026-11-01. The close boundary is exclusive: 15:40 is closed for new entries. UTC inputs are converted to IST. Declared `EXCHANGE_HOLIDAYS` are respected; missing holiday verification is visible, not silently represented as a complete exchange calendar. Special trading sessions and an automated holiday feed are not implemented.

Configured units per lot are unchanged: NIFTY 65, BANKNIFTY 30, FINNIFTY 60, MIDCPNIFTY 120, SENSEX 20. Policy sizing imports canonical settings and permits zero lots when one lot exceeds the planned risk budget. It never invents fractional lots.

## Entry playbooks

Both use completed one-minute bars, 30 contiguous observations, same-day EMA 9/21, a 14-period exponentially smoothed true range, five-bar momentum of at least 0.5 ATR, directional five-bar OI flow and EMA separation of at least 0.25 ATR. Entry window: 09:45–14:45 IST. Buy CE for bullish setups; buy PE for bearish setups. These are long-premium rules, not tested short-option/margin strategies.

- Opening range: use the fully completed 09:15–09:30 high/low; require a close beyond a 0.1 ATR buffer, no extension beyond 1.5 ATR, and two consecutive confirming bars. Missing opening bars invalidate the range.
- Pullback: the preceding bar tests the fast EMA within a 0.2 ATR allowance; the next completed bar closes beyond the preceding high/low in the trend direction. This is a discrete trigger, not two repeated crossover labels.

Quotes, exchange timestamps, contract identity, expiry, bid/ask, spread and risk are distinct checks. The strategy desk may show a setup while still blocking execution. Historical date/time inspection is always non-executable. New policy execution is always disabled pending fresh forward validation.

## Exit policy

Default initial premium stop: 20%; gross premium target: 1.5R (30% move). Stop/target sensitivities include 15%/20% stops and 1.5R/2R targets. After a +1R observed move, trailing protection ratchets upward; it cannot loosen. Maximum hold: 30 minutes; independent force-exit cutoff: 15:35. Stops are evaluated against the previously known stop on a subsequent quote. No intraminute high/low or ideal stop fill is invented.

Unpriceable/nonfinite quotes or a gap over 90 seconds mark the research outcome unresolved. Unchanged premium/OI/volume for 180 seconds does the same. The portfolio simulation locks future entries, including later dates, until reconciliation. Unknown outcomes remain counted with premium at risk and a separate zero-recovery stress scenario; they are not assigned fictional exits.

## Runtime paper controls

Within the existing ShonyaBot placement lock, manual/AI/automated paper entry paths check normal session and a 15:35 new-entry cutoff; stop distance plus assumed 1% roundtrip price friction and ₹85 fixed cost; default 1% capital planned-risk budget; maximum two concurrent positions; three entries per symbol/day; a persisted ten-minute post-exit cooldown; UUID trade identifiers; and an entry lock when realized daily losses reach the default 2% threshold. Gaps can exceed the planned stop or loss threshold: these are admission controls, not a guarantee of maximum realized loss.

Stop edits must be finite/positive, preserve target ordering and cannot widen the existing stop. Existing indicator formulas/legacy paper entry selection are not represented as the new policies. Broker mutation remains blocked by earlier hardening work.

## Forward evidence

The central poller records versioned shadow observations for both new policies once per symbol/minute. Rows include the precise observation time, completed-bar timestamp, state, direction, policy parameters, numerical inputs, source, quality and an ATM quote/contract reference. Unsafe inputs are recorded as blocked. Recorder work runs in a thread and does not place orders or send notifications. Retention follows the existing database policy.

## UI and API

`/strategy` adds a desktop/mobile strategy desk, linked from the main terminal. It includes risk budgets, preserved lot sizes, family selection, date/time replay, candidate states, execution blockers, inspection dialogs and an exit playbook. Bullish/bearish colors have text labels. Current/future/stale-data states are explicit. Mobile tables retain the index column; keyboard focus is preserved during background refresh. The main five modules remain available.

`GET /api/strategy/workspace` requires terminal authentication and never connects to a broker, activates a model or writes an order. It reads stored completed bars and a fresh in-memory quote cache. Calculations execute in FastAPI's thread pool. HTTP failures retain stale-data warnings. Future replay and times outside 09:15–15:40 are rejected.

## Testing and research

The policy study command is:

```sh
PYTHONPATH=backend python scripts/evaluate_strategy_policies.py /absolute/path/to/copy.db --output /private/output
```

The SQLite input opens read-only and is hashed. First seven sessions are a development slice and the remaining three a later diagnostic slice. This database was already inspected in prior work: **no dates in this new study are claimed as a fresh independent holdout**. No winner is selected from later profits. Eight fixed policy variants plus capital/slippage sensitivities are evaluated, with shared position limits, realized-loss admission checks and unchanged lot sizes. Results are private; no database or trade ledger is committed.

Tests cover clock boundaries/holidays, UTC conversion, invalid policies, lot/risk sizing, prefix invariance, observed-quote exits, trailing-stop monotonicity, out-of-order snapshot insertion, completed-bar OHLC, authenticated preview, shared position/loss controls, stop-edit restrictions, non-trading shadow deduplication and UI behavior. Existing offline/network-denial tests remain active.

Browser pixel/layout QA remains blocked by the cloud browser's localhost bearer-token proxy. ASGI/API and pure-JavaScript UI behavior checks are not a substitute for a real mobile/device/browser test. Broker account/market-hours soak, complete holiday/special-session handling, executable contract metadata and an independent forward sample remain release gates. Single-worker support is unchanged.
