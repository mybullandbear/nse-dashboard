/**
 * Interactive Option Candlestick Chart with PineScript OTT & ADX Overlays
 * ═══════════════════════════════════════════════════════════════════════════
 * ZERO-FLICKER ARCHITECTURE (TradingView Lightweight Charts Engine):
 *
 * 1. Chart canvas created ONCE, reused forever — never recreated on poll.
 * 2. Incremental update: only the LAST candle calls `update()`,
 *    historical bars use `setData()` only when the bar-count changes.
 * 3. Data fingerprint comparison — identical API responses are SKIPPED entirely.
 * 4. Scroll & zoom position PRESERVED across polls — never auto-fits.
 * 5. Chart instances properly destroyed only on symbol/strike/type change.
 * 6. Status banner, strike pills, and badges are surgically patched in-place.
 */
import { ApiClient } from '../api.js';
import { renderAtmSignalsTable } from './atm_signals_table.js';

/* ─── Module State ─────────────────────────────────────────────────────────── */
let selectedSymbol     = 'NIFTY';
let selectedOptionType = 'CE';
let selectedStrike     = null;
let chartPollTimer     = null;
let cachedActiveStrikes = [];
let cachedChartData    = null;
let _strikesFingerprint = '';

/* Chart engine state */
let _chartContractKey   = '';        // "NIFTY|23200|CE" — used to detect symbol/strike changes
let _dataFingerprint    = '';        // hash of candle timestamps+closes to skip identical polls
let _lastCandleCount    = 0;         // track bar count for incremental vs full update
let _initialFitDone     = false;     // only fitContent() on first data load

/* Lightweight Charts instances */
let optionChartInstance  = null;
let optionCandleSeries   = null;
let optionOttSeries      = null;
let optionMavgSeries     = null;

let adxChartInstance     = null;
let adxSeriesLine        = null;
let pdiSeriesLine        = null;
let mdiSeriesLine        = null;

/* Resize handler reference for cleanup */
let _resizeHandler       = null;

/* ─── Time Parsing ─────────────────────────────────────────────────────────── */
function parseTvTime(timeStr) {
  if (!timeStr) return 0;
  if (typeof timeStr === 'number') return timeStr;
  if (timeStr.includes('-')) {
    const d = new Date(timeStr.replace(' ', 'T'));
    return isNaN(d.getTime()) ? 0 : Math.floor(d.getTime() / 1000);
  }
  const parts = timeStr.split(':').map(Number);
  if (parts.length >= 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
    const d = new Date();
    d.setHours(parts[0], parts[1], parts[2] || 0, 0);
    return Math.floor(d.getTime() / 1000);
  }
  return 0;
}

/* ─── Data Fingerprinting ──────────────────────────────────────────────────── */
function _computeFingerprint(chartRes) {
  const candles = chartRes?.candles;
  if (!candles || candles.length === 0) return '';
  const last = candles[candles.length - 1];
  // Fingerprint = count + last candle's OHLC + last indicator values
  const inds = chartRes.indicators || {};
  const ottLast = (inds.ott || [])[candles.length - 1] || 0;
  const adxLast = (inds.adx || [])[candles.length - 1] || 0;
  return `${candles.length}|${last.time}|${last.open}|${last.high}|${last.low}|${last.close}|${ottLast}|${adxLast}`;
}

/* ─── Deduplicate & Sort ───────────────────────────────────────────────────── */
function _dedup(arr) {
  const seen = new Set();
  const out = [];
  for (const item of arr) {
    if (!seen.has(item.time) && item.time > 0) {
      seen.add(item.time);
      out.push(item);
    }
  }
  return out.sort((a, b) => a.time - b.time);
}

/* ─── Destroy Charts Cleanly ───────────────────────────────────────────────── */
function _destroyCharts() {
  if (_resizeHandler) {
    window.removeEventListener('resize', _resizeHandler);
    _resizeHandler = null;
  }
  if (optionChartInstance) {
    try { optionChartInstance.remove(); } catch (_) {}
    optionChartInstance = null;
    optionCandleSeries = null;
    optionOttSeries = null;
    optionMavgSeries = null;
  }
  if (adxChartInstance) {
    try { adxChartInstance.remove(); } catch (_) {}
    adxChartInstance = null;
    adxSeriesLine = null;
    pdiSeriesLine = null;
    mdiSeriesLine = null;
  }
  _lastCandleCount = 0;
  _lastAdxCount = 0;
  _dataFingerprint = '';
  _initialFitDone = false;
  _adxInitialFit = false;
}

