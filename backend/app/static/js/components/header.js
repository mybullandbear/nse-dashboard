/**
 * Top Navigation & Institutional Telemetry Header Component
 * FLICKER-FREE: skeleton built once; only dynamic values patched on each call.
 */
import { store } from '../state.js';
import { AccessGate } from './access_gate.js';

let _headerBuilt = false;
let _lastActivePair = null;
let _lastViewMode   = null;
let _lastFyersToken = null;

export function renderHeader(container, onPairChange, onSingleSymbolChange, onAuthClick, onRefreshClick) {
  const state      = store.getState();
  const session    = state.session || {};
  const fyers      = state.fyersStatus || {};
  const isLive     = session.is_market_open;
  const activePair = state.activePair;
  const viewMode   = state.viewMode;

  // ── Build skeleton only once (or if pair/mode changed) ──────────────────
  const pairChanged = activePair !== _lastActivePair || viewMode !== _lastViewMode;
  if (!_headerBuilt || pairChanged || !container.querySelector('header.top-header')) {
    _headerBuilt    = true;
    _lastActivePair = activePair;
    _lastViewMode   = viewMode;

    const nb = viewMode === 'PAIR' && activePair === 'NIFTY_BANKNIFTY' ? 'active' : '';
    const fm = viewMode === 'PAIR' && activePair === 'FINNIFTY_MIDCPNIFTY' ? 'active' : '';
    const sx = (viewMode === 'SINGLE' && state.symbol1 === 'SENSEX') || activePair === 'SENSEX' ? 'active' : '';

    container.innerHTML = `
      <header class="top-header" style="
        min-height: 52px; height: 52px;
        background: #090d16;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        display: flex; align-items: center; justify-content: space-between;
        padding: 0 18px; position: sticky; top: 0; z-index: 100;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
      ">
        <!-- Brand Identity -->
        <div class="logo-section" style="display: flex; align-items: center; gap: 10px;">
          <div style="
            width: 28px; height: 28px; border-radius: 6px;
            background: linear-gradient(135deg, #0284c7, #38bdf8);
            display: flex; align-items: center; justify-content: center;
            font-size: 14px; font-weight: 900; color: #fff;
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.35);
          ">⚡</div>
          <div style="display: flex; align-items: baseline; gap: 6px;">
            <span style="font-size: 14px; font-weight: 800; letter-spacing: 0.8px; color: #f8fafc; font-family: var(--font-sans);">MYBULLANDBEAR</span>
            <span style="
              font-size: 9px; font-weight: 800; font-family: var(--font-mono);
              color: #38bdf8; background: rgba(56, 189, 248, 0.12);
              padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(56, 189, 248, 0.25);
              letter-spacing: 0.5px;
            ">TERMINAL</span>
          </div>
        </div>

        <!-- Center Asset Segmented Switcher -->
        <div class="header-center" style="display: flex; align-items: center;">
          <div class="symbol-selector" id="pair-selector-group" style="
            display: inline-flex; background: rgba(15, 23, 42, 0.7);
            padding: 3px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.06);
            gap: 2px;
          ">
            <button class="pair-btn ${nb}" data-pair="NIFTY_BANKNIFTY" style="
              background: ${nb ? '#1e293b' : 'transparent'};
              color: ${nb ? '#38bdf8' : '#94a3b8'};
              border: 1px solid ${nb ? 'rgba(56, 189, 248, 0.3)' : 'transparent'};
              font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px; cursor: pointer;
              transition: all 0.2s; font-family: var(--font-mono);
            ">
              NIFTY · BANKNIFTY
            </button>
            <button class="pair-btn ${fm}" data-pair="FINNIFTY_MIDCPNIFTY" style="
              background: ${fm ? '#1e293b' : 'transparent'};
              color: ${fm ? '#38bdf8' : '#94a3b8'};
              border: 1px solid ${fm ? 'rgba(56, 189, 248, 0.3)' : 'transparent'};
              font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px; cursor: pointer;
              transition: all 0.2s; font-family: var(--font-mono);
            ">
              FINNIFTY · MIDCAP
            </button>
            <button class="pair-btn ${sx}" data-symbol="SENSEX" style="
              background: ${sx ? '#1e293b' : 'transparent'};
              color: ${sx ? '#38bdf8' : '#94a3b8'};
              border: 1px solid ${sx ? 'rgba(56, 189, 248, 0.3)' : 'transparent'};
              font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px; cursor: pointer;
              transition: all 0.2s; font-family: var(--font-mono);
            ">
              SENSEX
            </button>
          </div>
        </div>

        <!-- Header Actions & Telemetry -->
        <div class="header-actions" style="display: flex; align-items: center; gap: 8px;">
          <!-- Session Badge -->
          <div id="hdr-session-badge" style="
            display: inline-flex; align-items: center; gap: 6px;
            font-size: 10.5px; font-weight: 700; font-family: var(--font-mono);
            padding: 4px 8px; border-radius: 6px;
            background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08);
            color: #cbd5e1;
          ">
            <span class="pulse-dot" style="
              width: 6px; height: 6px; border-radius: 50%;
              background: ${isLive ? '#10b981' : '#64748b'};
              box-shadow: ${isLive ? '0 0 6px #10b981' : 'none'};
            "></span>
            <span id="hdr-session-state">${session.session_state || 'OFF-MARKET'}</span>
            <span id="hdr-session-time" style="color: #64748b; margin-left: 2px;">${session.current_time_ist || ''} IST</span>
          </div>

          <!-- Data Source Chip -->
          <div id="hdr-datasource" style="
            font-size: 10px; font-weight: 700; font-family: var(--font-mono);
            padding: 4px 8px; border-radius: 6px;
            background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08);
            color: #f59e0b;
          ">● LIVE</div>

          <!-- Fyers Connect Button -->
          <button class="btn-fyers" id="btn-open-fyers" style="
            display: inline-flex; align-items: center; gap: 6px;
            font-size: 11px; font-weight: 700; font-family: var(--font-mono);
            padding: 4px 10px; border-radius: 6px; cursor: pointer;
            background: ${fyers.has_token ? 'rgba(16, 185, 129, 0.12)' : 'rgba(14, 165, 233, 0.12)'};
            color: ${fyers.has_token ? '#34d399' : '#38bdf8'};
            border: 1px solid ${fyers.has_token ? 'rgba(16, 185, 129, 0.35)' : 'rgba(56, 189, 248, 0.35)'};
            transition: all 0.2s;
          ">
            <span id="hdr-fyers-dot" class="fyers-dot" style="
              width: 6px; height: 6px; border-radius: 50%;
              background: ${fyers.has_token ? '#10b981' : '#38bdf8'};
            "></span>
            <span id="hdr-fyers-label">${fyers.has_token ? 'FYERS ACTIVE' : 'CONNECT FYERS'}</span>
          </button>

          <!-- Force Refresh -->
          <button class="btn-fyers" id="btn-manual-refresh" title="Force Refresh" style="
            background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08);
            color: #94a3b8; font-size: 12px; padding: 4px 8px; border-radius: 6px; cursor: pointer;
          ">
            ↻
          </button>

          <!-- Lock Terminal -->
          <button class="btn-fyers" id="btn-lock-terminal" title="Lock Terminal" style="
            background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.25);
            color: #f87171; font-size: 11px; padding: 4px 8px; border-radius: 6px; cursor: pointer;
          ">
            🔒
          </button>
        </div>
      </header>
    `;

    // Attach listeners
    container.querySelectorAll('.pair-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const pair = btn.getAttribute('data-pair');
        const sym = btn.getAttribute('data-symbol');
        if (pair && onPairChange) onPairChange(pair);
        if (sym && onSingleSymbolChange) onSingleSymbolChange(sym);
      });
    });
    const fyersBtn = container.querySelector('#btn-open-fyers');
    if (fyersBtn && onAuthClick) fyersBtn.addEventListener('click', onAuthClick);
    const refreshBtn = container.querySelector('#btn-manual-refresh');
    if (refreshBtn && onRefreshClick) refreshBtn.addEventListener('click', onRefreshClick);
    const lockBtn = container.querySelector('#btn-lock-terminal');
    if (lockBtn) lockBtn.addEventListener('click', () => AccessGate.lockTerminal());

    _lastFyersToken = null;
  }

  // ── Patch dynamic values in-place every call ────────────────────────────
  const sessionBadge = container.querySelector('#hdr-session-badge');
  const dotEl = sessionBadge?.querySelector('.pulse-dot');
  if (dotEl) {
    dotEl.style.background = isLive ? '#10b981' : '#64748b';
    dotEl.style.boxShadow = isLive ? '0 0 6px #10b981' : 'none';
  }
  _setText(container.querySelector('#hdr-session-state'), session.session_state || 'OFF-MARKET');
  _setText(container.querySelector('#hdr-session-time'), (session.current_time_ist || '') + ' IST');

  const dsEl = container.querySelector('#hdr-datasource');
  if (dsEl) {
    const src = state.dataSource || 'REAL_MARKET';
    const col = src.startsWith('REPLAY') ? '#c084fc' : (src === 'FYERS_LIVE' ? '#10b981' : (src === 'NSE_LIVE' ? '#38bdf8' : '#f59e0b'));
    dsEl.style.color = col;
    _setText(dsEl, '● ' + src);
  }

  if (fyers.has_token !== _lastFyersToken) {
    _lastFyersToken = fyers.has_token;
    const fyersBtn = container.querySelector('#btn-open-fyers');
    const fyersDot = container.querySelector('#hdr-fyers-dot');
    const labelEl  = container.querySelector('#hdr-fyers-label');
    if (fyersBtn) {
      fyersBtn.style.background = fyers.has_token ? 'rgba(16, 185, 129, 0.12)' : 'rgba(14, 165, 233, 0.12)';
      fyersBtn.style.color = fyers.has_token ? '#34d399' : '#38bdf8';
      fyersBtn.style.borderColor = fyers.has_token ? 'rgba(16, 185, 129, 0.35)' : 'rgba(56, 189, 248, 0.35)';
    }
    if (fyersDot) fyersDot.style.background = fyers.has_token ? '#10b981' : '#38bdf8';
    if (labelEl) labelEl.textContent = fyers.has_token ? 'FYERS ACTIVE' : 'CONNECT FYERS';
  }
}

function _setText(el, text) {
  if (el && el.textContent !== text) el.textContent = text;
}
