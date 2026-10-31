/**
 * Multi-Index Alignment Matrix Bar & Institutional Conviction Telemetry
 * ═════════════════════════════════════════════════════════════════════════════
 * Professional Financial Design System (Bloomberg / TradingView / Linear Pro)
 * 1. 5-Index Institutional Grid (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX):
 *    - Real-time Spot price & Session % change
 *    - 6-Pillar Indicator Status (BRK, MAPO, PCR, OI FLOW, BUILDUOP, HULL)
 *    - Delta-Aligned Recommended Strike (1-ITM Δ0.53 / ATM Δ0.50)
 *    - Glowing Directive Verdict (BUY CALL, BUY PUT, CHOP GATE)
 * 2. Cross-Market Alignment Headline:
 *    - Instant institutional consensus (e.g., 4/5 Bullish Aligned)
 * 3. Collapsible 10-LED Symmetrical Conviction Scale
 */
import { store } from '../state.js';
import { ApiClient } from '../api.js';

let _activeSym = 'NIFTY';
let _isPolling = false;
let _weightagePollTimer = null;
let _lastAlignmentData = null;

export async function renderDirectionalWeightageBar(container) {
  if (!container) return;

  const state = store.getState();
  const currentSymbol = state.activeSymbol || state.symbol1 || _activeSym;
  _activeSym = currentSymbol;

  // Build structure once
  if (!container.querySelector('.institutional-alignment-panel')) {
    container.innerHTML = `
      <div class="institutional-alignment-panel" style="
        margin: 10px 0 14px 0;
        padding: 12px 16px;
        background: #090d16;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
        position: relative;
      ">
        <!-- 1. Macro Alignment Headline Strip -->
        <div style="
          display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center;
          gap: 10px; margin-bottom: 12px; padding-bottom: 10px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        ">
          <div style="display: flex; align-items: center; gap: 10px;">
            <div style="
              width: 28px; height: 28px; border-radius: 6px;
              background: linear-gradient(135deg, #0284c7, #38bdf8);
              display: flex; align-items: center; justify-content: center;
              font-size: 15px; color: #fff; box-shadow: 0 0 10px rgba(56, 189, 248, 0.35);
            ">⚡</div>
            <div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 13px; font-weight: 800; letter-spacing: 0.5px; color: #f8fafc; font-family: var(--font-sans);">
                  INSTITUTIONAL MULTI-INDEX ALIGNMENT
                </span>
                <span id="multi-macro-alignment-badge" style="
                  font-size: 10px; font-weight: 800; font-family: var(--font-mono);
                  padding: 2px 8px; border-radius: 4px;
                  background: rgba(56, 189, 248, 0.12); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.25);
                ">MONITORING 5M CONFLUENCE...</span>
              </div>
              <div style="font-size: 10.5px; color: #64748b; margin-top: 1px; font-family: var(--font-sans);">
                6-Pillar institutional harmony across all 5 indices • Click any tile to focus terminal
              </div>
            </div>
          </div>

          <div style="display: flex; align-items: center; gap: 8px;">
            <span id="dw-chop-shield-pill" style="
              font-size: 10px; font-weight: 700; font-family: var(--font-mono);
              padding: 3px 8px; border-radius: 4px;
              background: rgba(16, 185, 129, 0.12); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.25);
            ">🛡️ 5M CONFLUENCE CONFIRMED</span>
            <button id="toggle-conviction-scale-btn" style="
              background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08);
              color: #94a3b8; font-size: 10.5px; font-weight: 700; font-family: var(--font-mono);
              padding: 3px 9px; border-radius: 4px; cursor: pointer; transition: all 0.2s;
            ">⚖️ Conviction Gauge ▼</button>
          </div>
        </div>

        <!-- 2. The 5-Index Institutional Cards Grid -->
        <div id="multi-alignment-cards-grid" style="
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(215px, 1fr));
          gap: 10px;
          margin-bottom: 6px;
        ">
          <!-- Populated dynamically via _updateAlignmentGrid -->
        </div>

        <!-- 3. Collapsible Active Symbol LED Conviction Scale -->
        <div id="dw-conviction-scale-container" style="
          display: none;
          margin-top: 10px;
          background: #06090e;
          padding: 12px 16px;
          border-radius: 8px;
          border: 1px solid rgba(255, 255, 255, 0.06);
        ">
          <div style="display: flex; justify-content: space-between; font-size: 10.5px; font-weight: 800; font-family: var(--font-mono); margin-bottom: 6px;">
            <span style="color: #f43f5e;">◄ BEARISH WEIGHTAGE <span id="dw-bear-level" style="opacity: 0.7;">(0/5)</span></span>
            <span id="dw-center-status" style="color: #fbbf24;">● CHOP / DEAD CONSOLIDATION</span>
            <span style="color: #10b981;"><span id="dw-bull-level" style="opacity: 0.7;">(0/5)</span> BULLISH WEIGHTAGE ►</span>
          </div>

          <!-- Symmetrical 10-LED Segment Light Bar -->
          <div style="display: flex; gap: 4px; height: 14px; margin-bottom: 8px;">
            ${[5, 4, 3, 2, 1].map(n => `
              <div class="dw-led-seg dw-bear-seg" data-level="${n}" style="
                flex: 1; border-radius: 2px; background: rgba(244, 63, 94, 0.1);
                border: 1px solid rgba(244, 63, 94, 0.25); transition: all 0.2s ease;
              "></div>
            `).join('')}
            <div id="dw-center-amber-led" style="
              width: 12px; border-radius: 2px; background: rgba(245, 158, 11, 0.5);
              border: 1px solid #f59e0b;
            "></div>
            ${[1, 2, 3, 4, 5].map(n => `
              <div class="dw-led-seg dw-bull-seg" data-level="${n}" style="
                flex: 1; border-radius: 2px; background: rgba(16, 185, 129, 0.1);
                border: 1px solid rgba(16, 185, 129, 0.25); transition: all 0.2s ease;
              "></div>
            `).join('')}
          </div>

          <!-- Continuous Smooth Weightage Fill -->
          <div style="position: relative; height: 3px; background: rgba(255,255,255,0.06); border-radius: 2px; overflow: hidden; margin-bottom: 8px;">
            <div id="dw-continuous-fill" style="
              position: absolute; top: 0; bottom: 0; left: 50%; width: 0%;
              background: #f59e0b; transition: all 0.25s ease;
            "></div>
          </div>

          <!-- Bottom Telemetry Readouts -->
          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 10.5px; font-family: var(--font-mono); color: #94a3b8; border-top: 1px solid rgba(255, 255, 255, 0.05); padding-top: 6px;">
            <div>
              <span>FOCUS: </span><span id="dw-active-sym-title" style="color: #38bdf8; font-weight: 800;">${_activeSym}</span>
              <span style="margin: 0 6px;">•</span>
              <span>CONVICTION: </span><span id="dw-conviction-readout" style="color: #fbbf24; font-weight: 800;">0% NEUTRAL</span>
            </div>
            <div>
              <span>CONFLUENCE: </span><span id="dw-confluence-readout" style="color: #38bdf8; font-weight: 800;">50.0</span>
            </div>
            <div>
              <span>DIRECTIVE: </span><span id="dw-action-readout" style="color: #f8fafc; font-weight: 800;">CALCULATING...</span>
            </div>
          </div>
        </div>

      </div>
    `;

    // Hook up Toggle button for conviction scale
    const toggleBtn = container.querySelector('#toggle-conviction-scale-btn');
    const scaleEl = container.querySelector('#dw-conviction-scale-container');
    if (toggleBtn && scaleEl) {
      toggleBtn.addEventListener('click', () => {
        const isHidden = scaleEl.style.display === 'none';
        scaleEl.style.display = isHidden ? 'block' : 'none';
        toggleBtn.textContent = isHidden ? '⚖️ Conviction Gauge ▲' : '⚖️ Conviction Gauge ▼';
      });
    }
  }

  // Initial update
  await _fetchAndUpdate(container);

  // Background poller (2.2s)
  if (!_weightagePollTimer) {
    _weightagePollTimer = setInterval(() => {
      if (!document.body.contains(container)) {
        clearInterval(_weightagePollTimer);
        _weightagePollTimer = null;
        return;
      }
      _fetchAndUpdate(container);
    }, 2200);
  }
}

