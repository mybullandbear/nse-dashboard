/**
 * Smart OI Interrelated Multi-Pane Analytics View (StockMojo Style)
 * Synchronized Candlestick, Smart OI Delta Flow, Cumulative OI Change & Dual PCR
 */
import { store } from '../state.js';
import { ApiClient } from '../api.js?v=4.0.5';

// Defensive fallback in case browser has cached older api.js
if (!ApiClient.fetchSmartOITrend) {
  ApiClient.fetchSmartOITrend = function(symbol = 'NIFTY', interval = 5, date = null, range = 'ALL') {
    let url = `/api/smart-oi/trend/${symbol}?interval=${interval}&range_mode=${range}`;
    if (date) url += `&date=${encodeURIComponent(date)}`;
    return this.get(url);
  };
}
if (!ApiClient.fetchSmartOIDates) {
  ApiClient.fetchSmartOIDates = function(symbol = 'NIFTY') {
    return this.get(`/api/smart-oi/dates/${symbol}`);
  };
}

let activeSymbol = 'NIFTY';
let activeInterval = 5;
let activeDate = null;
let activeRange = 'ALL';
let activeMode = 'LIVE'; // 'LIVE' | 'HISTORICAL'
let activeExpiry = '';
let hoverIndex = -1;

// Curve visibility toggles
let showPutOI = true;
let showCallOI = true;
let showDiffOI = true;
let showOIPCR = true;
let showVolPCR = true;

let trendData = null;
let datesList = [];
let isFetching = false;