/* ─── Event listener for deep-linking from ATM signals ─────────────────────── */
window.addEventListener('open-option-chart', (e) => {
  if (e.detail) {
    if (e.detail.symbol)     selectedSymbol     = e.detail.symbol;
    if (e.detail.optionType) selectedOptionType = e.detail.optionType;
    if (e.detail.strike)     selectedStrike     = e.detail.strike;
  }
});

/* =========================================================================
   ENTRY POINT — called once when the tab activates
   Writes the static skeleton then starts the poll loop.
========================================================================= */
export async function renderOptionChart(container) {
  if (chartPollTimer) { clearInterval(chartPollTimer); chartPollTimer = null; }
  _strikesFingerprint = '';
  _destroyCharts();
  _chartContractKey = '';

  const symBtns = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'].map(sym => {
    const cls = sym === selectedSymbol ? 'active' : '';
    return `<button class="opt-sym-btn ${cls}" data-sym="${sym}" `
         + `style="padding:5px 12px;font-size:11px;font-weight:700;border:none;border-radius:4px;cursor:pointer;">`
         + `${sym}</button>`;
  }).join('');
  const ceCls = selectedOptionType === 'CE' ? 'active-ce' : '';
  const peCls = selectedOptionType === 'PE' ? 'active-pe' : '';

  container.innerHTML = [
    '<div class="option-chart-container" style="padding:16px;">',

    // ── Controls topbar ────────────────────────────────────────────────────
    '<div class="glass-panel" style="padding:14px;margin-bottom:16px;border:1px solid rgba(56,189,248,0.25);">',
    '<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;">',

    '<div style="display:flex;align-items:center;gap:6px;">',
    '<span style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Index:</span>',
    '<div style="display:flex;gap:4px;background:rgba(0,0,0,0.4);padding:3px;border-radius:6px;">',
    symBtns,
    '</div></div>',

    '<div style="display:flex;align-items:center;gap:6px;">',
    '<span style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Option:</span>',
    '<div style="display:flex;gap:4px;background:rgba(0,0,0,0.4);padding:3px;border-radius:6px;">',
    `<button class="opt-type-btn ${ceCls}" data-type="CE" style="padding:5px 14px;font-size:11px;font-weight:800;border:none;border-radius:4px;cursor:pointer;">CALLS (CE)</button>`,
    `<button class="opt-type-btn ${peCls}" data-type="PE" style="padding:5px 14px;font-size:11px;font-weight:800;border:none;border-radius:4px;cursor:pointer;">PUTS (PE)</button>`,
    '</div></div>',

    '<div style="display:flex;align-items:center;gap:8px;">',
    '<span class="badge-active" style="font-size:11px;padding:4px 10px;border-radius:6px;">\u23f1 5-MIN CANDLES (PINESCRIPT OTT)</span>',
    '<span id="chart-live-dot" class="status-pulse pulse-green" title="Auto-refreshing every 3s"></span>',
    '</div>',
    '</div>',

    // Strike pills
    '<div style="margin-top:12px;border-top:1px solid rgba(255,255,255,0.06);padding-top:10px;">',
    '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;" id="active-strikes-mount">',
    '<span style="font-size:11px;color:var(--text-muted);">Loading ATM \u00b1 2 strikes...</span>',
    '</div></div>',
    '</div>',

    // ── Status banner ────────────────────────────────────────────────────
    '<div id="contract-status-banner-mount" style="margin-bottom:14px;"></div>',

    // ── Candlestick chart ──────────────────────────────────────────────────
    '<div class="glass-panel" style="padding:16px;margin-bottom:14px;">',
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">',
    '<div style="display:flex;align-items:center;gap:8px;">',
    '<span style="font-size:18px;">\ud83d\udd6f\ufe0f</span>',
    '<strong id="chart-contract-title" style="font-size:14px;color:#f8fafc;">Option Chart</strong>',
    '<span id="chart-trigger-badge"></span>',
    '</div>',
    '<div style="display:flex;align-items:center;gap:14px;font-size:11px;">',
    '<span style="display:flex;align-items:center;gap:4px;color:#06b6d4;"><span style="display:inline-block;width:14px;height:3px;background:#06b6d4;"></span> OTT Line</span>',
    '<span style="display:flex;align-items:center;gap:4px;color:#eab308;"><span style="display:inline-block;width:14px;height:3px;background:#eab308;"></span> MAVG Line</span>',
    '<span style="display:flex;align-items:center;gap:4px;color:#10b981;">\u25b2 Buy Marker</span>',
    '<span style="display:flex;align-items:center;gap:4px;color:#ef4444;">\u25bc Exit Marker</span>',
    '</div></div>',
    '<div id="candlestick-tv-mount" style="width:100%;height:420px;position:relative;background:rgba(5,10,20,0.6);border-radius:8px;border:1px solid rgba(255,255,255,0.05);overflow:hidden;">',
    '</div>',
    '</div>',

    // ── ADX sub-panel ──────────────────────────────────────────────────────
    '<div class="glass-panel" style="padding:14px;">',
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">',
    '<div style="font-size:12px;font-weight:700;color:#cbd5e1;">\u26a1 OPTION PREMIUM ADX &amp; DMI MOMENTUM (5-MIN)</div>',
    '<div style="display:flex;align-items:center;gap:12px;font-size:10.5px;">',
    '<span style="color:#a855f7;">\u25cf ADX (Speed)</span>',
    '<span style="color:#10b981;">\u25cf +DI (Call Momentum)</span>',
    '<span style="color:#ef4444;">\u25cf -DI (Put Momentum)</span>',
    '<span style="color:var(--text-muted);">--- 18 Trend Floor | --- 25 High Momentum</span>',
    '</div></div>',
    '<div id="adx-tv-mount" style="width:100%;height:150px;background:rgba(5,10,20,0.6);border-radius:8px;border:1px solid rgba(255,255,255,0.05);overflow:hidden;"></div>',
    '</div>',

    // ── ATM signals table ────────────────────────────────────────────────
    '<div id="option-chart-atm-signals-mount" style="margin-top:20px;"></div>',
    '</div>',
  ].join('');

  const signalsMount = container.querySelector('#option-chart-atm-signals-mount');
  if (signalsMount) renderAtmSignalsTable(signalsMount);

  _attachControlsListeners(container);

  // First data load
  await _loadAndRenderChart(container);

  // Poll — 3 second cadence, but with fingerprint guard so identical data is free
  chartPollTimer = setInterval(async () => {
    if (!document.body.contains(container)) {
      clearInterval(chartPollTimer); chartPollTimer = null;
      _destroyCharts();
      return;
    }
    await _loadAndRenderChart(container);
  }, 3000);
}

