/**
 * Strike Buildup Lab Component (4-Quadrant Bubble Scatter Matrix)
 * Dual Side-by-Side:
 * - Column 1: Symbol 1 (NIFTY by default) ATM +- 5 Strikes
 * - Column 2: Symbol 2 (BANKNIFTY by default) ATM +- 5 Strikes
 * Features:
 * - Live vs Historical Available Data Toggle Button
 * - Historical Date Picker Dropdown
 * - ZERO Dummy Data Policy: 100% real market & database snapshots
 * - Real-Time Live Graph Updates During Market Hours (09:15 - 15:30 IST)
 * - Dynamic Quadrant Bubble Matrix (OI % vs Price %)
 * - Clear CE vs PE Badging and ATM Halo Highlights
 * - Intelligent Option Seller Implication Tooltips
 * - Interactive Intraday Time Scrubber & Auto-Playback
 */
import { store } from '../state.js';
import { ApiClient } from '../api.js';

let activeRange = 5; // 5, 7, 10
let activeFilter = 'ALL'; // 'ALL', 'CE', 'PE'
let activeMode = 'LIVE'; // 'LIVE' | 'HISTORICAL'
let activeDate = null;
let availableDates = [];
let isPlaybackMode = false;
let isPlaying = false;
let playTimer = null;
let currentScrubIndex = -1;
let timelineData1 = [];
let timelineData2 = [];
let liveData1 = null;
let liveData2 = null;

