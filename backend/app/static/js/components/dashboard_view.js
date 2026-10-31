/**
 * 5-Index Macro Dashboard Component (Unified Redesign)
 * Module A: 5-Index Top Cards + Quantitative Matrix + Extended 5M Strategy Confluence + Intraday OI Shift
 */
import { ApiClient } from '../api.js';
import { store } from '../state.js';

let pollTimer = null;
let currentActiveSymbol = 'NIFTY';
let currentOIGraphMode = 'split'; // 'split' | 'total' | 'chg'
let cachedMatrixData = [];
let cachedTimeseriesData = [];
let isFetching = false;

export async function renderDashboardView(container) {
  // If already mounted, do not re-create DOM skeleton to preserve user focus/scroll
  const existing = container.querySelector('#dashboard-view-root');
  if (existing) {
    await _loadAndRender(container);
    return;
  }

  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  container.innerHTML = `
    <div id="dashboard-view-root" style="display: flex; flex-direction: column; gap: 12px;">
      
      <!-- 1. Master Quantitative Parameter Matrix -->
      <div class="glass-panel" style="padding: 12px 16px; background: #0c1017; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
          <div style="font-size: 12px; font-weight: 800; color: #f8fafc; letter-spacing: 0.5px; text-transform: uppercase; display: flex; align-items: center; gap: 8px;">
            <span style="color: #38bdf8;">📊</span> 5-INDEX QUANTITATIVE PARAMETER MATRIX
          </div>
          <div style="font-size: 10.5px; color: #64748b; font-family: var(--font-mono); display: flex; align-items: center; gap: 10px;">
            <span id="dash-live-badge" style="display: inline-flex; align-items: center; gap: 5px; color: #10b981;">
              <span style="width: 6px; height: 6px; border-radius: 50%; background: #10b981; box-shadow: 0 0 6px #10b981;"></span>
              REAL-TIME SYNC
            </span>
            <span id="dash-clock" style="color: #94a3b8;">--:--:-- IST</span>
          </div>
        </div>
          <div style="font-size: 10px; color: #64748b;">Click any row to inspect deep dive below</div>
        </div>
        <div style="overflow-x: auto; max-height: 250px;">
          <table class="table-clean" id="dash-master-matrix-table">
            <thead>
              <tr>
                <th style="min-width: 140px;">Index &amp; Spot</th>
                <th>Trap Radar</th>
                <th>Breakout Strength</th>
                <th>Proximity (MAPO)</th>
                <th>PCR</th>
                <th>Net OI Diff</th>
                <th>Call Positioning</th>
                <th>Put Positioning</th>
                <th style="min-width: 130px;">Confluence &amp; Spark</th>
                <th>Directive</th>
              </tr>
            </thead>
            <tbody id="dash-matrix-tbody">
              <tr><td colspan="10" style="text-align: center; color: #64748b; padding: 20px;">Streaming live market data...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 3. Bottom Dual-Panel Analytics: OI Shift Chart (40%) + 5M Strategy Matrix (60%) -->
      <div style="display: grid; grid-template-columns: 1fr 1.65fr; gap: 10px; min-height: 280px;" id="dash-bottom-grid">
        
        <!-- Left Panel: Intraday Call vs Put OI Shift -->
        <div class="glass-panel" style="padding: 10px 12px; display: flex; flex-direction: column;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div style="font-size: 11px; font-weight: 800; color: #f1f5f9; display: flex; align-items: center; gap: 6px;">
              <span style="color: #f59e0b;">📉</span> <span id="dash-active-sym-title">NIFTY 50</span> OI SHIFT
            </div>
            <div style="display: flex; gap: 4px;">
              <button class="btn btn-sm ${currentOIGraphMode === 'split' ? 'btn-primary' : ''}" id="dash-btn-split" style="padding: 2px 6px; font-size: 9.5px;">Split</button>
              <button class="btn btn-sm ${currentOIGraphMode === 'total' ? 'btn-primary' : ''}" id="dash-btn-total" style="padding: 2px 6px; font-size: 9.5px;">Total</button>
              <button class="btn btn-sm ${currentOIGraphMode === 'chg' ? 'btn-primary' : ''}" id="dash-btn-chg" style="padding: 2px 6px; font-size: 9.5px;">Change</button>
            </div>
          </div>
          <div id="dash-oi-chart-container" style="flex: 1; min-height: 200px; position: relative;">
            <svg id="dash-oi-svg" width="100%" height="100%"></svg>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 9px; color: #64748b; font-family: var(--font-mono); margin-top: 4px;">
            <span>09:15</span><span>10:30</span><span>11:45</span><span>13:00</span><span>14:15</span><span>15:30</span>
          </div>
        </div>

        <!-- Right Panel: 5M Strategy Confluence Matrix (Extended Space) -->
        <div class="glass-panel" style="padding: 10px 14px; display: flex; flex-direction: column;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div style="font-size: 11px; font-weight: 800; color: #38bdf8; display: flex; align-items: center; gap: 6px;">
              <span>⚡</span> 5M STRATEGY CONFLUENCE MATRIX <span style="font-size: 9px; color: #94a3b8; font-weight: 600;">(SHONYA BOT EXECUTION HUB)</span>
            </div>
            <span style="font-size: 9.5px; color: #10b981; font-weight: 800; font-family: var(--font-mono);">● ALIGNED TICKS</span>
          </div>
          <div style="flex: 1; overflow-y: auto;">
            <table class="table-clean" style="font-size: 11px;">
              <thead>
                <tr>
                  <th style="width: 18%; text-align: left;">1. INDICES</th>
                  <th style="width: 32%; text-align: left;">2. OPTION CHAIN SIGNAL</th>
                  <th style="width: 25%; text-align: left;">3. HULL INDICATOR (5M)</th>
                  <th style="width: 25%; text-align: center;">4. WHAT TO DO (BUY CALL / PUT ?)</th>
                </tr>
              </thead>
              <tbody id="dash-strategy-tbody">
                <tr><td colspan="4" style="text-align: center; color: #64748b; padding: 20px;">Calculating 5M OI Buildup + Hull Confluence...</td></tr>
              </tbody>
            </table>
          </div>
          <div style="display: flex; flex-wrap: wrap; gap: 12px; margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 9px; color: #94a3b8;">
            <span><strong style="color: #10b981;">● BUY CALL:</strong> Put Hull Falling 🔴 (Market Bullish) + Put OI Floor</span>
            <span><strong style="color: #ef4444;">● BUY PUT:</strong> Call Hull Falling 🔴 (Market Bearish) + Call OI Wall</span>
            <span><strong style="color: #f59e0b;">● CONFLICT:</strong> Opposing Filter (Stand Aside)</span>
          </div>
        </div>

      </div>

    </div>
  `;

  // Attach button events
  const bSplit = container.querySelector('#dash-btn-split');
  const bTotal = container.querySelector('#dash-btn-total');
  const bChg = container.querySelector('#dash-btn-chg');
  if (bSplit) bSplit.addEventListener('click', () => { currentOIGraphMode = 'split'; _updateModeButtons(container); _renderOIChart(container, cachedTimeseriesData); });
  if (bTotal) bTotal.addEventListener('click', () => { currentOIGraphMode = 'total'; _updateModeButtons(container); _renderOIChart(container, cachedTimeseriesData); });
  if (bChg) bChg.addEventListener('click', () => { currentOIGraphMode = 'chg'; _updateModeButtons(container); _renderOIChart(container, cachedTimeseriesData); });

  // Initial load
  await _loadAndRender(container);

  // Background 2-second auto-poll
  pollTimer = setInterval(async () => {
    if (!document.body.contains(container)) {
      clearInterval(pollTimer);
      pollTimer = null;
      return;
    }
    await _loadAndRender(container);
  }, 2200);
}

