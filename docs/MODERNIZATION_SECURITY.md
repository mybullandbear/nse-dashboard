# Security and backend modernization — 2026-11-01

Base reviewed: main at 9a433b06199d99c211b02032ba867cf02a558a20. Existing draft PR #1 is a standalone portable syntax checker; it is preserved.

## Implemented

- Replaced the always-true access check and public-review browser bypass with a functioning password gate. Server-side random, hashed, expiring, revocable sessions; HttpOnly SameSite cookies; bounded login attempts; no password/token in browser storage or login JSON.
- Removed localhost, matrix, broker, architecture and diagnostic authentication exemptions. Origin checks cover writes; WebSocket handshake checks session and Origin. Production documentation disabled; CORS uses explicit configured origins.
- Webhook requires a configured secret and rejects absent/incorrect secrets. OAuth requires a browser nonce, rejects replay and arbitrary login redirect overrides, and avoids raw broker authorization errors in HTML/logs.
- Removed committed broker defaults from current runtime and copied archive/document references. Historical credentials remain in Git history and must be revoked/rotated at the broker; no history rewrite was performed.
- Live mode is rejected. Bot restarts paused in PAPER even if its database persisted LIVE. Broker mutation methods return an error; the new HTTP transport implements no order methods. These are deliberate safety changes, not trading-formula changes.
- Replaced required Fyers SDK REST dependency with a read-only v3 adapter, matching SDK 3.2.1 request formats, fixed HTTPS endpoints, connection/read timeouts, and no automatic redirects. This removes obsolete exact dependency pins. Broker socket streaming remains disabled; browser WebSockets remain supported.
- Credential persistence uses an atomic replacement and owner-only temporary file permissions. Runtime compatibility imports reuse canonical config and broker instances.
- Prevented slow/dead WebSocket clients from serially blocking healthy clients. Broadcast serializes once, snapshots the client set and uses bounded concurrent sends. Browser reconnect adds exponential backoff and jitter; unauthorized sockets wait for unlock.
- Shared bounded normalization cache reuses PCR/Max Pain work across API consumers, isolates mutable copies, and invalidates on payload/config changes. Existing indicator formulas are unchanged. Regression fixture generated from the reviewed base revision covers EMA/RMA/RSI/ADX/OTT/Hull/VWAP/Bollinger/Supertrend.
- Corrected coordinator ATM rounding to use configured index steps (including MIDCPNIFTY). Removed silent simulator fallback and propagated stale/closed provenance. Poller avoids trade and tick updates for stale/closed inputs; tracker rejects synthetic/stale input before processing.
- Paper placement serializes duplicate/capital checks within a process, validates finite prices/contracts/lots/stop-target ordering, checks capital at the resolved quote, rejects invented fallback fills, and preserves trades on restart.
- Shutdown awaits poller cancellation. Client HTTP requests have bounded timeouts. CI covers tests, syntax, dependency audit and offline benchmark artifacts; it contains no deployment job.

## Supported setup

Use Python 3.12 and a fresh environment:

```sh
python -m pip install -r backend/requirements.lock
# Copy backend/.env.example to backend/.env and configure server-owned values.
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Set a unique TERMINAL_PASSWORD of at least 16 characters. COOKIE_SECURE=true requires HTTPS; false is for isolated HTTP development. Add only required trusted ALLOWED_ORIGINS as a JSON list. Do not install the obsolete fyers-apiv3 SDK alongside this dependency lock. No broker credentials are included. Bind behind a trusted reverse proxy and use TLS for any nonlocal access.

Sessions, rate limits, normalized caches and trade locks are process local. Exactly one worker is supported in this milestone. Restart revokes sessions. Horizontal deployment needs a shared session/cache/risk store and distributed locks before use.

## Verification and limits

Local checks: full supported pytest collection passes; four research modules are explicitly skipped when the external `traning dataset` directory is missing. They previously failed collection/assertions because required models, comparison tables and training scripts are absent from this repository. They are not claimed as passing. A bot test's hardcoded ₹30,000 expectation was corrected to derive the configured capital ceiling; a synthetic-data rejection was moved ahead of market-hours gating.

`docs/dependency-audit.json` is pip-audit output for the complete pinned production graph, not the unrelated packages preinstalled on the execution host. It reports no known vulnerabilities at this run; this is not a guarantee against undisclosed vulnerabilities. `docs/modernization-benchmark.json` contains offline microbenchmarks, not broker/network/production latency. No credentialed broker, exchange-session, external webhook delivery or live order validation was performed.

Open release gates: real mobile/browser visual QA; market-hours soak with real read-only quotes; broker OAuth/read-only adapter validation in the user's account; confirmation of broker contract-master lot sizes/expiry metadata; external ML artifacts if those research suites are required. The repo has multiple legacy/archive implementations; the supported entrypoint is backend/app/main.py, not the archived upload package. Some older feature endpoints still compute their own derived state; the shared normalized cache does not claim a full replacement of all existing pipelines. Account-wide loss limits, cross-process execution guarantees and real fill/slippage validation remain prerequisites for any future live build.

Production deployment is not authorized and was not performed. Do not enable live trading from this branch.