async function _fetchAndUpdate(container) {
  if (_isPolling) return;
  _isPolling = true;

  try {
    const res = await ApiClient.fetchLiveMatrix();
    if (res && res.status === 'success') {
      _lastAlignmentData = res;
      _updateAlignmentGrid(container, res);
      _updateSingleConviction(container, res);
    }
  } catch (err) {
    console.debug('Alignment bar tick error:', err);
  } finally {
    _isPolling = false;
  }
}

function _updateAlignmentGrid(container, matrixRes) {
  const grid = container.querySelector('#multi-alignment-cards-grid');
  const macroBadge = container.querySelector('#multi-macro-alignment-badge');
  if (!grid || !matrixRes) return;

  const alignInfo = matrixRes.alignment_matrix || {};
  const indices = alignInfo.indices || [];

  if (macroBadge && alignInfo.macro_text) {
    macroBadge.textContent = alignInfo.macro_text;
    const isBull = alignInfo.macro_badge?.includes('green');
    const isBear = alignInfo.macro_badge?.includes('red');
    macroBadge.style.color = isBull ? '#34d399' : (isBear ? '#f87171' : '#fbbf24');
    macroBadge.style.background = isBull ? 'rgba(16, 185, 129, 0.12)' : (isBear ? 'rgba(239, 68, 68, 0.12)' : 'rgba(245, 158, 11, 0.12)');
    macroBadge.style.borderColor = isBull ? 'rgba(16, 185, 129, 0.3)' : (isBear ? 'rgba(239, 68, 68, 0.3)' : 'rgba(245, 158, 11, 0.3)');
  }

  const tickerList = store.getState().indices || [];

  grid.innerHTML = indices.map(idx => {
    const isSelected = idx.symbol === _activeSym;
    const isBull = idx.verdict === 'BUY CALL';
    const isBear = idx.verdict === 'BUY PUT';

    const tick = tickerList.find(t => t.symbol === idx.symbol);
    const pctChg = tick ? (tick.percent_change || 0) : 0;
    const isTickUp = pctChg >= 0;

    const badgeBg = isBull ? 'rgba(16, 185, 129, 0.15)' : (isBear ? 'rgba(239, 68, 68, 0.15)' : 'rgba(245, 158, 11, 0.12)');
    const badgeColor = isBull ? '#34d399' : (isBear ? '#f87171' : '#fbbf24');
    const badgeBorder = isBull ? 'rgba(16, 185, 129, 0.3)' : (isBear ? 'rgba(239, 68, 68, 0.3)' : 'rgba(245, 158, 11, 0.3)');

    // 6 Pillars Status Colors & Indicators
    const pBreakoutColor = idx.breakout === 'LONG' ? '#34d399' : (idx.breakout === 'SHORT' ? '#f87171' : '#94a3b8');
    const pMapoColor = idx.proximity?.includes('BULL') ? '#34d399' : (idx.proximity?.includes('BEAR') ? '#f87171' : '#fbbf24');
    const pPcrColor = idx.pcr >= 1.05 ? '#34d399' : (idx.pcr <= 0.85 ? '#f87171' : '#fbbf24');
    const pOiColor = idx.net_oi_flow?.includes('INCREASING') ? '#34d399' : (idx.net_oi_flow?.includes('DECREASING') ? '#f87171' : '#94a3b8');
    const pHullColor = idx.hull === 'BULLISH' ? '#34d399' : (idx.hull === 'BEARISH' ? '#f87171' : '#fbbf24');

    return `
      <div class="multi-alignment-card" data-sym="${idx.symbol}" style="
        background: ${isSelected ? '#111827' : '#0c1017'};
        border: 1px solid ${isSelected ? '#38bdf8' : 'rgba(255, 255, 255, 0.08)'};
        border-radius: 8px; padding: 10px 12px; cursor: pointer;
        box-shadow: ${isSelected ? '0 0 14px rgba(56, 189, 248, 0.25)' : 'none'};
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        display: flex; flex-direction: column; justify-content: space-between; gap: 8px;
      ">
        <!-- Top Row: Symbol & Spot Price -->
        <div style="display: flex; justify-content: space-between; align-items: baseline;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="font-size: 13px; font-weight: 800; color: ${isSelected ? '#38bdf8' : '#f8fafc'}; font-family: var(--font-mono);">
              ${idx.symbol}
            </span>
            <span style="
              font-size: 9px; font-weight: 700; font-family: var(--font-mono);
              color: ${isTickUp ? '#34d399' : '#f87171'};
              background: ${isTickUp ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)'};
              padding: 1px 4px; border-radius: 3px;
            ">
              ${isTickUp ? '+' : ''}${pctChg.toFixed(2)}%
            </span>
          </div>

          <div style="font-size: 12.5px; font-weight: 800; color: #f8fafc; font-family: var(--font-mono);">
            ₹${Number(idx.spot).toLocaleString('en-IN', { maximumFractionDigits: 1 })}
          </div>
        </div>

        <!-- 6 Pillars Telemetry Row -->
        <div style="
          display: flex; justify-content: space-between; align-items: center;
          background: rgba(0, 0, 0, 0.35); padding: 4px 6px; border-radius: 4px;
          font-size: 9.5px; font-family: var(--font-mono); border: 1px solid rgba(255, 255, 255, 0.04);
        ">
          <span title="Breakout: ${idx.breakout}" style="color: ${pBreakoutColor};">BRK ${idx.breakout === 'LONG' ? '▲' : (idx.breakout === 'SHORT' ? '▼' : '—')}</span>
          <span title="MAPO Proximity: ${idx.proximity}" style="color: ${pMapoColor};">MAPO</span>
          <span title="PCR: ${idx.pcr}" style="color: ${pPcrColor};">PCR ${idx.pcr}</span>
          <span title="Net OI Velocity: ${idx.net_oi_flow}" style="color: ${pOiColor};">OI ${idx.net_oi_flow?.includes('INCREASING') ? '▲' : '▼'}</span>
          <span title="5M Hull: ${idx.hull}" style="color: ${pHullColor};">HULL</span>
        </div>

        <!-- Bottom Directive & Delta-Aligned Strike -->
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px;">
          <span style="
            font-size: 9.5px; font-weight: 800; padding: 2px 6px; border-radius: 4px;
            background: ${badgeBg}; color: ${badgeColor}; border: 1px solid ${badgeBorder};
            font-family: var(--font-mono); letter-spacing: 0.3px;
          ">${idx.verdict}</span>

          <span style="
            font-size: 10px; font-weight: 700; color: #cbd5e1; font-family: var(--font-mono);
            background: rgba(255, 255, 255, 0.05); padding: 2px 6px; border-radius: 4px;
            border: 1px solid rgba(255, 255, 255, 0.08); text-align: right;
          " title="${idx.suggested_strike}">
            ${idx.suggested_strike.split('/')[0] || idx.suggested_strike}
          </span>
        </div>
      </div>
    `;
  }).join('');

  // Attach card click handlers
  grid.querySelectorAll('.multi-alignment-card').forEach(card => {
    card.addEventListener('click', () => {
      const sym = card.getAttribute('data-sym');
      if (sym) {
        _activeSym = sym;
        store.setState({ activeSymbol: sym, symbol1: sym });
        _updateAlignmentGrid(container, matrixRes);
        _updateSingleConviction(container, matrixRes);
      }
    });
  });
}