/* =========================================================================
   CONTROL LISTENERS
========================================================================= */
function _attachControlsListeners(container) {
  container.querySelectorAll('.opt-sym-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const sym = btn.getAttribute('data-sym');
      if (sym && sym !== selectedSymbol) {
        selectedSymbol = sym; selectedStrike = null; _strikesFingerprint = '';
        _destroyCharts(); _chartContractKey = '';
        container.querySelectorAll('.opt-sym-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        await _loadAndRenderChart(container);
      }
    });
  });
  container.querySelectorAll('.opt-type-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const otype = btn.getAttribute('data-type');
      if (otype && otype !== selectedOptionType) {
        selectedOptionType = otype; _strikesFingerprint = '';
        _destroyCharts(); _chartContractKey = '';
        container.querySelectorAll('.opt-type-btn').forEach(b => b.classList.remove('active-ce', 'active-pe'));
        btn.classList.add(otype === 'CE' ? 'active-ce' : 'active-pe');
        await _loadAndRenderChart(container);
      }
    });
  });
}

/* =========================================================================
   DATA FETCH → PATCH DYNAMIC REGIONS
   The fingerprint guard ensures that if data hasn't changed, the chart
   is never touched — zero work, zero flicker, zero reflow.
========================================================================= */
let _isFetching = false;

async function _loadAndRenderChart(container) {
  if (_isFetching) return;  // debounce overlapping fetches
  _isFetching = true;
  try {
    const strikesRes = await ApiClient.fetchActiveOptionStrikes(selectedSymbol);
    if (strikesRes && strikesRes.active_contracts) {
      cachedActiveStrikes = strikesRes.active_contracts;
      if (!selectedStrike && strikesRes.atm_strike) selectedStrike = strikesRes.atm_strike;
      _updateStrikePills(container, strikesRes);
    }
    const chartRes = await ApiClient.fetchOptionChart(selectedSymbol, selectedStrike, selectedOptionType);
    if (chartRes) {
      // Check if contract changed — if so, destroy and rebuild charts
      const contractKey = `${chartRes.symbol}|${chartRes.strike}|${chartRes.option_type}`;
      if (contractKey !== _chartContractKey) {
        _destroyCharts();
        _chartContractKey = contractKey;
      }

      cachedChartData = chartRes;
      _patchStatusBanner(container, chartRes);

      // Check fingerprint — update chart if data changed OR chart instance is not yet mounted
      const fp = _computeFingerprint(chartRes);
      const dataChanged = fp !== _dataFingerprint || !optionChartInstance;

      if (dataChanged) {
        _updateCandlestickChart(container, chartRes);
        _updateAdxChart(container, chartRes);
        _dataFingerprint = fp;
      }
    }
  } catch (err) {
    console.warn('Option chart poll error:', err);
  } finally {
    _isFetching = false;
  }
}