export async function renderStrikeBuildupLab(container) {
  const state = store.getState();
  const s1 = state.symbol1 || 'NIFTY';
  const s2 = state.symbol2 || 'BANKNIFTY';
  const isMarketOpen = Boolean(state.session?.is_market_open);

  // Load available dates once
  if (availableDates.length === 0) {
    try {
      const dRes = await ApiClient.fetchStrikeDates(s1);
      availableDates = dRes?.dates || [];
      if (!activeDate && availableDates.length > 0) {
        activeDate = availableDates[0];
      }
    } catch (e) {
      console.debug('Error fetching available strike dates:', e);
    }
  }

  // If master replay is active, synchronize directly to master replay date & time
  if (store.isReplayActive()) {
    activeMode = 'HISTORICAL';
    isPlaybackMode = true;
    if (state.replay?.selectedDate) activeDate = state.replay.selectedDate;
  } else if (!isMarketOpen && activeMode === 'LIVE' && timelineData1.length === 0) {
    activeMode = 'HISTORICAL';
    isPlaybackMode = true;
  }

  // Pre-load data depending on active mode
  if (activeMode === 'HISTORICAL') {
    if (!activeDate && availableDates.length > 0) {
      activeDate = availableDates[0];
    }
    if (activeDate && (timelineData1.length === 0 || (store.isReplayActive() && timelineData1[0]?.date !== activeDate))) {
      await loadTimelines(s1, s2, activeDate);
      if (timelineData1.length > 0) {
        currentScrubIndex = timelineData1.length - 1;
      }
    }
    if (store.isReplayActive() && timelineData1.length > 0 && state.replay?.selectedTime) {
      const matchIdx = timelineData1.findIndex(s => s.time >= state.replay.selectedTime);
      if (matchIdx !== -1) currentScrubIndex = matchIdx;
    }
  } else if (!liveData1) {
    await fetchLiveData(s1, s2);
  }

  const existingWrapper = container.querySelector('.strike-lab-wrapper');
  if (existingWrapper) {
    if (activeMode === 'LIVE') {
      await fetchLiveData(s1, s2);
      drawQuadrants();
    } else if (activeMode === 'HISTORICAL') {
      if (timelineData1.length === 0 || (store.isReplayActive() && timelineData1[0]?.date !== activeDate)) {
        await loadTimelines(s1, s2, activeDate);
      }
      if (store.isReplayActive() && timelineData1.length > 0 && state.replay?.selectedTime) {
        const matchIdx = timelineData1.findIndex(s => s.time >= state.replay.selectedTime);
        if (matchIdx !== -1) currentScrubIndex = matchIdx;
      }
      drawQuadrants();
    }
    return;
  }

  const lastTime = (timelineData1.length > 0 && currentScrubIndex >= 0 && timelineData1[currentScrubIndex])
    ? timelineData1[currentScrubIndex].time
    : (activeMode === 'LIVE' ? 'LIVE' : '15:30');
  const initialBubble = (activeMode === 'LIVE') ? (isMarketOpen ? 'LIVE' : 'CLOSED') : lastTime;
  const initialScrub = (activeMode === 'LIVE') ? (isMarketOpen ? 'LIVE' : 'MARKET CLOSED') : `${activeDate || ''} ${lastTime}`;

  container.innerHTML = `
    <div class="strike-lab-wrapper">
      <!-- TOP CONTROLS & FILTER TOOLBAR -->
      <div class="strike-lab-toolbar">
        <div class="toolbar-left">
          <!-- Active Pair Display -->
          <div class="sl-pair-badge">
            <span class="sl-dot ${isMarketOpen ? 'live-pulse' : 'market-closed-dot'}"></span>
            <span class="sl-pair-text">${s1} & ${s2}</span>
            ${!isMarketOpen ? `<span class="sl-status-closed-tag">MARKET CLOSED</span>` : ''}
          </div>

          <!-- Live vs Historical Toggle Buttons -->
          <div class="sl-btn-group" id="sl-mode-group" title="Toggle Live Market vs Historical Data">
            <button class="sl-btn ${activeMode === 'LIVE' ? 'active' : ''}" id="sl-btn-mode-live">${isMarketOpen ? '⚡ Live' : '⚡ Live (Closed)'}</button>
            <button class="sl-btn ${activeMode === 'HISTORICAL' ? 'active' : ''}" id="sl-btn-mode-hist">📅 Historical</button>
          </div>

          <!-- Historical Date Selector Dropdown -->
          <div class="sl-control-item ${activeMode === 'HISTORICAL' ? '' : 'hidden'}" id="sl-date-picker-wrap">
            <select id="sl-date-select" class="sl-select-styled" title="Select Historical Date">
              ${(availableDates.length > 0 ? availableDates : ['No Dates Found']).map(d => `
                <option value="${d}" ${d === activeDate ? 'selected' : ''}>${d}</option>
              `).join('')}
            </select>
          </div>

          <!-- Strike Range Buttons -->
          <div class="sl-btn-group" id="sl-range-group" title="Select number of strikes around ATM">
            <button class="sl-btn ${activeRange === 5 ? 'active' : ''}" data-range="5">±5 Strikes</button>
            <button class="sl-btn ${activeRange === 7 ? 'active' : ''}" data-range="7">±7 Strikes</button>
            <button class="sl-btn ${activeRange === 10 ? 'active' : ''}" data-range="10">±10 Strikes</button>
          </div>

          <!-- CE / PE Filter -->
          <div class="sl-btn-group" id="sl-filter-group" title="Filter Option Contracts">
            <button class="sl-btn ${activeFilter === 'ALL' ? 'active' : ''}" data-filter="ALL">All (CE + PE)</button>
            <button class="sl-btn ${activeFilter === 'CE' ? 'active' : ''}" data-filter="CE">Calls (CE)</button>
            <button class="sl-btn ${activeFilter === 'PE' ? 'active' : ''}" data-filter="PE">Puts (PE)</button>
          </div>
        </div>

        <!-- Quadrant Legend & Live Counts -->
        <div class="toolbar-right">
          <div class="sl-legend-item legend-lb">
            <span class="sl-legend-dot" style="background:#10b981;"></span>
            <span class="sl-legend-label">Long Buildup</span>
            <span class="sl-legend-count" id="count-lb">0</span>
          </div>
          <div class="sl-legend-item legend-sb">
            <span class="sl-legend-dot" style="background:#ef4444;"></span>
            <span class="sl-legend-label">Short Buildup</span>
            <span class="sl-legend-count" id="count-sb">0</span>
          </div>
          <div class="sl-legend-item legend-sc">
            <span class="sl-legend-dot" style="background:#06b6d4;"></span>
            <span class="sl-legend-label">Short Covering</span>
            <span class="sl-legend-count" id="count-sc">0</span>
          </div>
          <div class="sl-legend-item legend-lu">
            <span class="sl-legend-dot" style="background:#f59e0b;"></span>
            <span class="sl-legend-label">Long Unwinding</span>
            <span class="sl-legend-count" id="count-lu">0</span>
          </div>
        </div>
      </div>

      <!-- DUAL SIDE-BY-SIDE QUADRANT MATRIX -->
      <div class="strike-lab-grid">
        <!-- COLUMN 1: SYMBOL 1 (NIFTY) -->
        <div class="strike-column" id="strike-col-1">
          <div class="strike-col-header">
            <div class="col-header-left">
              <span class="col-symbol-title">${s1} STRIKE QUADRANT</span>
              <span class="col-atm-badge" id="atm-badge-1">ATM: --</span>
            </div>
            <div class="col-header-right">
              <span class="col-spot-text" id="spot-text-1">Spot: --</span>
            </div>
          </div>
          <div class="quadrant-canvas-container" id="canvas-wrap-1">
            <!-- SVG rendered here -->
          </div>
        </div>

        <!-- COLUMN 2: SYMBOL 2 (BANKNIFTY) -->
        <div class="strike-column" id="strike-col-2">
          <div class="strike-col-header">
            <div class="col-header-left">
              <span class="col-symbol-title">${s2} STRIKE QUADRANT</span>
              <span class="col-atm-badge" id="atm-badge-2">ATM: --</span>
            </div>
            <div class="col-header-right">
              <span class="col-spot-text" id="spot-text-2">Spot: --</span>
            </div>
          </div>
          <div class="quadrant-canvas-container" id="canvas-wrap-2">
            <!-- SVG rendered here -->
          </div>
        </div>
      </div>

      <!-- BOTTOM TIME SCRUBBER & PLAYBACK CONTROLS -->
      <div class="strike-lab-playback">
        <div class="playback-controls">
          <button class="playback-btn" id="btn-play-pause" title="Play/Pause Replay">
            <span id="play-icon">▶</span>
            <span id="play-label">PLAY</span>
          </button>
          <button class="playback-btn live-btn ${activeMode === 'LIVE' && !isPlaybackMode ? 'active' : ''}" id="btn-live" title="Switch to Real-Time Live Feed">
            <span class="live-dot-mini"></span>
            <span>LIVE</span>
          </button>
        </div>

        <!-- Slider Bar with Time Markers -->
        <div class="slider-track-wrap">
          <span class="time-limit-label">09:16 AM</span>
          <div class="slider-container">
            <input type="range" min="0" max="100" value="100" class="time-slider" id="time-slider" />
            <div class="slider-bubble" id="slider-bubble">${initialBubble}</div>
          </div>
          <span class="time-limit-label">03:30 PM</span>
        </div>

        <!-- Current Scrubbed Time Display -->
        <div class="playback-time-badge" id="scrub-time-display">
          <span class="clock-icon">🕒</span>
          <span id="scrubbed-time-text">${initialScrub}</span>
        </div>
      </div>

      <!-- HUD Floating Tooltip -->
      <div class="strike-hud-tooltip hidden" id="strike-hud-tooltip"></div>
    </div>
  `;

  attachEventListeners(container, s1, s2);
  drawQuadrants();
}

