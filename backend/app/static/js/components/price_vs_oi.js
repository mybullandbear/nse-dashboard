/**
 * Price vs OI Matrix Component (StockMojo Parity)
 * Multi-pane synchronized options lab tracking any strike:
 * 1. Price (Call vs Put)
 * 2. Straddle Price + PCR
 * 3. OI (Call vs Put)
 * 4. OI Change (Call vs Put)
 * 5. CE - Price vs OI (Dual-Axis Divergence)
 * 6. PE - Price vs OI (Dual-Axis Divergence)
 * Synchronized crosshair & HUD across all 6 panels.
 */
import { store } from '../state.js';
import { ApiClient } from '../api.js';

// Component State
let activeSymbol = 'NIFTY';
let activeMode = 'HISTORICAL'; // 'LIVE' | 'HISTORICAL'
let activeDate = null;
let availableDates = [];
let activeInterval = 1; // 1, 3, 5, 15
let activeStrike = null;
let availableStrikes = [];
let expiryDates = [];
let chartData = { series: [], latest: {}, spot_price: 0, atm_strike: 0 };
let hoverIdx = null;

export async function renderPriceVsOIMatrix(container) {
  const state = store.getState();
  const isMarketOpen = Boolean(state.session?.is_market_open);
  const currentSymbol = state.symbol1 || 'NIFTY';

  if (activeSymbol !== currentSymbol && ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'].includes(currentSymbol)) {
    activeSymbol = currentSymbol;
  }

  // If master replay is active, synchronize directly to master replay date
  if (store.isReplayActive()) {
    activeMode = 'HISTORICAL';
    if (state.replay?.selectedDate && activeDate !== state.replay.selectedDate) {
      activeDate = state.replay.selectedDate;
      chartData = { series: [], latest: {}, spot_price: 0, atm_strike: 0 };
    }
  } else if (!isMarketOpen && activeMode === 'LIVE' && chartData.series.length === 0) {
    activeMode = 'HISTORICAL';
  }

  // Load available dates once if empty
  if (availableDates.length === 0) {
    try {
      const dRes = await ApiClient.fetchPriceVsOIDates(activeSymbol);
      availableDates = dRes?.dates || [];
      if (!activeDate && availableDates.length > 0) {
        activeDate = availableDates[0];
      }
    } catch (e) {
      console.debug('Error fetching dates for price-vs-oi:', e);
    }
  }

  // Load initial data if empty
  if (chartData.series.length === 0) {
    await loadData();
  }

  // Synchronize crosshair position to master replay time
  if (store.isReplayActive() && chartData.series && chartData.series.length > 0 && state.replay?.selectedTime) {
    const sTime = state.replay.selectedTime;
    let idx = chartData.series.findIndex(d => (d.time || '').slice(0, 5) >= sTime);
    if (idx === -1) idx = chartData.series.length - 1;
    hoverIdx = idx;
  }

  const existing = container.querySelector('.pvo-container');
  if (existing) {
    updateView(container);
    return;
  }

  container.innerHTML = `
    <div class="pvo-container">
      <!-- LEFT SETTINGS SIDEBAR -->
      <aside class="pvo-sidebar">
        <div class="pvo-sidebar-header">
          <span class="pvo-title">Settings</span>
          <span class="pvo-collapse-icon">«</span>
        </div>

        <!-- Symbol Selector -->
        <div class="pvo-control-group">
          <div class="pvo-symbol-picker">
            <span class="pvo-sym-tag">IDX</span>
            <select id="pvo-symbol-select" class="pvo-select-inline">
              ${['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX'].map(s => `
                <option value="${s}" ${s === activeSymbol ? 'selected' : ''}>${s}</option>
              `).join('')}
            </select>
            <div class="pvo-sym-arrows">
              <button class="pvo-arrow-btn" id="pvo-sym-prev">‹</button>
              <button class="pvo-arrow-btn" id="pvo-sym-next">›</button>
            </div>
          </div>
        </div>

        <!-- Mode Selector -->
        <div class="pvo-control-group">
          <label class="pvo-label">Select Mode</label>
          <div class="pvo-btn-group">
            <button class="pvo-btn ${activeMode === 'LIVE' ? 'active' : ''}" id="pvo-btn-live">
              ${isMarketOpen ? 'Live' : 'Live (Closed)'}
            </button>
            <button class="pvo-btn ${activeMode === 'HISTORICAL' ? 'active' : ''}" id="pvo-btn-hist">
              Historical
            </button>
          </div>
        </div>

        <!-- Date Selector -->
        <div class="pvo-control-group ${activeMode === 'HISTORICAL' ? '' : 'hidden'}" id="pvo-date-group">
          <label class="pvo-label">Date</label>
          <div class="pvo-date-picker-wrap">
            <select id="pvo-date-select" class="pvo-select-full">
              ${(availableDates.length > 0 ? availableDates : ['No Dates Found']).map(d => `
                <option value="${d}" ${d === activeDate ? 'selected' : ''}>${formatDisplayDate(d)}</option>
              `).join('')}
            </select>
            <div class="pvo-date-arrows">
              <button class="pvo-arrow-btn" id="pvo-date-prev">‹</button>
              <button class="pvo-arrow-btn" id="pvo-date-next">›</button>
            </div>
          </div>
        </div>

        <!-- Expiry Selector -->
        <div class="pvo-control-group">
          <label class="pvo-label">Expiry</label>
          <select id="pvo-expiry-select" class="pvo-select-full">
            ${(expiryDates.length > 0 ? expiryDates : ['Near Expiry']).map((exp, i) => `
              <option value="${exp}" ${i === 0 ? 'selected' : ''}>${exp}</option>
            `).join('')}
          </select>
        </div>

        <!-- Timeframe Selector -->
        <div class="pvo-control-group">
          <label class="pvo-label">Timeframe</label>
          <div class="pvo-tf-group">
            ${[1, 3, 5, 15].map(tf => `
              <button class="pvo-tf-btn ${activeInterval === tf ? 'active' : ''}" data-tf="${tf}">
                ${tf}m
              </button>
            `).join('')}
          </div>
        </div>

        <!-- Vertical Strike Selector -->
        <div class="pvo-control-group pvo-strike-group">
          <div class="pvo-strike-header">
            <span>Select Strike</span>
            <span class="pvo-strike-sub">ATM: ${chartData.atm_strike || '--'}</span>
          </div>
          <div class="pvo-strike-list" id="pvo-strike-list">
            <!-- Strike rows rendered dynamically -->
          </div>
        </div>
      </aside>

      <!-- RIGHT MAIN CONTENT: 6-PANEL SYNCHRONIZED MATRIX -->
      <main class="pvo-main">
        <!-- TOP STATUS HEADER BAR -->
        <header class="pvo-top-bar">
          <div class="pvo-bar-left">
            <span class="pvo-strike-hero" id="pvo-hero-strike">${activeStrike || chartData.atm_strike || '--'}</span>
            <span class="pvo-hero-tag">STRIKE MATRIX</span>
            <span class="pvo-hero-spot" id="pvo-hero-spot">Spot: ≈ ₹${(chartData.spot_price || 0).toLocaleString('en-IN')}</span>
          </div>
          <div class="pvo-bar-right">
            <span class="pvo-metric-pill" id="pvo-pill-straddle">Straddle: ₹${(chartData.latest?.straddle_price || 0).toFixed(2)}</span>
            <span class="pvo-metric-pill" id="pvo-pill-pcr">PCR: ${(chartData.latest?.pcr || 0).toFixed(3)}</span>
            <span class="pvo-metric-pill pvo-badge-${isMarketOpen ? 'live' : 'closed'}">
              ${isMarketOpen ? '● LIVE' : 'MARKET CLOSED'}
            </span>
          </div>
        </header>

        <!-- 6-PANEL SYNCHRONIZED CHARTS GRID -->
        <div class="pvo-charts-grid" id="pvo-charts-grid">
          <!-- CARD 1: Price (Call vs Put) -->
          <div class="pvo-chart-card" id="pvo-card-1">
            <div class="pvo-chart-header">
              <div class="pvo-chart-title">
                <span>📈 Price (Call vs Put)</span>
              </div>
              <div class="pvo-chart-legend">
                <span class="pvo-leg-item leg-ce">🟢 <span class="pvo-leg-ce-label">${activeStrike} CE Price</span></span>
                <span class="pvo-leg-item leg-pe">🔴 <span class="pvo-leg-pe-label">${activeStrike} PE Price</span></span>
                <span class="pvo-leg-item leg-pcr">🔵 PCR</span>
              </div>
            </div>
            <div class="pvo-svg-container" id="pvo-svg-wrap-1"></div>
          </div>

          <!-- CARD 2: Straddle Price + PCR -->
          <div class="pvo-chart-card" id="pvo-card-2">
            <div class="pvo-chart-header">
              <div class="pvo-chart-title">
                <span id="pvo-card2-title">${activeStrike} - Straddle Price + PCR</span>
              </div>
              <div class="pvo-chart-legend">
                <span class="pvo-leg-item leg-straddle">🔵 Straddle Price</span>
                <span class="pvo-leg-item leg-pcr">⚪ PCR</span>
              </div>
            </div>
            <div class="pvo-svg-container" id="pvo-svg-wrap-2"></div>
          </div>

          <!-- CARD 3: OI (Call vs Put) -->
          <div class="pvo-chart-card" id="pvo-card-3">
            <div class="pvo-chart-header">
              <div class="pvo-chart-title">
                <span>📊 OI (Call vs Put)</span>
              </div>
              <div class="pvo-chart-legend">
                <span class="pvo-leg-item leg-ce">🟢 <span class="pvo-leg-ce-oi-label">${activeStrike} CE OI</span></span>
                <span class="pvo-leg-item leg-pe">🔴 <span class="pvo-leg-pe-oi-label">${activeStrike} PE OI</span></span>
                <span class="pvo-leg-item leg-pcr">🔵 PCR</span>
              </div>
            </div>
            <div class="pvo-svg-container" id="pvo-svg-wrap-3"></div>
          </div>

          <!-- CARD 4: OI Change (Call vs Put) -->
          <div class="pvo-chart-card" id="pvo-card-4">
            <div class="pvo-chart-header">
              <div class="pvo-chart-title">
                <span>📊 OI Change (Call vs Put)</span>
              </div>
              <div class="pvo-chart-legend">
                <span class="pvo-leg-item leg-ce">🟢 <span class="pvo-leg-ce-oichg-label">${activeStrike} CE OI Change</span></span>
                <span class="pvo-leg-item leg-pe">🔴 <span class="pvo-leg-pe-oichg-label">${activeStrike} PE OI Change</span></span>
              </div>
            </div>
            <div class="pvo-svg-container" id="pvo-svg-wrap-4"></div>
          </div>

          <!-- CARD 5: CE - Price vs OI -->
          <div class="pvo-chart-card" id="pvo-card-5">
            <div class="pvo-chart-header">
              <div class="pvo-chart-title">
                <span id="pvo-card5-title">${activeStrike} CE - Price vs OI</span>
              </div>
              <div class="pvo-chart-legend">
                <span class="pvo-leg-item leg-ce">🟢 CE Price</span>
                <span class="pvo-leg-item leg-oi">⚪ CE OI</span>
                <span class="pvo-leg-item leg-pcr">🔵 PCR</span>
              </div>
            </div>
            <div class="pvo-svg-container" id="pvo-svg-wrap-5"></div>
          </div>

          <!-- CARD 6: PE - Price vs OI -->
          <div class="pvo-chart-card" id="pvo-card-6">
            <div class="pvo-chart-header">
              <div class="pvo-chart-title">
                <span id="pvo-card6-title">${activeStrike} PE - Price vs OI</span>
              </div>
              <div class="pvo-chart-legend">
                <span class="pvo-leg-item leg-pe">🔴 PE Price</span>
                <span class="pvo-leg-item leg-oi">⚪ PE OI</span>
                <span class="pvo-leg-item leg-pcr">🔵 PCR</span>
              </div>
            </div>
            <div class="pvo-svg-container" id="pvo-svg-wrap-6"></div>
          </div>
        </div>

        <!-- SYNCHRONIZED FLOATING HUD TOOLTIP -->
        <div class="pvo-hud-tooltip hidden" id="pvo-hud-tooltip"></div>
      </main>
    </div>
  `;

  attachEventListeners(container);
  renderStrikeList();
  renderAllCharts();
}

