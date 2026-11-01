# Signal-quality research and recording repairs

This branch is stacked on the terminal/PWA PR. No broker connection, live execution, merge or deployment is part of the work. User databases and trade-level results must not be committed to this public repository.

## Verified defects corrected

1. OI snapshots passed no confluence value, so database defaults silently recorded 50. New observations without an evaluated decision store NULL. The central poller computes the actual decision before recording it; signal evaluation appends a versioned `decision_audit` row and fills `signal_history`. Previous timestamps are never rewritten with later decisions.
2. Aggregate option volumes were omitted and recorded as zero. Recorder now passes observed aggregate contract volumes.
3. Strike persistence referenced an undefined `atm` and silently swallowed exceptions. ATM is defined and persistence failures are logged.
4. Straddle opening premium was fabricated as current premium times 1.10, forcing approximately 9.1% decay. The analyzer now uses an opening-window observation and the same strike through the session. Midday startup/missing reference returns unavailable. Premium change is not pure theta decay; no traded straddle VWAP is invented.
5. A changing ingestion timestamp was treated as fresh data even when economic fields were frozen. A causal payload-fingerprint gate marks unchanged spot/contract price/OI/volume/bid/ask data FROZEN after 180 seconds. Signal generation, tracker and automated ShonyaBot entries reject it. Legitimate unchanged markets can also trigger this conservative protection; OBSERVED is not a guarantee of exchange freshness.
6. Index fallback could still emit simulator data. That remaining automatic fallback has been removed. Broker execution remains disabled by the earlier modernization branch.
7. Future strike recording preserves available expiry, contract symbol, bid/ask, source and quality metadata. Existing historical rows are not enriched with invented metadata. Missing exchange timestamps remain unavailable.
8. Confluence confidence is explicitly labeled heuristic strength, not a calibrated probability. Index strike steps use canonical settings, including SENSEX/MIDCPNIFTY.

Decision audit rows currently use first-observation-per-minute sampling and do not claim to record every intraminute score change. Exactly one backend worker remains the supported deployment model.

## Offline research

```sh
python scripts/research_signals.py /absolute/path/to/copy.db --output /private/output-directory
```

The command opens SQLite with `mode=ro`. It records the input hash and runs `quick_check`, verifies table coverage, counts missing/uninformative fields, and produces private JSON and trade CSV files. Use at least ten sessions. Do not upload its database or outputs to this repository.

The fixed date split uses the first five sessions for training checks, the next two for validation and the remaining sessions for a final holdout. Candidate selection never reads holdout outcomes. The comparator is an EMA/momentum research rule, **not a reconstruction of the production confluence strategy or ShonyaBot**. If recorded confluence is constant or decisions are absent, their actual historical performance is unrecoverable.

Features use completed one-minute bars with a 30-bar warmup, same-day EMA/ATR/momentum and recent OI changes. Candidates vary persistence, momentum threshold and OI confirmation. Causal quality checks reject unchanged/missing observations. No machine-learning probability is claimed.

Entries select a contract from an earlier quote, then use the first strictly subsequent quote after the signal. Exits use subsequent sampled quotes, with 25% premium stop, 40% target, 20-minute maximum holding period and a 15:15 cutoff. They do not fill ideal stop/target prices or infer intraminute high/low touches. There is a ten-minute cooldown, at most three accepted trades per symbol/day, a 30k per-entry debit ceiling and a conservative 100k shared premium-capital filter.

Reference costs are assumptions: one lot using repository-configured sizes, ₹85 roundtrip fee and 0%, 0.25%, 0.5% or 1% slippage per side. They are not verified historical broker charges or contract-master data. Portfolio capital rejection is a conservative post-filter and does not re-simulate replacement signals. Drawdown is measured on closed-trade equity, not mark-to-market equity.

Expiry, bid/ask, exchange timestamps and fills absent from an uploaded database cannot be recovered. Unpriceable outcomes are counted and excluded, which can bias research. Correlated indices are not independent trials; a short sample cannot establish durable profitability. No candidate is automatically enabled, even if sample results look attractive.

## Validation

Synthetic tests cover prefix invariance, no future contract selection, frozen-input rejection/recovery, observed same-strike straddle references, no invented opening/VWAP, actual decision persistence, unchanged earlier snapshots, correct ATM strike writes, observed volume and nullable metadata. Existing tests remain required. Four legacy research modules still require external datasets/models not included in the repository.