/* =========================================================================
   STRIKE PILLS — re-render only when structure changes; patch LTP in-place
========================================================================= */
function _updateStrikePills(container, strikesRes) {
  const mount = container.querySelector('#active-strikes-mount');
  if (!mount) return;
  const contracts = cachedActiveStrikes.filter(c => c.option_type === selectedOptionType);
  if (!contracts || contracts.length === 0) return;

  const newFp = contracts.map(c => `${c.strike}|${c.strike_tag}|${c.ott_state}`).join(',')
              + `|sel=${selectedStrike}`;

  const ltpChanged = contracts.some(c => {
    const btn = mount.querySelector(`[data-strike="${c.strike}"]`);
    if (!btn) return true;
    const el = btn.querySelector('.pill-ltp');
    return el && el.textContent !== `\u20b9${c.ltp.toFixed(1)}`;
  });

  if (newFp === _strikesFingerprint && !ltpChanged) return;

  if (newFp !== _strikesFingerprint) {
    _strikesFingerprint = newFp;
    const pillHtml = contracts.map(c => {
      const isSel  = selectedStrike === c.strike;
      const isBull = c.ott_state === 'BULLISH';
      const isAtm  = c.strike_tag === 'ATM';
      const bdr    = isSel ? '#38bdf8' : 'rgba(255,255,255,0.08)';
      const bg     = isSel ? 'rgba(56,189,248,0.15)' : 'rgba(255,255,255,0.02)';
      const tagBg  = isAtm ? 'rgba(56,189,248,0.2)' : 'rgba(255,255,255,0.06)';
      const tagC   = isAtm ? '#38bdf8' : 'var(--text-muted)';
      const ottC   = isBull ? '#10b981' : '#ef4444';
      const ottL   = isBull ? '\u25b2 OTT' : '\u25bc OTT';
      return [
        `<button class="opt-strike-pill${isSel ? ' selected' : ''}" data-strike="${c.strike}"`,
        ` style="display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:6px;`,
        `font-family:var(--font-mono);font-size:11px;cursor:pointer;`,
        `border:1px solid ${bdr};background:${bg};color:#f8fafc;">`,
        `<strong>${intOrFloat(c.strike)}</strong>`,
        `<span style="font-size:9.5px;padding:1px 4px;border-radius:3px;font-weight:800;background:${tagBg};color:${tagC};">${c.strike_tag}</span>`,
        `<span class="pill-ltp" style="color:#38bdf8;font-weight:700;">\u20b9${c.ltp.toFixed(1)}</span>`,
        `<span style="font-size:9.5px;font-weight:700;color:${ottC};">${ottL}</span>`,
        `</button>`,
      ].join('');
    }).join('');

    mount.innerHTML = `<span style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">ATM \u00b1 2 Strikes:</span>${pillHtml}`;

    mount.querySelectorAll('.opt-strike-pill').forEach(btn => {
      btn.addEventListener('click', async () => {
        const stk = parseFloat(btn.getAttribute('data-strike'));
        if (stk && stk !== selectedStrike) {
          selectedStrike = stk; _strikesFingerprint = '';
          _destroyCharts(); _chartContractKey = '';
          await _loadAndRenderChart(container);
        }
      });
    });
  } else {
    contracts.forEach(c => {
      const el = mount.querySelector(`[data-strike="${c.strike}"] .pill-ltp`);
      if (el) el.textContent = `\u20b9${c.ltp.toFixed(1)}`;
    });
  }
}