function _updateSingleConviction(container, matrixRes) {
  const indices = matrixRes.data || [];
  const currentItem = indices.find(i => i.symbol === _activeSym) || indices[0];
  if (!currentItem) return;

  const score = currentItem.confluence?.score || 50;
  const isBull = score >= 58;
  const isBear = score <= 42;
  const absWeight = Math.abs(score - 50);

  const symTitle = container.querySelector('#dw-active-sym-title');
  if (symTitle) symTitle.textContent = currentItem.symbol;

  let barsLit = 0;
  if (absWeight >= 25) barsLit = 5;
  else if (absWeight >= 18) barsLit = 4;
  else if (absWeight >= 12) barsLit = 3;
  else if (absWeight >= 6) barsLit = 2;
  else if (absWeight >= 2) barsLit = 1;

  container.querySelectorAll('.dw-bull-seg').forEach(el => {
    const lvl = parseInt(el.getAttribute('data-level'), 10);
    if (isBull && lvl <= barsLit) {
      el.style.background = '#10b981';
      el.style.borderColor = '#34d399';
      el.style.boxShadow = '0 0 8px rgba(16, 185, 129, 0.6)';
    } else {
      el.style.background = 'rgba(16, 185, 129, 0.08)';
      el.style.borderColor = 'rgba(16, 185, 129, 0.2)';
      el.style.boxShadow = 'none';
    }
  });

  container.querySelectorAll('.dw-bear-seg').forEach(el => {
    const lvl = parseInt(el.getAttribute('data-level'), 10);
    if (isBear && lvl <= barsLit) {
      el.style.background = '#f43f5e';
      el.style.borderColor = '#fb7185';
      el.style.boxShadow = '0 0 8px rgba(244, 63, 94, 0.6)';
    } else {
      el.style.background = 'rgba(244, 63, 94, 0.08)';
      el.style.borderColor = 'rgba(244, 63, 94, 0.2)';
      el.style.boxShadow = 'none';
    }
  });

  const fillEl = container.querySelector('#dw-continuous-fill');
  if (fillEl) {
    if (isBull) {
      fillEl.style.left = '50%';
      fillEl.style.width = `${absWeight}%`;
      fillEl.style.background = 'linear-gradient(90deg, #10b981, #34d399)';
    } else if (isBear) {
      fillEl.style.left = `${50 - absWeight}%`;
      fillEl.style.width = `${absWeight}%`;
      fillEl.style.background = 'linear-gradient(90deg, #fb7185, #f43f5e)';
    } else {
      fillEl.style.left = '48%';
      fillEl.style.width = '4%';
      fillEl.style.background = '#f59e0b';
    }
  }

  const convEl = container.querySelector('#dw-conviction-readout');
  if (convEl) {
    if (isBull) {
      convEl.style.color = '#10b981';
      convEl.textContent = `+${absWeight.toFixed(0)}% BULLISH (${barsLit}/5)`;
    } else if (isBear) {
      convEl.style.color = '#f43f5e';
      convEl.textContent = `-${absWeight.toFixed(0)}% BEARISH (${barsLit}/5)`;
    } else {
      convEl.style.color = '#fbbf24';
      convEl.textContent = `±${absWeight.toFixed(0)}% NEUTRAL`;
    }
  }

  const confEl = container.querySelector('#dw-confluence-readout');
  if (confEl) {
    confEl.textContent = `${score.toFixed(1)} / 100`;
    confEl.style.color = score >= 58 ? '#10b981' : (score <= 42 ? '#f43f5e' : '#38bdf8');
  }

  const actionEl = container.querySelector('#dw-action-readout');
  const strat = currentItem.strategy_confluence?.action || {};
  if (actionEl) {
    actionEl.textContent = strat.verdict || 'NEUTRAL';
    actionEl.style.color = strat.verdict === 'BUY CALL' ? '#10b981' : (strat.verdict === 'BUY PUT' ? '#f43f5e' : '#fbbf24');
  }
}
