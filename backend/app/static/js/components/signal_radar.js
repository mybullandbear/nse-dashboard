/**
 * Confluence Signal Radar & Institutional Dual-Regime Trade Recommendation Engine
 * Adheres to UI Design Agent & Backend Architectural Guidelines.
 * Features:
 * - Dynamic Regime Classification:
 *   - 🛡️ SELLER REGIME: When market is uncertain, choppy, or mild drift (Earn by Theta Decay & Safety Cushions)
 *   - 🚀 BUYER REGIME: When market is strongly trending or breakout velocity (Explode on Delta Acceleration)
 * - Interactive Mode Selectors: [🔥 AI Top Pick] [🛡️ Option Seller (Decay)] [🎯 Option Buyer (Momentum)]
 * - Real live strike execution parameters, lot sizes, ₹ profit/loss calculations, and daily theta decay.
 * - Dual-Symbol Simultaneous Grid (NIFTY & BANKNIFTY / FINNIFTY & MIDCPNIFTY).
 */
import { store } from '../state.js';
import { ApiClient } from '../api.js';
import { renderAtmSignalsTable } from './atm_signals_table.js?v=4.5.0';

// Interactive tab state per symbol: 'TOP' | 'SELLER' | 'BUYER'
if (!window._signalTabState) {
  window._signalTabState = {};
}

export function renderSignalRadar(container) {
  const state = store.getState();
  const s1 = state.symbol1 || 'NIFTY';
  const s2 = state.symbol2 || 'BANKNIFTY';
  const sig1 = state.signals1?.data || state.signals1 || {};
  const sig2 = state.signals2?.data || state.signals2 || {};
  const spot1 = state.oiData1?.spot_price || sig1.spot_price || 0;
  const spot2 = state.oiData2?.spot_price || sig2.spot_price || 0;

  // Auto-fetch if signals are missing
  if ((!sig1 || !sig1.top_recommendation) && !container._fetchingSignals) {
    container._fetchingSignals = true;
    Promise.all([
      ApiClient.fetchSignals(s1).catch(() => null),
      ApiClient.fetchSignals(s2).catch(() => null)
    ]).then(([d1, d2]) => {
      container._fetchingSignals = false;
      if (d1 || d2) {
        store.setState({
          signals1: d1 || state.signals1,
          signals2: d2 || state.signals2
        });
      }
    });
  }

  const currentFund = sig1.total_fund || sig2.total_fund || state.totalFund || 50000;

  container.innerHTML = `
    <!-- Top Continuous Live ATM +- 1 Signals Table (PineScript + Option Chain) -->
    <div id="radar-atm-signals-mount"></div>

    <!-- Capital & Fund Management Control Bar -->
    <div class="fund-control-bar" style="background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 8px; padding: 10px 16px; margin: 12px 0 16px 0; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
      <div style="display: flex; align-items: center; gap: 12px;">
        <span style="font-size: 20px;">💰</span>
        <div>
          <div style="font-size: 10.5px; color: var(--text-secondary); text-transform: uppercase; font-family: var(--font-mono); letter-spacing: 0.5px;">ACTIVE TRADING CAPITAL & POSITION BUDGET</div>
          <div style="font-size: 16px; font-weight: 800; color: #38bdf8; font-family: var(--font-mono);">
            ₹${Number(currentFund).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            <span style="font-size: 11px; font-weight: 500; color: #94a3b8; margin-left: 6px;">(Default: ₹50,000)</span>
          </div>
        </div>
      </div>
      
      <!-- System Lot Sizes Badge -->
      <div style="display: flex; align-items: center; gap: 8px; font-size: 11px; font-family: var(--font-mono);">
        <span class="logo-badge" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #cbd5e1; padding: 4px 8px; border-radius: 4px;">NIFTY: <strong>65</strong></span>
        <span class="logo-badge" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #cbd5e1; padding: 4px 8px; border-radius: 4px;">BANK: <strong>30</strong></span>
        <span class="logo-badge" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #cbd5e1; padding: 4px 8px; border-radius: 4px;">FINNIFTY: <strong>60</strong></span>
        <span class="logo-badge" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #cbd5e1; padding: 4px 8px; border-radius: 4px;">MIDCAP: <strong>120</strong></span>
      </div>

      <!-- Edit / Save Fund Action -->
      <div style="display: flex; align-items: center; gap: 8px;">
        <button id="btn-edit-fund" style="background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.4); color: #38bdf8; font-size: 11.5px; font-weight: 700; padding: 6px 14px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: all 0.2s;">
          <span>✏️</span>
          <span>Change / Save Fund</span>
        </button>
      </div>
    </div>

    <div class="dual-symbol-grid">
      <!-- COLUMN 1: SYMBOL 1 (NIFTY by default) -->
      <div class="symbol-column">
        ${renderSymbolSignalBlock(s1, sig1, spot1)}
      </div>

      <!-- COLUMN 2: SYMBOL 2 (BANKNIFTY by default) -->
      <div class="symbol-column">
        ${renderSymbolSignalBlock(s2, sig2, spot2)}
      </div>
    </div>
  `;

  // Mount Continuous Live ATM +- 1 Signals Table
  const atmMount = container.querySelector('#radar-atm-signals-mount');
  if (atmMount) {
    renderAtmSignalsTable(atmMount);
  }

  // Attach fund editor listener
  const btnEditFund = container.querySelector('#btn-edit-fund');
  if (btnEditFund) {
    btnEditFund.addEventListener('click', async () => {
      const current = currentFund;
      const input = prompt(`Enter Total Trading Capital in ₹ (e.g. 50000, 75000, 100000):`, current);
      if (input !== null && !isNaN(parseFloat(input)) && parseFloat(input) > 0) {
        const newFund = parseFloat(input);
        try {
          btnEditFund.disabled = true;
          btnEditFund.innerText = 'Saving...';
          await ApiClient.updateTradingFund(newFund);
          store.setState({ totalFund: newFund });
          const [d1, d2] = await Promise.all([
            ApiClient.fetchSignals(s1),
            ApiClient.fetchSignals(s2)
          ]);
          store.setState({ signals1: d1, signals2: d2 });
          renderSignalRadar(container);
        } catch (err) {
          alert(`Error saving fund: ${err.message}`);
          btnEditFund.disabled = false;
          btnEditFund.innerHTML = '<span>✏️</span><span>Change / Save Fund</span>';
        }
      }
    });
  }


  // Attach interactive tab listeners
  container.querySelectorAll('.strat-tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const sym = btn.getAttribute('data-sym');
      const mode = btn.getAttribute('data-mode');
      if (sym && mode) {
        window._signalTabState[sym] = mode;
        renderSignalRadar(container);
      }
    });
  });
}