async function loadData() {
  try {
    const res = await ApiClient.fetchPriceVsOIData(
      activeSymbol,
      activeStrike,
      activeDate,
      activeInterval,
      activeMode
    );
    if (res) {
      chartData = res;
      if (!activeStrike && res.strike) {
        activeStrike = res.strike;
      }
      if (res.available_strikes && res.available_strikes.length > 0) {
        availableStrikes = res.available_strikes;
      }
      if (res.available_dates && res.available_dates.length > 0) {
        availableDates = res.available_dates;
        if (!activeDate) activeDate = availableDates[0];
      }
      if (res.expiry_dates && res.expiry_dates.length > 0) {
        expiryDates = res.expiry_dates;
      }
    }
  } catch (err) {
    console.debug('Error loading Price vs OI data:', err);
  }
}

function updateView(container) {
  // Update header indicators
  const heroStk = container.querySelector('#pvo-hero-strike');
  const heroSpot = container.querySelector('#pvo-hero-spot');
  const pillStraddle = container.querySelector('#pvo-pill-straddle');
  const pillPcr = container.querySelector('#pvo-pill-pcr');

  if (heroStk) heroStk.textContent = activeStrike || chartData.atm_strike || '--';
  if (heroSpot) heroSpot.textContent = `Spot: ≈ ₹${(chartData.spot_price || 0).toLocaleString('en-IN')}`;
  if (pillStraddle) pillStraddle.textContent = `Straddle: ₹${(chartData.latest?.straddle_price || 0).toFixed(2)}`;
  if (pillPcr) pillPcr.textContent = `PCR: ${(chartData.latest?.pcr || 0).toFixed(3)}`;

  // Update card titles and legend labels
  const card2Title = container.querySelector('#pvo-card2-title');
  const card5Title = container.querySelector('#pvo-card5-title');
  const card6Title = container.querySelector('#pvo-card6-title');
  if (card2Title) card2Title.textContent = `${activeStrike} - Straddle Price + PCR`;
  if (card5Title) card5Title.textContent = `${activeStrike} CE - Price vs OI`;
  if (card6Title) card6Title.textContent = `${activeStrike} PE - Price vs OI`;

  container.querySelectorAll('.pvo-leg-ce-label').forEach(el => el.textContent = `${activeStrike} CE Price`);
  container.querySelectorAll('.pvo-leg-pe-label').forEach(el => el.textContent = `${activeStrike} PE Price`);
  container.querySelectorAll('.pvo-leg-ce-oi-label').forEach(el => el.textContent = `${activeStrike} CE OI`);
  container.querySelectorAll('.pvo-leg-pe-oi-label').forEach(el => el.textContent = `${activeStrike} PE OI`);
  container.querySelectorAll('.pvo-leg-ce-oichg-label').forEach(el => el.textContent = `${activeStrike} CE OI Change`);
  container.querySelectorAll('.pvo-leg-pe-oichg-label').forEach(el => el.textContent = `${activeStrike} PE OI Change`);

  renderStrikeList();
  renderAllCharts();
}

