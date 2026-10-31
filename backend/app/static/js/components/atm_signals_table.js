/**
 * Continuous Live ATM +- 2 Signals & Strike Matrix Component
 * Displays real-time PineScript OTT & ADX indicators + Option Chain Pricing
 * Strictly monitors ATM +- 2 Options (ATM-2, ATM-1, ATM, ATM+1, ATM+2).
 * Features:
 * - Real-time auto-refresh every 2.5s with live spot & option pricing.
 * - Total OI, Change in OI, Strike PCR, Net Difference in OI (PE - CE, PE Chg - CE Chg).
 * - Action Signal Column: BUY CE, BUY PE, SELL CE, SELL PE, NEUTRAL.
 * - Filters: [🔥 Strike Matrix (ATM ± 2)] [🚀 Buying Signals] [🛡️ Selling Signals] [⭐ AI Top Picks]
 * - Symbol Switcher: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY.
 * - Interactive 5m Option Candlestick Chart link for each strike.
 */
import { ApiClient } from '../api.js';
import { store } from '../state.js';

let currentFilterMode = 'MATRIX'; // 'MATRIX' | 'BUYER' | 'SELLER' | 'TOP'
let currentSymbol = 'NIFTY';       // 'NIFTY' | 'BANKNIFTY' | 'FINNIFTY' | 'MIDCPNIFTY'
let refreshTimer = null;
let lastSignalsData = [];

let _lastAtmScrollLeft = null;
let _isUserTouchingAtm = false;

export function renderAtmSignalsTable(container, initialData = null) {
  if (initialData && initialData.length > 0) {
    lastSignalsData = initialData;
  }

  // Initial render
  container.innerHTML = buildTableHTML(lastSignalsData, currentFilterMode, currentSymbol);
  attachTableEventListeners(container);

  // Start continuous polling loop (every 2.5 seconds)
  if (refreshTimer) {
    clearInterval(refreshTimer);
  }

  let _isAtmPollingInFlight = false;

  const pollAtmSignals = async () => {
    // Only continue polling if container is still connected to the DOM
    if (!document.body.contains(container)) {
      clearInterval(refreshTimer);
      refreshTimer = null;
      return;
    }

    // Prevent concurrent request stampedes or polling during historical replay
    if (_isAtmPollingInFlight || _isUserTouchingAtm || store.isReplayActive()) return;
    _isAtmPollingInFlight = true;

    try {
      const data = await ApiClient.fetchAtmSignals();
      if (data && data.length > 0) {
        lastSignalsData = data;
        const countSpan = container.querySelector('#signals-count-badge');
        if (countSpan) {
          countSpan.textContent = `● LIVE UPDATING (${lastSignalsData.length} INDICES)`;
        }

        const scrollWrapper = container.querySelector('#atm-matrix-scroll-wrapper');
        const existingTbody = container.querySelector('#atm-matrix-table-body');
        const summaryBanner = container.querySelector('#atm-corridor-summary-banner');

        // FLICKER-FREE & SCROLL-PRESERVING IN-PLACE UPDATE:
        // If not in TOP picks mode and the table elements exist, update ONLY the rows and summary!
        // This ensures the browser NEVER resets scrollLeft to 0 (Call data) during background polling!
        if (currentFilterMode !== 'TOP' && scrollWrapper && existingTbody) {
          if (scrollWrapper.scrollLeft > 0) {
            _lastAtmScrollLeft = scrollWrapper.scrollLeft;
          }

          const symData = lastSignalsData.find(s => s.symbol === currentSymbol) || lastSignalsData[0];
          if (symData) {
            const spot = symData.spot_price || 0;
            const atm = symData.atm_strike || 0;
            const matrix = symData.strikes_matrix || [];

            let displayStrikes = matrix;
            if (currentFilterMode === 'BUYER') {
              displayStrikes = matrix.filter(r => r.signal && r.signal.role === 'BUYER');
            } else if (currentFilterMode === 'SELLER') {
              displayStrikes = matrix.filter(r => r.signal && r.signal.role === 'SELLER');
            }

            existingTbody.innerHTML = displayStrikes.length > 0 
              ? displayStrikes.map(r => renderMatrixRow(symData.symbol, r, spot, atm)).join('') 
              : `<tr><td colspan="7" style="text-align: center; padding: 25px; color: var(--text-muted);">No strikes matched filter mode "${currentFilterMode}" for ${symData.symbol}.</td></tr>`;

            if (summaryBanner) {
              summaryBanner.innerHTML = buildCorridorSummaryBannerInner(symData);
            }

            attachChartClickListeners(container);
            return;
          }
        }

        // Full dynamic content render if switching modes or first load
        const matrixMount = container.querySelector('#atm-signals-dynamic-content');
        if (matrixMount) {
          matrixMount.innerHTML = buildDynamicContentHTML(lastSignalsData, currentFilterMode, currentSymbol);
          attachChartClickListeners(container);
          _setupAtmScrollListeners(container);
        }
      }
    } catch (err) {
      console.debug('ATM signals refresh error:', err);
    } finally {
      _isAtmPollingInFlight = false;
    }
  };

  // Immediate first poll if no initial data
  if (!initialData || initialData.length === 0) {
    pollAtmSignals();
  }

  refreshTimer = setInterval(pollAtmSignals, 4000);
}

