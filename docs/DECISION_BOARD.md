# One-screen desktop decision board

The Dashboard tab at `/` now shows all five configured indices in one table.
No pair switch is required. Each row includes:

- configured lot size and last completed five-minute candle time;
- index price (fresh cached quote when available, otherwise the closed-bar price) and change from the session's first recorded sample;
- call OI, put OI, five-minute put-minus-call OI change, net put-minus-call OI and PCR;
- Hull/AlphaTrend/Shonya/OTT directional agreement;
- completed 09:15–09:30 opening range and breakout location;
- contextual CE WATCH / PE WATCH / WAIT, separate from current data readiness;
- six session sparklines: price, call OI, put OI, OI flow, PCR and indicator alignment.

Select any index to inspect native indicator states, ATR, opening range, data and
execution blockers, and the available cached contract quote. A fresh bid/ask can
produce a **paper risk illustration** using the existing policy stop/target and
canonical lot sizing. It is not an order or a strategy activation. Current account
capital, available capital and open-position count are displayed above the table.
Full historical charts and risk rules remain one click away.

Desktop uses a compact table and a shallow evidence strip. The previous duplicate
alignment matrix is not mounted on Dashboard, its polling is suppressed there,
and pair-specific chain/OI/signal initial requests are skipped on this tab. Other
modules remain available. Mobile uses labeled cards with the same evidence and
native touch controls. The layout targets ordinary 1366×768 and larger desktop
viewports; browser zoom, OS scaling and actual device layouts still need visual QA.

## Signal and freshness semantics

The watchlist rule is explicit and **unvalidated**: at least three ready native
indicators agree, and the latest observed five-minute put-minus-call OI change
matches that direction. Native formulas are unchanged. This is contextual signal
alignment, not a probability of profit or a replacement for legacy confluence
formulas in other modules. OI positioning alone does not establish writing,
buying, future direction or executable liquidity.

Sparklines use completed five-minute data, independent vertical scales and visible
gaps; missing OI intervals do not become five-minute changes. Missing data remains
unavailable, including SENSEX when the archive has no SENSEX observations.

Native signals and sparklines always use closed bars. When a fresh current quote is displayed, the prior five-minute close is labeled beneath it.

The default view selects today's recorded session when available, otherwise the
latest stored session, visibly marked **REPLAY**. Explicit date/time selection is
also replay; live refresh pauses. Cutoffs round down to completed five-minute
boundaries. Live-source/quote-age gates recalculate on every response independently
of cached candle features. Failed refreshes immediately replace action guidance
with NO TRADE / STALE; a 25-second browser watchdog also blocks unattended live
snapshots. Data source, exchange time, expiry, spread, holidays and unvalidated
strategy blockers remain inspectable. Live order mutations remain disabled.

## Local testing — Windows PowerShell

Use the new branch, which includes the earlier stacked modernization changes:

```powershell
git clone --branch improvement/one-screen-dashboard-20261101 https://github.com/mybullandbear/nse-dashboard.git
cd nse-dashboard
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.lock -r backend/requirements-test.txt
$env:TERMINAL_PASSWORD = Read-Host 'Choose a local terminal password (16+ characters)'
$env:COOKIE_SECURE = 'false'
$env:PYTHONPATH = 'backend'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000/`, sign in with that password, then choose **Dashboard**.
For historical testing, stop the server and set `DATABASE_PATH` to the absolute
path of a **copy** of your snapshot database, then restart. Preserve the original:
normal application ingestion/retention can modify a database even though the new
board endpoint is read-only. No broker credentials are needed for replay.

Keep `COOKIE_SECURE=true` for HTTPS deployments; the local override above is only
for HTTP localhost. Do not add credentials or private DB files to Git.

## Verification and limitations

Automated checks exercise all-index coverage, native indicator warmup, source and
missing-quote blockers, replay cutoff validation, missing-interval OI handling,
immutable cache results, authenticated API access, actual DOM/SVG controller
behavior, index inspection, replay selection, stale refreshes and timer cleanup.
Other-tab OI fetching is regression tested. The suite denies outbound network/DNS
and mocks notifications. Native formula and broader API regressions remain covered.

The uploaded archive was read in SQLite read-only mode and its checksum remained
unchanged. A five-index board on that archive measured about 2 seconds cold and
16 ms cached locally; this is not a production SLA. No raw user data is committed.

Browser visual verification is blocked in this environment: the browser cannot
connect to the executor's localhost preview. DOM VM tests do not substitute for
pixel/mobile-device QA. Pine-reference parity, broker/market-hours soak, verified
expiry/bid/ask/fills for historical option P&L and independent forward validation
remain outstanding. No deployment or merge into main is performed.