function _updateModeButtons(container) {
  ['split', 'total', 'chg'].forEach(m => {
    const btn = container.querySelector(`#dash-btn-${m}`);
    if (btn) btn.classList.toggle('btn-primary', currentOIGraphMode === m);
  });
}

async function _loadAndRender(container) {
  if (isFetching) return;
  isFetching = true;
  try {
    const res = await ApiClient.fetchLiveMatrix();
    if (res && res.status === 'success' && res.data) {
      cachedMatrixData = res.data;
      _renderSwitcherCards(container, res.data);
      _renderMasterMatrix(container, res.data);
      
      const stratList = (res.strategy_table && res.strategy_table.length) 
        ? res.strategy_table 
        : res.data.map(d => d.strategy_confluence).filter(Boolean);
      _renderStrategyTable(container, stratList);

      if (res.timestamp) {
        const clk = container.querySelector('#dash-clock');
        if (clk) clk.textContent = `${res.timestamp.split(' ')[1] || res.timestamp} IST`;
      }
    }

    // Also update timeseries for active symbol
    const tsRes = await ApiClient.fetchMatrixTimeseries(currentActiveSymbol);
    if (tsRes && tsRes.status === 'success') {
      cachedTimeseriesData = tsRes.timeline || [];
      _renderOIChart(container, cachedTimeseriesData);
    }
  } catch (err) {
    console.debug('Dashboard tick update error:', err);
  } finally {
    isFetching = false;
  }
}