function attachTableEventListeners(container) {
  // Filter button clicks
  container.querySelectorAll('.signal-filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const mode = btn.getAttribute('data-mode');
      if (mode && mode !== currentFilterMode) {
        currentFilterMode = mode;
        container.querySelectorAll('.signal-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const matrixMount = container.querySelector('#atm-signals-dynamic-content');
        if (matrixMount) {
          matrixMount.innerHTML = buildDynamicContentHTML(lastSignalsData, currentFilterMode, currentSymbol);
          attachChartClickListeners(container);
        }
      }
    });
  });

  // Symbol selector pills
  container.querySelectorAll('.atm-sym-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const sym = btn.getAttribute('data-sym');
      if (sym && sym !== currentSymbol) {
        currentSymbol = sym;
        container.querySelectorAll('.atm-sym-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const matrixMount = container.querySelector('#atm-signals-dynamic-content');
        if (matrixMount) {
          matrixMount.innerHTML = buildDynamicContentHTML(lastSignalsData, currentFilterMode, currentSymbol);
          attachChartClickListeners(container);
        }
      }
    });
  });

  attachChartClickListeners(container);
}

function attachChartClickListeners(container) {
  // No-op: PineScript charts removed per user request
}

function buildTableHTML(signals, filterMode, activeSym) {
  return `
    <div class="glass-panel atm-signals-panel" style="margin-bottom: 20px; padding: 18px; border: 1px solid rgba(56, 189, 248, 0.28); background: linear-gradient(180deg, rgba(15, 23, 42, 0.92) 0%, rgba(10, 15, 30, 0.98) 100%); border-radius: 12px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);">
      <!-- Header with Title, Mode Filters, and Symbol Pills -->
      <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 14px; margin-bottom: 16px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 14px;">
        <div style="display: flex; align-items: center; gap: 12px;">
          <span style="font-size: 26px;">⚡</span>
          <div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <h3 style="margin: 0; font-size: 16px; font-weight: 800; letter-spacing: 0.5px; color: #f8fafc;">
                CONTINUOUS LIVE ATM ± 2 SIGNALS & STRIKE MATRIX
              </h3>
              <span id="signals-count-badge" class="badge-active" style="font-size: 10px; padding: 2px 8px; border-radius: 9999px; background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3);">
                ● LIVE UPDATING (4 INDICES)
              </span>
            </div>
            <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 3px;">
              Strictly monitors <strong>ATM ± 2 Strikes (ATM-2, ATM-1, ATM, ATM+1, ATM+2)</strong> | Total OI, &Delta;OI, Strike PCR, Net Difference in OI & PineScript OTT Action Engine
            </div>
          </div>
        </div>

        <!-- Controls: Symbol Selector & Filter Modes -->
        <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 10px;">
          <!-- Index Switcher Pills -->
          <div style="display: flex; align-items: center; gap: 4px; background: rgba(0, 0, 0, 0.45); padding: 3px 6px; border-radius: 8px; border: 1px solid rgba(56, 189, 248, 0.2);">
            <span style="font-size: 10px; font-weight: 800; color: #94a3b8; margin-right: 2px;">INDEX:</span>
            ${['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX'].map(s => `
              <button class="atm-sym-btn ${activeSym === s ? 'active' : ''}" data-sym="${s}" style="padding: 4px 10px; font-size: 11px; font-weight: 800; border-radius: 5px; border: none; cursor: pointer; transition: all 0.2s ease;">
                ${s}
              </button>
            `).join('')}
          </div>

          <!-- View Mode Filter Buttons -->
          <div style="display: flex; align-items: center; gap: 4px; background: rgba(0, 0, 0, 0.45); padding: 3px 6px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08);">
            <button class="signal-filter-btn ${filterMode === 'MATRIX' ? 'active' : ''}" data-mode="MATRIX" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 6px; border: none; cursor: pointer;">
              🔥 STRIKE MATRIX (5)
            </button>
            <button class="signal-filter-btn ${filterMode === 'BUYER' ? 'active' : ''}" data-mode="BUYER" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 6px; border: none; cursor: pointer;">
              🚀 BUY SIGNALS ONLY
            </button>
            <button class="signal-filter-btn ${filterMode === 'SELLER' ? 'active' : ''}" data-mode="SELLER" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 6px; border: none; cursor: pointer;">
              🛡️ SELL SIGNALS ONLY
            </button>
            <button class="signal-filter-btn ${filterMode === 'TOP' ? 'active' : ''}" data-mode="TOP" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 6px; border: none; cursor: pointer;">
              ⭐ AI TOP PICKS (4 INDICES)
            </button>
          </div>
        </div>
      </div>

      <!-- Dynamic Content Mount: Corridor Summary Card + Strike Table -->
      <div id="atm-signals-dynamic-content">
        ${buildDynamicContentHTML(signals, filterMode, activeSym)}
      </div>
    </div>
  `;
}