function renderSymbolSignalBlock(symbol, signals, spot) {
  const conf = signals.confluence_score || 50.0;
  const dir = signals.direction || 'NEUTRAL';
  const stateLabel = signals.operational_state || 'WATCH';
  const activeRegime = signals.active_regime || 'SELLER_REGIME';
  const certaintyPct = signals.market_certainty_pct || 50.0;
  const regimeTitle = signals.regime_title || 'UNCERTAIN / RANGE-BOUND (SELLER DECAY ADVANTAGE)';
  const regimeDesc = signals.regime_description || 'Market direction is uncertain. Theta decay & safety buffers provide statistical edge.';
  const lotSize = signals.lot_size || (symbol === 'BANKNIFTY' ? 30 : (symbol === 'MIDCPNIFTY' ? 120 : (symbol === 'FINNIFTY' ? 60 : (symbol === 'SENSEX' ? 20 : 65))));

  const topRec = signals.top_recommendation || {};
  const sellerStrat = signals.seller_strategy || {};
  const buyerStrat = signals.buyer_strategy || {};

  const factors = signals.factors || {
    positioning_score: 50.0,
    price_action_score: 50.0,
    wall_proximity_score: 50.0,
    straddle_decay_score: 50.0,
  };

  const isBull = dir === 'BULLISH';
  const isBear = dir === 'BEARISH';
  const badgeClass = isBull ? 'badge-bull-lg' : isBear ? 'badge-bear-lg' : 'badge-neut-lg';

  // Active View Tab for this symbol
  const activeTab = window._signalTabState[symbol] || 'TOP';

  // Determine which strategy payload to display in the main card
  let activeStrategy = null;
  let activeCardType = 'SELLER';
  let activeCardTitle = '';

  if (activeTab === 'SELLER') {
    activeStrategy = sellerStrat;
    activeCardType = 'SELLER';
    activeCardTitle = '🛡️ OPTION SELLER STRATEGY (DECAY & BUFFER ADVANTAGE)';
  } else if (activeTab === 'BUYER') {
    activeStrategy = buyerStrat;
    activeCardType = 'BUYER';
    activeCardTitle = '🚀 OPTION BUYER STRATEGY (MOMENTUM VELOCITY)';
  } else {
    // TOP PICK (Option Buyer / Scalper Priority)
    if (topRec && topRec.role === 'STANDBY') {
      activeStrategy = topRec.strategy;
      activeCardType = 'STANDBY';
      activeCardTitle = topRec.tag || '🛡️ AI TOP PICK: STANDBY (AVOID CHOP)';
    } else if (topRec && topRec.role === 'SELLER' && activeRegime === 'SELLER_REGIME') {
      activeStrategy = sellerStrat;
      activeCardType = 'SELLER';
      activeCardTitle = topRec.tag || '🛡️ AI TOP PICK: ATM CREDIT SPREAD';
    } else {
      activeStrategy = buyerStrat;
      activeCardType = 'BUYER';
      activeCardTitle = topRec?.tag || '🚀 AI TOP PICK: ATM MOMENTUM SCALP';
    }
  }

  const isSellerRegime = activeRegime === 'SELLER_REGIME';

  return `
    <!-- Column Header -->
    <div class="symbol-col-header">
      <div class="symbol-col-title">
        <span>⚡</span>
        <span>${symbol} SIGNAL & TRADE RADAR</span>
        <span class="logo-badge" style="color: #10b981;">● LIVE</span>
      </div>
      <div class="symbol-col-spot">
        SPOT: ${spot ? spot.toLocaleString('en-IN', { minimumFractionDigits: 1 }) : '--'}
      </div>
    </div>

    <!-- Dual-Regime Market Status Banner -->
    <div class="regime-banner ${isSellerRegime ? 'regime-seller-banner' : 'regime-buyer-banner'}">
      <div class="regime-banner-header">
        <div class="regime-banner-title">
          <span>${isSellerRegime ? '🛡️' : '🚀'}</span>
          <span>${regimeTitle}</span>
        </div>
        <div class="regime-certainty-badge">
          CERTAINTY: <strong>${certaintyPct.toFixed(0)}%</strong>
        </div>
      </div>
      <div class="regime-banner-desc">${regimeDesc}</div>
    </div>

    <!-- Confluence Radar Radial & Factors -->
    <div class="glass-panel confluence-box">
      <div class="panel-title" style="margin-bottom: 0;">
        <span>🎯</span>
        <span>CONFLUENCE SCORE & RADAR</span>
      </div>

      <!-- Radial Dial -->
      <div class="confluence-radial">
        <svg width="140" height="140" viewBox="0 0 140 140">
          <circle cx="70" cy="70" r="54" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="12" />
          <circle 
            cx="70" cy="70" r="54" 
            fill="none" 
            stroke="${isBull ? '#10b981' : isBear ? '#ef4444' : '#f59e0b'}" 
            stroke-width="12"
            stroke-dasharray="339"
            stroke-dashoffset="${339 - (339 * conf) / 100}"
            stroke-linecap="round"
            transform="rotate(-90 70 70)"
            style="transition: stroke-dashoffset 0.8s ease;"
          />
        </svg>
        <div style="position: absolute; display: flex; flex-direction: column; align-items: center;">
          <span class="radial-score" style="color: ${isBull ? '#10b981' : isBear ? '#ef4444' : '#f59e0b'}; font-size: 30px;">
            ${conf.toFixed(0)}
          </span>
          <span class="radial-label">OUT OF 100</span>
        </div>
      </div>

      <!-- Decision Badge -->
      <div class="direction-badge ${badgeClass}">
        ${dir} ${dir === 'BULLISH' ? '▲' : dir === 'BEARISH' ? '▼' : '◆'}
      </div>

      <div style="font-family: var(--font-mono); font-size: 11.5px; color: var(--text-secondary);">
        STATE: <strong style="color: var(--text-primary);">${stateLabel}</strong>
      </div>

      <!-- 4 Factor Breakdown -->
      <div class="factor-list">
        <div class="factor-item">
          <div class="factor-header">
            <span>POSITIONING (35%)</span>
            <span>${factors.positioning_score}%</span>
          </div>
          <div class="factor-bar-bg">
            <div class="factor-bar-fill" style="width: ${factors.positioning_score}%;"></div>
          </div>
        </div>

        <div class="factor-item">
          <div class="factor-header">
            <span>PRICE ACTION (30%)</span>
            <span>${factors.price_action_score}%</span>
          </div>
          <div class="factor-bar-bg">
            <div class="factor-bar-fill" style="width: ${factors.price_action_score}%;"></div>
          </div>
        </div>

        <div class="factor-item">
          <div class="factor-header">
            <span>WALL PROXIMITY (15%)</span>
            <span>${factors.wall_proximity_score}%</span>
          </div>
          <div class="factor-bar-bg">
            <div class="factor-bar-fill" style="width: ${factors.wall_proximity_score}%;"></div>
          </div>
        </div>

        <div class="factor-item">
          <div class="factor-header">
            <span>STRADDLE DECAY (20%)</span>
            <span>${factors.straddle_decay_score}%</span>
          </div>
          <div class="factor-bar-bg">
            <div class="factor-bar-fill" style="width: ${factors.straddle_decay_score}%;"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Trade Strategy Section: Multi-Mode Selector -->
    <div class="glass-panel" style="display: flex; flex-direction: column; gap: 12px;">
      <!-- Tab Selector Toolbar -->
      <div class="strategy-mode-tabs">
        <button class="strat-tab-btn ${activeTab === 'TOP' ? 'active' : ''}" data-sym="${symbol}" data-mode="TOP">
          🔥 AI Top Pick
        </button>
        <button class="strat-tab-btn ${activeTab === 'SELLER' ? 'active' : ''}" data-sym="${symbol}" data-mode="SELLER">
          🛡️ Option Seller (Decay)
        </button>
        <button class="strat-tab-btn ${activeTab === 'BUYER' ? 'active' : ''}" data-sym="${symbol}" data-mode="BUYER">
          🎯 Option Buyer (Momentum)
        </button>
      </div>

      <!-- Strategy Header -->
      <div class="panel-header" style="margin-bottom: 0;">
        <div class="panel-title" style="font-size: 11.5px;">
          <span>${activeCardType === 'SELLER' ? '🛡️' : activeCardType === 'STANDBY' ? '⏸️' : '🚀'}</span>
          <span>${activeCardTitle}</span>
        </div>
        <span class="logo-badge" style="color: ${activeCardType === 'SELLER' ? '#10b981' : activeCardType === 'STANDBY' ? '#f59e0b' : '#38bdf8'}; font-weight: 700;">
          LOT: ${lotSize} QTY
        </span>
      </div>

      <!-- Render Strategy Details -->
      ${activeCardType === 'STANDBY' ? renderStandbyCard(activeStrategy, lotSize) : (activeCardType === 'SELLER' ? renderSellerCard(activeStrategy, lotSize) : renderBuyerCard(activeStrategy, lotSize))}

      <!-- Analytical Context -->
      <div class="strategy-context-box">
        <div class="context-row">
          <span class="context-lbl">MARKET REGIME:</span>
          <span class="context-val">${activeRegime.replace('_', ' ')}</span>
        </div>
        <div class="context-row">
          <span class="context-lbl">CONFIDENCE / CERTAINTY:</span>
          <span class="context-val" style="color: ${certaintyPct >= 65 ? '#10b981' : '#f59e0b'};">
            ${certaintyPct.toFixed(0)}% (${certaintyPct >= 65 ? 'High Conviction' : 'Range / Chop Mode'})
          </span>
        </div>
        <div class="context-row">
          <span class="context-lbl">EXECUTION TIP:</span>
          <span class="context-val" style="color: var(--text-secondary);">
            ${activeCardType === 'SELLER' ? 'Earns steady decay if market stays flat or drifts slightly.' : 'Needs momentum breakout to outpace daily theta.'}
          </span>
        </div>
      </div>
    </div>
  `;
}

