/**
 * Call vs Put Open Interest Visualizations Component
 * Displays Simultaneous Dual Views:
 * - Default: NIFTY & BANKNIFTY side-by-side
 * - Secondary: FINNIFTY & MIDCPNIFTY side-by-side
 * Features:
 * - Intraday OI Timeline of ATM ± 20 strikes for smooth institutional accumulation/unwinding curves
 * - Strike OI Bar Chart (ATM ± 15 strikes default, selectable ±10, ±15, ±20)
 * - Composite StockMojo-style View: Total OI + OI Change breakdown with hatched increase & hollow decrease
 * - Floating Spot Price & Max Pain pin markers
 * - Fixed Full-Day Intraday Time Scale (09:15 AM to 15:40 PM IST)
 * - Responsive Mobile & Desktop Layout with Interactive HUD Scrubbing
 */
import { store } from '../state.js';

// Fixed Market Session Constants (IST)
const MARKET_START_MIN = 9 * 60 + 15; // 09:15 = 555 min
const MARKET_END_MIN = 15 * 60 + 40;  // 15:40 = 940 min
const TOTAL_SESSION_MIN = MARKET_END_MIN - MARKET_START_MIN; // 385 minutes

const FIXED_TIME_TICKS = [
  { time: "09:15", label: "09:15" },
  { time: "10:00", label: "10:00" },
  { time: "11:00", label: "11:00" },
  { time: "12:00", label: "12:00" },
  { time: "13:00", label: "13:00" },
  { time: "14:00", label: "14:00" },
  { time: "15:00", label: "15:00" },
  { time: "15:40", label: "15:40" }
];

function timeToMinutes(timeStr) {
  if (!timeStr || typeof timeStr !== 'string') return null;
  const parts = timeStr.split(':');
  if (parts.length < 2) return null;
  const h = parseInt(parts[0], 10);
  const m = parseInt(parts[1], 10);
  if (isNaN(h) || isNaN(m)) return null;
  return h * 60 + m;
}

let hasInitialStrikeAligned1 = false;
let hasInitialStrikeAligned2 = false;
let lastOISymbol1 = null;
let lastOISymbol2 = null;

export function renderOICharts(container, onMode1Change, onMode2Change, onStrike1Change, onStrike2Change) {
  const state = store.getState();
  const s1 = state.symbol1;
  const s2 = state.symbol2;
  const d1 = state.oiData1 || {};
  const d2 = state.oiData2 || {};
  const m1 = state.chartMode1 || 'total';
  const m2 = state.chartMode2 || 'total';
  const sm1 = state.strikeChartMode1 || 'composite';
  const sm2 = state.strikeChartMode2 || 'composite';
  const sr1 = state.strikeRange1 || 15;
  const sr2 = state.strikeRange2 || 15;

  if (lastOISymbol1 !== s1) {
    lastOISymbol1 = s1;
    hasInitialStrikeAligned1 = false;
  }
  if (lastOISymbol2 !== s2) {
    lastOISymbol2 = s2;
    hasInitialStrikeAligned2 = false;
  }

  const prevScroll1 = container.querySelector('#strike-chart-container-1')?.scrollLeft;
  const prevScroll2 = container.querySelector('#strike-chart-container-2')?.scrollLeft;

  container.innerHTML = `
    <div class="dual-symbol-grid">
      <!-- COLUMN 1: SYMBOL 1 (NIFTY by default) -->
      <div class="symbol-column">
        ${renderSymbolOIBlock(s1, d1, m1, sm1, sr1, 1)}
      </div>

      <!-- COLUMN 2: SYMBOL 2 (BANKNIFTY by default) -->
      <div class="symbol-column">
        ${renderSymbolOIBlock(s2, d2, m2, sm2, sr2, 2)}
      </div>
    </div>
  `;

  // Control listeners for Column 1
  container.querySelectorAll('[data-mode1]').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.getAttribute('data-mode1');
      if (onMode1Change) onMode1Change(mode);
    });
  });

  container.querySelectorAll('[data-smode1]').forEach(btn => {
    btn.addEventListener('click', () => {
      const smode = btn.getAttribute('data-smode1');
      store.setState({ strikeChartMode1: smode });
    });
  });

  container.querySelectorAll('[data-srange1]').forEach(btn => {
    btn.addEventListener('click', () => {
      const range = parseInt(btn.getAttribute('data-srange1'), 10);
      store.setState({ strikeRange1: range });
    });
  });

  // Control listeners for Column 2
  container.querySelectorAll('[data-mode2]').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.getAttribute('data-mode2');
      if (onMode2Change) onMode2Change(mode);
    });
  });

  container.querySelectorAll('[data-smode2]').forEach(btn => {
    btn.addEventListener('click', () => {
      const smode = btn.getAttribute('data-smode2');
      store.setState({ strikeChartMode2: smode });
    });
  });

  container.querySelectorAll('[data-srange2]').forEach(btn => {
    btn.addEventListener('click', () => {
      const range = parseInt(btn.getAttribute('data-srange2'), 10);
      store.setState({ strikeRange2: range });
    });
  });

  // Attach interactive crosshair & tooltip handlers for timelines
  attachChartInteractivity(container, 1, d1.timeline || []);
  attachChartInteractivity(container, 2, d2.timeline || []);

  // Attach interactive tooltip handlers for strike bars
  attachStrikeInteractivity(container, 1, prevScroll1);
  attachStrikeInteractivity(container, 2, prevScroll2);
}