export async function renderSmartOIView(container) {
  if (!trendData && !isFetching) {
    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;height:60vh;flex-direction:column;gap:16px;">
        <div style="width:40px;height:40px;border:3px solid rgba(56,189,248,0.2);border-top-color:#38bdf8;border-radius:50%;animation:spin 0.8s linear infinite;"></div>
        <div style="color:#94a3b8;font-size:14px;font-weight:600;letter-spacing:0.5px;">Loading Smart OI Multi-Pane Dashboard...</div>
      </div>
    `;
    await fetchSmartOIData();
  }

  const existingWrapper = container.querySelector('.smart-oi-wrapper');
  if (existingWrapper && trendData) {
    if (typeof redrawAll === 'function') redrawAll();
    return;
  }

  container.innerHTML = `
    <div class="smart-oi-wrapper">
      <!-- TOP CONTROL & FILTER TOOLBAR -->
      <div class="smart-oi-toolbar">
        <div class="toolbar-left">
          <!-- Symbol Selector -->
          <div class="soi-symbol-pill-group">
            <span class="soi-label-badge">50</span>
            <select id="soi-symbol-select" class="soi-select-styled">
              <option value="NIFTY" ${activeSymbol === 'NIFTY' ? 'selected' : ''}>NIFTY</option>
              <option value="BANKNIFTY" ${activeSymbol === 'BANKNIFTY' ? 'selected' : ''}>BANKNIFTY</option>
              <option value="FINNIFTY" ${activeSymbol === 'FINNIFTY' ? 'selected' : ''}>FINNIFTY</option>
              <option value="MIDCPNIFTY" ${activeSymbol === 'MIDCPNIFTY' ? 'selected' : ''}>MIDCPNIFTY</option>
            </select>
          </div>

          <!-- Expiry Dropdown -->
          <div class="soi-control-item">
            <select id="soi-expiry-select" class="soi-select-styled">
              ${(trendData?.expiries || ['22 Sep 2026 (6d)']).map(exp => `
                <option value="${exp}" ${exp === activeExpiry ? 'selected' : ''}>${exp}</option>
              `).join('')}
            </select>
          </div>

          <!-- Timeframe Buttons -->
          <div class="soi-btn-group" id="soi-interval-group">
            ${[1, 3, 5, 15].map(iv => `
              <button class="soi-btn ${activeInterval === iv ? 'active' : ''}" data-interval="${iv}">${iv}m</button>
            `).join('')}
          </div>

          <!-- Live vs Historical Mode -->
          <div class="soi-btn-group">
            <button class="soi-btn ${activeMode === 'LIVE' ? 'active' : ''}" id="soi-mode-live">Live</button>
            <button class="soi-btn ${activeMode === 'HISTORICAL' ? 'active' : ''}" id="soi-mode-hist">Historical</button>
          </div>

          <!-- Historical Date Picker -->
          <div class="soi-control-item ${activeMode === 'HISTORICAL' ? '' : 'hidden'}" id="soi-date-picker-wrap">
            <select id="soi-date-select" class="soi-select-styled">
              ${(datesList.length > 0 ? datesList : [trendData?.trade_date || 'Today']).map(d => `
                <option value="${d}" ${d === activeDate ? 'selected' : ''}>${d}</option>
              `).join('')}
            </select>
          </div>

          <!-- Strike Range Filter -->
          <div class="soi-range-control">
            <span class="soi-range-label">Range:</span>
            <div class="soi-btn-group" id="soi-range-group">
              <button class="soi-btn ${activeRange === 'ALL' ? 'active' : ''}" data-range="ALL">All</button>
              <button class="soi-btn ${activeRange === '10' ? 'active' : ''}" data-range="10">±10</button>
              <button class="soi-btn ${activeRange === '5' ? 'active' : ''}" data-range="5">±5</button>
            </div>
            <span class="soi-bounds-badge">${trendData?.strike_bounds?.label || ''}</span>
          </div>
        </div>

        <div class="toolbar-right">
          <div class="soi-spot-chip">
            <span class="soi-spot-lbl">${activeSymbol} SPOT</span>
            <span class="soi-spot-val" id="soi-spot-display">
              ${trendData?.current_spot ? trendData.current_spot.toLocaleString('en-IN', { minimumFractionDigits: 1 }) : '--'}
            </span>
          </div>
          <button class="soi-btn" id="soi-refresh-btn" title="Refresh Data">⚡ Refresh</button>
        </div>
      </div>

      <!-- MAIN MULTI-PANE WORKSTATION -->
      <div class="smart-oi-grid">
        <!-- LEFT PANEL: Candlestick + Smart OI Flow + Volume -->
        <div class="soi-left-panel glass-panel">
          <!-- Pane Header & HUD -->
          <div class="soi-pane-header">
            <div class="soi-legend-tags">
              <span class="soi-tag-item"><span class="dot" style="background:#38bdf8;"></span> ${activeSymbol} OHLC</span>
              <span class="soi-tag-item"><span class="dot" style="background:#10b981;"></span> Smart OI Flow</span>
              <span class="soi-tag-item"><span class="dot" style="background:#64748b;"></span> Volume</span>
            </div>
            <div class="soi-hud-metrics" id="soi-left-hud">
              <span class="hud-item" id="hud-ohlc">O: -- H: -- L: -- C: --</span>
              <span class="hud-item" id="hud-smart-oi">Smart OI: --</span>
            </div>
          </div>

          <!-- Canvas Container (Synchronized Candlestick, Delta, Volume) -->
          <div class="soi-canvas-container" id="soi-left-canvas-wrap">
            <canvas id="soi-main-canvas"></canvas>
          </div>
        </div>

        <!-- RIGHT PANEL: Stacked Options Intelligence Panes -->
        <div class="soi-right-panel">
          <!-- TOP RIGHT: Cumulative OI Change (Day Trend) -->
          <div class="glass-panel soi-pane-block">
            <div class="soi-pane-header">
              <div class="soi-interactive-legends">
                <button class="soi-legend-toggle ${showPutOI ? 'active' : ''}" id="toggle-put-oi" style="--accent: #ef4444;">
                  <span>👁️ Put OI (Chg Day)</span>
                  <span class="soi-val-pill" id="val-put-oi-pill">--</span>
                </button>
                <button class="soi-legend-toggle ${showCallOI ? 'active' : ''}" id="toggle-call-oi" style="--accent: #10b981;">
                  <span>👁️ Call OI (Chg Day)</span>
                  <span class="soi-val-pill" id="val-call-oi-pill">--</span>
                </button>
                <button class="soi-legend-toggle ${showDiffOI ? 'active' : ''}" id="toggle-diff-oi" style="--accent: #a855f7;">
                  <span>👁️ PE-CE (Chg Day)</span>
                  <span class="soi-val-pill" id="val-diff-oi-pill">--</span>
                </button>
              </div>
            </div>
            <div class="soi-canvas-container" id="soi-oi-canvas-wrap">
              <canvas id="soi-oi-canvas"></canvas>
            </div>
          </div>

          <!-- BOTTOM RIGHT: Dual PCR (OI PCR & Volume PCR) -->
          <div class="glass-panel soi-pane-block">
            <div class="soi-pane-header">
              <div class="soi-interactive-legends">
                <button class="soi-legend-toggle ${showOIPCR ? 'active' : ''}" id="toggle-oi-pcr" style="--accent: #38bdf8;">
                  <span>👁️ OI PCR</span>
                  <span class="soi-val-pill" id="val-oi-pcr-pill">--</span>
                </button>
                <button class="soi-legend-toggle ${showVolPCR ? 'active' : ''}" id="toggle-vol-pcr" style="--accent: #f59e0b;">
                  <span>👁️ Vol PCR (Total)</span>
                  <span class="soi-val-pill" id="val-vol-pcr-pill">--</span>
                </button>
              </div>
              <div class="soi-pcr-guide">Neutral: 1.00</div>
            </div>
            <div class="soi-canvas-container" id="soi-pcr-canvas-wrap">
              <canvas id="soi-pcr-canvas"></canvas>
            </div>
          </div>
        </div>
      </div>

      <!-- Synchronized Floating Timestamp Indicator -->
      <div class="soi-time-footer" id="soi-sync-time">
        Hover over any chart to inspect synchronized multi-pane metrics
      </div>
    </div>
  `;

  // Wire event listeners
  attachToolbarListeners(container);
  setupCanvasRenderers(container);
}

async function fetchSmartOIData() {
  if (isFetching) return;
  isFetching = true;
  try {
    const data = await ApiClient.fetchSmartOITrend(activeSymbol, activeInterval, activeDate, activeRange);
    if (data) {
      trendData = data;
      if (data.available_dates && data.available_dates.length > 0) {
        datesList = data.available_dates;
      }
      if (!activeDate && data.trade_date) {
        activeDate = data.trade_date;
      }
      if (data.expiries && data.expiries.length > 0 && !activeExpiry) {
        activeExpiry = data.expiries[0];
      }
    }
  } catch (err) {
    console.error('Failed to fetch smart OI trend data:', err);
  } finally {
    isFetching = false;
  }
}

function attachToolbarListeners(container) {
  // Symbol change
  const symSelect = container.querySelector('#soi-symbol-select');
  if (symSelect) {
    symSelect.addEventListener('change', async (e) => {
      activeSymbol = e.target.value;
      await fetchSmartOIData();
      renderSmartOIView(container);
    });
  }

  // Expiry change
  const expSelect = container.querySelector('#soi-expiry-select');
  if (expSelect) {
    expSelect.addEventListener('change', (e) => {
      activeExpiry = e.target.value;
    });
  }

  // Interval buttons
  container.querySelectorAll('[data-interval]').forEach(btn => {
    btn.addEventListener('click', async () => {
      activeInterval = parseInt(btn.getAttribute('data-interval'), 10);
      await fetchSmartOIData();
      renderSmartOIView(container);
    });
  });

  // Range buttons
  container.querySelectorAll('[data-range]').forEach(btn => {
    btn.addEventListener('click', async () => {
      activeRange = btn.getAttribute('data-range');
      await fetchSmartOIData();
      renderSmartOIView(container);
    });
  });

  // Mode toggles
  const btnLive = container.querySelector('#soi-mode-live');
  const btnHist = container.querySelector('#soi-mode-hist');
  const dateWrap = container.querySelector('#soi-date-picker-wrap');
  const dateSelect = container.querySelector('#soi-date-select');

  if (btnLive) {
    btnLive.addEventListener('click', async () => {
      activeMode = 'LIVE';
      activeDate = null;
      if (dateWrap) dateWrap.classList.add('hidden');
      await fetchSmartOIData();
      renderSmartOIView(container);
    });
  }

  if (btnHist) {
    btnHist.addEventListener('click', () => {
      activeMode = 'HISTORICAL';
      if (dateWrap) dateWrap.classList.remove('hidden');
      btnLive.classList.remove('active');
      btnHist.classList.add('active');
    });
  }

  if (dateSelect) {
    dateSelect.addEventListener('change', async (e) => {
      activeDate = e.target.value;
      await fetchSmartOIData();
      renderSmartOIView(container);
    });
  }

  // Refresh button
  const refreshBtn = container.querySelector('#soi-refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
      await fetchSmartOIData();
      renderSmartOIView(container);
    });
  }

  // Curve visibility toggles
  const btnPut = container.querySelector('#toggle-put-oi');
  if (btnPut) {
    btnPut.addEventListener('click', () => {
      showPutOI = !showPutOI;
      btnPut.classList.toggle('active', showPutOI);
      redrawAll();
    });
  }

  const btnCall = container.querySelector('#toggle-call-oi');
  if (btnCall) {
    btnCall.addEventListener('click', () => {
      showCallOI = !showCallOI;
      btnCall.classList.toggle('active', showCallOI);
      redrawAll();
    });
  }

  const btnDiff = container.querySelector('#toggle-diff-oi');
  if (btnDiff) {
    btnDiff.addEventListener('click', () => {
      showDiffOI = !showDiffOI;
      btnDiff.classList.toggle('active', showDiffOI);
      redrawAll();
    });
  }

  const btnOIPcr = container.querySelector('#toggle-oi-pcr');
  if (btnOIPcr) {
    btnOIPcr.addEventListener('click', () => {
      showOIPCR = !showOIPCR;
      btnOIPcr.classList.toggle('active', showOIPCR);
      redrawAll();
    });
  }

  const btnVolPcr = container.querySelector('#toggle-vol-pcr');
  if (btnVolPcr) {
    btnVolPcr.addEventListener('click', () => {
      showVolPCR = !showVolPCR;
      btnVolPcr.classList.toggle('active', showVolPCR);
      redrawAll();
    });
  }
}

// -------------------------------------------------------------
// HIGH-PRECISION CANVAS MULTI-PANE RENDERING & CROSSHAIR ENGINE
// -------------------------------------------------------------
let redrawAll = () => {};

function setupCanvasRenderers(container) {
  const mainCanvas = container.querySelector('#soi-main-canvas');
  const oiCanvas = container.querySelector('#soi-oi-canvas');
  const pcrCanvas = container.querySelector('#soi-pcr-canvas');

  if (!mainCanvas || !oiCanvas || !pcrCanvas || !trendData) return;

  const candles = trendData.candles || [];
  const oiTrend = trendData.oi_trend || [];
  const pcrTrend = trendData.pcr_trend || [];
  const numPoints = candles.length;

  if (numPoints === 0) {
    drawEmptyNotice(mainCanvas, "Awaiting Intraday Candles for " + activeSymbol);
    drawEmptyNotice(oiCanvas, "Awaiting OI Trend Data");
    drawEmptyNotice(pcrCanvas, "Awaiting PCR Trend Data");
    return;
  }

  // Set default hoverIndex to last point
  if (hoverIndex < 0 || hoverIndex >= numPoints) {
    hoverIndex = numPoints - 1;
  }

  const leftHUD = container.querySelector('#soi-left-hud');
  const hudOHLC = container.querySelector('#hud-ohlc');
  const hudSmartOI = container.querySelector('#hud-smart-oi');
  const pillPutOI = container.querySelector('#val-put-oi-pill');
  const pillCallOI = container.querySelector('#val-call-oi-pill');
  const pillDiffOI = container.querySelector('#val-diff-oi-pill');
  const pillOIPCR = container.querySelector('#val-oi-pcr-pill');
  const pillVolPCR = container.querySelector('#val-vol-pcr-pill');
  const syncTimeEl = container.querySelector('#soi-sync-time');

  function updateHUD(idx) {
    if (idx < 0 || idx >= numPoints) return;
    const c = candles[idx];
    const oi = oiTrend[idx] || {};
    const pcr = pcrTrend[idx] || {};

    if (hudOHLC && c) {
      hudOHLC.innerHTML = `O: <b style="color:#f8fafc;">${c.open.toFixed(1)}</b>  H: <b style="color:#10b981;">${c.high.toFixed(1)}</b>  L: <b style="color:#ef4444;">${c.low.toFixed(1)}</b>  C: <b style="color:#38bdf8;">${c.close.toFixed(1)}</b>`;
    }
    if (hudSmartOI && c) {
      const soi = c.smart_oi || 0;
      const soiStr = (soi > 0 ? '+' : '') + soi.toLocaleString('en-IN');
      hudSmartOI.innerHTML = `Smart OI: <b style="color:${soi >= 0 ? '#10b981' : '#ef4444'};">${soiStr}</b>`;
    }
    if (pillPutOI) pillPutOI.textContent = `${(oi.put_oi_chg || 0).toFixed(2)}Cr`;
    if (pillCallOI) pillCallOI.textContent = `${(oi.call_oi_chg || 0).toFixed(2)}Cr`;
    if (pillDiffOI) pillDiffOI.textContent = `${(oi.pe_minus_ce || 0).toFixed(2)}Cr`;
    if (pillOIPCR) pillOIPCR.textContent = (pcr.oi_pcr || 0).toFixed(3);
    if (pillVolPCR) pillVolPCR.textContent = (pcr.vol_pcr || 0).toFixed(3);

    if (syncTimeEl && c) {
      syncTimeEl.textContent = `Selected Candle: ${trendData.trade_date}  ●  ${c.time} IST  (Index: ${idx + 1}/${numPoints})`;
    }
  }

  // Crosshair pointer event handler
  function handlePointerMove(e, canvasEl) {
    const rect = canvasEl.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const padL = 50;
    const padR = 60;
    const chartW = rect.width - padL - padR;

    if (chartW <= 0) return;
    const frac = Math.max(0, Math.min(1, (x - padL) / chartW));
    const newIdx = Math.round(frac * (numPoints - 1));

    if (newIdx !== hoverIndex) {
      hoverIndex = newIdx;
      updateHUD(hoverIndex);
      drawAllCanvases();
    }
  }

  [mainCanvas, oiCanvas, pcrCanvas].forEach(c => {
    c.addEventListener('mousemove', (e) => handlePointerMove(e, c));
    c.addEventListener('touchmove', (e) => {
      if (e.touches && e.touches.length > 0) {
        handlePointerMove(e.touches[0], c);
      }
    }, { passive: true });
    c.addEventListener('mouseleave', () => {
      hoverIndex = numPoints - 1;
      updateHUD(hoverIndex);
      drawAllCanvases();
    });
  });

  function drawAllCanvases() {
    renderMainPane(mainCanvas, candles, hoverIndex);
    renderCumulativeOIPane(oiCanvas, oiTrend, hoverIndex);
    renderPCRPane(pcrCanvas, pcrTrend, hoverIndex);
  }

  redrawAll = drawAllCanvases;

  // Initial draw & HUD update
  requestAnimationFrame(() => {
    updateHUD(hoverIndex);
    drawAllCanvases();
  });

  // ResizeObserver for dynamic DPI-crisp scaling
  const ro = new ResizeObserver(() => {
    drawAllCanvases();
  });
  ro.observe(container);
}

function drawEmptyNotice(canvas, text) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.parentElement.clientWidth || 400;
  const h = canvas.parentElement.clientHeight || 200;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.fillStyle = '#64748b';
  ctx.font = '12px JetBrains Mono, monospace';
  ctx.textAlign = 'center';
  ctx.fillText(text, w / 2, h / 2);
}

// -------------------------------------------------------------
// PANE 1: Candlestick + Smart OI Flow + Volume
// -------------------------------------------------------------
function renderMainPane(canvas, candles, activeIdx) {
  const dpr = window.devicePixelRatio || 1;
  const parent = canvas.parentElement;
  if (!parent) return;
  const rect = parent.getBoundingClientRect();
  const w = rect.width || parent.clientWidth || 600;
  const h = Math.max(380, rect.height || parent.clientHeight || 450);
  if (w <= 0 || h <= 0) return;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const padL = 45;
  const padR = 65;
  const padT = 15;
  const padB = 25;

  const chartW = w - padL - padR;
  const n = candles.length;
  const stepX = chartW / Math.max(1, n - 1);
  const candleW = Math.max(3, Math.min(18, stepX * 0.7));

  // Heights allocation: 60% Candles, 25% Smart OI Delta, 15% Volume
  const topChartH = (h - padT - padB) * 0.60;
  const deltaChartH = (h - padT - padB) * 0.25;
  const volChartH = (h - padT - padB) * 0.15;

  const deltaTop = padT + topChartH + 8;
  const volTop = deltaTop + deltaChartH + 8;

  // Find min/max for prices
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  let minPrice = Math.min(...lows);
  let maxPrice = Math.max(...highs);
  if (minPrice === maxPrice) { minPrice -= 20; maxPrice += 20; }
  const priceRange = (maxPrice - minPrice) * 1.08;
  const adjMinPrice = minPrice - (priceRange * 0.04);
  const adjMaxPrice = maxPrice + (priceRange * 0.04);

  // Background grids
  ctx.strokeStyle = 'rgba(51, 65, 85, 0.4)';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);

  // Horizontal price grid lines
  const steps = 5;
  for (let i = 0; i <= steps; i++) {
    const yVal = adjMinPrice + (priceRange * i) / steps;
    const yPix = padT + topChartH - ((yVal - adjMinPrice) / priceRange) * topChartH;

    ctx.beginPath();
    ctx.moveTo(padL, yPix);
    ctx.lineTo(padL + chartW, yPix);
    ctx.stroke();

    // Price label on right
    ctx.fillStyle = '#94a3b8';
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.fillText(yVal.toFixed(1), padL + chartW + 6, yPix + 3);
  }

  // Clip and Draw Candlesticks in top sub-pane
  ctx.save();
  ctx.beginPath();
  ctx.rect(padL, padT - 4, chartW, topChartH + 8);
  ctx.clip();

  candles.forEach((c, i) => {
    const cx = padL + i * stepX;
    const isBull = c.close >= c.open;
    const color = isBull ? '#10b981' : '#ef4444';

    const yHigh = padT + topChartH - ((c.high - adjMinPrice) / priceRange) * topChartH;
    const yLow = padT + topChartH - ((c.low - adjMinPrice) / priceRange) * topChartH;
    const yOpen = padT + topChartH - ((c.open - adjMinPrice) / priceRange) * topChartH;
    const yClose = padT + topChartH - ((c.close - adjMinPrice) / priceRange) * topChartH;

    // Wick
    ctx.strokeStyle = color;
    ctx.setLineDash([]);
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(cx, yHigh);
    ctx.lineTo(cx, yLow);
    ctx.stroke();

    // Body
    const bodyTop = Math.min(yOpen, yClose);
    const bodyH = Math.max(2, Math.abs(yClose - yOpen));
    ctx.fillStyle = color;
    ctx.fillRect(cx - candleW / 2, bodyTop, candleW, bodyH);
  });

  // Spot Price Guide Line
  const currentSpot = candles[candles.length - 1]?.close || 0;
  if (currentSpot > 0) {
    const spotY = padT + topChartH - ((currentSpot - adjMinPrice) / priceRange) * topChartH;
    ctx.strokeStyle = '#38bdf8';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(padL, spotY);
    ctx.lineTo(padL + chartW, spotY);
    ctx.stroke();
  }
  ctx.restore();

  // Spot Badge on Axis
  if (currentSpot > 0) {
    const spotY = Math.max(padT + 8, Math.min(padT + topChartH, padT + topChartH - ((currentSpot - adjMinPrice) / priceRange) * topChartH));
    ctx.fillStyle = '#0284c7';
    ctx.fillRect(padL + chartW + 2, spotY - 8, 56, 16);
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 9.5px JetBrains Mono, monospace';
    ctx.fillText(currentSpot.toFixed(1), padL + chartW + 5, spotY + 4);
  }

  // Divider between Candles and Smart OI
  ctx.strokeStyle = 'rgba(71, 85, 105, 0.4)';
  ctx.setLineDash([]);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padL, deltaTop - 4);
  ctx.lineTo(padL + chartW, deltaTop - 4);
  ctx.stroke();

  // -------------------------
  // PANE 2: Smart OI Delta Oscillator
  // -------------------------
  const deltas = candles.map(c => c.smart_oi || 0);
  const maxAbsDelta = Math.max(1, ...deltas.map(d => Math.abs(d)));
  const zeroY = deltaTop + deltaChartH / 2;

  // Zero Line
  ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)';
  ctx.setLineDash([]);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padL, zeroY);
  ctx.lineTo(padL + chartW, zeroY);
  ctx.stroke();

  // Smart OI label on side
  ctx.fillStyle = '#64748b';
  ctx.font = '9px Inter, sans-serif';
  ctx.fillText('Smart OI', padL + 4, deltaTop + 10);

  ctx.save();
  ctx.beginPath();
  ctx.rect(padL, deltaTop, chartW, deltaChartH);
  ctx.clip();

  deltas.forEach((d, i) => {
    const cx = padL + i * stepX;
    const barH = (Math.abs(d) / maxAbsDelta) * (deltaChartH / 2 - 4);
    const isPos = d >= 0;
    const color = isPos ? 'rgba(16, 185, 129, 0.85)' : 'rgba(239, 68, 68, 0.85)';
    const barTop = isPos ? zeroY - barH : zeroY;

    ctx.fillStyle = color;
    ctx.fillRect(cx - candleW / 2, barTop, candleW, Math.max(1.5, barH));
  });
  ctx.restore();

  // Current Smart OI Badge on right
  const currDelta = deltas[activeIdx >= 0 ? activeIdx : deltas.length - 1] || 0;
  const deltaBadgeColor = currDelta >= 0 ? '#10b981' : '#ef4444';
  ctx.fillStyle = deltaBadgeColor;
  ctx.fillRect(padL + chartW + 2, zeroY - 8, 58, 16);
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 9px JetBrains Mono, monospace';
  const deltaTxt = (currDelta / 1000).toFixed(0) + 'k';
  ctx.fillText(deltaTxt, padL + chartW + 6, zeroY + 4);

  // Divider between Smart OI and Volume
  ctx.strokeStyle = 'rgba(71, 85, 105, 0.4)';
  ctx.beginPath();
  ctx.moveTo(padL, volTop - 4);
  ctx.lineTo(padL + chartW, volTop - 4);
  ctx.stroke();

  // -------------------------
  // PANE 3: Volume Histogram
  // -------------------------
  const volumes = candles.map(c => c.volume || 0);
  const maxVol = Math.max(1, ...volumes);

  ctx.save();
  ctx.beginPath();
  ctx.rect(padL, volTop, chartW, volChartH);
  ctx.clip();

  volumes.forEach((v, i) => {
    const cx = padL + i * stepX;
    const barH = (v / maxVol) * (volChartH - 4);
    const isBull = candles[i].close >= candles[i].open;
    ctx.fillStyle = isBull ? 'rgba(16, 185, 129, 0.45)' : 'rgba(239, 68, 68, 0.45)';
    ctx.fillRect(cx - candleW / 2, volTop + volChartH - barH, candleW, barH);
  });
  ctx.restore();

  // -------------------------
  // X-AXIS TIME TICKS
  // -------------------------
  ctx.fillStyle = '#64748b';
  ctx.font = '9.5px JetBrains Mono, monospace';
  ctx.textAlign = 'center';
  const tickInterval = Math.max(1, Math.floor(n / 6));

  for (let i = 0; i < n; i += tickInterval) {
    const cx = padL + i * stepX;
    ctx.fillText(candles[i].time, cx, h - 6);
  }

  // -------------------------
  // SYNCHRONIZED CROSSHAIR
  // -------------------------
  if (activeIdx >= 0 && activeIdx < n) {
    const crossX = padL + activeIdx * stepX;
    ctx.strokeStyle = '#f8fafc';
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(crossX, padT);
    ctx.lineTo(crossX, h - padB + 2);
    ctx.stroke();

    // Time pill at bottom
    const tStr = candles[activeIdx].time;
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(crossX - 25, h - padB + 4, 50, 16);
    ctx.strokeStyle = '#38bdf8';
    ctx.strokeRect(crossX - 25, h - padB + 4, 50, 16);
    ctx.fillStyle = '#38bdf8';
    ctx.font = 'bold 9px JetBrains Mono, monospace';
    ctx.fillText(tStr, crossX, h - padB + 16);
  }
}

// -------------------------------------------------------------
// PANE 2: Cumulative OI Change (Day Trend)
// -------------------------------------------------------------
function renderCumulativeOIPane(canvas, oiTrend, activeIdx) {
  const dpr = window.devicePixelRatio || 1;
  const parent = canvas.parentElement;
  if (!parent) return;
  const rect = parent.getBoundingClientRect();
  const w = rect.width || parent.clientWidth || 500;
  const h = Math.max(170, rect.height || parent.clientHeight || 180);
  if (w <= 0 || h <= 0) return;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const padL = 35;
  const padR = 52;
  const padT = 15;
  const padB = 22;
  const chartW = w - padL - padR;
  const chartH = h - padT - padB;

  const n = oiTrend.length;
  if (n === 0) return;

  const stepX = chartW / Math.max(1, n - 1);

  // Determine scaling in Crores
  const allVals = [];
  if (showPutOI) allVals.push(...oiTrend.map(d => d.put_oi_chg || 0));
  if (showCallOI) allVals.push(...oiTrend.map(d => d.call_oi_chg || 0));
  if (showDiffOI) allVals.push(...oiTrend.map(d => d.pe_minus_ce || 0));

  let minV = allVals.length > 0 ? Math.min(0, ...allVals) : 0;
  let maxV = allVals.length > 0 ? Math.max(1, ...allVals) : 5;
  const range = (maxV - minV) * 1.15 || 1;
  const adjMin = minV - range * 0.05;

  // Grid lines
  ctx.strokeStyle = 'rgba(51, 65, 85, 0.4)';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);

  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const val = adjMin + (range * i) / steps;
    const yPix = padT + chartH - ((val - adjMin) / range) * chartH;

    ctx.beginPath();
    ctx.moveTo(padL, yPix);
    ctx.lineTo(padL + chartW, yPix);
    ctx.stroke();

    ctx.fillStyle = '#94a3b8';
    ctx.font = '9.5px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`${val.toFixed(1)}Cr`, padL + chartW + 4, yPix + 3);
  }

  function drawSeries(key, color, lineWidth = 2) {
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.setLineDash([]);
    ctx.beginPath();

    oiTrend.forEach((d, i) => {
      const cx = padL + i * stepX;
      const cy = padT + chartH - (((d[key] || 0) - adjMin) / range) * chartH;
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
    ctx.stroke();

    // Active hovered marker
    if (activeIdx >= 0 && activeIdx < n) {
      const hx = padL + activeIdx * stepX;
      const hy = padT + chartH - (((oiTrend[activeIdx][key] || 0) - adjMin) / range) * chartH;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(hx, hy, 3.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  if (showPutOI) drawSeries('put_oi_chg', '#ef4444', 2);
  if (showCallOI) drawSeries('call_oi_chg', '#10b981', 2);
  if (showDiffOI) drawSeries('pe_minus_ce', '#a855f7', 2.2);

  // Synchronized Crosshair
  if (activeIdx >= 0 && activeIdx < n) {
    const crossX = padL + activeIdx * stepX;
    ctx.strokeStyle = '#f8fafc';
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(crossX, padT);
    ctx.lineTo(crossX, h - padB + 2);
    ctx.stroke();
  }
}

// -------------------------------------------------------------
// PANE 3: Dual PCR Oscillators (OI PCR vs Vol PCR)
// -------------------------------------------------------------
function renderPCRPane(canvas, pcrTrend, activeIdx) {
  const dpr = window.devicePixelRatio || 1;
  const parent = canvas.parentElement;
  if (!parent) return;
  const rect = parent.getBoundingClientRect();
  const w = rect.width || parent.clientWidth || 500;
  const h = Math.max(150, rect.height || parent.clientHeight || 160);
  if (w <= 0 || h <= 0) return;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const padL = 35;
  const padR = 52;
  const padT = 15;
  const padB = 22;
  const chartW = w - padL - padR;
  const chartH = h - padT - padB;

  const n = pcrTrend.length;
  if (n === 0) return;

  const stepX = chartW / Math.max(1, n - 1);

  // Find min/max PCR values
  const allVals = [];
  if (showOIPCR) allVals.push(...pcrTrend.map(d => d.oi_pcr || 1.0));
  if (showVolPCR) allVals.push(...pcrTrend.map(d => d.vol_pcr || 1.0));

  let minV = allVals.length > 0 ? Math.min(...allVals) : 0.7;
  let maxV = allVals.length > 0 ? Math.max(...allVals) : 1.3;
  minV = Math.min(minV, 0.8);
  maxV = Math.max(maxV, 1.2);
  const range = (maxV - minV) * 1.15 || 0.4;
  const adjMin = minV - range * 0.05;

  // Grid lines
  ctx.strokeStyle = 'rgba(51, 65, 85, 0.4)';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);

  // Neutral 1.0 baseline
  const neutralY = padT + chartH - ((1.0 - adjMin) / range) * chartH;
  ctx.strokeStyle = 'rgba(245, 158, 11, 0.4)';
  ctx.beginPath();
  ctx.moveTo(padL, neutralY);
  ctx.lineTo(padL + chartW, neutralY);
  ctx.stroke();

  // Y-axis ticks
  const steps = 3;
  for (let i = 0; i <= steps; i++) {
    const val = adjMin + (range * i) / steps;
    const yPix = padT + chartH - ((val - adjMin) / range) * chartH;

    ctx.strokeStyle = 'rgba(51, 65, 85, 0.4)';
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(padL, yPix);
    ctx.lineTo(padL + chartW, yPix);
    ctx.stroke();

    ctx.fillStyle = '#94a3b8';
    ctx.font = '9.5px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.fillText(val.toFixed(2), padL + chartW + 4, yPix + 3);
  }

  function drawSeries(key, color, lineWidth = 2) {
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.setLineDash([]);
    ctx.beginPath();

    pcrTrend.forEach((d, i) => {
      const cx = padL + i * stepX;
      const cy = padT + chartH - (((d[key] || 1.0) - adjMin) / range) * chartH;
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
    ctx.stroke();

    if (activeIdx >= 0 && activeIdx < n) {
      const hx = padL + activeIdx * stepX;
      const hy = padT + chartH - (((pcrTrend[activeIdx][key] || 1.0) - adjMin) / range) * chartH;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(hx, hy, 3.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  if (showOIPCR) drawSeries('oi_pcr', '#38bdf8', 2);
  if (showVolPCR) drawSeries('vol_pcr', '#f59e0b', 2);

  // Synchronized Crosshair
  if (activeIdx >= 0 && activeIdx < n) {
    const crossX = padL + activeIdx * stepX;
    ctx.strokeStyle = '#f8fafc';
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(crossX, padT);
    ctx.lineTo(crossX, h - padB + 2);
    ctx.stroke();
  }
}