function renderStrikeList() {
  const listEl = document.getElementById('pvo-strike-list');
  if (!listEl) return;

  if (!availableStrikes || availableStrikes.length === 0) {
    listEl.innerHTML = `<div class="pvo-empty-msg">No strikes available</div>`;
    return;
  }

  listEl.innerHTML = availableStrikes.map(s => {
    const isSelected = (s.strike === activeStrike);
    const isAtm = s.is_atm;
    return `
      <div class="pvo-strike-row ${isSelected ? 'selected' : ''}" data-strike="${s.strike}">
        <span class="pvo-stk-val">${Math.round(s.strike)}</span>
        <div class="pvo-stk-tags">
          ${isAtm ? '<span class="pvo-tag-atm">ATM</span>' : ''}
          ${isSelected ? '<span class="pvo-check">✓</span>' : ''}
        </div>
      </div>
    `;
  }).join('');

  // Attach click listener on strike rows
  listEl.querySelectorAll('.pvo-strike-row').forEach(row => {
    row.addEventListener('click', async () => {
      const stk = parseFloat(row.getAttribute('data-strike'));
      if (stk && stk !== activeStrike) {
        activeStrike = stk;
        await loadData();
        const container = document.querySelector('.pvo-container');
        if (container) updateView(container);
      }
    });
  });

  // Auto-scroll inside list container only (never scroll window)
  const selRow = listEl.querySelector('.pvo-strike-row.selected');
  if (selRow && listEl) {
    listEl.scrollTop = selRow.offsetTop - listEl.clientHeight / 2;
  }
}

function attachEventListeners(container) {
  // 1. Symbol change
  const symSelect = container.querySelector('#pvo-symbol-select');
  if (symSelect) {
    symSelect.addEventListener('change', async (e) => {
      activeSymbol = e.target.value;
      activeStrike = null;
      await loadData();
      updateView(container);
    });
  }

  const symPrev = container.querySelector('#pvo-sym-prev');
  const symNext = container.querySelector('#pvo-sym-next');
  const symbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'];
  if (symPrev) {
    symPrev.addEventListener('click', async () => {
      const idx = symbols.indexOf(activeSymbol);
      activeSymbol = symbols[(idx - 1 + symbols.length) % symbols.length];
      if (symSelect) symSelect.value = activeSymbol;
      activeStrike = null;
      await loadData();
      updateView(container);
    });
  }
  if (symNext) {
    symNext.addEventListener('click', async () => {
      const idx = symbols.indexOf(activeSymbol);
      activeSymbol = symbols[(idx + 1) % symbols.length];
      if (symSelect) symSelect.value = activeSymbol;
      activeStrike = null;
      await loadData();
      updateView(container);
    });
  }

  // 2. Mode toggle
  const btnLive = container.querySelector('#pvo-btn-live');
  const btnHist = container.querySelector('#pvo-btn-hist');
  const dateGroup = container.querySelector('#pvo-date-group');

  if (btnLive) {
    btnLive.addEventListener('click', async () => {
      activeMode = 'LIVE';
      btnLive.classList.add('active');
      btnHist.classList.remove('active');
      if (dateGroup) dateGroup.classList.add('hidden');
      await loadData();
      updateView(container);
    });
  }

  if (btnHist) {
    btnHist.addEventListener('click', async () => {
      activeMode = 'HISTORICAL';
      btnHist.classList.add('active');
      btnLive.classList.remove('active');
      if (dateGroup) dateGroup.classList.remove('hidden');
      if (!activeDate && availableDates.length > 0) activeDate = availableDates[0];
      await loadData();
      updateView(container);
    });
  }

  // 3. Date select
  const dateSelect = container.querySelector('#pvo-date-select');
  if (dateSelect) {
    dateSelect.addEventListener('change', async (e) => {
      activeDate = e.target.value;
      await loadData();
      updateView(container);
    });
  }

  const datePrev = container.querySelector('#pvo-date-prev');
  const dateNext = container.querySelector('#pvo-date-next');
  if (datePrev) {
    datePrev.addEventListener('click', async () => {
      const idx = availableDates.indexOf(activeDate);
      if (idx < availableDates.length - 1) {
        activeDate = availableDates[idx + 1];
        if (dateSelect) dateSelect.value = activeDate;
        await loadData();
        updateView(container);
      }
    });
  }
  if (dateNext) {
    dateNext.addEventListener('click', async () => {
      const idx = availableDates.indexOf(activeDate);
      if (idx > 0) {
        activeDate = availableDates[idx - 1];
        if (dateSelect) dateSelect.value = activeDate;
        await loadData();
        updateView(container);
      }
    });
  }

  // 4. Timeframe buttons
  container.querySelectorAll('.pvo-tf-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      activeInterval = parseInt(btn.getAttribute('data-tf'), 10);
      container.querySelectorAll('.pvo-tf-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      await loadData();
      updateView(container);
    });
  });

  // Global window resize
  window.addEventListener('resize', () => {
    renderAllCharts();
  });
}