function renderSymbolOIBlock(symbol, data, chartMode, strikeMode, strikeRange, colIndex) {
  const timeline = data.timeline || [];
  const strikes = data.strike_comparison || [];
  const walls = data.walls || {};
  const pressure = data.pressure || {};
  const spot = data.spot_price || 0;
  const atm = data.atm_strike || 0;
  const maxPain = data.max_pain || atm;
  const pcr = data.pcr || 1.0;

  const toLakhs = (num) => {
    if (!num) return '0 L';
    if (Math.abs(num) >= 10000000) return (num / 10000000).toFixed(2) + ' Cr';
    return (num / 100000).toFixed(1) + ' L';
  };

  return `
    <!-- Column Title & Live Spot -->
    <div class="symbol-col-header">
      <div class="symbol-col-title">
        <span>⚡</span>
        <span>${symbol}</span>
        <span class="logo-badge" style="color: #10b981;">● ${data.source || 'FYERS_LIVE'}</span>
      </div>
      <div class="symbol-col-spot">
        SPOT: ${spot ? spot.toLocaleString('en-IN', { minimumFractionDigits: 1 }) : '--'}
      </div>
    </div>

    <!-- 4 KPI Telemetry Strip (Responsive Grid) -->
    <div class="oi-metric-cards">
      <div class="oi-stat-card">
        <span class="oi-stat-label">PUT / CALL RATIO (PCR)</span>
        <div class="oi-stat-val ${pcr >= 1.1 ? 'text-bull' : pcr <= 0.85 ? 'text-bear' : 'text-orange'}">
          ${pcr.toFixed(2)}
        </div>
        <span class="oi-stat-sub">
          ${pcr >= 1.1 ? '● BULLISH BIAS' : pcr <= 0.85 ? '● BEARISH BIAS' : '● BALANCED RANGE'}
        </span>
      </div>

      <div class="oi-stat-card">
        <span class="oi-stat-label">WRITER PRESSURE</span>
        <div class="oi-stat-val" style="color: ${pressure.dominant_side === 'PUT_SUPPORT' ? '#10b981' : '#ef4444'}; font-size: 16px;">
          ${pressure.put_writer_pressure_pct || 50}% PE : ${pressure.call_writer_pressure_pct || 50}% CE
        </div>
        <span class="oi-stat-sub">
          ${pressure.dominant_side === 'PUT_SUPPORT' ? 'Put Support Floor' : 'Call Resistance'}
        </span>
      </div>

      <div class="oi-stat-card">
        <span class="oi-stat-label">PUT SUPPORT WALL</span>
        <div class="oi-stat-val text-bull">
          ${walls.support_strike || '--'} PE
        </div>
        <span class="oi-stat-sub">
          Strength: ${toLakhs(walls.support_oi)} Contracts
        </span>
      </div>

      <div class="oi-stat-card">
        <span class="oi-stat-label">CALL RESISTANCE WALL</span>
        <div class="oi-stat-val text-bear">
          ${walls.resistance_strike || '--'} CE
        </div>
        <span class="oi-stat-sub">
          Strength: ${toLakhs(walls.resistance_oi)} Contracts
        </span>
      </div>
    </div>

    <!-- CHART 1: INTRADAY TIMELINE GRAPH (ATM ± 20 STRIKES, FIXED 09:15 - 15:40) -->
    <div class="glass-panel">
      <div class="panel-header" style="flex-wrap: wrap; gap: 8px;">
        <div class="panel-title" style="font-size: 11.5px; display: flex; align-items: center; gap: 6px;">
          <span>📈</span>
          <span>${symbol} INTRADAY OI TIMELINE (ATM ± 20 STRIKES)</span>
        </div>

        <div class="chart-controls">
          <button class="chart-mode-btn ${chartMode === 'total' ? 'active' : ''}" data-mode${colIndex}="total">TOTAL</button>
          <button class="chart-mode-btn ${chartMode === 'change' ? 'active' : ''}" data-mode${colIndex}="change">CHANGE</button>
          <button class="chart-mode-btn ${chartMode === 'diff' ? 'active' : ''}" data-mode${colIndex}="diff">NET DIFF</button>
        </div>
      </div>

      <!-- HUD Telemetry Hover/Touch Tooltip Container -->
      <div id="chart-hud-${colIndex}" class="chart-hud-badge" style="display: none;"></div>

      <div class="svg-chart-container" id="chart-container-${colIndex}" style="height: 230px; position: relative;">
        ${renderTimelineSVG(timeline, chartMode, colIndex)}
      </div>

      <div class="chart-legend">
        ${chartMode !== 'diff' ? `
          <div class="legend-item">
            <span class="legend-dot" style="background: #10b981;"></span>
            <span>PUT OI (Bulls / Support)</span>
          </div>
          <div class="legend-item">
            <span class="legend-dot" style="background: #ef4444;"></span>
            <span>CALL OI (Bears / Resistance)</span>
          </div>
        ` : `
          <div class="legend-item">
            <span class="legend-dot" style="background: #38bdf8;"></span>
            <span>NET DIFF (CE - PE)</span>
          </div>
        `}
        <div class="legend-item" style="margin-left: auto;">
          <span class="legend-dot" style="background: #f59e0b; border-radius: 50%;"></span>
          <span>SPOT PRICE (Secondary Axis)</span>
        </div>
      </div>
    </div>

    <!-- CHART 2: STRIKE-WISE COMPARATIVE BAR CHART (ATM ± 15 STRIKES COMPOSITE) -->
    <div class="glass-panel">
      <div class="panel-header" style="flex-wrap: wrap; gap: 8px;">
        <div class="panel-title" style="font-size: 11.5px; display: flex; align-items: center; gap: 6px;">
          <span>📊</span>
          <span>${symbol} STRIKE OI (ATM ± ${strikeRange} STRIKES)</span>
        </div>

        <div class="chart-controls" style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center;">
          <!-- View Modes -->
          <div style="display: flex; gap: 3px;">
            <button class="chart-mode-btn ${strikeMode === 'composite' ? 'active' : ''}" data-smode${colIndex}="composite" title="Change stacked on Total OI">Change + Total</button>
            <button class="chart-mode-btn ${strikeMode === 'change' ? 'active' : ''}" data-smode${colIndex}="change">OI Change</button>
            <button class="chart-mode-btn ${strikeMode === 'total' ? 'active' : ''}" data-smode${colIndex}="total">Total OI</button>
          </div>

          <!-- Range Selector Buttons -->
          <div style="display: flex; gap: 3px; margin-left: 6px; border-left: 1px solid rgba(255,255,255,0.12); padding-left: 6px;">
            <button class="chart-mode-btn ${strikeRange === 10 ? 'active' : ''}" data-srange${colIndex}="10" title="ATM ± 10 strikes">±10</button>
            <button class="chart-mode-btn ${strikeRange === 15 ? 'active' : ''}" data-srange${colIndex}="15" title="ATM ± 15 strikes">±15</button>
            <button class="chart-mode-btn ${strikeRange === 20 ? 'active' : ''}" data-srange${colIndex}="20" title="ATM ± 20 strikes">±20</button>
          </div>
        </div>
      </div>

      <!-- Strike Hover Telemetry HUD -->
      <div id="strike-hud-${colIndex}" class="chart-hud-badge" style="display: none; margin-bottom: 6px;"></div>

      <div class="strike-bar-chart" id="strike-chart-container-${colIndex}">
        ${renderStrikeBarChart(strikes, atm, spot, maxPain, strikeMode, strikeRange, colIndex)}
      </div>

      <div class="chart-legend" style="flex-wrap: wrap; gap: 10px 14px; font-size: 10px;">
        <div class="legend-item">
          <span class="legend-pattern-box legend-ce-solid"></span>
          <span>Call OI</span>
        </div>
        <div class="legend-item">
          <span class="legend-pattern-box legend-ce-increase"></span>
          <span>Call OI Increase</span>
        </div>
        <div class="legend-item">
          <span class="legend-pattern-box legend-ce-decrease"></span>
          <span>Call OI Decrease</span>
        </div>
        <div class="legend-item">
          <span class="legend-pattern-box legend-pe-solid"></span>
          <span>Put OI</span>
        </div>
        <div class="legend-item">
          <span class="legend-pattern-box legend-pe-increase"></span>
          <span>Put OI Increase</span>
        </div>
        <div class="legend-item">
          <span class="legend-pattern-box legend-pe-decrease"></span>
          <span>Put OI Decrease</span>
        </div>
        <div class="legend-item" style="margin-left: auto;">
          <span class="legend-dot" style="background: rgba(245, 158, 11, 0.4); border: 1px solid #f59e0b;"></span>
          <span>ATM: ${atm}</span>
        </div>
        <div class="legend-item">
          <span class="legend-dot" style="background: #fbbf24;"></span>
          <span>Max Pain: ${maxPain || '--'}</span>
        </div>
        <div class="legend-item">
          <span class="legend-dot" style="background: #38bdf8;"></span>
          <span>Spot: ${spot ? spot.toFixed(1) : '--'}</span>
        </div>
      </div>
    </div>
  `;
}