function buildDynamicContentHTML(signals, filterMode, activeSym) {
  if (!signals || signals.length === 0) {
    return `
      <div style="text-align: center; padding: 40px; color: var(--text-muted);">
        <div style="display: flex; flex-direction: column; align-items: center; gap: 8px;">
          <span style="font-size: 28px;">⏳</span>
          <span style="font-size: 13px;">Streaming live ATM ± 2 option chain & PineScript indicators...</span>
        </div>
      </div>
    `;
  }

  // If in TOP picks mode, render the executive 4-index comparison view
  if (filterMode === 'TOP') {
    return buildExecutiveTopPicksHTML(signals);
  }

  // Find the selected symbol's dataset
  const symData = signals.find(s => s.symbol === activeSym) || signals[0];
  if (!symData) return '';

  const spot = symData.spot_price || 0;
  const atm = symData.atm_strike || 0;
  const tech = symData.technical_indicators || {};
  const ott = tech.ott_state || 'NEUTRAL';
  const adx = tech.adx || 20.0;
  const velocity = tech.velocity || 'MODERATE';
  const corridor = symData.atm_corridor_summary || {};
  const matrix = symData.strikes_matrix || [];

  // Filter rows if BUYER or SELLER mode is active
  let displayStrikes = matrix;
  if (filterMode === 'BUYER') {
    displayStrikes = matrix.filter(r => r.signal && r.signal.role === 'BUYER');
  } else if (filterMode === 'SELLER') {
    displayStrikes = matrix.filter(r => r.signal && r.signal.role === 'SELLER');
  }

  return `
    <!-- 1. Live Corridor Summary Glass Banner -->
    <div id="atm-corridor-summary-banner" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 14px; background: rgba(0, 0, 0, 0.4); padding: 12px 16px; border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.06);">
      ${buildCorridorSummaryBannerInner(symData)}
    </div>

    <!-- Mobile Quick Jump Bar (For easy 1-tap navigation between Call, Strike, Put, and Action Signals) -->
    <div class="atm-quick-jump-bar" style="display: flex; gap: 6px; margin-bottom: 10px; overflow-x: auto; padding-bottom: 4px;">
      <span style="font-size: 10px; font-weight: 800; color: #94a3b8; align-self: center; margin-right: 4px;">QUICK VIEW:</span>
      <button class="atm-jump-btn" id="atm-jump-calls" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(16,185,129,0.4); background: rgba(16,185,129,0.15); color: #34d399; cursor: pointer; white-space: nowrap;">
        🟢 Calls (CE)
      </button>
      <button class="atm-jump-btn" id="atm-jump-strike" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(56,189,248,0.4); background: rgba(56,189,248,0.15); color: #38bdf8; cursor: pointer; white-space: nowrap;">
        ⚓ Strike (ATM)
      </button>
      <button class="atm-jump-btn" id="atm-jump-puts" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(239,68,68,0.4); background: rgba(239,68,68,0.15); color: #f87171; cursor: pointer; white-space: nowrap;">
        🔴 Puts (PE)
      </button>
      <button class="atm-jump-btn" id="atm-jump-signals" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(245,158,11,0.4); background: rgba(245,158,11,0.15); color: #fbbf24; cursor: pointer; white-space: nowrap;">
        ⚡ Action Signals
      </button>
    </div>

    <!-- 2. The Full ATM ± 2 Strike Matrix Table -->
    <div id="atm-matrix-scroll-wrapper" style="overflow-x: auto; -webkit-overflow-scrolling: touch; position: relative;">
      <table class="terminal-table atm-table" style="width: 100%; min-width: 900px; font-size: 12px; border-collapse: separate; border-spacing: 0 4px;">
        <thead>
          <tr style="background: rgba(255, 255, 255, 0.04); color: var(--text-muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;">
            <th id="atm-th-strike" style="padding: 10px; text-align: left; position: sticky; left: 0; background: #0c1324; z-index: 10; border-right: 1px solid rgba(56,189,248,0.3);">STRIKE / TAG</th>
            <th id="atm-th-ce" style="padding: 10px; text-align: left; background: rgba(16, 185, 129, 0.04);">CALL (CE) CONTRACT & OI</th>
            <th id="atm-th-diff" style="padding: 10px; text-align: center; background: rgba(56, 189, 248, 0.04);">OI DIFFERENCE & PCR</th>
            <th id="atm-th-pe" style="padding: 10px; text-align: right; background: rgba(239, 68, 68, 0.04);">PUT (PE) CONTRACT & OI</th>
            <th id="atm-th-sig" style="padding: 10px; text-align: center; background: rgba(245, 158, 11, 0.08); border-left: 1px solid rgba(245, 158, 11, 0.3); border-right: 1px solid rgba(245, 158, 11, 0.3); color: #f8fafc; font-weight: 800;">
              ⚡ ACTION SIGNAL (BUY / SELL)
            </th>
            <th style="padding: 10px; text-align: center;">TQS SCORE</th>
            <th style="padding: 10px; text-align: center;">30s GATE / FLOW</th>
          </tr>
        </thead>
        <tbody id="atm-matrix-table-body">
          ${displayStrikes.length > 0 ? displayStrikes.map(r => renderMatrixRow(symData.symbol, r, spot, atm)).join('') : `
            <tr>
              <td colspan="7" style="text-align: center; padding: 25px; color: var(--text-muted);">
                No strikes matched filter mode "${filterMode}" for ${symData.symbol}.
              </td>
            </tr>
          `}
        </tbody>
      </table>
    </div>
  `;
}