function renderAllCharts() {
  const series = chartData.series || [];
  renderCard1('pvo-svg-wrap-1', series);
  renderCard2('pvo-svg-wrap-2', series);
  renderCard3('pvo-svg-wrap-3', series);
  renderCard4('pvo-svg-wrap-4', series);
  renderCard5('pvo-svg-wrap-5', series);
  renderCard6('pvo-svg-wrap-6', series);
}

// ==============================================================================
// 6 SVG CHART RENDERERS (High-DPI Vector Rendering with Synchronized Crosshairs)
// ==============================================================================

function getDims(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return { w: 400, h: 260, padL: 45, padR: 50, padT: 20, padB: 30 };
  const w = el.clientWidth || 400;
  const h = el.clientHeight || 260;
  return { w, h, padL: 45, padR: 50, padT: 20, padB: 30 };
}

/**
 * Card 1: Price (Call vs Put)
 * Green CE Price vs Red PE Price with right axis tags
 */
function renderCard1(wrapId, series) {
  const container = document.getElementById(wrapId);
  if (!container) return;
  const { w, h, padL, padR, padT, padB } = getDims(wrapId);
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  if (!series || series.length === 0) {
    container.innerHTML = renderEmptySVG(w, h, 'No Price Data');
    return;
  }

  const cePrices = series.map(d => d.ce_price);
  const pePrices = series.map(d => d.pe_price);
  const allPrices = [...cePrices, ...pePrices];

  let minP = Math.min(...allPrices);
  let maxP = Math.max(...allPrices);
  if (minP === maxP) { minP -= 10; maxP += 10; }
  const rangeP = (maxP - minP) * 1.1;
  const baseP = minP - rangeP * 0.05;

  const getX = (i) => padL + (i / Math.max(1, series.length - 1)) * innerW;
  const getY = (val) => padT + innerH - ((val - baseP) / rangeP) * innerH;

  const cePath = makeLinePath(series, (d, i) => [getX(i), getY(d.ce_price)]);
  const pePath = makeLinePath(series, (d, i) => [getX(i), getY(d.pe_price)]);

  const lastCe = cePrices[cePrices.length - 1] || 0;
  const lastPe = pePrices[pePrices.length - 1] || 0;

  const yCe = getY(lastCe);
  const yPe = getY(lastPe);

  const crosshairX = (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < series.length) ? getX(hoverIdx) : null;

  container.innerHTML = `
    <svg width="${w}" height="${h}" class="pvo-svg" data-wrap="${wrapId}">
      <rect width="${w}" height="${h}" fill="#0a0e17" />
      ${renderGrid(padL, padR, padT, padB, innerW, innerH, series)}
      
      <!-- Right Y-Axis Price Labels -->
      <text x="${w - 8}" y="${padT + 10}" text-anchor="end" class="pvo-axis-text">₹${Math.round(maxP)}</text>
      <text x="${w - 8}" y="${padT + innerH / 2}" text-anchor="end" class="pvo-axis-text">₹${Math.round((maxP + minP) / 2)}</text>
      <text x="${w - 8}" y="${padT + innerH}" text-anchor="end" class="pvo-axis-text">₹${Math.round(minP)}</text>

      <!-- CE Price Curve (Green) -->
      <path d="${cePath}" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

      <!-- PE Price Curve (Red) -->
      <path d="${pePath}" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

      <!-- Right Price Axis Tags -->
      <g transform="translate(${w - 48}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yCe - 8))})">
        <rect width="44" height="16" rx="3" fill="#10b981" />
        <text x="22" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${lastCe.toFixed(1)}</text>
      </g>
      <g transform="translate(${w - 48}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yPe - 8))})">
        <rect width="44" height="16" rx="3" fill="#ef4444" />
        <text x="22" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${lastPe.toFixed(1)}</text>
      </g>

      ${renderCrosshair(crosshairX, padT, innerH)}
      ${renderInteractiveOverlay(w, h, padL, innerW, series.length)}
    </svg>
  `;

  bindCrosshairHover(container, series);
}

/**
 * Card 2: Straddle Price + PCR
 * Blue Straddle combined premium + White/Slate PCR
 */
