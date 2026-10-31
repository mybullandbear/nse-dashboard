/**
 * Institutional Smart Money & Defense Walls Component
 * Displays Simultaneous Dual Views:
 * - Default: NIFTY & BANKNIFTY side-by-side
 * - Secondary: FINNIFTY & MIDCPNIFTY side-by-side
 */
import { store } from '../state.js';

export function renderSmartMoney(container) {
  const state = store.getState();
  const s1 = state.symbol1;
  const s2 = state.symbol2;
  const sm1 = state.smartMoney1 || {};
  const sm2 = state.smartMoney2 || {};
  const oi1 = state.oiData1 || {};
  const oi2 = state.oiData2 || {};

  container.innerHTML = `
    <div class="dual-symbol-grid">
      <!-- COLUMN 1: SYMBOL 1 (NIFTY by default) -->
      <div class="symbol-column">
        ${renderSymbolSmartMoneyBlock(s1, sm1, oi1)}
      </div>

      <!-- COLUMN 2: SYMBOL 2 (BANKNIFTY by default) -->
      <div class="symbol-column">
        ${renderSymbolSmartMoneyBlock(s2, sm2, oi2)}
      </div>
    </div>
  `;
}

function renderSymbolSmartMoneyBlock(symbol, sm, oiData) {
  const walls = oiData.walls || {};
  const straddle = oiData.straddle || {};
  const spot = oiData.spot_price || 0;

  const conviction = sm.conviction_score || 50;
  const netFlow = sm.net_flow_cr || 0.0;
  const peFlow = sm.pe_flow_cr || 0.0;
  const ceFlow = sm.ce_flow_cr || 0.0;
  const bias = sm.bias || 'NEUTRAL';
  const label = sm.label || 'Balanced Institutional Positioning';

  const isBull = netFlow >= 0;

  return `
    <!-- Column Header -->
    <div class="symbol-col-header">
      <div class="symbol-col-title">
        <span>🌊</span>
        <span>${symbol} SMART MONEY FLOW</span>
        <span class="logo-badge" style="color: #10b981;">● LIVE</span>
      </div>
      <div class="symbol-col-spot">
        SPOT: ${spot ? spot.toLocaleString('en-IN', { minimumFractionDigits: 1 }) : '--'}
      </div>
    </div>

    <!-- Conviction Speedometer Card -->
    <div class="glass-panel confluence-box">
      <div class="panel-title" style="margin-bottom: 0;">
        <span>🎯</span>
        <span>INSTITUTIONAL CONVICTION</span>
      </div>

      <div class="confluence-radial">
        <svg width="140" height="140" viewBox="0 0 140 140">
          <circle cx="70" cy="70" r="54" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="12" />
          <circle 
            cx="70" cy="70" r="54" 
            fill="none" 
            stroke="${isBull ? '#10b981' : '#ef4444'}" 
            stroke-width="12"
            stroke-dasharray="339"
            stroke-dashoffset="${339 - (339 * conviction) / 100}"
            stroke-linecap="round"
            transform="rotate(-90 70 70)"
            style="transition: stroke-dashoffset 0.8s ease;"
          />
        </svg>
        <div style="position: absolute; display: flex; flex-direction: column; align-items: center;">
          <span class="radial-score" style="color: ${isBull ? '#10b981' : '#ef4444'}; font-size: 30px;">
            ${conviction}
          </span>
          <span class="radial-label">CONVICTION / 100</span>
        </div>
      </div>

      <div class="direction-badge ${isBull ? 'badge-bull-lg' : 'badge-bear-lg'}">
        ${bias}
      </div>

      <div style="font-family: var(--font-mono); font-size: 11px; color: var(--text-secondary); text-align: center;">
        ${label}
      </div>
    </div>

    <!-- Institutional Capital Flow (ATM ± 5 Strikes) -->
    <div class="glass-panel" style="display: flex; flex-direction: column; gap: 12px;">
      <div class="panel-header" style="margin-bottom: 0;">
        <div class="panel-title" style="font-size: 11.5px;">
          <span>💰</span>
          <span>NET CAPITAL FLOW (ATM ± 5)</span>
        </div>
        <span class="logo-badge" style="color: ${isBull ? '#10b981' : '#ef4444'};">
          ${isBull ? '+₹' + netFlow.toFixed(2) : '-₹' + Math.abs(netFlow).toFixed(2)} CR NET
        </span>
      </div>

      <div class="strategy-grid">
        <div class="strategy-param">
          <div class="strategy-param-lbl">PE WRITING FLOW</div>
          <div class="strategy-param-val text-bull" style="font-size: 13px;">
            +₹${peFlow.toFixed(2)} Cr
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">CE WRITING FLOW</div>
          <div class="strategy-param-val text-bear" style="font-size: 13px;">
            +₹${ceFlow.toFixed(2)} Cr
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">INST. BIAS</div>
          <div class="strategy-param-val" style="color: ${isBull ? '#10b981' : '#ef4444'}; font-size: 13px;">
            ${isBull ? 'BULLISH' : 'BEARISH'}
          </div>
        </div>
      </div>
    </div>

    <!-- Defense Walls & Straddle Tracker -->
    <div class="glass-panel" style="display: flex; flex-direction: column; gap: 12px;">
      <div class="panel-header" style="margin-bottom: 0;">
        <div class="panel-title" style="font-size: 11.5px;">
          <span>🛡️</span>
          <span>DEFENSE WALLS & STRADDLE</span>
        </div>
        <span class="logo-badge" style="color: #f59e0b;">
          RANGE: ${walls.wall_range_pts || 0} PTS
        </span>
      </div>

      <div class="strategy-grid">
        <div class="strategy-param">
          <div class="strategy-param-lbl">PUT SUPPORT FLOOR</div>
          <div class="strategy-param-val text-bull" style="font-size: 13px;">
            ${walls.support_strike || '--'} PE
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">CALL RESISTANCE</div>
          <div class="strategy-param-val text-bear" style="font-size: 13px;">
            ${walls.resistance_strike || '--'} CE
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">ATM STRADDLE</div>
          <div class="strategy-param-val text-orange" style="font-size: 13px;">
            ₹${straddle.combined_premium || '--'} (${straddle.decay_pct || 0}%)
          </div>
        </div>
      </div>
    </div>
  `;
}