/* =========================================================================
   STATUS BANNER — patch individual elements; build once, patch thereafter
========================================================================= */
function _patchStatusBanner(container, chartRes) {
  const mount      = container.querySelector('#contract-status-banner-mount');
  const titleMount = container.querySelector('#chart-contract-title');
  const badgeMount = container.querySelector('#chart-trigger-badge');
  if (!mount) return;

  const curr    = chartRes.current_state || {};
  const close   = curr.close      || 0;
  const ott     = curr.ott        || 0;
  const state   = curr.ott_state  || 'NEUTRAL';
  const adx     = curr.adx        || 20;
  const trigger = curr.signal_trigger || 'NEUTRAL_HOLD';
  const distPts = curr.distance_pts   || 0;
  const distPct = curr.distance_pct   || 0;
  const oi      = curr.oi;
  const oiChg   = curr.oi_chg;
  const buildup = curr.buildup        || 'NEUTRAL';

  const isBull    = state === 'BULLISH';
  const isBuy     = trigger === 'OPTION_BUY_CONFIRMED';
  const isExit    = trigger === 'OPTION_EXIT_SIGNAL';
  const isBupBull = buildup === 'LONG_BUILDUP' || buildup === 'SHORT_COVERING';
  const bupCls    = isBupBull ? 'badge-active' : (buildup === 'SHORT_BUILDUP' ? 'badge-bear' : 'badge-neutral');
  const label     = `${chartRes.symbol} ${intOrFloat(chartRes.strike)} ${chartRes.option_type}`;

  if (titleMount) titleMount.textContent = `${label} (5-Min Option Chart)`;

  if (badgeMount) {
    const txt = isBuy  ? '\ud83d\ude80 OPTION BUY CONFIRMED (ABOVE OTT)'
              : isExit ? '\ud83d\udea8 OPTION EXIT TRIGGER (BELOW OTT)'
                       : '\u2696\ufe0f NEUTRAL CONSOLIDATION';
    const sty = isBuy  ? 'background:rgba(16,185,129,0.2);color:#34d399;border:1px solid rgba(16,185,129,0.4);'
              : isExit ? 'background:rgba(239,68,68,0.2);color:#f87171;border:1px solid rgba(239,68,68,0.4);'
                       : 'background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid rgba(245,158,11,0.3);';
    const existing = badgeMount.querySelector('span');
    if (!existing || existing.textContent.trim() !== txt) {
      badgeMount.innerHTML = `<span style="padding:2px 8px;border-radius:4px;font-size:10.5px;font-weight:800;letter-spacing:0.3px;${sty}">${txt}</span>`;
    }
  }

  const borderC = `1px solid ${isBull ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`;
  const bgG     = isBull
    ? 'linear-gradient(90deg,rgba(16,185,129,0.08) 0%,rgba(15,23,42,0.6) 100%)'
    : 'linear-gradient(90deg,rgba(239,68,68,0.08) 0%,rgba(15,23,42,0.6) 100%)';

  const sbGrid = mount.querySelector('.sbgrid');
  if (!sbGrid) {
    mount.innerHTML = [
      `<div class="glass-panel sbgrid" style="padding:12px 16px;border:${borderC};background:${bgG};">`,
      `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;align-items:center;">`,

      `<div><span style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Option Premium (LTP)</span>`,
      `<div id="sb-ltp" style="font-size:18px;font-family:var(--font-mono);font-weight:800;color:#38bdf8;">\u20b9${close.toFixed(2)}</div></div>`,

      `<div><span style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">PineScript OTT Line</span>`,
      `<div id="sb-ott" style="font-size:16px;font-family:var(--font-mono);font-weight:800;color:#06b6d4;">\u20b9${ott.toFixed(2)}</div></div>`,

      `<div><span style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Distance from OTT</span>`,
      `<div id="sb-dist" style="font-size:15px;font-family:var(--font-mono);font-weight:800;color:${distPts >= 0 ? '#10b981' : '#ef4444'};">`,
      `${distPts >= 0 ? '+' : ''}${distPts.toFixed(2)} pts (${distPct >= 0 ? '+' : ''}${distPct.toFixed(1)}%)</div></div>`,

      `<div><span style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Open Interest (OI)</span>`,
      `<div id="sb-oi" style="font-size:15px;font-family:var(--font-mono);font-weight:800;color:#f8fafc;">`,
      `${formatOI(oi)} <span id="sb-oi-chg" style="font-size:11px;font-weight:700;color:${(oiChg || 0) >= 0 ? '#10b981' : '#ef4444'};">(${formatOIChg(oiChg)})</span></div></div>`,

      `<div><span style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Institutional Buildup</span>`,
      `<div style="margin-top:2px;"><span id="sb-buildup" class="badge ${bupCls}" style="font-size:10px;font-weight:800;padding:2px 7px;border-radius:4px;">`,
      `${buildup.replace('_', ' ')}</span></div></div>`,

      `<div><span style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Option ADX Speed</span>`,
      `<div id="sb-adx" style="font-size:15px;font-family:var(--font-mono);font-weight:800;color:${adx >= 25 ? '#38bdf8' : 'var(--text-secondary)'};">`,
      `${adx.toFixed(1)} ${adx >= 25 ? '\u26a1 High' : (adx >= 18 ? '\u25cf Trend' : '\u2615 Low')}</div></div>`,

      `</div></div>`,
    ].join('');
    return;
  }

  // Subsequent polls — surgical patch only
  sbGrid.style.border     = borderC;
  sbGrid.style.background = bgG;

  const sb = id => mount.querySelector(`#${id}`);
  _setText(sb('sb-ltp'), `\u20b9${close.toFixed(2)}`);
  _setText(sb('sb-ott'), `\u20b9${ott.toFixed(2)}`);

  const distEl = sb('sb-dist');
  if (distEl) {
    distEl.textContent = `${distPts >= 0 ? '+' : ''}${distPts.toFixed(2)} pts (${distPct >= 0 ? '+' : ''}${distPct.toFixed(1)}%)`;
    distEl.style.color = distPts >= 0 ? '#10b981' : '#ef4444';
  }

  const oiEl = sb('sb-oi');
  if (oiEl) {
    const txt = formatOI(oi);
    const firstNode = oiEl.firstChild;
    if (firstNode && firstNode.nodeType === 3) {
      if (firstNode.textContent.trim() !== txt) firstNode.textContent = txt + ' ';
    }
  }
  const oiChgEl = sb('sb-oi-chg');
  if (oiChgEl) {
    oiChgEl.textContent = `(${formatOIChg(oiChg)})`;
    oiChgEl.style.color = (oiChg || 0) >= 0 ? '#10b981' : '#ef4444';
  }

  const bupEl = sb('sb-buildup');
  if (bupEl) { bupEl.textContent = buildup.replace('_', ' '); bupEl.className = `badge ${bupCls}`; }

  const adxEl = sb('sb-adx');
  if (adxEl) {
    adxEl.textContent = `${adx.toFixed(1)} ${adx >= 25 ? '\u26a1 High' : (adx >= 18 ? '\u25cf Trend' : '\u2615 Low')}`;
    adxEl.style.color = adx >= 25 ? '#38bdf8' : 'var(--text-secondary)';
  }
}