function buildCorridorSummaryBannerInner(symData) {
  const spot = symData.spot_price || 0;
  const atm = symData.atm_strike || 0;
  const tech = symData.technical_indicators || {};
  const ott = tech.ott_state || 'NEUTRAL';
  const adx = tech.adx || 20.0;
  const corridor = symData.atm_corridor_summary || {};
  const regime = symData.market_regime || {};
  const regimeName = regime.regime ? regime.regime.replace(/_/g, ' ') : 'BALANCED';
  const isChop = regime.chop_shield_active;

  return `
    <!-- Spot & ATM -->
    <div>
      <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
        ${symData.symbol} SPOT & ATM
      </div>
      <div style="display: flex; align-items: baseline; gap: 6px; margin-top: 3px;">
        <strong style="font-size: 16px; font-family: var(--font-mono); color: #f8fafc;">
          ${spot.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
        </strong>
        <span style="font-size: 11px; color: #38bdf8; font-weight: 700;">
          (ATM: ${intOrFloat(atm)})
        </span>
      </div>
    </div>

    <!-- Corridor Total OI -->
    <div>
      <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
        ATM ± 2 CORRIDOR TOTAL OI
      </div>
      <div style="display: flex; align-items: baseline; gap: 6px; margin-top: 3px;">
        <strong style="font-size: 15px; font-family: var(--font-mono); color: #cbd5e1;">
          ${corridor.total_corridor_oi_formatted || '--'}
        </strong>
        <span style="font-size: 10.5px; color: ${corridor.total_put_oi_chg >= 0 ? '#10b981' : '#ef4444'};">
          (${corridor.total_call_oi_chg_formatted || '0'} CE : ${corridor.total_put_oi_chg_formatted || '0'} PE)
        </span>
      </div>
    </div>

    <!-- Difference in OI (Net Lead) -->
    <div>
      <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
        DIFFERENCE IN OI (NET BIAS)
      </div>
      <div style="display: flex; align-items: baseline; gap: 6px; margin-top: 3px;">
        <strong style="font-size: 14px; font-family: var(--font-mono); color: ${corridor.corridor_oi_diff >= 0 ? '#10b981' : '#ef4444'};">
          ${corridor.corridor_oi_diff_formatted || '--'}
        </strong>
      </div>
      <div style="font-size: 10px; color: var(--text-muted); margin-top: 1px;">
        &Delta;OI Diff: <span style="color: ${corridor.corridor_oi_chg_diff >= 0 ? '#10b981' : '#ef4444'}; font-weight: 700;">${corridor.corridor_oi_chg_diff_formatted || '0'}</span>
      </div>
    </div>

    <!-- Corridor PCR -->
    <div>
      <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
        CORRIDOR PCR
      </div>
      <div style="display: flex; align-items: baseline; gap: 6px; margin-top: 3px;">
        <strong style="font-size: 16px; font-family: var(--font-mono); color: ${corridor.corridor_pcr >= 1.0 ? '#10b981' : '#ef4444'};">
          ${corridor.corridor_pcr || '--'}
        </strong>
        <span style="font-size: 10.5px; font-weight: 700; color: ${corridor.corridor_pcr >= 1.0 ? '#10b981' : '#ef4444'};">
          ${corridor.corridor_pcr >= 1.15 ? 'BULLISH SUPPORT' : (corridor.corridor_pcr <= 0.85 ? 'BEARISH RESISTANCE' : 'BALANCED')}
        </span>
      </div>
    </div>

    <!-- Spot PineScript OTT & Momentum -->
    <div>
      <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
        SPOT PINESCRIPT OTT & ADX
      </div>
      <div style="display: flex; align-items: center; gap: 6px; margin-top: 3px;">
        <span style="font-size: 11px; padding: 2px 7px; border-radius: 4px; font-weight: 800; ${ott === 'BULLISH' ? 'background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);' : (ott === 'BEARISH' ? 'background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4);' : 'background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4);')}">
          ${ott === 'BULLISH' ? '🐂 OTT BULLISH' : (ott === 'BEARISH' ? '🐻 OTT BEARISH' : '⚖️ OTT NEUTRAL')}
        </span>
        <span style="font-size: 10.5px; font-family: var(--font-mono); color: var(--text-secondary);">
          ADX: <strong>${adx.toFixed(1)}</strong>
        </span>
      </div>
    </div>

    <!-- Vol-Regime & Chop Shield (AI-Trader Addon) -->
    <div>
      <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
        VOL-REGIME & CHOP SHIELD
      </div>
      <div style="display: flex; align-items: center; gap: 6px; margin-top: 3px;">
        <span class="badge ${regime.badge_class || 'badge-neutral'}" style="font-size: 11px; padding: 2px 7px; border-radius: 4px; font-weight: 800;">
          ${regimeName}
        </span>
      </div>
      <div style="font-size: 10px; margin-top: 2px; color: ${isChop ? '#fbbf24' : '#34d399'}; font-weight: 700;">
        ${isChop ? '🛡️ CHOP SHIELD ACTIVE' : '🚀 TREND RUNNER ACTIVE'}
      </div>
    </div>
  `;
}

function _setupAtmScrollListeners(container) {
  const scrollWrapper = container.querySelector('#atm-matrix-scroll-wrapper');
  if (!scrollWrapper) return;

  scrollWrapper.addEventListener('touchstart', () => { _isUserTouchingAtm = true; }, { passive: true });
  scrollWrapper.addEventListener('touchend', () => { 
    _isUserTouchingAtm = false; 
    _lastAtmScrollLeft = scrollWrapper.scrollLeft;
  }, { passive: true });
  scrollWrapper.addEventListener('scroll', () => {
    _lastAtmScrollLeft = scrollWrapper.scrollLeft;
  }, { passive: true });

  if (_lastAtmScrollLeft !== null) {
    scrollWrapper.scrollLeft = _lastAtmScrollLeft;
    requestAnimationFrame(() => { scrollWrapper.scrollLeft = _lastAtmScrollLeft; });
    setTimeout(() => { scrollWrapper.scrollLeft = _lastAtmScrollLeft; }, 50);
  }

  // Quick jump listeners
  const btnJumpCalls = container.querySelector('#atm-jump-calls');
  const btnJumpStrike = container.querySelector('#atm-jump-strike');
  const btnJumpPuts = container.querySelector('#atm-jump-puts');
  const btnJumpSignals = container.querySelector('#atm-jump-signals');

  btnJumpCalls?.addEventListener('click', () => {
    scrollWrapper.scrollTo({ left: 0, behavior: 'smooth' });
  });
  btnJumpStrike?.addEventListener('click', () => {
    const el = container.querySelector('#atm-th-strike');
    if (el) scrollWrapper.scrollTo({ left: 0, behavior: 'smooth' });
  });
  btnJumpPuts?.addEventListener('click', () => {
    const el = container.querySelector('#atm-th-pe');
    if (el) scrollWrapper.scrollTo({ left: el.offsetLeft - 30, behavior: 'smooth' });
  });
  btnJumpSignals?.addEventListener('click', () => {
    const el = container.querySelector('#atm-th-sig');
    if (el) scrollWrapper.scrollTo({ left: el.offsetLeft - 30, behavior: 'smooth' });
  });
}

