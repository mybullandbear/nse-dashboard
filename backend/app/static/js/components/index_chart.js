/**
 * Index Candlestick Chart — TradingView Lightweight Charts Engine
 * ═══════════════════════════════════════════════════════════════
 * ZERO-FLICKER ARCHITECTURE:
 * • Chart instance created ONCE per symbol, reused across polls
 * • Incremental update() for the last bar, setData() only when new bars arrive
 * • Data fingerprint comparison — identical API responses are SKIPPED
 * • Scroll/zoom position preserved across poll cycles
 * • Clean destruction on symbol/interval change
 */
import { ApiClient } from '../api.js';

/* ─── Module State ─────────────────────────────────────────────────────────── */
let selectedSymbol   = 'NIFTY';
let selectedInterval = 5;
let chartPollTimer   = null;

/* Chart engine state */
let chartInstance     = null;
let candleSeries     = null;
let _dataFingerprint = '';
let _lastBarCount    = 0;
let _initialFitDone  = false;
let _resizeHandler   = null;
let _isFetching      = false;

/* ─── Time Parsing ─────────────────────────────────────────────────────────── */
function parseTimeStr(timeStr) {
  if (!timeStr) return 0;
  if (timeStr.includes('-')) {
    const d = new Date(timeStr.replace(' ', 'T'));
    if (isNaN(d.getTime())) return 0;
    return Math.floor(d.getTime() / 1000);
  }
  const now = new Date();
  const [h, m] = timeStr.split(':').map(Number);
  now.setHours(h, m, 0, 0);
  return Math.floor(now.getTime() / 1000);
}

/* ─── Dedup & Sort ─────────────────────────────────────────────────────────── */
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

/* ─── Clean Destroy ────────────────────────────────────────────────────────── */
function _destroyChart() {
  if (_resizeHandler) {
    window.removeEventListener('resize', _resizeHandler);
    _resizeHandler = null;
  }
  if (chartInstance) {
    try { chartInstance.remove(); } catch (_) {}
    chartInstance = null;
    candleSeries = null;
  }
  _dataFingerprint = '';
  _lastBarCount = 0;
  _initialFitDone = false;
}

/* ─── Entry Point ──────────────────────────────────────────────────────────── */
export async function renderIndexChart(container) {
  if (chartPollTimer) { clearInterval(chartPollTimer); chartPollTimer = null; }
  _destroyChart();

  const symBtns = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'].map(sym => {
    const cls = sym === selectedSymbol ? 'active' : '';
    return `<button class="idx-sym-btn ${cls}" data-sym="${sym}" `
         + `style="padding:5px 12px;font-size:11px;font-weight:700;border:none;border-radius:4px;cursor:pointer;">`
         + `${sym}</button>`;
  }).join('');

  const intBtns = [1, 3, 5, 15].map(int => {
    const cls = int === selectedInterval ? 'active' : '';
    return `<button class="idx-int-btn ${cls}" data-int="${int}" `
         + `style="padding:5px 12px;font-size:11px;font-weight:700;border:none;border-radius:4px;cursor:pointer;">`
         + `${int}M</button>`;
  }).join('');

  container.innerHTML = `
    <div class="index-chart-container" style="padding:16px;">
      <div class="glass-panel" style="padding:14px;margin-bottom:16px;border:1px solid rgba(56,189,248,0.25);">
        <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;">
          <div style="display:flex;align-items:center;gap:6px;">
            <span style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Index:</span>
            <div style="display:flex;gap:4px;background:rgba(0,0,0,0.4);padding:3px;border-radius:6px;">
              ${symBtns}
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:6px;">
            <span style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Interval:</span>
            <div style="display:flex;gap:4px;background:rgba(0,0,0,0.4);padding:3px;border-radius:6px;">
              ${intBtns}
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:11px;padding:4px 10px;border-radius:6px;background:rgba(16,185,129,0.2);color:#10b981;">LIVE CANDLES</span>
            <span class="status-pulse pulse-green" title="Auto-refreshing"></span>
          </div>
        </div>
      </div>
      <div class="glass-panel" style="padding:16px;margin-bottom:14px;">
        <div id="index-tv-chart" style="width:100%;height:500px;background:rgba(5,10,20,0.6);border-radius:8px;border:1px solid rgba(255,255,255,0.05);overflow:hidden;"></div>
      </div>
    </div>
  `;

  // Attach controls
  container.querySelectorAll('.idx-sym-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const sym = btn.getAttribute('data-sym');
      if (sym !== selectedSymbol) {
        selectedSymbol = sym;
        _destroyChart();
        container.querySelectorAll('.idx-sym-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        await loadAndRenderData();
      }
    });
  });

  container.querySelectorAll('.idx-int-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const int = parseInt(btn.getAttribute('data-int'), 10);
      if (int !== selectedInterval) {
        selectedInterval = int;
        _destroyChart();
        container.querySelectorAll('.idx-int-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        await loadAndRenderData();
      }
    });
  });

  await loadAndRenderData();

  chartPollTimer = setInterval(async () => {
    if (!document.body.contains(container)) {
      clearInterval(chartPollTimer); chartPollTimer = null;
      _destroyChart();
      return;
    }
    await loadAndRenderData();
  }, 5000);
}

/* ─── Data Fetch & Smart Update ────────────────────────────────────────────── */
async function loadAndRenderData() {
  if (_isFetching) return;
  _isFetching = true;
  try {
    const res = await ApiClient.fetchSmartOITrend(selectedSymbol, selectedInterval);
    if (!res || !res.trend || res.trend.length === 0) return;

    // Build fingerprint
    const last = res.trend[res.trend.length - 1];
    const fp = `${res.trend.length}|${last.time}|${last.close || last.spot}`;
    if (fp === _dataFingerprint) return; // identical data — skip entirely
    _dataFingerprint = fp;

    const data = [];
    for (const t of res.trend) {
      const time = parseTimeStr(t.time);
      const open  = parseFloat(t.open  || t.spot || 0);
      const high  = parseFloat(t.high  || t.spot || 0);
      const low   = parseFloat(t.low   || t.spot || 0);
      const close = parseFloat(t.close || t.spot || 0);
      if (time && open) data.push({ time, open, high, low, close });
    }
    const uniqueData = _dedup(data);
    if (uniqueData.length === 0) return;

    // Create chart if needed
    if (!chartInstance) {
      const mount = document.getElementById('index-tv-chart');
      if (!mount) return;

      chartInstance = LightweightCharts.createChart(mount, {
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

      candleSeries = chartInstance.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderDownColor: '#ef4444',
        borderUpColor: '#10b981',
        wickDownColor: '#b91c1c',
        wickUpColor: '#059669',
      });

      _resizeHandler = () => {
        const el = document.getElementById('index-tv-chart');
        if (chartInstance && el) chartInstance.applyOptions({ width: el.clientWidth });
      };
      window.addEventListener('resize', _resizeHandler);
    }

    // Smart update
    const newCount = uniqueData.length;
    if (newCount !== _lastBarCount || _lastBarCount === 0) {
      candleSeries.setData(uniqueData);
      if (!_initialFitDone) {
        chartInstance.timeScale().fitContent();
        _initialFitDone = true;
      }
      _lastBarCount = newCount;
    } else {
      candleSeries.update(uniqueData[uniqueData.length - 1]);
    }

  } catch (err) {
    console.warn('Index chart poll error:', err);
  } finally {
    _isFetching = false;
  }
}