function renderCard2(wrapId, series) {
  const container = document.getElementById(wrapId);
  if (!container) return;
  const { w, h, padL, padR, padT, padB } = getDims(wrapId);
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  if (!series || series.length === 0) {
    container.innerHTML = renderEmptySVG(w, h, 'No Straddle Data');
    return;
  }

  const straddles = series.map(d => d.straddle_price);
  const pcrs = series.map(d => d.pcr);

  let minS = Math.min(...straddles);
  let maxS = Math.max(...straddles);
  if (minS === maxS) { minS -= 10; maxS += 10; }
  const rangeS = (maxS - minS) * 1.1;
  const baseS = minS - rangeS * 0.05;

  let minPCR = Math.min(...pcrs);
  let maxPCR = Math.max(...pcrs);
  if (minPCR === maxPCR) { minPCR -= 0.2; maxPCR += 0.2; }
  const rangePCR = Math.max(0.1, (maxPCR - minPCR) * 1.2);
  const basePCR = Math.max(0, minPCR - rangePCR * 0.05);

  const getX = (i) => padL + (i / Math.max(1, series.length - 1)) * innerW;
  const getYS = (val) => padT + innerH - ((val - baseS) / rangeS) * innerH;
  const getYPCR = (val) => padT + innerH - ((val - basePCR) / rangePCR) * innerH;

  const sPath = makeLinePath(series, (d, i) => [getX(i), getYS(d.straddle_price)]);
  const pcrPath = makeLinePath(series, (d, i) => [getX(i), getYPCR(d.pcr)]);

  const lastS = straddles[straddles.length - 1] || 0;
  const lastPCR = pcrs[pcrs.length - 1] || 0;

  const yS = getYS(lastS);
  const yPCR = getYPCR(lastPCR);
  const crosshairX = (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < series.length) ? getX(hoverIdx) : null;

  container.innerHTML = `
    <svg width="${w}" height="${h}" class="pvo-svg" data-wrap="${wrapId}">
      <rect width="${w}" height="${h}" fill="#0a0e17" />
      ${renderGrid(padL, padR, padT, padB, innerW, innerH, series)}
      
      <!-- Left Y-Axis PCR Labels -->
      <text x="${padL - 6}" y="${padT + 10}" text-anchor="end" class="pvo-axis-text">${maxPCR.toFixed(2)}</text>
      <text x="${padL - 6}" y="${padT + innerH / 2}" text-anchor="end" class="pvo-axis-text">${((maxPCR + minPCR) / 2).toFixed(2)}</text>
      <text x="${padL - 6}" y="${padT + innerH}" text-anchor="end" class="pvo-axis-text">${minPCR.toFixed(2)}</text>

      <!-- Right Y-Axis Straddle Labels -->
      <text x="${w - 8}" y="${padT + 10}" text-anchor="end" class="pvo-axis-text">₹${Math.round(maxS)}</text>
      <text x="${w - 8}" y="${padT + innerH / 2}" text-anchor="end" class="pvo-axis-text">₹${Math.round((maxS + minS) / 2)}</text>
      <text x="${w - 8}" y="${padT + innerH}" text-anchor="end" class="pvo-axis-text">₹${Math.round(minS)}</text>

      <!-- PCR Curve (Slate/Dotted) -->
      <path d="${pcrPath}" fill="none" stroke="#64748b" stroke-width="1.5" stroke-dasharray="3,3" />

      <!-- Straddle Curve (Cyan/Blue) -->
      <path d="${sPath}" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

      <!-- Left PCR Tag -->
      <g transform="translate(${padL - 38}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yPCR - 8))})">
        <rect width="36" height="16" rx="3" fill="#334155" />
        <text x="18" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${lastPCR.toFixed(2)}</text>
      </g>

      <!-- Right Straddle Tag -->
      <g transform="translate(${w - 48}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yS - 8))})">
        <rect width="44" height="16" rx="3" fill="#0284c7" />
        <text x="22" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${lastS.toFixed(1)}</text>
      </g>

      ${renderCrosshair(crosshairX, padT, innerH)}
      ${renderInteractiveOverlay(w, h, padL, innerW, series.length)}
    </svg>
  `;

  bindCrosshairHover(container, series);
}

/**
 * Card 3: OI (Call vs Put)
 * Green CE OI vs Red PE OI (in Lakhs / Crores)
 */
function renderCard3(wrapId, series) {
  const container = document.getElementById(wrapId);
  if (!container) return;
  const { w, h, padL, padR, padT, padB } = getDims(wrapId);
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  if (!series || series.length === 0) {
    container.innerHTML = renderEmptySVG(w, h, 'No OI Data');
    return;
  }

  const ceOIs = series.map(d => d.ce_oi);
  const peOIs = series.map(d => d.pe_oi);
  const allOIs = [...ceOIs, ...peOIs];

  let minOI = Math.min(...allOIs);
  let maxOI = Math.max(...allOIs);
  if (minOI === maxOI) { minOI = 0; maxOI += 100000; }
  const rangeOI = (maxOI - minOI) * 1.1;
  const baseOI = Math.max(0, minOI - rangeOI * 0.05);

  const getX = (i) => padL + (i / Math.max(1, series.length - 1)) * innerW;
  const getY = (val) => padT + innerH - ((val - baseOI) / rangeOI) * innerH;

  const cePath = makeLinePath(series, (d, i) => [getX(i), getY(d.ce_oi)]);
  const pePath = makeLinePath(series, (d, i) => [getX(i), getY(d.pe_oi)]);

  const lastCeOI = ceOIs[ceOIs.length - 1] || 0;
  const lastPeOI = peOIs[peOIs.length - 1] || 0;
  const yCe = getY(lastCeOI);
  const yPe = getY(lastPeOI);

  const crosshairX = (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < series.length) ? getX(hoverIdx) : null;

  container.innerHTML = `
    <svg width="${w}" height="${h}" class="pvo-svg" data-wrap="${wrapId}">
      <rect width="${w}" height="${h}" fill="#0a0e17" />
      ${renderGrid(padL, padR, padT, padB, innerW, innerH, series)}
      
      <!-- Right Y-Axis OI Labels -->
      <text x="${w - 8}" y="${padT + 10}" text-anchor="end" class="pvo-axis-text">${formatCompactOI(maxOI)}</text>
      <text x="${w - 8}" y="${padT + innerH / 2}" text-anchor="end" class="pvo-axis-text">${formatCompactOI((maxOI + minOI) / 2)}</text>
      <text x="${w - 8}" y="${padT + innerH}" text-anchor="end" class="pvo-axis-text">${formatCompactOI(minOI)}</text>

      <!-- CE OI Curve (Green) -->
      <path d="${cePath}" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

      <!-- PE OI Curve (Red) -->
      <path d="${pePath}" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

      <!-- Right OI Tags -->
      <g transform="translate(${w - 48}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yCe - 8))})">
        <rect width="44" height="16" rx="3" fill="#10b981" />
        <text x="22" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${formatCompactOI(lastCeOI)}</text>
      </g>
      <g transform="translate(${w - 48}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yPe - 8))})">
        <rect width="44" height="16" rx="3" fill="#ef4444" />
        <text x="22" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${formatCompactOI(lastPeOI)}</text>
      </g>

      ${renderCrosshair(crosshairX, padT, innerH)}
      ${renderInteractiveOverlay(w, h, padL, innerW, series.length)}
    </svg>
  `;

  bindCrosshairHover(container, series);
}

/**
 * Card 4: OI Change (Call vs Put)
 * Net additions / liquidations with zero line
 */