/* =========================================================================
   CANDLESTICK CHART — TradingView Lightweight Charts (zero-flicker engine)
   ─────────────────────────────────────────────────────────────────────────
   Strategy:
   • Chart instance created ONCE per contract (symbol+strike+type)
   • If new candle count > previous → setData() for all historical +
     update() for the new last bar, then fitContent() ONLY on first load
   • If candle count is same → update() ONLY the last bar (in-place)
   • User scroll/zoom position is NEVER reset during live polling
========================================================================= */
function _updateCandlestickChart(container, chartRes) {
  const mount = container.querySelector('#candlestick-tv-mount');
  if (!mount) return;

  if (typeof LightweightCharts === 'undefined') {
    mount.innerHTML = `
      <div style="display:flex;height:100%;align-items:center;justify-content:center;color:#f59e0b;font-size:12px;font-family:var(--font-mono);gap:8px;">
        <span class="status-pulse pulse-yellow"></span> Loading TradingView chart library...
      </div>`;
    return;
  }

  const candles = chartRes.candles || [];
  if (candles.length === 0) {
    if (!optionChartInstance) {
      mount.innerHTML = `
        <div style="display:flex;flex-direction:column;height:100%;align-items:center;justify-content:center;color:#94a3b8;font-size:12px;font-family:var(--font-mono);gap:8px;">
          <span class="status-pulse pulse-green"></span>
          <span>Awaiting 5-minute candle data for ${chartRes.symbol} ${intOrFloat(chartRes.strike)} ${chartRes.option_type}...</span>
          <span style="font-size:11px;color:var(--text-muted);">Real-time ticks are being recorded. Candles will plot as data arrives.</span>
        </div>`;
    }
    return;
  }

  // Clear any placeholder before creating chart
  if (!optionChartInstance) {
    mount.innerHTML = '';
  }

  // ── Create chart instance if needed ──────────────────────────────────
  if (!optionChartInstance) {
    optionChartInstance = LightweightCharts.createChart(mount, {
      width: mount.clientWidth,
      height: mount.clientHeight,
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#94a3b8',
        fontSize: 11,
        fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: 'rgba(255, 255, 255, 0.06)',
        rightOffset: 5,
        barSpacing: 8,
        minBarSpacing: 3,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.06)',
        scaleMargins: { top: 0.1, bottom: 0.08 },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: 'rgba(56, 189, 248, 0.3)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
        horzLine: { color: 'rgba(56, 189, 248, 0.3)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });

    optionCandleSeries = optionChartInstance.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#10b981',
      wickDownColor: '#b91c1c',
      wickUpColor: '#059669',
    });

    optionOttSeries = optionChartInstance.addLineSeries({
      color: '#06b6d4',
      lineWidth: 2,
      lineStyle: 0,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    optionMavgSeries = optionChartInstance.addLineSeries({
      color: '#eab308',
      lineWidth: 1,
      lineStyle: 2,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Single resize handler
    _resizeHandler = () => {
      const tvMount = document.getElementById('candlestick-tv-mount');
      const adxMount = document.getElementById('adx-tv-mount');
      if (optionChartInstance && tvMount) {
        optionChartInstance.applyOptions({ width: tvMount.clientWidth });
      }
      if (adxChartInstance && adxMount) {
        adxChartInstance.applyOptions({ width: adxMount.clientWidth });
      }
    };
    window.addEventListener('resize', _resizeHandler);
  }

  // ── Build data arrays ───────────────────────────────────────────────
  const inds  = chartRes.indicators || {};
  const ottV  = inds.ott  || [];
  const mavgV = inds.mavg || [];

  const cData = [];
  const oData = [];
  const mData = [];
  const markers = [];

  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    const t = parseTvTime(c.time);
    if (!t) continue;
    cData.push({ time: t, open: c.open, high: c.high, low: c.low, close: c.close });
    if (ottV[i] !== undefined && ottV[i] !== null)  oData.push({ time: t, value: ottV[i] });
    if (mavgV[i] !== undefined && mavgV[i] !== null) mData.push({ time: t, value: mavgV[i] });
  }

  (chartRes.signals || []).forEach(sig => {
    if (sig.index >= candles.length) return;
    const t = parseTvTime(candles[sig.index].time);
    if (!t) return;
    if (sig.type === 'BUY') {
      markers.push({ time: t, position: 'belowBar', color: '#10b981', shape: 'arrowUp', text: 'BUY' });
    } else if (sig.type === 'EXIT') {
      markers.push({ time: t, position: 'aboveBar', color: '#ef4444', shape: 'arrowDown', text: 'EXIT' });
    }
  });

  const candlesFinal = _dedup(cData);
  const ottFinal     = _dedup(oData);
  const mavgFinal    = _dedup(mData);

  // ── Smart update strategy ───────────────────────────────────────────
  const newCount = candlesFinal.length;

  if (newCount !== _lastCandleCount || _lastCandleCount === 0) {
    // Structure changed (new bar added) — full setData, but only fit on first load
    optionCandleSeries.setData(candlesFinal);
    optionOttSeries.setData(ottFinal);
    optionMavgSeries.setData(mavgFinal);

    if (!_initialFitDone) {
      optionChartInstance.timeScale().fitContent();
      _initialFitDone = true;
    }
    _lastCandleCount = newCount;
  } else {
    // Same bar count — just update the LAST bar in-place (zero redraw)
    if (candlesFinal.length > 0) {
      optionCandleSeries.update(candlesFinal[candlesFinal.length - 1]);
    }
    if (ottFinal.length > 0) {
      optionOttSeries.update(ottFinal[ottFinal.length - 1]);
    }
    if (mavgFinal.length > 0) {
      optionMavgSeries.update(mavgFinal[mavgFinal.length - 1]);
    }
  }

  // Markers always set (deduplicated by time & sorted)
  const seenMarkerTimes = new Set();
  const sortedMarkers = [];
  markers.sort((a, b) => a.time - b.time);
  for (const m of markers) {
    if (!seenMarkerTimes.has(m.time)) {
      seenMarkerTimes.add(m.time);
      sortedMarkers.push(m);
    }
  }
  try {
    optionCandleSeries.setMarkers(sortedMarkers);
  } catch (_) {}
}

/* =========================================================================
   ADX CHART — Lightweight Charts (same zero-flicker strategy)
========================================================================= */
let _lastAdxCount = 0;
let _adxInitialFit = false;

function _updateAdxChart(container, chartRes) {
  const mount = container.querySelector('#adx-tv-mount');
  if (!mount) return;

  if (typeof LightweightCharts === 'undefined') return;

  const candles = chartRes.candles || [];
  if (candles.length < 2) {
    if (!adxChartInstance) {
      mount.innerHTML = `
        <div style="display:flex;height:100%;align-items:center;justify-content:center;color:var(--text-muted);font-size:11px;font-family:var(--font-mono);">
          ADX momentum requires at least 2 bars to calculate
        </div>`;
    }
    return;
  }

  // Clear placeholder before mounting chart
  if (!adxChartInstance) {
    mount.innerHTML = '';
  }

  if (!adxChartInstance) {
    adxChartInstance = LightweightCharts.createChart(mount, {
      width: mount.clientWidth,
      height: mount.clientHeight,
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#94a3b8',
        fontSize: 10,
        fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: 'rgba(255, 255, 255, 0.06)',
        rightOffset: 5,
        barSpacing: 8,
        minBarSpacing: 3,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.06)',
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: 'rgba(56, 189, 248, 0.3)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
        horzLine: { color: 'rgba(56, 189, 248, 0.3)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });

    adxSeriesLine = adxChartInstance.addLineSeries({ color: '#a855f7', lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
    pdiSeriesLine = adxChartInstance.addLineSeries({ color: '#10b981', lineWidth: 1, lineStyle: 0, priceLineVisible: false, lastValueVisible: false });
    mdiSeriesLine = adxChartInstance.addLineSeries({ color: '#ef4444', lineWidth: 1, lineStyle: 0, priceLineVisible: false, lastValueVisible: false });

    // Reference lines at 18 and 25
    adxSeriesLine.createPriceLine({ price: 18, color: 'rgba(255,255,255,0.12)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '18' });
    adxSeriesLine.createPriceLine({ price: 25, color: 'rgba(56,189,248,0.3)',   lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '25' });
  }

  const inds = chartRes.indicators || {};
  const adxV = inds.adx      || [];
  const pdiV = inds.plus_di  || [];
  const mdiV = inds.minus_di || [];

  const aData = [];
  const pData = [];
  const mData = [];

  for (let i = 0; i < candles.length; i++) {
    const t = parseTvTime(candles[i].time);
    if (!t) continue;
    if (adxV[i] !== undefined && adxV[i] !== null) aData.push({ time: t, value: adxV[i] });
    if (pdiV[i] !== undefined && pdiV[i] !== null) pData.push({ time: t, value: pdiV[i] });
    if (mdiV[i] !== undefined && mdiV[i] !== null) mData.push({ time: t, value: mdiV[i] });
  }

  const adxFinal = _dedup(aData);
  const pdiFinal = _dedup(pData);
  const mdiFinal = _dedup(mData);

  const newCount = adxFinal.length;

  if (newCount !== _lastAdxCount || _lastAdxCount === 0) {
    adxSeriesLine.setData(adxFinal);
    pdiSeriesLine.setData(pdiFinal);
    mdiSeriesLine.setData(mdiFinal);
    if (!_adxInitialFit) {
      adxChartInstance.timeScale().fitContent();
      _adxInitialFit = true;
    }
    _lastAdxCount = newCount;
  } else {
    if (adxFinal.length > 0) adxSeriesLine.update(adxFinal[adxFinal.length - 1]);
    if (pdiFinal.length > 0) pdiSeriesLine.update(pdiFinal[pdiFinal.length - 1]);
    if (mdiFinal.length > 0) mdiSeriesLine.update(mdiFinal[mdiFinal.length - 1]);
  }
}

/* =========================================================================
   UTILITY HELPERS
========================================================================= */
function _setText(el, text) {
  if (el && el.textContent !== text) el.textContent = text;
}

function formatOI(oi) {
  if (!oi) return '--';
  if (Math.abs(oi) >= 10000000) return (oi / 10000000).toFixed(2) + 'Cr';
  if (Math.abs(oi) >= 100000)   return (oi / 100000).toFixed(1)   + 'L';
  if (Math.abs(oi) >= 1000)     return (oi / 1000).toFixed(0)     + 'K';
  return oi.toString();
}

function formatOIChg(chg) {
  if (chg === undefined || chg === null) return '0';
  const sign = chg >= 0 ? '+' : '';
  if (Math.abs(chg) >= 10000000) return sign + (chg / 10000000).toFixed(2) + 'Cr';
  if (Math.abs(chg) >= 100000)   return sign + (chg / 100000).toFixed(1)   + 'L';
  if (Math.abs(chg) >= 1000)     return sign + (chg / 1000).toFixed(0)     + 'K';
  return sign + chg.toString();
}

function intOrFloat(val) {
  if (val === undefined || val === null) return '--';
  return Number.isInteger(val) ? val : Math.round(val);
}