function filterTodaySessionPoints(points) {
  if (!points || !points.length) return [];
  const latestDate = points.reduce((acc, p) => {
    const d = (p.timestamp || '').slice(0, 10);
    return d > acc ? d : acc;
  }, '');

  let filtered = points.filter(p => {
    const d = (p.timestamp || '').slice(0, 10);
    if (latestDate && d && d !== latestDate) return false;
    const m = timeToMinutes(p.time);
    return m !== null && m >= MARKET_START_MIN && m <= MARKET_END_MIN + 5;
  });

  // If time filtering yielded points, return them; otherwise if points exist, return points
  return filtered.length > 0 ? filtered : points;
}

function renderTimelineSVG(points, mode, colIndex) {
  const activePts = filterTodaySessionPoints(points);
  if (activePts.length === 0) {
    return `<div style="height: 100%; display: flex; align-items: center; justify-content: center; color: var(--text-muted); font-family: var(--font-mono); font-size: 11px;">Awaiting Intraday Snapshots (09:15 - 15:40 IST)...</div>`;
  }

  const width = 640;
  const height = 210;
  const paddingLeft = 52;
  const paddingRight = 52;
  const paddingTop = 22;
  const paddingBottom = 32;

  const chartW = width - paddingLeft - paddingRight;
  const chartH = height - paddingTop - paddingBottom;

  let val1 = [];
  let val2 = [];
  const spots = activePts.map(p => p.spot || 0);

  if (mode === 'total') {
    val1 = activePts.map(p => p.ce_oi || 0);
    val2 = activePts.map(p => p.pe_oi || 0);
  } else if (mode === 'change') {
    val1 = activePts.map(p => p.ce_oi_chg || 0);
    val2 = activePts.map(p => p.pe_oi_chg || 0);
  } else {
    val1 = activePts.map(p => (p.ce_oi || 0) - (p.pe_oi || 0));
  }

  const allOI = mode === 'diff' ? val1 : [...val1, ...val2];
  let minOI = Math.min(...allOI);
  let maxOI = Math.max(...allOI);
  if (minOI === maxOI) { minOI -= 100; maxOI += 100; }
  const oiRange = maxOI - minOI || 1;

  let minSpot = Math.min(...spots);
  let maxSpot = Math.max(...spots);
  if (minSpot === maxSpot) { minSpot -= 50; maxSpot += 50; }
  const spotRange = maxSpot - minSpot || 1;

  // STRICT FIXED TIME MAPPING: 09:15 (0%) -> 15:40 (100%)
  const getXByTimeStr = (tStr) => {
    const m = timeToMinutes(tStr);
    if (m === null) return paddingLeft;
    const clamped = Math.max(MARKET_START_MIN, Math.min(MARKET_END_MIN, m));
    const frac = (clamped - MARKET_START_MIN) / TOTAL_SESSION_MIN;
    return paddingLeft + frac * chartW;
  };

  const getY_OI = (val) => paddingTop + chartH - ((val - minOI) / oiRange) * chartH;
  const getY_Spot = (val) => paddingTop + chartH - ((val - minSpot) / spotRange) * chartH;

  // Build SVG path strings using exact clock time coordinates
  const spotPath = activePts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${getXByTimeStr(p.time).toFixed(1)} ${getY_Spot(p.spot).toFixed(1)}`).join(' ');
  const val1Path = activePts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${getXByTimeStr(p.time).toFixed(1)} ${getY_OI(val1[i]).toFixed(1)}`).join(' ');
  const val2Path = mode !== 'diff' ? activePts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${getXByTimeStr(p.time).toFixed(1)} ${getY_OI(val2[i]).toFixed(1)}`).join(' ') : '';

  const fmtLakh = (n) => {
    if (Math.abs(n) >= 10000000) return (n / 10000000).toFixed(2) + 'Cr';
    return (n / 100000).toFixed(1) + 'L';
  };

  // Current Live Marker position
  const latestPt = activePts[activePts.length - 1];
  const latestX = latestPt ? getXByTimeStr(latestPt.time) : null;
  const latestSpotY = latestPt ? getY_Spot(latestPt.spot) : null;
  const latestV1Y = latestPt ? getY_OI(val1[val1.length - 1]) : null;
  const latestV2Y = latestPt && mode !== 'diff' ? getY_OI(val2[val2.length - 1]) : null;

  return `
    <svg viewBox="0 0 ${width} ${height}" class="terminal-chart-svg" style="width: 100%; height: 100%; overflow: visible;" data-chart-col="${colIndex}">
      <defs>
        <filter id="glow-${colIndex}" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>
      </defs>

      <!-- Horizontal OI & Spot Gridlines -->
      ${[0, 0.33, 0.66, 1.0].map(frac => {
        const y = paddingTop + frac * chartH;
        const oiVal = maxOI - frac * oiRange;
        const sVal = maxSpot - frac * spotRange;
        return `
          <line x1="${paddingLeft}" y1="${y}" x2="${width - paddingRight}" y2="${y}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="2,2" />
          <text x="${paddingLeft - 6}" y="${y + 3}" fill="#64748b" font-size="9" font-family="JetBrains Mono" text-anchor="end">${fmtLakh(oiVal)}</text>
          <text x="${width - paddingRight + 6}" y="${y + 3}" fill="#f59e0b" font-size="9" font-family="JetBrains Mono" text-anchor="start">${sVal.toFixed(0)}</text>
        `;
      }).join('')}

      <!-- FIXED FULL-DAY VERTICAL TIME GRIDLINES & LABELS (09:15 to 15:40) -->
      ${FIXED_TIME_TICKS.map(tick => {
        const x = getXByTimeStr(tick.time);
        const anchor = tick.time === "09:15" ? "start" : tick.time === "15:40" ? "end" : "middle";
        return `
          <line x1="${x}" y1="${paddingTop}" x2="${x}" y2="${height - paddingBottom}" stroke="rgba(255,255,255,0.05)" stroke-dasharray="2,2" />
          <text x="${x}" y="${height - 10}" fill="#64748b" font-size="9" font-family="JetBrains Mono" text-anchor="${anchor}">
            ${tick.label}
          </text>
        `;
      }).join('')}

      <!-- Spot Price Line (Gold Dashed) -->
      <path d="${spotPath}" fill="none" stroke="#f59e0b" stroke-width="1.8" stroke-dasharray="3,3" opacity="0.85" />

      <!-- Call & Put / Diff OI Lines -->
      ${mode !== 'diff' ? `
        <path d="${val2Path}" fill="none" stroke="#10b981" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow-${colIndex})" />
        <path d="${val1Path}" fill="none" stroke="#ef4444" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow-${colIndex})" />
      ` : `
        <path d="${val1Path}" fill="none" stroke="#38bdf8" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow-${colIndex})" />
      `}

      <!-- LIVE / NOW Vertical Marker & Beacon -->
      ${latestPt && latestX ? `
        <line x1="${latestX}" y1="${paddingTop}" x2="${latestX}" y2="${height - paddingBottom}" stroke="#38bdf8" stroke-width="1.2" stroke-dasharray="3,3" opacity="0.85" />
        <rect x="${latestX - 22}" y="${paddingTop - 16}" width="44" height="14" rx="3" fill="rgba(14, 165, 233, 0.25)" stroke="#38bdf8" stroke-width="0.8"/>
        <text x="${latestX}" y="${paddingTop - 6}" fill="#38bdf8" font-size="8.5" font-family="JetBrains Mono" font-weight="700" text-anchor="middle">
          ${latestPt.time || ''}
        </text>

        <!-- Pulsing Dots at Line Heads -->
        <circle cx="${latestX}" cy="${latestSpotY}" r="3.5" fill="#f59e0b" stroke="#0f172a" stroke-width="1.5" />
        ${mode !== 'diff' ? `
          <circle cx="${latestX}" cy="${latestV2Y}" r="3.5" fill="#10b981" stroke="#0f172a" stroke-width="1.5" />
          <circle cx="${latestX}" cy="${latestV1Y}" r="3.5" fill="#ef4444" stroke="#0f172a" stroke-width="1.5" />
        ` : `
          <circle cx="${latestX}" cy="${latestV1Y}" r="3.5" fill="#38bdf8" stroke="#0f172a" stroke-width="1.5" />
        `}
      ` : ''}

      <!-- Interactive Crosshair -->
      <g id="crosshair-group-${colIndex}" style="display: none;">
        <line id="crosshair-v-${colIndex}" x1="0" y1="${paddingTop}" x2="0" y2="${height - paddingBottom}" stroke="#ffffff" stroke-width="1" stroke-dasharray="2,2" opacity="0.6"/>
        <circle id="crosshair-dot-${colIndex}" cx="0" cy="0" r="4" fill="#38bdf8" stroke="#fff" stroke-width="1.5"/>
      </g>

      <!-- Transparent Touch/Mouse Overlay for Scrubbing -->
      <rect 
        x="${paddingLeft}" 
        y="${paddingTop}" 
        width="${chartW}" 
        height="${chartH}" 
        fill="transparent" 
        style="cursor: crosshair; touch-action: none;" 
        id="chart-overlay-${colIndex}"
      />
    </svg>
  `;
}

function renderStrikeBarChart(strikes, atm, spot, maxPain, mode = 'composite', strikeRange = 15, colIndex = 1) {
  if (!strikes || strikes.length === 0) {
    return `<div style="padding: 16px; text-align: center; color: var(--text-muted); font-family: var(--font-mono); font-size: 11px;">Awaiting strike option data...</div>`;
  }

  // Slice visible strikes around ATM based on strikeRange (10, 15, or 20)
  const atmIdx = strikes.findIndex(s => s.strike === atm);
  let visibleStrikes = strikes;
  if (atmIdx !== -1) {
    const start = Math.max(0, atmIdx - strikeRange);
    const end = Math.min(strikes.length, atmIdx + strikeRange + 1);
    visibleStrikes = strikes.slice(start, end);
  } else {
    visibleStrikes = strikes.slice(0, Math.min(strikes.length, strikeRange * 2 + 1));
  }

  if (!visibleStrikes.length) return '';

  // Identify strikes closest to Spot and Max Pain for floating markers
  let closestSpotStrike = visibleStrikes[0].strike;
  let minSpotDiff = Math.abs(closestSpotStrike - spot);
  let closestMaxPainStrike = maxPain || atm;

  visibleStrikes.forEach(s => {
    const sDiff = Math.abs(s.strike - spot);
    if (sDiff < minSpotDiff) {
      minSpotDiff = sDiff;
      closestSpotStrike = s.strike;
    }
  });

  // Compute scale ceiling across visible strikes
  let maxVal = 1;
  visibleStrikes.forEach(s => {
    const cTot = Math.max(0, s.ce_oi || 0);
    const pTot = Math.max(0, s.pe_oi || 0);
    const cChg = s.ce_oi_chg || 0;
    const pChg = s.pe_oi_chg || 0;

    if (mode === 'total') {
      if (cTot > maxVal) maxVal = cTot;
      if (pTot > maxVal) maxVal = pTot;
    } else if (mode === 'change') {
      if (Math.abs(cChg) > maxVal) maxVal = Math.abs(cChg);
      if (Math.abs(pChg) > maxVal) maxVal = Math.abs(pChg);
    } else {
      // Composite (Change + Total)
      const cPeak = cChg < 0 ? cTot + Math.abs(cChg) : cTot;
      const pPeak = pChg < 0 ? pTot + Math.abs(pChg) : pTot;
      if (cPeak > maxVal) maxVal = cPeak;
      if (pPeak > maxVal) maxVal = pPeak;
    }
  });

  const toLakhs = (n) => {
    if (n === undefined || n === null) return '0 L';
    const sign = n < 0 ? '-' : '+';
    const abs = Math.abs(n);
    if (abs >= 10000000) return sign + (abs / 10000000).toFixed(2) + ' Cr';
    return sign + (abs / 100000).toFixed(1) + ' L';
  };

  const toLakhsRaw = (n) => {
    if (!n) return '0 L';
    if (n >= 10000000) return (n / 10000000).toFixed(2) + ' Cr';
    return (n / 100000).toFixed(1) + ' L';
  };

  return `
    <div class="strike-bars-row">
      ${visibleStrikes.map(s => {
        const isATM = s.strike === atm;
        const isSpot = s.strike === closestSpotStrike;
        const isMaxPain = s.strike === closestMaxPainStrike && Math.abs(s.strike - closestSpotStrike) > 0;

        const cTot = Math.max(0, s.ce_oi || 0);
        const pTot = Math.max(0, s.pe_oi || 0);
        const cChg = s.ce_oi_chg || 0;
        const pChg = s.pe_oi_chg || 0;

        let cBaseHeight = 0, cIncHeight = 0, cDecHeight = 0;
        let pBaseHeight = 0, pIncHeight = 0, pDecHeight = 0;

        if (mode === 'total') {
          cBaseHeight = Math.max(3, (cTot / maxVal) * 100);
          pBaseHeight = Math.max(3, (pTot / maxVal) * 100);
        } else if (mode === 'change') {
          if (cChg >= 0) {
            cIncHeight = Math.max(3, (cChg / maxVal) * 100);
          } else {
            cDecHeight = Math.max(3, (Math.abs(cChg) / maxVal) * 100);
          }
          if (pChg >= 0) {
            pIncHeight = Math.max(3, (pChg / maxVal) * 100);
          } else {
            pDecHeight = Math.max(3, (Math.abs(pChg) / maxVal) * 100);
          }
        } else {
          // Composite (Change + Total)
          if (cChg >= 0) {
            const baseVal = Math.max(0, cTot - cChg);
            cBaseHeight = (baseVal / maxVal) * 100;
            cIncHeight = Math.max(2, (cChg / maxVal) * 100);
          } else {
            cBaseHeight = Math.max(2, (cTot / maxVal) * 100);
            cDecHeight = Math.max(2, (Math.abs(cChg) / maxVal) * 100);
          }

          if (pChg >= 0) {
            const baseVal = Math.max(0, pTot - pChg);
            pBaseHeight = (baseVal / maxVal) * 100;
            pIncHeight = Math.max(2, (pChg / maxVal) * 100);
          } else {
            pBaseHeight = Math.max(2, (pTot / maxVal) * 100);
            pDecHeight = Math.max(2, (Math.abs(pChg) / maxVal) * 100);
          }
        }

        return `
          <div 
            class="strike-col ${isATM ? 'strike-col-atm' : ''}" 
            data-col-index="${colIndex}"
            data-strike="${s.strike}"
            data-ce-tot="${cTot}"
            data-ce-chg="${cChg}"
            data-pe-tot="${pTot}"
            data-pe-chg="${pChg}"
          >
            <!-- Floating Spot Marker -->
            ${isSpot ? `
              <div class="strike-floating-marker marker-spot">
                Spot: ${spot.toFixed(1)}
              </div>
              <div class="marker-pin-line pin-spot"></div>
            ` : ''}

            <!-- Floating Max Pain Marker -->
            ${isMaxPain ? `
              <div class="strike-floating-marker marker-maxpain">
                Max Pain: ${closestMaxPainStrike}
              </div>
              <div class="marker-pin-line pin-maxpain"></div>
            ` : ''}

            <div class="strike-bars-pair">
              <!-- CALL BAR (Green) -->
              <div class="strike-bar-composite" title="Call OI ${s.strike}: ${toLakhsRaw(cTot)} (${toLakhs(cChg)})">
                ${cDecHeight > 0 ? `<div class="strike-bar-segment bar-ce-decrease" style="height: ${cDecHeight}%;"></div>` : ''}
                ${cIncHeight > 0 ? `<div class="strike-bar-segment bar-ce-increase" style="height: ${cIncHeight}%;"></div>` : ''}
                ${cBaseHeight > 0 ? `<div class="strike-bar-segment bar-ce-solid" style="height: ${cBaseHeight}%;"></div>` : ''}
              </div>

              <!-- PUT BAR (Red) -->
              <div class="strike-bar-composite" title="Put OI ${s.strike}: ${toLakhsRaw(pTot)} (${toLakhs(pChg)})">
                ${pDecHeight > 0 ? `<div class="strike-bar-segment bar-pe-decrease" style="height: ${pDecHeight}%;"></div>` : ''}
                ${pIncHeight > 0 ? `<div class="strike-bar-segment bar-pe-increase" style="height: ${pIncHeight}%;"></div>` : ''}
                ${pBaseHeight > 0 ? `<div class="strike-bar-segment bar-pe-solid" style="height: ${pBaseHeight}%;"></div>` : ''}
              </div>
            </div>

            <!-- Strike Label Tag -->
            <div class="strike-label-tag ${isATM ? 'atm-tag' : ''}">
              ${s.strike}
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

/**
 * Attaches touch/mouse scrubbing for the intraday timeline
 */
function attachChartInteractivity(container, colIndex, timeline) {
  const overlay = container.querySelector(`#chart-overlay-${colIndex}`);
  const hud = container.querySelector(`#chart-hud-${colIndex}`);
  const crosshairGroup = container.querySelector(`#crosshair-group-${colIndex}`);
  const crosshairV = container.querySelector(`#crosshair-v-${colIndex}`);
  const crosshairDot = container.querySelector(`#crosshair-dot-${colIndex}`);

  const activeTimeline = filterTodaySessionPoints(timeline);
  if (!overlay || !hud || !activeTimeline || activeTimeline.length === 0) return;

  const width = 640;
  const paddingLeft = 52;
  const paddingRight = 52;
  const chartW = width - paddingLeft - paddingRight;

  const handlePointer = (clientX, clientY) => {
    const rect = overlay.getBoundingClientRect();
    const relX = clientX - rect.left;
    const frac = Math.max(0, Math.min(1, relX / rect.width));

    const targetMin = MARKET_START_MIN + frac * TOTAL_SESSION_MIN;

    let closestPt = null;
    let minDist = Infinity;

    for (const pt of activeTimeline) {
      const m = timeToMinutes(pt.time);
      if (m !== null) {
        const dist = Math.abs(m - targetMin);
        if (dist < minDist) {
          minDist = dist;
          closestPt = pt;
        }
      }
    }

    if (!closestPt) return;

    const ptMin = timeToMinutes(closestPt.time) || targetMin;
    const clampedMin = Math.max(MARKET_START_MIN, Math.min(MARKET_END_MIN, ptMin));
    const svgPtX = paddingLeft + ((clampedMin - MARKET_START_MIN) / TOTAL_SESSION_MIN) * chartW;

    if (crosshairGroup && crosshairV) {
      crosshairGroup.style.display = 'inline';
      crosshairV.setAttribute('x1', svgPtX);
      crosshairV.setAttribute('x2', svgPtX);
      if (crosshairDot) {
        crosshairDot.setAttribute('cx', svgPtX);
        crosshairDot.setAttribute('cy', 80);
      }
    }

    const toLakhs = (n) => {
      if (Math.abs(n) >= 10000000) return (n / 10000000).toFixed(2) + 'Cr';
      return (n / 100000).toFixed(1) + 'L';
    };
    const diff = (closestPt.ce_oi || 0) - (closestPt.pe_oi || 0);

    hud.style.display = 'flex';
    hud.innerHTML = `
      <span style="color: #38bdf8; font-weight: 700;">🕒 ${closestPt.time || '--:--'}</span>
      <span>SPOT: <b style="color: #f59e0b;">${closestPt.spot ? closestPt.spot.toFixed(1) : '--'}</b></span>
      <span>PE OI: <b style="color: #ef4444;">${toLakhs(closestPt.pe_oi)}</b></span>
      <span>CE OI: <b style="color: #10b981;">${toLakhs(closestPt.ce_oi)}</b></span>
      <span>DIFF: <b style="color: ${diff <= 0 ? '#ef4444' : '#10b981'};">${toLakhs(diff)}</b></span>
      <span>PCR: <b style="color: #38bdf8;">${closestPt.pcr ? closestPt.pcr.toFixed(2) : '--'}</b></span>
    `;
  };

  const hideHUD = () => {
    if (hud) hud.style.display = 'none';
    if (crosshairGroup) crosshairGroup.style.display = 'none';
  };

  overlay.addEventListener('mousemove', (e) => handlePointer(e.clientX, e.clientY));
  overlay.addEventListener('mouseleave', hideHUD);

  overlay.addEventListener('touchstart', (e) => {
    if (e.touches && e.touches[0]) {
      handlePointer(e.touches[0].clientX, e.touches[0].clientY);
    }
  }, { passive: true });

  overlay.addEventListener('touchmove', (e) => {
    if (e.touches && e.touches[0]) {
      handlePointer(e.touches[0].clientX, e.touches[0].clientY);
    }
  }, { passive: true });

  overlay.addEventListener('touchend', hideHUD);
}

/**
 * Attaches interactive tooltip hover/scrub for strike bars
 */
function attachStrikeInteractivity(container, colIndex, prevScroll) {
  const chartContainer = container.querySelector(`#strike-chart-container-${colIndex}`);
  const hud = container.querySelector(`#strike-hud-${colIndex}`);
  if (!chartContainer || !hud) return;

  const toLakhs = (n) => {
    if (n === undefined || n === null) return '0 L';
    const sign = n < 0 ? '-' : '+';
    const abs = Math.abs(n);
    if (abs >= 10000000) return sign + (abs / 10000000).toFixed(2) + ' Cr';
    return sign + (abs / 100000).toFixed(1) + ' L';
  };

  const toLakhsRaw = (n) => {
    if (!n) return '0 L';
    if (n >= 10000000) return (n / 10000000).toFixed(2) + ' Cr';
    return (n / 100000).toFixed(1) + ' L';
  };

  chartContainer.querySelectorAll('.strike-col').forEach(col => {
    col.addEventListener('mouseenter', () => {
      const strike = col.getAttribute('data-strike');
      const cTot = parseInt(col.getAttribute('data-ce-tot') || '0', 10);
      const cChg = parseInt(col.getAttribute('data-ce-chg') || '0', 10);
      const pTot = parseInt(col.getAttribute('data-pe-tot') || '0', 10);
      const pChg = parseInt(col.getAttribute('data-pe-chg') || '0', 10);
      const diff = pTot - cTot;

      hud.style.display = 'flex';
      hud.innerHTML = `
        <span style="color: #f59e0b; font-weight: 800;">STRIKE ${strike}</span>
        <span>CALL OI: <b style="color: #10b981;">${toLakhsRaw(cTot)} (${toLakhs(cChg)})</b></span>
        <span>PUT OI: <b style="color: #ef4444;">${toLakhsRaw(pTot)} (${toLakhs(pChg)})</b></span>
        <span>NET DIFF (PE - CE): <b style="color: ${diff >= 0 ? '#10b981' : '#ef4444'};">${toLakhs(diff)}</b></span>
        <span style="color: ${diff >= 0 ? '#10b981' : '#ef4444'}; font-weight: 700;">● ${diff >= 0 ? 'PUT SUPPORT' : 'CALL RESISTANCE'}</span>
      `;
    });
  });

  chartContainer.addEventListener('mouseleave', () => {
    hud.style.display = 'none';
  });

  // Only auto-center on ATM on initial load or symbol change
  // During live polling, preserve user's exact scroll position so it never jumps back!
  const isAligned = colIndex === 1 ? hasInitialStrikeAligned1 : hasInitialStrikeAligned2;
  if (!isAligned) {
    if (colIndex === 1) hasInitialStrikeAligned1 = true;
    else hasInitialStrikeAligned2 = true;

    const atmCol = chartContainer.querySelector('.strike-col-atm');
    if (atmCol) {
      setTimeout(() => {
        const targetScroll = atmCol.offsetLeft - (chartContainer.clientWidth / 2) + (atmCol.clientWidth / 2);
        chartContainer.scrollLeft = Math.max(0, targetScroll);
      }, 60);
    }
  } else if (prevScroll !== undefined && prevScroll !== null) {
    chartContainer.scrollLeft = prevScroll;
  }
}