function renderCard4(wrapId, series) {
  const container = document.getElementById(wrapId);
  if (!container) return;
  const { w, h, padL, padR, padT, padB } = getDims(wrapId);
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  if (!series || series.length === 0) {
    container.innerHTML = renderEmptySVG(w, h, 'No OI Change Data');
    return;
  }

  const ceChgs = series.map(d => d.ce_oi_chg);
  const peChgs = series.map(d => d.pe_oi_chg);
  const allChgs = [...ceChgs, ...peChgs, 0];

  let minChg = Math.min(...allChgs);
  let maxChg = Math.max(...allChgs);
  if (minChg === maxChg) { minChg = -10000; maxChg = 10000; }
  const rangeChg = (maxChg - minChg) * 1.15;
  const baseChg = minChg - rangeChg * 0.05;

  const getX = (i) => padL + (i / Math.max(1, series.length - 1)) * innerW;
  const getY = (val) => padT + innerH - ((val - baseChg) / rangeChg) * innerH;

  const cePath = makeLinePath(series, (d, i) => [getX(i), getY(d.ce_oi_chg)]);
  const pePath = makeLinePath(series, (d, i) => [getX(i), getY(d.pe_oi_chg)]);
  const zeroY = getY(0);

  const lastCeChg = ceChgs[ceChgs.length - 1] || 0;
  const lastPeChg = peChgs[peChgs.length - 1] || 0;
  const yCe = getY(lastCeChg);
  const yPe = getY(lastPeChg);

  const crosshairX = (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < series.length) ? getX(hoverIdx) : null;

  container.innerHTML = `
    <svg width="${w}" height="${h}" class="pvo-svg" data-wrap="${wrapId}">
      <rect width="${w}" height="${h}" fill="#0a0e17" />
      ${renderGrid(padL, padR, padT, padB, innerW, innerH, series)}

      <!-- Zero Line -->
      <line x1="${padL}" y1="${zeroY}" x2="${padL + innerW}" y2="${zeroY}" stroke="#334155" stroke-width="1.5" stroke-dasharray="2,2" />
      
      <!-- Right Y-Axis OI Change Labels -->
      <text x="${w - 8}" y="${padT + 10}" text-anchor="end" class="pvo-axis-text">${formatCompactOI(maxChg)}</text>
      <text x="${w - 8}" y="${zeroY - 4}" text-anchor="end" class="pvo-axis-text">0</text>
      <text x="${w - 8}" y="${padT + innerH}" text-anchor="end" class="pvo-axis-text">${formatCompactOI(minChg)}</text>

      <!-- CE OI Change Curve (Green) -->
      <path d="${cePath}" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

      <!-- PE OI Change Curve (Red) -->
      <path d="${pePath}" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

      <!-- Right OI Change Tags -->
      <g transform="translate(${w - 48}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yCe - 8))})">
        <rect width="44" height="16" rx="3" fill="#10b981" />
        <text x="22" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${(lastCeChg >= 0 ? '+' : '') + formatCompactOI(lastCeChg)}</text>
      </g>
      <g transform="translate(${w - 48}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yPe - 8))})">
        <rect width="44" height="16" rx="3" fill="#ef4444" />
        <text x="22" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${(lastPeChg >= 0 ? '+' : '') + formatCompactOI(lastPeChg)}</text>
      </g>

      ${renderCrosshair(crosshairX, padT, innerH)}
      ${renderInteractiveOverlay(w, h, padL, innerW, series.length)}
    </svg>
  `;

  bindCrosshairHover(container, series);
}

/**
 * Card 5: CE - Price vs OI (Dual Axis)
 * Left: Green CE Price | Right: Grey CE OI
 */
function renderCard5(wrapId, series) {
  const container = document.getElementById(wrapId);
  if (!container) return;
  const { w, h, padL, padR, padT, padB } = getDims(wrapId);
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  if (!series || series.length === 0) {
    container.innerHTML = renderEmptySVG(w, h, 'No CE Data');
    return;
  }

  const cePrices = series.map(d => d.ce_price);
  const ceOIs = series.map(d => d.ce_oi);

  let minP = Math.min(...cePrices);
  let maxP = Math.max(...cePrices);
  if (minP === maxP) { minP -= 10; maxP += 10; }
  const rangeP = (maxP - minP) * 1.1;
  const baseP = minP - rangeP * 0.05;

  let minOI = Math.min(...ceOIs);
  let maxOI = Math.max(...ceOIs);
  if (minOI === maxOI) { minOI = 0; maxOI += 100000; }
  const rangeOI = (maxOI - minOI) * 1.1;
  const baseOI = Math.max(0, minOI - rangeOI * 0.05);

  const getX = (i) => padL + (i / Math.max(1, series.length - 1)) * innerW;
  const getYP = (val) => padT + innerH - ((val - baseP) / rangeP) * innerH;
  const getYOI = (val) => padT + innerH - ((val - baseOI) / rangeOI) * innerH;

  const pricePath = makeLinePath(series, (d, i) => [getX(i), getYP(d.ce_price)]);
  const oiPath = makeLinePath(series, (d, i) => [getX(i), getYOI(d.ce_oi)]);

  const lastP = cePrices[cePrices.length - 1] || 0;
  const lastOI = ceOIs[ceOIs.length - 1] || 0;
  const yP = getYP(lastP);
  const yOI = getYOI(lastOI);

  const crosshairX = (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < series.length) ? getX(hoverIdx) : null;

  container.innerHTML = `
    <svg width="${w}" height="${h}" class="pvo-svg" data-wrap="${wrapId}">
      <rect width="${w}" height="${h}" fill="#0a0e17" />
      ${renderGrid(padL, padR, padT, padB, innerW, innerH, series)}
      
      <!-- Left Y-Axis Price Labels -->
      <text x="${padL - 6}" y="${padT + 10}" text-anchor="end" class="pvo-axis-text">₹${Math.round(maxP)}</text>
      <text x="${padL - 6}" y="${padT + innerH / 2}" text-anchor="end" class="pvo-axis-text">₹${Math.round((maxP + minP) / 2)}</text>
      <text x="${padL - 6}" y="${padT + innerH}" text-anchor="end" class="pvo-axis-text">₹${Math.round(minP)}</text>

      <!-- Right Y-Axis OI Labels -->
      <text x="${w - 8}" y="${padT + 10}" text-anchor="end" class="pvo-axis-text">${formatCompactOI(maxOI)}</text>
      <text x="${w - 8}" y="${padT + innerH / 2}" text-anchor="end" class="pvo-axis-text">${formatCompactOI((maxOI + minOI) / 2)}</text>
      <text x="${w - 8}" y="${padT + innerH}" text-anchor="end" class="pvo-axis-text">${formatCompactOI(minOI)}</text>

      <!-- CE OI Curve (Grey/White) -->
      <path d="${oiPath}" fill="none" stroke="#64748b" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />

      <!-- CE Price Curve (Green) -->
      <path d="${pricePath}" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

      <!-- Left Price Tag -->
      <g transform="translate(${padL - 42}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yP - 8))})">
        <rect width="40" height="16" rx="3" fill="#10b981" />
        <text x="20" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${lastP.toFixed(1)}</text>
      </g>

      <!-- Right OI Tag -->
      <g transform="translate(${w - 48}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yOI - 8))})">
        <rect width="44" height="16" rx="3" fill="#475569" />
        <text x="22" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${formatCompactOI(lastOI)}</text>
      </g>

      ${renderCrosshair(crosshairX, padT, innerH)}
      ${renderInteractiveOverlay(w, h, padL, innerW, series.length)}
    </svg>
  `;

  bindCrosshairHover(container, series);
}

