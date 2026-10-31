# Release gates for MYBULLANDBEAR

This repository handles trading-related market data and potentially broker execution.
A passing syntax check **does not** mean the application is production ready.

## Gate 0 — Secrets and access
- Revoke any tokens disclosed in chat, committed to Git, or otherwise exposed.
- Audit complete Git history and rotate compromised broker/API/session credentials.
- Never commit .env files, credentials, or private keys.
- Require HTTPS, secure cookies, session expiration and CSRF protection for state-changing requests.
- Verify WebSocket authentication and webhook secret enforcement.

## Gate 1 — Data correctness
- Timestamp each observation with exchange and ingestion times and a data-source identifier.
- Reject stale, incomplete or simulated data from live execution.
- Resolve contracts, lot sizes and expiry metadata from a validated current instrument master.
- Add regression fixtures for existing confluence and ShonyaBot calculations.

## Gate 2 — Research validity
- Eliminate look-ahead bias; include spreads, slippage, fees and margin assumptions.
- Run walk-forward and out-of-sample testing with recorded reproducible parameters.
- Clearly separate hypothetical backtests from live realized performance.

## Gate 3 — Broker execution
- Default LIVE_TRADING_ENABLED to false.
- Require explicit pre-trade risk authorization, position limits and maximum daily loss.
- Ensure idempotent order intents, reconcile fills and rejected/partial orders.
- Test disconnects, duplicate events, and emergency stop in paper mode.

## Gate 4 — Deployment
- Run unit, integration, browser and performance tests in staging.
- Validate production reverse proxy, rate limits, alerts, backups and rollback.
- Deploy only after manual approval and monitor the first release.

## Engineering principles
- Preserve existing strategy formulas unless tests demonstrate a defect.
- Keep AI advisory; deterministic code must enforce execution permissions.
- Prefer small reviewed pull requests over replacing the production branch.