async function fetchLiveData(s1, s2) {
  try {
    const [d1, d2] = await Promise.all([
      ApiClient.fetchStrikeBuildup(s1, activeRange),
      ApiClient.fetchStrikeBuildup(s2, activeRange)
    ]);
    liveData1 = d1;
    liveData2 = d2;
  } catch (err) {
    console.debug('Error fetching live strike buildup:', err);
  }
}

async function loadTimelines(s1, s2, date = null) {
  try {
    const [t1, t2] = await Promise.all([
      ApiClient.fetchStrikeTimeline(s1, activeRange, date),
      ApiClient.fetchStrikeTimeline(s2, activeRange, date)
    ]);
    timelineData1 = t1?.timeline || [];
    timelineData2 = t2?.timeline || [];
  } catch (err) {
    console.debug('Error fetching strike timelines:', err);
  }
}

function attachEventListeners(container, s1, s2) {
  // 1. Live vs Historical Mode Toggle
  const btnLive = container.querySelector('#sl-btn-mode-live');
  const btnHist = container.querySelector('#sl-btn-mode-hist');
  const datePickerWrap = container.querySelector('#sl-date-picker-wrap');
  const dateSelect = container.querySelector('#sl-date-select');
  const slider = container.querySelector('#time-slider');
  const sliderBubble = container.querySelector('#slider-bubble');
  const scrubTimeText = container.querySelector('#scrubbed-time-text');
  const liveBtnBottom = container.querySelector('#btn-live');

  if (btnLive) {
    btnLive.addEventListener('click', async () => {
      activeMode = 'LIVE';
      isPlaybackMode = false;
      pausePlayback();
      btnLive.classList.add('active');
      btnHist.classList.remove('active');
      liveBtnBottom.classList.add('active');
      if (datePickerWrap) datePickerWrap.classList.add('hidden');
      slider.value = 100;
      const isMarketLive = Boolean(store.getState()?.session?.is_market_open);
      sliderBubble.textContent = isMarketLive ? 'LIVE' : 'CLOSED';
      scrubTimeText.textContent = isMarketLive ? 'LIVE' : 'MARKET CLOSED';
      await fetchLiveData(s1, s2);
      drawQuadrants();
    });
  }

  if (btnHist) {
    btnHist.addEventListener('click', async () => {
      activeMode = 'HISTORICAL';
      isPlaybackMode = true;
      pausePlayback();
      btnHist.classList.add('active');
      btnLive.classList.remove('active');
      liveBtnBottom.classList.remove('active');
      if (datePickerWrap) datePickerWrap.classList.remove('hidden');

      if (availableDates.length === 0) {
        const dRes = await ApiClient.fetchStrikeDates(s1);
        availableDates = dRes?.dates || [];
        if (dateSelect) {
          dateSelect.innerHTML = (availableDates.length > 0 ? availableDates : ['No Dates Found']).map(d => `
            <option value="${d}" ${d === activeDate ? 'selected' : ''}>${d}</option>
          `).join('');
        }
      }
      if (!activeDate && availableDates.length > 0) {
        activeDate = availableDates[0];
      }

      await loadTimelines(s1, s2, activeDate);
      if (timelineData1.length > 0) {
        currentScrubIndex = timelineData1.length - 1;
        const lastTime = timelineData1[currentScrubIndex]?.time || '15:30';
        slider.value = 100;
        sliderBubble.textContent = lastTime;
        scrubTimeText.textContent = `${activeDate} ${lastTime}`;
      } else {
        currentScrubIndex = -1;
        slider.value = 0;
        sliderBubble.textContent = 'NO DATA';
        scrubTimeText.textContent = `${activeDate} (No Data)`;
      }
      drawQuadrants();
    });
  }

  // 2. Historical Date Selection Change
  if (dateSelect) {
    dateSelect.addEventListener('change', async (e) => {
      activeDate = e.target.value;
      pausePlayback();
      await loadTimelines(s1, s2, activeDate);
      if (timelineData1.length > 0) {
        currentScrubIndex = timelineData1.length - 1;
        const lastTime = timelineData1[currentScrubIndex]?.time || '15:30';
        slider.value = 100;
        sliderBubble.textContent = lastTime;
        scrubTimeText.textContent = `${activeDate} ${lastTime}`;
      } else {
        currentScrubIndex = -1;
        slider.value = 0;
        sliderBubble.textContent = 'NO DATA';
        scrubTimeText.textContent = `${activeDate} (No Data)`;
      }
      drawQuadrants();
    });
  }

  // 3. Strike Range
  container.querySelectorAll('#sl-range-group button').forEach(btn => {
    btn.addEventListener('click', async () => {
      activeRange = parseInt(btn.getAttribute('data-range'), 10);
      container.querySelectorAll('#sl-range-group button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (activeMode === 'LIVE') {
        await fetchLiveData(s1, s2);
      } else {
        await loadTimelines(s1, s2, activeDate);
      }
      drawQuadrants();
    });
  });

  // 4. CE / PE Filter
  container.querySelectorAll('#sl-filter-group button').forEach(btn => {
    btn.addEventListener('click', () => {
      activeFilter = btn.getAttribute('data-filter');
      container.querySelectorAll('#sl-filter-group button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      drawQuadrants();
    });
  });

  // 5. Play / Pause Button
  const playBtn = container.querySelector('#btn-play-pause');
  if (playBtn) {
    playBtn.addEventListener('click', async () => {
      if (activeMode === 'LIVE' && !isPlaybackMode) {
        isPlaybackMode = true;
        liveBtnBottom.classList.remove('active');
        if (timelineData1.length === 0) {
          await loadTimelines(s1, s2, activeDate);
        }
        if (currentScrubIndex < 0) currentScrubIndex = 0;
      }

      if (isPlaying) {
        pausePlayback();
      } else {
        startPlayback();
      }
    });
  }

  // 6. Bottom Live Button
  if (liveBtnBottom) {
    liveBtnBottom.addEventListener('click', async () => {
      pausePlayback();
      activeMode = 'LIVE';
      isPlaybackMode = false;
      liveBtnBottom.classList.add('active');
      if (btnLive) btnLive.classList.add('active');
      if (btnHist) btnHist.classList.remove('active');
      if (datePickerWrap) datePickerWrap.classList.add('hidden');
      slider.value = 100;
      sliderBubble.textContent = 'LIVE';
      scrubTimeText.textContent = 'LIVE';
      await fetchLiveData(s1, s2);
      drawQuadrants();
    });
  }

  // 7. Time Slider Scrubbing
  if (slider) {
    slider.addEventListener('input', async (e) => {
      const val = parseInt(e.target.value, 10);
      if (activeMode === 'LIVE' && !isPlaybackMode) {
        isPlaybackMode = true;
        liveBtnBottom.classList.remove('active');
        if (timelineData1.length === 0) {
          await loadTimelines(s1, s2, activeDate);
        }
      }
      pausePlayback();

      if (timelineData1.length > 0) {
        const idx = Math.min(
          timelineData1.length - 1,
          Math.floor((val / 100) * (timelineData1.length - 1))
        );
        currentScrubIndex = idx;
        const timeStr = timelineData1[idx]?.time || '09:16';
        sliderBubble.textContent = timeStr;
        scrubTimeText.textContent = activeMode === 'HISTORICAL' ? `${activeDate} ${timeStr}` : timeStr;
        drawQuadrants();
      }
    });
  }
}

function startPlayback() {
  if (!timelineData1 || timelineData1.length === 0) return;
  isPlaying = true;
  const playIcon = document.getElementById('play-icon');
  const playLabel = document.getElementById('play-label');
  if (playIcon) playIcon.textContent = '⏸';
  if (playLabel) playLabel.textContent = 'PAUSE';

  if (playTimer) clearInterval(playTimer);
  playTimer = setInterval(() => {
    if (!timelineData1 || timelineData1.length === 0) return;

    currentScrubIndex++;
    if (currentScrubIndex >= timelineData1.length) {
      currentScrubIndex = 0;
    }

    const slider = document.getElementById('time-slider');
    const sliderBubble = document.getElementById('slider-bubble');
    const scrubTimeText = document.getElementById('scrubbed-time-text');

    const pct = Math.round((currentScrubIndex / (timelineData1.length - 1)) * 100);
    if (slider) slider.value = pct;
    const timeStr = timelineData1[currentScrubIndex]?.time || '09:16';
    if (sliderBubble) sliderBubble.textContent = timeStr;
    if (scrubTimeText) scrubTimeText.textContent = activeMode === 'HISTORICAL' ? `${activeDate} ${timeStr}` : timeStr;

    drawQuadrants();
  }, 900);
}

function pausePlayback() {
  isPlaying = false;
  if (playTimer) clearInterval(playTimer);
  const playIcon = document.getElementById('play-icon');
  const playLabel = document.getElementById('play-label');
  if (playIcon) playIcon.textContent = '▶';
  if (playLabel) playLabel.textContent = 'PLAY';
}

function getActiveStrikes(colIdx) {
  if (activeMode === 'HISTORICAL' || isPlaybackMode) {
    const timeline = (colIdx === 1) ? timelineData1 : timelineData2;
    if (!timeline || timeline.length === 0 || currentScrubIndex < 0) return [];
    const slot = timeline[Math.max(0, Math.min(currentScrubIndex, timeline.length - 1))];
    return slot?.strikes || [];
  } else {
    const live = (colIdx === 1) ? liveData1 : liveData2;
    return live?.strikes || [];
  }
}

function getHeaderInfo(colIdx) {
  if (activeMode === 'HISTORICAL' || isPlaybackMode) {
    const timeline = (colIdx === 1) ? timelineData1 : timelineData2;
    const strikes = getActiveStrikes(colIdx);
    const atmObj = strikes.find(s => s.is_atm);
    const atm = atmObj ? atmObj.strike : (strikes.length > 0 ? strikes[Math.floor(strikes.length / 2)].strike : '--');
    const spot = atm !== '--' ? `≈ ₹${Number(atm).toLocaleString('en-IN')}` : '--';
    const timeVal = (timeline && currentScrubIndex >= 0 && timeline[currentScrubIndex]) ? timeline[currentScrubIndex].time : (activeDate || 'HISTORICAL');
    return {
      atm: atm,
      spot: spot,
      time: timeVal
    };
  } else {
    const live = (colIdx === 1) ? liveData1 : liveData2;
    return {
      atm: live?.atm_strike || '--',
      spot: live?.spot_price ? `₹${live.spot_price.toLocaleString('en-IN')}` : '--',
      time: live?.time || 'LIVE'
    };
  }
}

function drawQuadrants() {
  const strikes1 = filterStrikes(getActiveStrikes(1));
  const strikes2 = filterStrikes(getActiveStrikes(2));

  // Update header titles & badges
  const h1 = getHeaderInfo(1);
  const h2 = getHeaderInfo(2);

  const atmBadge1 = document.getElementById('atm-badge-1');
  const spotText1 = document.getElementById('spot-text-1');
  if (atmBadge1) atmBadge1.textContent = `ATM: ${h1.atm}`;
  if (spotText1) spotText1.textContent = `Spot: ${h1.spot}`;

  const atmBadge2 = document.getElementById('atm-badge-2');
  const spotText2 = document.getElementById('spot-text-2');
  if (atmBadge2) atmBadge2.textContent = `ATM: ${h2.atm}`;
  if (spotText2) spotText2.textContent = `Spot: ${h2.spot}`;

  // Update overall counts
  const allStrikes = [...strikes1, ...strikes2];
  let lb = 0, sb = 0, sc = 0, lu = 0;
  allStrikes.forEach(s => {
    const bType = s.buildup_type || (
      (s.price_pchange >= 0 && s.oi_pchange >= 0) ? 'LONG_BUILDUP' :
      (s.price_pchange < 0 && s.oi_pchange >= 0) ? 'SHORT_BUILDUP' :
      (s.price_pchange >= 0 && s.oi_pchange < 0) ? 'SHORT_COVERING' : 'LONG_UNWINDING'
    );
    if (bType === 'LONG_BUILDUP') lb++;
    else if (bType === 'SHORT_BUILDUP') sb++;
    else if (bType === 'SHORT_COVERING') sc++;
    else if (bType === 'LONG_UNWINDING') lu++;
  });

  const cLB = document.getElementById('count-lb');
  const cSB = document.getElementById('count-sb');
  const cSC = document.getElementById('count-sc');
  const cLU = document.getElementById('count-lu');
  if (cLB) cLB.textContent = lb;
  if (cSB) cSB.textContent = sb;
  if (cSC) cSC.textContent = sc;
  if (cLU) cLU.textContent = lu;

  // Render SVGs in both columns
  renderQuadrantSVG('canvas-wrap-1', strikes1, 1);
  renderQuadrantSVG('canvas-wrap-2', strikes2, 2);
}

function filterStrikes(strikes) {
  if (!strikes) return [];
  if (activeFilter === 'ALL') return strikes;
  return strikes.filter(s => s.option_type === activeFilter);
}

function renderQuadrantSVG(wrapId, strikes, colIdx) {
  const container = document.getElementById(wrapId);
  if (!container) return;

  const width = container.clientWidth || 550;
  const height = Math.max(380, container.clientHeight || 420);
  const margin = { top: 30, right: 35, bottom: 35, left: 45 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  // If NO DATA: Display clean institutional zero-dummy message
  if (!strikes || strikes.length === 0) {
    const isHist = (activeMode === 'HISTORICAL');
    container.innerHTML = `
      <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" class="quadrant-svg">
        <rect width="${width}" height="${height}" fill="#080b12" />
        <g transform="translate(${width / 2}, ${height / 2})">
          <circle cx="0" cy="-24" r="28" fill="rgba(56, 189, 248, 0.06)" stroke="rgba(56, 189, 248, 0.2)" stroke-width="1.5" />
          <text x="0" y="-18" text-anchor="middle" font-size="22" fill="#38bdf8">${isHist ? '📅' : '⚡'}</text>
          <text x="0" y="24" text-anchor="middle" fill="#94a3b8" font-family="var(--font-mono)" font-size="13" font-weight="700" letter-spacing="0.5">
            ${isHist ? 'NO HISTORICAL STRIKE SNAPSHOTS RECORDED' : 'WAITING FOR LIVE MARKET STREAM'}
          </text>
          <text x="0" y="44" text-anchor="middle" fill="#64748b" font-family="var(--font-sans)" font-size="11">
            ${isHist ? `No recorded strike snapshots exist for ${activeDate || 'this date'}` : 'Real-time strike graph updates automatically during NSE trading hours (09:15 - 15:30 IST)'}
          </text>
        </g>
      </svg>
    `;
    return;
  }

  // Calculate dynamic axis limits
  let maxAbsOI = 15;
  let maxAbsPrice = 25;

  strikes.forEach(s => {
    const absOI = Math.abs(s.oi_pchange || 0);
    const absP = Math.abs(s.price_pchange || 0);
    if (absOI > maxAbsOI) maxAbsOI = absOI;
    if (absP > maxAbsPrice) maxAbsPrice = absP;
  });

  maxAbsOI = Math.min(150, Math.ceil(maxAbsOI * 1.15 / 5) * 5);
  maxAbsPrice = Math.min(200, Math.ceil(maxAbsPrice * 1.15 / 10) * 10);

  const xScale = (val) => margin.left + ((val + maxAbsOI) / (2 * maxAbsOI)) * innerW;
  const yScale = (val) => margin.top + ((maxAbsPrice - val) / (2 * maxAbsPrice)) * innerH;

  const zeroX = xScale(0);
  const zeroY = yScale(0);

  const volumes = strikes.map(s => s.volume || 1);
  const minVol = Math.min(...volumes, 1);
  const maxVol = Math.max(...volumes, 100);

  const getRadius = (vol) => {
    const norm = (vol - minVol) / Math.max(1, maxVol - minVol);
    return Math.round(9 + norm * 15);
  };

  let svg = `
    <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" class="quadrant-svg">
      <defs>
        <filter id="glow-lb" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <filter id="glow-sb" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      <!-- QUADRANT BACKGROUND TINTS -->
      <rect x="${zeroX}" y="${margin.top}" width="${margin.left + innerW - zeroX}" height="${zeroY - margin.top}"
            fill="rgba(16, 185, 129, 0.04)" />
      <rect x="${margin.left}" y="${margin.top}" width="${zeroX - margin.left}" height="${zeroY - margin.top}"
            fill="rgba(6, 182, 212, 0.04)" />
      <rect x="${margin.left}" y="${zeroY}" width="${zeroX - margin.left}" height="${margin.top + innerH - zeroY}"
            fill="rgba(245, 158, 11, 0.04)" />
      <rect x="${zeroX}" y="${zeroY}" width="${margin.left + innerW - zeroX}" height="${margin.top + innerH - zeroY}"
            fill="rgba(239, 68, 68, 0.04)" />

      <!-- WATERMARK QUADRANT LABELS -->
      <text x="${margin.left + 12}" y="${margin.top + 20}" class="quadrant-watermark" fill="rgba(6, 182, 212, 0.35)">Short Covering</text>
      <text x="${margin.left + innerW - 12}" y="${margin.top + 20}" text-anchor="end" class="quadrant-watermark" fill="rgba(16, 185, 129, 0.35)">Long Buildup</text>
      <text x="${margin.left + 12}" y="${margin.top + innerH - 12}" class="quadrant-watermark" fill="rgba(245, 158, 11, 0.35)">Long Unwinding</text>
      <text x="${margin.left + innerW - 12}" y="${margin.top + innerH - 12}" text-anchor="end" class="quadrant-watermark" fill="rgba(239, 68, 68, 0.35)">Short Buildup</text>

      <!-- AXIS GRID LINES & TICKS -->
      ${[-maxAbsOI * 0.5, 0, maxAbsOI * 0.5].map(tick => {
        const xPos = xScale(tick);
        return `
          <line x1="${xPos}" y1="${margin.top}" x2="${xPos}" y2="${margin.top + innerH}"
                stroke="${tick === 0 ? 'rgba(255, 255, 255, 0.25)' : 'rgba(255, 255, 255, 0.06)'}"
                stroke-width="${tick === 0 ? '1.5' : '1'}"
                stroke-dasharray="${tick === 0 ? 'none' : '3,3'}" />
          <text x="${xPos}" y="${margin.top + innerH + 18}" text-anchor="middle" class="axis-tick-text">
            ${tick > 0 ? '+' : ''}${Math.round(tick)}%
          </text>
        `;
      }).join('')}

      ${[-maxAbsPrice * 0.5, 0, maxAbsPrice * 0.5].map(tick => {
        const yPos = yScale(tick);
        return `
          <line x1="${margin.left}" y1="${yPos}" x2="${margin.left + innerW}" y2="${yPos}"
                stroke="${tick === 0 ? 'rgba(255, 255, 255, 0.25)' : 'rgba(255, 255, 255, 0.06)'}"
                stroke-width="${tick === 0 ? '1.5' : '1'}"
                stroke-dasharray="${tick === 0 ? 'none' : '3,3'}" />
          <text x="${margin.left - 8}" y="${yPos + 4}" text-anchor="end" class="axis-tick-text">
            ${tick > 0 ? '+' : ''}${Math.round(tick)}%
          </text>
        `;
      }).join('')}

      <text x="${margin.left + innerW / 2}" y="${margin.top + innerH + 32}" text-anchor="middle" class="axis-title-text">
        OI Change % →
      </text>
      <text x="${12}" y="${margin.top + innerH / 2}" text-anchor="middle" transform="rotate(-90 12 ${margin.top + innerH / 2})" class="axis-title-text">
        Price Change % →
      </text>

      <!-- STRIKE BUBBLES -->
      <g class="bubbles-group">
        ${strikes.map((s, idx) => {
          const cx = xScale(s.oi_pchange || 0);
          const cy = yScale(s.price_pchange || 0);
          const r = getRadius(s.volume || 1);
          const isCE = s.option_type === 'CE';

          let fillColor = '#10b981';
          let strokeColor = '#34d399';
          let shadowFilter = 'url(#glow-lb)';

          if (s.buildup_type === 'SHORT_BUILDUP') {
            fillColor = '#ef4444';
            strokeColor = '#f87171';
            shadowFilter = 'url(#glow-sb)';
          } else if (s.buildup_type === 'SHORT_COVERING') {
            fillColor = '#06b6d4';
            strokeColor = '#38bdf8';
          } else if (s.buildup_type === 'LONG_UNWINDING') {
            fillColor = '#f59e0b';
            strokeColor = '#fbbf24';
          }

          const ringStroke = isCE ? '#38bdf8' : '#f43f5e';
          const strikeLabel = `${Math.round(s.strike)} ${isCE ? 'CE' : 'PE'}`;

          return `
            <g class="strike-bubble-node" data-idx="${idx}" data-col="${colIdx}" transform="translate(${cx}, ${cy})">
              ${s.is_atm ? `
                <circle cx="0" cy="0" r="${r + 5}" fill="none" stroke="#f59e0b" stroke-width="2" stroke-dasharray="3,2" class="atm-halo-ring">
                  <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="8s" repeatCount="indefinite" />
                </circle>
              ` : ''}

              <circle cx="0" cy="0" r="${r}" fill="${fillColor}" fill-opacity="0.82"
                      stroke="${s.is_atm ? '#fbbf24' : strokeColor}" stroke-width="${s.is_atm ? 2.5 : 1.5}"
                      style="cursor: pointer; transition: transform 0.2s;" />

              <circle cx="0" cy="0" r="${Math.max(4, r - 3)}" fill="none" stroke="${ringStroke}" stroke-width="1" stroke-opacity="0.6" />

              <g transform="translate(0, ${r + 13})">
                <rect x="-24" y="-9" width="48" height="13" rx="3" fill="rgba(6, 8, 13, 0.85)" stroke="rgba(255,255,255,0.15)" stroke-width="0.5" />
                <text x="0" y="0" text-anchor="middle" class="bubble-strike-label" fill="#ffffff">
                  ${strikeLabel}
                </text>
              </g>
            </g>
          `;
        }).join('')}
      </g>
    </svg>
  `;

  container.innerHTML = svg;

  container.querySelectorAll('.strike-bubble-node').forEach(node => {
    node.addEventListener('mouseenter', (e) => {
      const idx = parseInt(node.getAttribute('data-idx'), 10);
      const s = strikes[idx];
      if (s) showTooltip(e, s);
    });

    node.addEventListener('mousemove', (e) => {
      moveTooltip(e);
    });

    node.addEventListener('mouseleave', () => {
      hideTooltip();
    });
  });
}

function showTooltip(e, s) {
  const tooltip = document.getElementById('strike-hud-tooltip');
  if (!tooltip) return;

  const isCE = s.option_type === 'CE';
  const bType = s.buildup_type || (
    (s.price_pchange >= 0 && s.oi_pchange >= 0) ? 'LONG_BUILDUP' :
    (s.price_pchange < 0 && s.oi_pchange >= 0) ? 'SHORT_BUILDUP' :
    (s.price_pchange >= 0 && s.oi_pchange < 0) ? 'SHORT_COVERING' : 'LONG_UNWINDING'
  );
  const bColor = (bType === 'LONG_BUILDUP') ? '#10b981' :
                 (bType === 'SHORT_BUILDUP') ? '#ef4444' :
                 (bType === 'SHORT_COVERING') ? '#06b6d4' : '#f59e0b';

  const sentimentLabel = s.sentiment_label || (
    (isCE && bType === 'LONG_BUILDUP') ? 'Call Buying (Bullish Momentum)' :
    (isCE && bType === 'SHORT_BUILDUP') ? 'Call Writing (Bearish Resistance Wall)' :
    (isCE && bType === 'SHORT_COVERING') ? 'Call Short Squeeze (Bears Covering)' :
    (isCE && bType === 'LONG_UNWINDING') ? 'Call Longs Liquidating (Profit Taking)' :
    (!isCE && bType === 'LONG_BUILDUP') ? 'Put Buying (Bearish Downside Bet)' :
    (!isCE && bType === 'SHORT_BUILDUP') ? 'Put Writing (Bullish Support Cushion)' :
    (!isCE && bType === 'SHORT_COVERING') ? 'Put Short Squeeze (Downside Panic)' :
    'Put Longs Liquidating (Bulls Rebounding)'
  );

  tooltip.innerHTML = `
    <div class="hud-header">
      <div class="hud-strike-title">
        <span class="hud-badge ${isCE ? 'hud-ce' : 'hud-pe'}">${s.option_type}</span>
        <span class="hud-strike-val">${s.strike.toLocaleString('en-IN')}</span>
        ${s.is_atm ? '<span class="hud-atm-pill">ATM STRIKE</span>' : ''}
      </div>
      <div class="hud-buildup-tag" style="color:${bColor}; border-color:${bColor};">
        ${bType.replace('_', ' ')}
      </div>
    </div>

    <div class="hud-grid">
      <div class="hud-item">
        <span class="hud-k">LTP (Price)</span>
        <span class="hud-v mono">₹${(s.ltp || 0).toFixed(2)} (${s.price_pchange >= 0 ? '+' : ''}${s.price_pchange}%)</span>
      </div>
      <div class="hud-item">
        <span class="hud-k">Open Interest</span>
        <span class="hud-v mono">${((s.oi || 0) / 100000).toFixed(2)}L (${s.oi_pchange >= 0 ? '+' : ''}${s.oi_pchange}%)</span>
      </div>
      <div class="hud-item">
        <span class="hud-k">OI Change</span>
        <span class="hud-v mono">${s.oi_chg >= 0 ? '+' : ''}${((s.oi_chg || 0) / 100000).toFixed(2)}L</span>
      </div>
      <div class="hud-item">
        <span class="hud-k">Traded Volume</span>
        <span class="hud-v mono">${((s.volume || 0) / 100000).toFixed(2)}L</span>
      </div>
    </div>

    <div class="hud-insight">
      <div class="hud-insight-title">💡 TRADER SENTIMENT INSIGHT</div>
      <div class="hud-insight-text">${sentimentLabel}</div>
    </div>
  `;

  tooltip.classList.remove('hidden');
  moveTooltip(e);
}

function moveTooltip(e) {
  const tooltip = document.getElementById('strike-hud-tooltip');
  if (!tooltip) return;

  const pad = 16;
  let x = e.clientX + pad;
  let y = e.clientY + pad;

  if (x + 300 > window.innerWidth) {
    x = e.clientX - 310;
  }
  if (y + 200 > window.innerHeight) {
    y = e.clientY - 210;
  }

  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
}

function hideTooltip() {
  const tooltip = document.getElementById('strike-hud-tooltip');
  if (tooltip) tooltip.classList.add('hidden');
}