function renderSellerCard(strat, lotSize) {
  if (!strat || !strat.name) {
    return `<div class="strategy-card">Awaiting option chain feed to compute exact seller strikes...</div>`;
  }

  const netCreditPts = strat.net_credit_pts || 0;
  const netCreditInr = strat.net_credit_inr || (netCreditPts * lotSize);
  const maxRiskInr = strat.max_risk_inr || 0;
  const dailyTheta = strat.daily_theta_decay_inr || 0;
  const pop = strat.probability_of_profit_pct || 75;

  return `
    <div class="strategy-card seller-card">
      <div class="strategy-title">
        <span>🛡️</span>
        <span>${strat.name}</span>
        <span class="pop-pill">POP: ${pop}%</span>
      </div>

      <!-- Action Legs -->
      <div class="strategy-legs" style="font-size: 13px; font-weight: 700; color: #10b981; line-height: 1.4;">
        ${strat.action}
      </div>

      <!-- 4-Grid Seller Financial Metrics -->
      <div class="strategy-grid">
        <div class="strategy-param">
          <div class="strategy-param-lbl">NET CREDIT (MAX PROFIT)</div>
          <div class="strategy-param-val text-bull" style="font-size: 13.5px;">
            ₹${netCreditPts.toFixed(2)} pts <span style="font-size: 11px; font-weight: 500;">(+₹${netCreditInr.toLocaleString('en-IN')})</span>
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">SAFETY CUSHION</div>
          <div class="strategy-param-val" style="font-size: 12px; color: #38bdf8;">
            ${strat.safety_cushion || 'At Support Wall'}
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">DAILY THETA DECAY</div>
          <div class="strategy-param-val text-bull" style="font-size: 12.5px;">
            +₹${dailyTheta.toLocaleString('en-IN')} / day
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">MAX RISK (DEFINED)</div>
          <div class="strategy-param-val text-bear" style="font-size: 12px;">
            ₹${maxRiskInr.toLocaleString('en-IN')} / lot
          </div>
        </div>
      </div>

      <!-- Execution Rules -->
      <div class="trade-rules-box">
        <div class="trade-rule-item">
          <span class="rule-icon">🎯</span>
          <span><strong>Target Exit:</strong> ${strat.target_rule || 'Exit at 70% decay'}</span>
        </div>
        <div class="trade-rule-item">
          <span class="rule-icon">🛑</span>
          <span><strong>Stop Loss:</strong> ${strat.stop_loss_rule || '1x Net Credit or Wall Breach'}</span>
        </div>
        <div class="trade-rule-item">
          <span class="rule-icon">💡</span>
          <span style="color: var(--text-secondary);">${strat.seller_rationale || 'High statistical edge.'}</span>
        </div>
      </div>
    </div>
  `;
}