/**
 * Card 6: PE - Price vs OI (Dual Axis)
 * Left: Red PE Price | Right: Grey PE OI
 */
function renderCard6(wrapId, series) {
  const container = document.getElementById(wrapId);
  if (!container) return;
  const { w, h, padL, padR, padT, padB } = getDims(wrapId);
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  if (!series || series.length === 0) {
    container.innerHTML = renderEmptySVG(w, h, 'No PE Data');
    return;
  }

  const pePrices = series.map(d => d.pe_price);
  const peOIs = series.map(d => d.pe_oi);

  let minP = Math.min(...pePrices);
  let maxP = Math.max(...pePrices);
  if (minP === maxP) { minP -= 10; maxP += 10; }
  const rangeP = (maxP - minP) * 1.1;
  const baseP = minP - rangeP * 0.05;

  let minOI = Math.min(...peOIs);
  let maxOI = Math.max(...peOIs);
  if (minOI === maxOI) { minOI = 0; maxOI += 100000; }
  const rangeOI = (maxOI - minOI) * 1.1;
  const baseOI = Math.max(0, minOI - rangeOI * 0.05);

  const getX = (i) => padL + (i / Math.max(1, series.length - 1)) * innerW;
  const getYP = (val) => padT + innerH - ((val - baseP) / rangeP) * innerH;
  const getYOI = (val) => padT + innerH - ((val - baseOI) / rangeOI) * innerH;

  const pricePath = makeLinePath(series, (d, i) => [getX(i), getYP(d.pe_price)]);
  const oiPath = makeLinePath(series, (d, i) => [getX(i), getYOI(d.pe_oi)]);

  const lastP = pePrices[pePrices.length - 1] || 0;
  const lastOI = peOIs[peOIs.length - 1] || 0;
  const yP = getYP(lastP);
  const yOI = getYOI(lastOI);

  const crosshairX = (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < series.length) ? getX(hoverIdx) : null;

  container.innerHTML = `
    <svg width="${w}" height="${h}" class="pvo-svg" data-wrap="${wrapId}">
      <rect width="${w}" height="${h}" fill="#0a0e17" />
      ${renderGrid(padL, padR, padT, padB, innerW, innerH, series)}
      
      <!-- Left Y-Axis Price Labels -->
      <text x="${padL - 6}" y="${padT + 10}" text-anchor="end" class="pvo-axis-text">₹${Math.round(maxP)}</text>
      <text x="${padL - 6}" y="${padT + innerH / 2}" text-anchor="end" class="pvo-axis-text">₹${Math.round((maxP + minP) / 2)}</text>
      <text x="${padL - 6}" y="${padT + innerH}" text-anchor="end" class="pvo-axis-text">₹${Math.round(minP)}</text>

      <!-- Right Y-Axis OI Labels -->
      <text x="${w - 8}" y="${padT + 10}" text-anchor="end" class="pvo-axis-text">${formatCompactOI(maxOI)}</text>
      <text x="${w - 8}" y="${padT + innerH / 2}" text-anchor="end" class="pvo-axis-text">${formatCompactOI((maxOI + minOI) / 2)}</text>
      <text x="${w - 8}" y="${padT + innerH}" text-anchor="end" class="pvo-axis-text">${formatCompactOI(minOI)}</text>

      <!-- PE OI Curve (Grey/White) -->
      <path d="${oiPath}" fill="none" stroke="#64748b" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />

      <!-- PE Price Curve (Red) -->
      <path d="${pricePath}" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />

      <!-- Left Price Tag -->
      <g transform="translate(${padL - 42}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yP - 8))})">
        <rect width="40" height="16" rx="3" fill="#ef4444" />
        <text x="20" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${lastP.toFixed(1)}</text>
      </g>

      <!-- Right OI Tag -->
      <g transform="translate(${w - 48}, ${Math.max(padT + 8, Math.min(padT + innerH - 8, yOI - 8))})">
        <rect width="44" height="16" rx="3" fill="#475569" />
        <text x="22" y="11" text-anchor="middle" fill="#ffffff" class="pvo-pill-text">${formatCompactOI(lastOI)}</text>
      </g>

      ${renderCrosshair(crosshairX, padT, innerH)}
      ${renderInteractiveOverlay(w, h, padL, innerW, series.length)}
    </svg>
  `;

  bindCrosshairHover(container, series);
}

// ==============================================================================
// HELPER UTILITIES: PATHS, GRIDS, CROSSHAIRS & TOOLTIPS
// ==============================================================================

function makeLinePath(series, coordFn) {
  if (!series || series.length === 0) return '';
  let path = '';
  for (let i = 0; i < series.length; i++) {
    const [x, y] = coordFn(series[i], i);
    if (isNaN(x) || isNaN(y)) continue;
    path += (i === 0 ? `M ${x.toFixed(1)} ${y.toFixed(1)}` : ` L ${x.toFixed(1)} ${y.toFixed(1)}`);
  }
  return path;
}

function renderGrid(padL, padR, padT, padB, innerW, innerH, series) {
  const horizontalLines = [0.25, 0.5, 0.75].map(ratio => {
    const y = padT + innerH * ratio;
    return `<line x1="${padL}" y1="${y}" x2="${padL + innerW}" y2="${y}" stroke="rgba(255,255,255,0.05)" stroke-width="1" />`;
  }).join('');

  // X Axis markers (09:30, 11:30, 13:30, 15:30)
  const timeIndices = [
    0,
    Math.floor(series.length * 0.25),
    Math.floor(series.length * 0.5),
    Math.floor(series.length * 0.75),
    series.length - 1
  ];

  const xMarkers = timeIndices.map(idx => {
    if (!series[idx]) return '';
    const x = padL + (idx / Math.max(1, series.length - 1)) * innerW;
    const timeLabel = series[idx].time || '';
    return `
      <line x1="${x}" y1="${padT}" x2="${x}" y2="${padT + innerH}" stroke="rgba(255,255,255,0.04)" stroke-width="1" stroke-dasharray="2,2" />
      <text x="${x}" y="${padT + innerH + 18}" text-anchor="middle" class="pvo-axis-text">${timeLabel}</text>
    `;
  }).join('');

  return `${horizontalLines}${xMarkers}`;
}

function renderCrosshair(x, padT, innerH) {
  if (x === null || isNaN(x)) return '';
  return `
    <line x1="${x}" y1="${padT}" x2="${x}" y2="${padT + innerH}" stroke="#38bdf8" stroke-width="1.5" stroke-dasharray="3,3" class="pvo-crosshair-hairline" style="pointer-events: none;" />
  `;
}