function renderMatrixRow(sym, row, spot, atm) {
  const stk = row.strike;
  const stepTag = row.step_tag;
  const isAtm = stepTag === 'ATM';
  const ce = row.call || {};
  const pe = row.put || {};
  const sig = row.signal || {};
  const oiDiff = row.oi_diff || 0;
  const strikePcr = row.strike_pcr || 1.0;
  const ceGate = ce.premium_gate || {};
  const peGate = pe.premium_gate || {};

  // Moneyness / Step Tag styling
  let tagBg = 'rgba(255, 255, 255, 0.06)';
  let tagColor = '#94a3b8';
  if (isAtm) {
    tagBg = 'rgba(56, 189, 248, 0.2)';
    tagColor = '#38bdf8';
  } else if (stepTag.includes('1')) {
    tagBg = 'rgba(16, 185, 129, 0.15)';
    tagColor = '#34d399';
  } else if (stepTag.includes('2')) {
    tagBg = 'rgba(245, 158, 11, 0.15)';
    tagColor = '#fbbf24';
  }

  // Action Signal Badge & Detail
  let signalHtml = '';
  const act = sig.action || 'NEUTRAL';
  const tqs = sig.tqs_score || 50.0;
  const tqsColor = tqs >= 85 ? '#10b981' : (tqs >= 70 ? '#38bdf8' : '#f59e0b');

  if (act === 'BUY_CE' || act === 'BUY_PE') {
    const isCe = act === 'BUY_CE';
    signalHtml = `
      <div style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
        <span style="display: inline-block; padding: 3px 9px; border-radius: 6px; font-size: 11px; font-weight: 800; letter-spacing: 0.3px; ${isCe ? 'background: linear-gradient(135deg, rgba(16, 185, 129, 0.25), rgba(5, 150, 105, 0.3)); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.5); box-shadow: 0 0 10px rgba(16, 185, 129, 0.2);' : 'background: linear-gradient(135deg, rgba(239, 68, 68, 0.25), rgba(220, 38, 38, 0.3)); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.5); box-shadow: 0 0 10px rgba(239, 68, 68, 0.2);'}">
          ${sig.action_label}
        </span>
        <div style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); line-height: 1.2;">
          <span style="color: #10b981; font-weight: 700;">T1: ₹${sig.target_price}</span> | <span style="color: #ef4444;">SL: ₹${sig.stop_loss_price}</span>
        </div>
        <div style="font-size: 9.5px; color: #94a3b8; max-width: 190px; text-align: center; white-space: normal; line-height: 1.15; margin-top: 1px;">
          ${sig.reason || ''}
        </div>
      </div>
    `;
  } else if (act === 'WAIT_KNIFE' || act === 'CHOP_GATED') {
    signalHtml = `
      <div style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
        <span style="display: inline-block; padding: 3px 9px; border-radius: 6px; font-size: 11px; font-weight: 800; letter-spacing: 0.3px; background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.5);">
          ${sig.action_label}
        </span>
        <div style="font-size: 9.5px; color: #fbbf24; max-width: 190px; text-align: center; white-space: normal; line-height: 1.15; margin-top: 1px;">
          ${sig.reason || ''}
        </div>
      </div>
    `;
  } else if (act === 'SELL_CE' || act === 'SELL_PE') {
    signalHtml = `
      <div style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
        <span style="display: inline-block; padding: 3px 9px; border-radius: 6px; font-size: 11px; font-weight: 800; letter-spacing: 0.3px; background: linear-gradient(135deg, rgba(56, 189, 248, 0.25), rgba(2, 132, 199, 0.3)); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.5); box-shadow: 0 0 10px rgba(56, 189, 248, 0.2);">
          ${sig.action_label}
        </span>
        <div style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); line-height: 1.2;">
          <span style="color: #38bdf8; font-weight: 700;">Credit: ₹${sig.net_credit}</span> | <span style="color: #cbd5e1;">Tgt: ₹${sig.target_price}</span>
        </div>
        <div style="font-size: 9.5px; color: #94a3b8; max-width: 190px; text-align: center; white-space: normal; line-height: 1.15; margin-top: 1px;">
          ${sig.reason || ''}
        </div>
      </div>
    `;
  } else {
    signalHtml = `
      <div style="display: flex; flex-direction: column; align-items: center; gap: 2px;">
        <span style="display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 10.5px; font-weight: 700; background: rgba(255, 255, 255, 0.05); color: #94a3b8; border: 1px solid rgba(255, 255, 255, 0.1);">
          ⚖️ NEUTRAL
        </span>
        <div style="font-size: 9.5px; color: #64748b; max-width: 160px; text-align: center; white-space: normal;">
          ${sig.reason || 'Monitoring corridor'}
        </div>
      </div>
    `;
  }

  return `
    <tr style="background: ${isAtm ? 'rgba(56, 189, 248, 0.03)' : 'rgba(255, 255, 255, 0.015)'}; border-bottom: 1px solid rgba(255, 255, 255, 0.04); transition: background 0.15s ease;" onmouseover="this.style.background='rgba(56, 189, 248, 0.06)'" onmouseout="this.style.background='${isAtm ? 'rgba(56, 189, 248, 0.03)' : 'rgba(255, 255, 255, 0.015)'}'">
      <!-- 1. STRIKE & TAG -->
      <td style="padding: 10px; white-space: nowrap;">
        <div style="display: flex; align-items: center; gap: 6px;">
          <strong style="font-size: 14px; font-family: var(--font-mono); color: #f8fafc;">
            ${intOrFloat(stk)}
          </strong>
          <span style="font-size: 10px; font-weight: 800; padding: 1px 6px; border-radius: 4px; background: ${tagBg}; color: ${tagColor}; border: 1px solid ${tagColor};">
            ${stepTag}
          </span>
        </div>
        <div style="font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); margin-top: 2px;">
          ${row.dist_from_spot > 0 ? `+${row.dist_from_spot}` : row.dist_from_spot} pts from spot
        </div>
      </td>

      <!-- 2. CALL (CE) CONTRACT -->
      <td style="padding: 10px; background: rgba(16, 185, 129, 0.015);">
        <div style="display: flex; align-items: baseline; gap: 6px;">
          <strong style="font-size: 13px; font-family: var(--font-mono); color: #38bdf8;">
            ₹${(ce.ltp || 0).toFixed(2)}
          </strong>
          <span style="font-size: 10.5px; font-family: var(--font-mono); color: ${ce.pchange >= 0 ? '#10b981' : '#ef4444'};">
            ${ce.pchange >= 0 ? '+' : ''}${(ce.pchange || 0).toFixed(1)}%
          </span>
        </div>
        <div style="font-family: var(--font-mono); font-size: 10.5px; color: #cbd5e1; margin-top: 2px;">
          OI: <strong>${ce.oi_formatted || '--'}</strong> <span style="font-size: 9.5px; color: ${ce.oi_chg >= 0 ? '#10b981' : '#ef4444'};">(${ce.oi_chg_formatted || '0'})</span>
        </div>
        <div style="display: flex; align-items: center; gap: 4px; margin-top: 2px;">
          <span class="badge ${ce.buildup_badge || 'badge-neutral'}" style="font-size: 8.5px; padding: 1px 4px; border-radius: 3px; font-weight: 800;">
            ${ce.buildup ? ce.buildup.replace('_', ' ') : 'NEUTRAL'}
          </span>
          <span style="font-size: 9.5px; font-weight: 700; color: ${ce.opt_above_ott ? '#10b981' : '#f59e0b'};">
            ${ce.opt_above_ott ? `▲ Opt > OTT (+₹${ce.opt_distance})` : '▼ Under OTT'}
          </span>
        </div>
      </td>

      <!-- 3. OI DIFFERENCE & PCR -->
      <td style="padding: 10px; text-align: center; background: rgba(56, 189, 248, 0.015);">
        <div style="font-family: var(--font-mono); font-size: 12px; font-weight: 800; color: ${oiDiff >= 0 ? '#10b981' : '#ef4444'};">
          ${row.oi_diff_formatted || '--'}
        </div>
        <div style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); margin-top: 1px;">
          &Delta;OI: <strong style="color: ${row.oi_chg_diff >= 0 ? '#10b981' : '#ef4444'};">${row.oi_chg_diff_formatted || '0'}</strong>
        </div>
        <div style="display: inline-flex; align-items: center; gap: 4px; margin-top: 2px;">
          <span style="font-size: 10px; font-family: var(--font-mono); color: #cbd5e1;">
            PCR: <strong style="color: ${strikePcr >= 1.0 ? '#10b981' : '#ef4444'};">${strikePcr.toFixed(2)}</strong>
          </span>
        </div>
        <div style="font-size: 8.5px; font-weight: 800; color: ${row.writer_bias === 'BULLISH_SUPPORT' ? '#10b981' : (row.writer_bias === 'BEARISH_RESISTANCE' ? '#ef4444' : '#94a3b8')}; margin-top: 1px;">
          ${row.dominant_writer || ''}
        </div>
      </td>

      <!-- 4. PUT (PE) CONTRACT -->
      <td style="padding: 10px; text-align: right; background: rgba(239, 68, 68, 0.015);">
        <div style="display: flex; align-items: baseline; justify-content: flex-end; gap: 6px;">
          <span style="font-size: 10.5px; font-family: var(--font-mono); color: ${pe.pchange >= 0 ? '#10b981' : '#ef4444'};">
            ${pe.pchange >= 0 ? '+' : ''}${(pe.pchange || 0).toFixed(1)}%
          </span>
          <strong style="font-size: 13px; font-family: var(--font-mono); color: #38bdf8;">
            ₹${(pe.ltp || 0).toFixed(2)}
          </strong>
        </div>
        <div style="font-family: var(--font-mono); font-size: 10.5px; color: #cbd5e1; margin-top: 2px;">
          OI: <strong>${pe.oi_formatted || '--'}</strong> <span style="font-size: 9.5px; color: ${pe.oi_chg >= 0 ? '#10b981' : '#ef4444'};">(${pe.oi_chg_formatted || '0'})</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: flex-end; gap: 4px; margin-top: 2px;">
          <span style="font-size: 9.5px; font-weight: 700; color: ${pe.opt_above_ott ? '#10b981' : '#f59e0b'};">
            ${pe.opt_above_ott ? `▲ Opt > OTT (+₹${pe.opt_distance})` : '▼ Under OTT'}
          </span>
          <span class="badge ${pe.buildup_badge || 'badge-neutral'}" style="font-size: 8.5px; padding: 1px 4px; border-radius: 3px; font-weight: 800;">
            ${pe.buildup ? pe.buildup.replace('_', ' ') : 'NEUTRAL'}
          </span>
        </div>
      </td>

      <!-- 5. ACTION SIGNAL (BUY / SELL) -->
      <td style="padding: 10px; text-align: center; background: rgba(245, 158, 11, 0.03); border-left: 1px solid rgba(245, 158, 11, 0.15); border-right: 1px solid rgba(245, 158, 11, 0.15);">
        ${signalHtml}
      </td>

      <!-- 6. TQS SCORE -->
      <td style="padding: 10px; text-align: center;">
        <div style="font-size: 13px; font-family: var(--font-mono); font-weight: 800; color: ${tqsColor};">
          ${tqs.toFixed(0)} <span style="font-size: 9.5px; color: var(--text-muted);">/100</span>
        </div>
        <div style="font-size: 9px; font-weight: 700; color: ${tqsColor};">
          ${sig.conviction || 'NEUTRAL'}
        </div>
      </td>

      <!-- 7. 30s PREMIUM GATE & TICK MOMENTUM -->
      <td style="padding: 10px; text-align: center; white-space: nowrap;">
        <div style="display: flex; flex-direction: column; gap: 3px; align-items: center;">
          <span style="font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; ${ceGate?.is_falling_knife ? 'background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4);' : (ceGate?.momentum_pct >= 0.4 ? 'background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);' : 'background: rgba(255, 255, 255, 0.05); color: #94a3b8; border: 1px solid rgba(255, 255, 255, 0.1);')}">
            CE: ${ceGate?.is_falling_knife ? '⚠️ KNIFE' : (ceGate?.momentum_pct ? `${ceGate.momentum_pct > 0 ? '+' : ''}${ceGate.momentum_pct.toFixed(1)}%` : 'STEADY')}
          </span>
          <span style="font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; ${peGate?.is_falling_knife ? 'background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4);' : (peGate?.momentum_pct >= 0.4 ? 'background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);' : 'background: rgba(255, 255, 255, 0.05); color: #94a3b8; border: 1px solid rgba(255, 255, 255, 0.1);')}">
            PE: ${peGate?.is_falling_knife ? '⚠️ KNIFE' : (peGate?.momentum_pct ? `${peGate.momentum_pct > 0 ? '+' : ''}${peGate.momentum_pct.toFixed(1)}%` : 'STEADY')}
          </span>
        </div>
      </td>
    </tr>
  `;
}