function renderBuyerCard(strat, lotSize) {
  if (!strat || !strat.name) {
    return `<div class="strategy-card">Awaiting option chain feed to compute exact buyer strikes...</div>`;
  }

  const ltp = strat.ltp || 0;
  const rr = strat.risk_reward_ratio || '1 : 2.5';
  const delta = strat.delta !== undefined ? Math.abs(strat.delta) : 0.50;
  const commBuffer = strat.commission_buffer_inr || 75;
  const target1Net = strat.target1_net_profit_inr || Math.round((strat.target1_gross_profit_inr || (ltp * 0.1 * lotSize)) - commBuffer);
  const aiAudit = strat.ai_audit;

  return `
    <div class="strategy-card buyer-card">
      <div class="strategy-title">
        <span>🚀</span>
        <span>${strat.name}</span>
        <span class="rr-pill">R : R = ${rr}</span>
      </div>

      <!-- Action -->
      <div class="strategy-legs" style="font-size: 13px; font-weight: 700; color: #38bdf8; line-height: 1.4;">
        ${strat.action}
      </div>

      <!-- Commission Protection Guarantee Badge -->
      <div style="background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 6px; padding: 6px 10px; margin-top: 6px; display: flex; align-items: center; justify-content: space-between; font-size: 11px;">
        <span style="color: #10b981; font-weight: 700;">🛡️ COMMISSION PROTECTION GUARANTEE</span>
        <span style="color: #ffffff;">Brokerage & Taxes Buffer: <strong>₹${commBuffer}</strong> | Target 1 Net: <strong style="color: #10b981;">+₹${target1Net.toLocaleString('en-IN')}</strong> in pocket</span>
      </div>

      <!-- 4-Grid Buyer Financial Metrics -->
      <div class="strategy-grid">
        <div class="strategy-param">
          <div class="strategy-param-lbl">ENTRY ZONE (LTP)</div>
          <div class="strategy-param-val" style="font-size: 13px; color: #ffffff;">
            ${strat.entry_zone || `₹${ltp.toFixed(2)}`}
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">DELTA RESPONSIVENESS</div>
          <div class="strategy-param-val" style="font-size: 13px; color: #38bdf8;">
            ${delta.toFixed(2)} <span style="font-size: 10px; color: var(--text-secondary);">(Strict ATM)</span>
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">TARGET 1 (SCALP PROFIT)</div>
          <div class="strategy-param-val text-bull" style="font-size: 12px;">
            ${strat.target1 || '₹' + (ltp * 1.5).toFixed(1)}
          </div>
        </div>

        <div class="strategy-param">
          <div class="strategy-param-lbl">STRICT STOP LOSS</div>
          <div class="strategy-param-val text-bear" style="font-size: 12px;">
            ${strat.stop_loss || '₹' + (ltp * 0.70).toFixed(1)}
          </div>
        </div>
      </div>

      <!-- Execution Rules & Catalyst -->
      <div class="trade-rules-box">
        <div class="trade-rule-item">
          <span class="rule-icon">🏁</span>
          <span><strong>Target 2 (Runner):</strong> ${strat.target2 || '₹' + (ltp * 2.2).toFixed(1)}</span>
        </div>
        <div class="trade-rule-item">
          <span class="rule-icon">⚡</span>
          <span><strong>Momentum Catalyst:</strong> ${strat.catalyst || 'Opposite writer unwinding'}</span>
        </div>
        <div class="trade-rule-item">
          <span class="rule-icon">💡</span>
          <span style="color: var(--text-secondary);">${strat.buyer_rationale || 'Delta expansion outpaces Theta.'}</span>
        </div>
      </div>

      <!-- Capital Allocation & Sizing Box -->
      ${renderCapitalAllocationBox(strat, lotSize)}

      ${aiAudit ? `
      <!-- Real-Time AI Model Audit -->
      <div style="background: rgba(14, 165, 233, 0.08); border: 1px solid rgba(14, 165, 233, 0.25); border-radius: 6px; padding: 7px 10px; margin-top: 8px; font-size: 11px; line-height: 1.4;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
          <span style="color: #38bdf8; font-weight: 700;">🤖 AI VALIDATION (${aiAudit.model_used || 'Groq LPU'}):</span>
          <span class="logo-badge" style="color: #10b981; font-size: 9px;">CONVICTION: ${aiAudit.conviction || 'HIGH'}</span>
        </div>
        <div style="color: #e2e8f0;"><strong>Decision:</strong> ${aiAudit.recommendation}</div>
        <div style="color: var(--text-secondary); font-size: 10.5px; margin-top: 2px;">${aiAudit.reasoning || ''}</div>
      </div>
      ` : ''}
    </div>
  `;
}