function renderInteractiveOverlay(w, h, padL, innerW, totalPoints) {
  return `
    <rect class="pvo-hover-overlay" x="${padL}" y="0" width="${innerW}" height="${h}" fill="rgba(0,0,0,0.001)" pointer-events="all" style="cursor: crosshair; pointer-events: all;" />
  `;
}

function bindCrosshairHover(container, series) {
  const overlay = container.querySelector('.pvo-hover-overlay');
  if (!overlay) return;

  overlay.addEventListener('mousemove', (e) => {
    const rect = overlay.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    const idx = Math.min(series.length - 1, Math.floor(pct * series.length));

    hoverIdx = idx;
    updateCrosshairPosition(e, series[idx]);
  });

  overlay.addEventListener('mouseleave', () => {
    hoverIdx = null;
    hideCrosshairs();
  });
}

function updateCrosshairPosition(e, point) {
  if (!point) return;

  // Re-render hair lines across all charts
  document.querySelectorAll('.pvo-crosshair-hairline').forEach(el => el.remove());

  document.querySelectorAll('.pvo-svg').forEach(svg => {
    const wrapId = svg.getAttribute('data-wrap');
    const { w, padL, padR, padT, innerH } = getDims(wrapId);
    const innerW = w - padL - padR;
    const series = chartData.series || [];
    if (series.length > 0 && hoverIdx !== null) {
      const x = padL + (hoverIdx / Math.max(1, series.length - 1)) * innerW;
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', x);
      line.setAttribute('y1', padT);
      line.setAttribute('x2', x);
      line.setAttribute('y2', padT + innerH);
      line.setAttribute('stroke', '#38bdf8');
      line.setAttribute('stroke-width', '1.5');
      line.setAttribute('stroke-dasharray', '3,3');
      line.setAttribute('class', 'pvo-crosshair-hairline');
      line.style.pointerEvents = 'none';
      svg.appendChild(line);
    }
  });

  // Render Synchronized Tooltip
  showHUDTooltip(e, point);
}

function showHUDTooltip(e, p) {
  const tooltip = document.getElementById('pvo-hud-tooltip');
  if (!tooltip) return;

  const cePchg = (p.ce_oi_chg >= 0 ? '+' : '') + formatCompactOI(p.ce_oi_chg);
  const pePchg = (p.pe_oi_chg >= 0 ? '+' : '') + formatCompactOI(p.pe_oi_chg);

  // Sentiment analysis
  let insight = "Neutral Positioning";
  if (p.ce_oi_chg > p.pe_oi_chg && p.ce_price < p.pe_price) {
    insight = "Call Writing Wall Dominating (Bearish Resistance)";
  } else if (p.pe_oi_chg > p.ce_oi_chg && p.pe_price < p.ce_price) {
    insight = "Put Writing Support Cushion (Bullish Floor)";
  } else if (p.ce_price > p.pe_price && p.pcr > 1.2) {
    insight = "Call Momentum / Bulls Expanding";
  }

  tooltip.innerHTML = `
    <div class="pvo-hud-header">
      <span class="pvo-hud-time">🕒 ${p.time || '--:--'}</span>
      <span class="pvo-hud-strike-tag">${activeStrike} Matrix</span>
    </div>

    <div class="pvo-hud-grid">
      <div class="pvo-hud-cell">
        <span class="pvo-hud-k">CE Price</span>
        <span class="pvo-hud-v mono text-green">₹${p.ce_price.toFixed(2)}</span>
      </div>
      <div class="pvo-hud-cell">
        <span class="pvo-hud-k">PE Price</span>
        <span class="pvo-hud-v mono text-red">₹${p.pe_price.toFixed(2)}</span>
      </div>
      <div class="pvo-hud-cell">
        <span class="pvo-hud-k">Straddle Premium</span>
        <span class="pvo-hud-v mono text-cyan">₹${p.straddle_price.toFixed(2)}</span>
      </div>
      <div class="pvo-hud-cell">
        <span class="pvo-hud-k">Strike PCR</span>
        <span class="pvo-hud-v mono text-white">${p.pcr.toFixed(3)}</span>
      </div>
      <div class="pvo-hud-cell">
        <span class="pvo-hud-k">CE Open Interest</span>
        <span class="pvo-hud-v mono text-green">${formatCompactOI(p.ce_oi)} (${cePchg})</span>
      </div>
      <div class="pvo-hud-cell">
        <span class="pvo-hud-k">PE Open Interest</span>
        <span class="pvo-hud-v mono text-red">${formatCompactOI(p.pe_oi)} (${pePchg})</span>
      </div>
    </div>

    <div class="pvo-hud-insight">
      <span class="pvo-insight-bulb">💡</span>
      <span class="pvo-insight-txt">${insight}</span>
    </div>
  `;

  tooltip.classList.remove('hidden');
  positionTooltip(e);
}

function positionTooltip(e) {
  const tooltip = document.getElementById('pvo-hud-tooltip');
  if (!tooltip) return;

  const pad = 16;
  let x = e.clientX + pad;
  let y = e.clientY + pad;

  if (x + 320 > window.innerWidth) {
    x = e.clientX - 330;
  }
  if (y + 220 > window.innerHeight) {
    y = e.clientY - 230;
  }

  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
}

function hideCrosshairs() {
  document.querySelectorAll('.pvo-crosshair-hairline').forEach(el => el.remove());
  const tooltip = document.getElementById('pvo-hud-tooltip');
  if (tooltip) tooltip.classList.add('hidden');
}

function renderEmptySVG(w, h, msg) {
  return `
    <svg width="${w}" height="${h}" class="pvo-svg">
      <rect width="${w}" height="${h}" fill="#0a0e17" />
      <text x="${w / 2}" y="${h / 2}" text-anchor="middle" fill="#475569" font-size="12" font-family="var(--font-mono)">
        ${msg}
      </text>
    </svg>
  `;
}

function formatCompactOI(val) {
  if (val === null || val === undefined) return '0';
  const abs = Math.abs(val);
  const sign = val < 0 ? '-' : '';
  if (abs >= 10000000) {
    return sign + (abs / 10000000).toFixed(2) + 'Cr';
  } else if (abs >= 100000) {
    return sign + (abs / 100000).toFixed(2) + 'L';
  } else if (abs >= 1000) {
    return sign + (abs / 1000).toFixed(1) + 'k';
  }
  return sign + Math.round(abs);
}

function formatDisplayDate(dateStr) {
  if (!dateStr) return '';
  try {
    const [y, m, d] = dateStr.split('-');
    const date = new Date(parseInt(y), parseInt(m) - 1, parseInt(d));
    return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  } catch (e) {
    return dateStr;
  }
}