function _renderSwitcherCards(container, dataList) {
  const mount = container.querySelector('#dash-switcher-cards');
  if (!mount || !dataList) return;

  mount.innerHTML = dataList.map(item => {
    const sym = item.symbol;
    const isSelected = (sym === currentActiveSymbol);
    const spot = item.spot_price || 0;
    const pcr = item.pcr?.value ? item.pcr.value.toFixed(2) : '--';
    const conf = item.confluence?.score || 50;
    const isBull = conf >= 55;
    const isBear = conf <= 45;
    const badgeColor = isBull ? '#10b981' : (isBear ? '#ef4444' : '#f59e0b');
    const badgeText = isBull ? 'BULLISH' : (isBear ? 'BEARISH' : 'NEUTRAL');

    return `
      <div class="dash-card ${isSelected ? 'selected' : ''}" data-sym="${sym}" style="
        background: ${isSelected ? 'rgba(14, 165, 233, 0.16)' : 'rgba(255, 255, 255, 0.03)'};
        border: 1px solid ${isSelected ? '#38bdf8' : 'rgba(255, 255, 255, 0.08)'};
        border-radius: 8px;
        padding: 8px 12px;
        cursor: pointer;
        transition: all 0.15s ease;
      ">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
          <span style="font-weight: 800; font-size: 12px; color: #fff;">⚡ ${sym}</span>
          <span style="font-size: 9px; font-weight: 800; color: ${badgeColor}; background: rgba(0,0,0,0.3); padding: 1px 5px; border-radius: 4px;">${badgeText} (${conf})</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: baseline;">
          <span style="font-family: var(--font-mono); font-size: 13px; font-weight: 800; color: #38bdf8;">₹${spot > 0 ? spot.toLocaleString('en-IN', {minimumFractionDigits: 1, maximumFractionDigits: 1}) : '--'}</span>
          <span style="font-size: 9px; color: #94a3b8; font-family: var(--font-mono);">PCR ${pcr} • Lot ${item.lot_size || 20}</span>
        </div>
      </div>
    `;
  }).join('');

  mount.querySelectorAll('.dash-card').forEach(c => {
    c.addEventListener('click', () => {
      currentActiveSymbol = c.getAttribute('data-sym');
      const titleEl = container.querySelector('#dash-active-sym-title');
      if (titleEl) titleEl.textContent = currentActiveSymbol === 'NIFTY' ? 'NIFTY 50' : currentActiveSymbol;
      _loadAndRender(container);
    });
  });
}