function renderCapitalAllocationBox(strat, lotSize) {
  const cap = strat.capital_allocation || {};
  const totalFund = cap.total_fund || store.getState().totalFund || 50000;
  const ltp = strat.ltp || 0;
  const marginPerLot = cap.margin_per_lot || Math.round(ltp * lotSize);
  const recLots = cap.recommended_lots || Math.max(1, Math.min(Math.floor(totalFund / Math.max(1, marginPerLot)), Math.floor((totalFund * 0.5) / Math.max(1, marginPerLot)) || 1));
  const recQty = cap.recommended_qty || (recLots * lotSize);
  const capDeployed = cap.capital_deployed || Math.round(marginPerLot * recLots);
  const capUtil = cap.capital_utilization_pct || (totalFund > 0 ? ((capDeployed / totalFund) * 100).toFixed(1) : '0.0');
  const remFund = cap.remaining_fund || Math.round(totalFund - capDeployed);
  const totalRisk = cap.total_risk_inr || Math.round((strat.max_risk_inr || 500) * recLots);
  const riskPct = cap.risk_pct_of_fund || (totalFund > 0 ? ((totalRisk / totalFund) * 100).toFixed(1) : '0.0');
  const portNet = cap.target1_net_portfolio || Math.round((strat.target1_net_profit_inr || 200) * recLots);

  return `
    <div style="background: rgba(30, 41, 59, 0.55); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 6px; padding: 9px 12px; margin-top: 8px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 7px;">
        <span style="font-size: 11px; font-weight: 700; color: #38bdf8; font-family: var(--font-mono); letter-spacing: 0.3px;">
          📊 CAPITAL ALLOCATION & POSITION SIZING (₹${Number(totalFund).toLocaleString('en-IN')})
        </span>
        <span class="logo-badge" style="background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #10b981; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px;">
          SIZING: ${recLots} LOT${recLots > 1 ? 'S' : ''} (${recQty} QTY)
        </span>
      </div>
      <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; font-size: 11px; font-family: var(--font-mono);">
        <div style="background: rgba(15, 23, 42, 0.5); padding: 5px 8px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05);">
          <div style="color: var(--text-secondary); font-size: 9.5px;">1 LOT MARGIN</div>
          <div style="color: #ffffff; font-weight: 700; margin-top: 1px;">₹${marginPerLot.toLocaleString('en-IN')}</div>
        </div>
        <div style="background: rgba(15, 23, 42, 0.5); padding: 5px 8px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05);">
          <div style="color: var(--text-secondary); font-size: 9.5px;">CAPITAL DEPLOYED</div>
          <div style="color: #38bdf8; font-weight: 700; margin-top: 1px;">₹${capDeployed.toLocaleString('en-IN')} <span style="font-size: 9px; color: var(--text-secondary);">(${capUtil}%)</span></div>
        </div>
        <div style="background: rgba(15, 23, 42, 0.5); padding: 5px 8px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05);">
          <div style="color: var(--text-secondary); font-size: 9.5px;">RISK ON CAPITAL (SL)</div>
          <div style="color: #ef4444; font-weight: 700; margin-top: 1px;">-₹${totalRisk.toLocaleString('en-IN')} <span style="font-size: 9px; color: var(--text-secondary);">(${riskPct}%)</span></div>
        </div>
        <div style="background: rgba(15, 23, 42, 0.5); padding: 5px 8px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05);">
          <div style="color: var(--text-secondary); font-size: 9.5px;">PROJECTED NET TGT 1</div>
          <div style="color: #10b981; font-weight: 700; margin-top: 1px;">+₹${portNet.toLocaleString('en-IN')}</div>
        </div>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px; font-size: 10px; color: var(--text-secondary); font-family: var(--font-mono);">
        <span>Available Buffer: <strong style="color: #94a3b8;">₹${remFund.toLocaleString('en-IN')}</strong></span>
        <span>Max Affordable: <strong style="color: #cbd5e1;">${cap.max_affordable_lots || recLots} Lots</strong></span>
      </div>
    </div>
  `;
}