function buildExecutiveTopPicksHTML(signals) {
  return `
    <div style="overflow-x: auto;">
      <table class="terminal-table atm-table" style="width: 100%; font-size: 12px; border-collapse: separate; border-spacing: 0 4px;">
        <thead>
          <tr style="background: rgba(255, 255, 255, 0.04); color: var(--text-muted); font-size: 10.5px; text-transform: uppercase;">
            <th style="padding: 10px; text-align: left;">INDEX / SPOT</th>
            <th style="padding: 10px; text-align: center;">VOL-REGIME & OTT</th>
            <th style="padding: 10px; text-align: center;">ROLE</th>
            <th style="padding: 10px; text-align: left;">TOP STRIKE (ATM ± 2)</th>
            <th style="padding: 10px; text-align: right;">LTP & SPREAD</th>
            <th style="padding: 10px; text-align: right;">TARGET / CREDIT</th>
            <th style="padding: 10px; text-align: center;">TQS SCORE</th>
            <th style="padding: 10px; text-align: left;">SIZING & THETA SHIELD</th>
          </tr>
        </thead>
        <tbody>
          ${signals.map(s => {
            const buyer = s.best_buyer_trade;
            const seller = s.best_seller_trade;
            const top = s.top_recommendation || {};
            const regime = s.market_regime || {};
            let rows = [];
            if (buyer) rows.push(renderTopRow(s.symbol, s.spot_price, s.atm_strike, s.lot_size, s.technical_indicators, buyer, 'BUYER', top.role === 'BUYER', regime));
            if (seller) rows.push(renderTopRow(s.symbol, s.spot_price, s.atm_strike, s.lot_size, s.technical_indicators, seller, 'SELLER', top.role === 'SELLER', regime));
            return rows.join('');
          }).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderTopRow(sym, spot, atm, lotSize, tech, trade, role, isTop, regime) {
  if (!trade) return '';
  const isBuyer = role === 'BUYER';
  const ott = tech?.ott_state || 'NEUTRAL';
  const adx = tech?.adx || 20.0;
  const isOttBull = ott === 'BULLISH';
  const isOttBear = ott === 'BEARISH';
  const tqs = trade.tqs_score || 80.0;
  const tqsColor = tqs >= 85 ? '#10b981' : (tqs >= 70 ? '#38bdf8' : '#f59e0b');
  const regimeName = regime?.regime ? regime.regime.replace(/_/g, ' ') : 'BALANCED';

  return `
    <tr style="background: rgba(255, 255, 255, 0.02); transition: background 0.15s ease;" onmouseover="this.style.background='rgba(56, 189, 248, 0.05)'" onmouseout="this.style.background='rgba(255, 255, 255, 0.02)'">
      <td style="padding: 10px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <strong style="font-size: 13px; color: #f8fafc;">${sym}</strong>
          ${isTop ? `<span style="font-size: 9.5px; padding: 1px 5px; border-radius: 4px; background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); font-weight: 800;">★ TOP PICK</span>` : ''}
        </div>
        <div style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); margin-top: 2px;">
          Spot: <span style="color: var(--text-primary); font-weight: 600;">${spot.toLocaleString('en-IN', { minimumFractionDigits: 1 })}</span> | ATM: ${intOrFloat(atm)}
        </div>
      </td>
      <td style="padding: 10px; text-align: center;">
        <div style="display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; border-radius: 4px; font-weight: 800; font-size: 10.5px; ${isOttBull ? 'background: rgba(16, 185, 129, 0.15); color: #10b981;' : (isOttBear ? 'background: rgba(239, 68, 68, 0.15); color: #ef4444;' : 'background: rgba(245, 158, 11, 0.15); color: #f59e0b;')}">
          ${isOttBull ? '🐂' : (isOttBear ? '🐻' : '⚖️')} OTT ${ott}
        </div>
        <div style="font-size: 9.5px; font-weight: 700; color: #94a3b8; margin-top: 2px;">
          ${regimeName} (ADX: ${adx.toFixed(1)})
        </div>
      </td>
      <td style="padding: 10px; text-align: center;">
        <span style="display: inline-block; padding: 3px 8px; border-radius: 5px; font-size: 10.5px; font-weight: 800; ${isBuyer ? 'background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4);' : 'background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4);'}">
          ${isBuyer ? '🚀 BUY MOMENTUM' : '🛡️ SELL DECAY'}
        </span>
      </td>
      <td style="padding: 10px;">
        <div style="display: flex; align-items: center; gap: 6px;">
          <strong style="font-size: 13px; font-family: var(--font-mono); color: #f1f5f9;">
            ${trade.strike_label || trade.strike}
          </strong>
        </div>
        <div style="font-family: var(--font-mono); font-size: 10.5px; color: #cbd5e1; margin-top: 2px;">
          OI: <strong>${trade.oi_formatted || '--'}</strong> <span style="font-size: 9.5px; color: ${trade.oi_chg >= 0 ? '#10b981' : '#ef4444'};">(${trade.oi_chg_formatted || '0'})</span>
        </div>
        <div style="font-size: 9.5px; font-weight: 700; color: ${trade.option_ott_confirmed ? '#10b981' : '#f59e0b'}; margin-top: 1px;">
          ${trade.option_ott_confirmed ? '▲ Opt Confirmed with OTT' : '▼ Opt Testing OTT'}
        </div>
      </td>
      <td style="padding: 10px; text-align: right;">
        <div style="font-family: var(--font-mono); font-size: 13px; font-weight: 800; color: #38bdf8;">
          ₹${(trade.ltp || 0).toFixed(2)}
        </div>
      </td>
      <td style="padding: 10px; text-align: right;">
        ${isBuyer ? `
          <div style="font-family: var(--font-mono); font-size: 11px; color: #10b981; font-weight: 700;">
            T1: ₹${(trade.target1_price || 0).toFixed(1)}
          </div>
          <div style="font-family: var(--font-mono); font-size: 10px; color: #ef4444;">
            SL: ₹${(trade.stop_loss_price || 0).toFixed(1)}
          </div>
        ` : `
          <div style="font-family: var(--font-mono); font-size: 11px; color: #38bdf8; font-weight: 700;">
            Credit: ₹${(trade.net_credit_inr || 0).toLocaleString('en-IN')}
          </div>
          <div style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted);">
            Theta: ₹${trade.daily_theta_inr || 0}/d
          </div>
        `}
      </td>
      <td style="padding: 10px; text-align: center;">
        <div style="font-size: 13px; font-family: var(--font-mono); font-weight: 800; color: ${tqsColor};">
          ${tqs.toFixed(0)} <span style="font-size: 9.5px; color: var(--text-muted);">/100</span>
        </div>
        <div style="font-size: 9px; font-weight: 700; color: ${tqsColor};">
          ${trade.conviction || 'GOOD'}
        </div>
      </td>
      <td style="padding: 10px;">
        <div style="display: flex; align-items: center; gap: 6px;">
          <span class="badge ${trade.sizing_badge || 'badge-active'}" style="font-size: 10px; font-weight: 800; padding: 2px 6px;">
            ${trade.suggested_lots ? `${trade.suggested_lots} LOTS` : '2 LOTS'}
          </span>
          <span style="font-size: 9.5px; color: #94a3b8; font-family: var(--font-mono);">
            (${trade.sizing_tier ? trade.sizing_tier.split(' ')[2] : 'TIER'})
          </span>
        </div>
        ${trade.premium_gate?.status_label ? `
          <div style="font-size: 9.5px; font-weight: 700; color: ${trade.premium_gate?.is_falling_knife ? '#ef4444' : '#10b981'}; margin-top: 2px;">
            Gate: ${trade.premium_gate.status_label}
          </div>
        ` : ''}
        <div style="font-size: 9.5px; color: #cbd5e1; max-width: 190px; line-height: 1.2; margin-top: 2px;">
          ${trade.theta_shield?.advice || 'Dynamic Trailing Ratchet Active'}
        </div>
      </td>
    </tr>
  `;
}

function intOrFloat(val) {
  if (val === undefined || val === null) return '--';
  return Number.isInteger(val) ? val : Math.round(val);
}