function _renderMasterMatrix(container, dataList) {
  const tbody = container.querySelector('#dash-matrix-tbody');
  if (!tbody || !dataList) return;

  tbody.innerHTML = dataList.map(item => {
    const sym = item.symbol;
    const isSelected = (sym === currentActiveSymbol);
    const spot = item.spot_price || 0;
    const brk = item.breakout || { state: 'FLAT', signal: 'WAIT', strength_score: 0, color: 'yellow' };
    const prox = item.proximity || { mapo_pct: 50, state: 'MID', color: 'yellow' };
    const pcr = item.pcr || { value: 1.0, color: 'yellow', trend: 'BALANCED' };
    const oid = item.oi_difference || { net_diff_formatted: '--', diff_velocity_1m: '--', velocity_label: 'FLAT', color: 'yellow' };
    const ce = item.call_positioning || item.call_oi || { buildup: '--', total_oi: '--', oi_chg_session: '--', color: 'yellow' };
    const pe = item.put_positioning || item.put_oi || { buildup: '--', total_oi: '--', oi_chg_session: '--', color: 'yellow' };
    const conf = item.confluence || { score: 50, color: 'yellow' };
    const act = item.action || { signal: 'STANDBY', verdict_text: 'Hold', color: 'yellow' };
    const trap = item.trap || { badge: '🛡️ CLEAN', color: 'yellow', trap_risk: 'LOW (12%)', action: 'NORMAL' };

    const confScore = conf.score || 50;
    const confColor = confScore >= 55 ? '#10b981' : (confScore <= 45 ? '#ef4444' : '#f59e0b');

    return `
      <tr style="cursor: pointer; background: ${isSelected ? 'rgba(14, 165, 233, 0.08)' : 'transparent'};">
        <td>
          <div style="font-weight: 800; color: #fff;">⚡ ${sym}</div>
          <div style="font-size: 10px; font-family: var(--font-mono); color: #38bdf8;">₹${spot > 0 ? spot.toFixed(1) : '--'}</div>
        </td>
        <td><span style="font-size: 10px; font-weight: 700;">${trap.badge || '🛡️ CLEAN'}</span></td>
        <td><span style="font-size: 10px; font-weight: 700;">${brk.signal || 'WAIT'} (${(brk.strength_score || 0).toFixed(0)}%)</span></td>
        <td><span style="font-size: 10px; font-family: var(--font-mono);">${(prox.mapo_pct || 50).toFixed(1)}%</span></td>
        <td><span style="font-size: 10px; font-family: var(--font-mono);">${(pcr.value || 1.0).toFixed(2)}</span></td>
        <td><span style="font-size: 10px; font-family: var(--font-mono);">${oid.net_diff_formatted || '--'}</span></td>
        <td><span style="font-size: 10px; font-weight: 700;">${ce.buildup || '--'}</span></td>
        <td><span style="font-size: 10px; font-weight: 700;">${pe.buildup || '--'}</span></td>
        <td>
          <div style="display: flex; align-items: center; gap: 6px;">
            <div style="width: 50px; height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; overflow: hidden;">
              <div style="width: ${confScore}%; height: 100%; background: ${confColor};"></div>
            </div>
            <strong style="font-size: 10px; font-family: var(--font-mono); color: ${confColor};">${confScore}</strong>
          </div>
        </td>
        <td>
          <span style="font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 4px; background: ${act.signal?.includes('BUY') ? 'rgba(16,185,129,0.2)' : 'rgba(255,255,255,0.05)'}; color: ${act.signal?.includes('BUY') ? '#34d399' : '#cbd5e1'};">
            ${act.signal || 'STANDBY'}
          </span>
        </td>
      </tr>
    `;
  }).join('');
}