function renderStandbyCard(strat, lotSize) {
  return `
    <div class="strategy-card" style="border: 1px solid rgba(245, 158, 11, 0.35); background: rgba(245, 158, 11, 0.06);">
      <div class="strategy-title" style="color: #f59e0b;">
        <span>⏸️</span>
        <span>${strat?.name || 'CHOP GATE ACTIVE — CAPITAL PRESERVATION'}</span>
        <span class="pop-pill" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid #f59e0b;">STANDBY</span>
      </div>

      <div class="strategy-legs" style="font-size: 13px; font-weight: 700; color: #f59e0b; line-height: 1.4; margin: 8px 0;">
        ${strat?.action || 'NO BUY TRADE — Market in choppy consolidation zone.'}
      </div>

      <div class="trade-rules-box" style="margin-top: 8px;">
        <div class="trade-rule-item">
          <span class="rule-icon">🛡️</span>
          <span><strong>Capital Rule:</strong> ${strat?.target_rule || 'Preserve capital. Avoid buying in low-velocity consolidation.'}</span>
        </div>
        <div class="trade-rule-item">
          <span class="rule-icon">🛑</span>
          <span><strong>Risk Rule:</strong> ${strat?.stop_loss_rule || 'Zero risk — Cash is a valid position.'}</span>
        </div>
      </div>
    </div>
  `;
}