function _renderStrategyTable(container, stratList) {
  const tbody = container.querySelector('#dash-strategy-tbody');
  if (!tbody || !stratList) return;

  tbody.innerHTML = stratList.map(item => {
    const sym = item.symbol;
    const spot = item.spot_price || 0;
    const atm = item.atm_strike || 0;
    const lot = item.lot_size || 20;

    const oi = item.option_chain_signal || {};
    const hull = item.hull_indicator || {};
    const act = item.action || {};

    let actClass = 'standby';
    if (act.type === 'CE' || act.verdict === 'BUY CALL' || act.badge_color === 'dark-green') actClass = 'buy-call';
    else if (act.type === 'PE' || act.verdict === 'BUY PUT' || act.badge_color === 'dark-red') actClass = 'buy-put';
    else if (act.is_opposed || (act.verdict && act.verdict.includes('CONFLICT'))) actClass = 'conflict';

    return `
      <tr>
        <td>
          <div style="font-weight: 800; color: #fff;">⚡ ${sym}</div>
          <div style="font-size: 10px; font-family: var(--font-mono); color: #38bdf8;">₹${spot > 0 ? spot.toFixed(1) : '--'}</div>
          <div style="font-size: 8.5px; color: #64748b; font-family: var(--font-mono);">ATM ${atm} • Lot ${lot}</div>
        </td>
        <td>
          <div style="font-weight: 800; font-size: 10px; color: ${oi.direction === 'BULLISH' ? '#34d399' : (oi.direction === 'BEARISH' ? '#f87171' : '#fbbf24')};">
            ${oi.label || 'NEUTRAL'}
          </div>
          <div style="font-size: 8.5px; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 250px;">
            ${oi.strength_desc || '--'}
          </div>
        </td>
        <td>
          <div style="font-weight: 800; font-size: 10px; color: ${hull.trend === 'BULLISH' ? '#34d399' : (hull.trend === 'BEARISH' ? '#f87171' : '#fbbf24')};">
            ${hull.label || 'NEUTRAL'}
          </div>
          <div style="font-size: 8.5px; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px;">
            ${hull.desc || 'EHMA 34x2'}
          </div>
        </td>
        <td style="text-align: center;">
          <div style="display: flex; flex-direction: column; align-items: center; gap: 2px;">
            <span class="pill-verdict ${actClass}">${act.verdict || 'STANDBY'}</span>
            <span style="font-family: var(--font-mono); font-size: 10px; font-weight: 800; color: #fff;">${act.strike || '--'}</span>
            <span style="font-size: 8px; color: #94a3b8; max-width: 220px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${act.sub || ''}</span>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function _renderOIChart(container, timeline) {
  const svg = container.querySelector('#dash-oi-svg');
  if (!svg || !timeline || !timeline.length) return;

  const w = svg.clientWidth || 380;
  const h = svg.clientHeight || 180;
  const pad = { top: 10, right: 10, bottom: 10, left: 35 };
  const innerW = Math.max(10, w - pad.left - pad.right);
  const innerH = Math.max(10, h - pad.top - pad.bottom);

  let ceValues = timeline.map(d => d.ce_oi || 0);
  let peValues = timeline.map(d => d.pe_oi || 0);

  if (currentOIGraphMode === 'chg') {
    ceValues = timeline.map(d => d.ce_oi_chg || 0);
    peValues = timeline.map(d => d.pe_oi_chg || 0);
  }

  const allVals = ceValues.concat(peValues);
  const minVal = Math.min(...allVals);
  const maxVal = Math.max(...allVals);
  const span = Math.max(1, maxVal - minVal);

  const getX = i => pad.left + (i / Math.max(1, timeline.length - 1)) * innerW;
  const getY = val => pad.top + innerH - ((val - minVal) / span) * innerH;

  const cePoints = ceValues.map((v, i) => `${getX(i).toFixed(1)},${getY(v).toFixed(1)}`).join(' ');
  const pePoints = peValues.map((v, i) => `${getX(i).toFixed(1)},${getY(v).toFixed(1)}`).join(' ');

  svg.innerHTML = `
    <!-- Grid -->
    <line x1="${pad.left}" y1="${pad.top}" x2="${w - pad.right}" y2="${pad.top}" stroke="rgba(255,255,255,0.06)" />
    <line x1="${pad.left}" y1="${pad.top + innerH/2}" x2="${w - pad.right}" y2="${pad.top + innerH/2}" stroke="rgba(255,255,255,0.06)" />
    <line x1="${pad.left}" y1="${pad.top + innerH}" x2="${w - pad.right}" y2="${pad.top + innerH}" stroke="rgba(255,255,255,0.06)" />

    <!-- Polyline Call OI (Red) -->
    <polyline points="${cePoints}" fill="none" stroke="#f87171" stroke-width="2" />
    
    <!-- Polyline Put OI (Green) -->
    <polyline points="${pePoints}" fill="none" stroke="#34d399" stroke-width="2" />
  `;
}
