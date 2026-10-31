/**
 * Full Option Chain Table Component
 * Features:
 * - Desktop Layout (>768px): Sensibull / Institutional 12-Column Matrix
 * - Mobile Layout (<=768px): Dedicated Center-Locked Strike Architecture
 *   - Strike is locked in the center with ATM halo and Max Pain badge
 *   - Side Focus Filters: [⚡ BOTH DUAL] [🔴 PUTS FOCUS] [🟢 CALLS FOCUS]
 *     - When PUTS FOCUS is active: Shows Strike | Put Signals | Put OI | Put LTP | Put Vol
 *       with 100% full-screen visibility of Put signals, ZERO reorientation to Call data!
 *   - Metric Quick-Pills: SIGNALS, OI, PRICE, OI CHG, VOLUME, DUAL
 *   - STRICT SCROLL POSITION MEMORY: Never resets scroll positions during live polling ticks!
 *   - Quick-Jump buttons in full table mode: [‹ Calls] [• Strike •] [Puts & Signals ›]
 */
import { store } from '../state.js';

let activeMobileMetric = 'SIGNALS'; // Default to SIGNALS so Put/Call signals are immediately visible!
let activeMobileViewMode = 'CENTERED'; // 'CENTERED' | 'TABLE'
let activeMobileSide = 'BOTH'; // 'BOTH' | 'PUTS' | 'CALLS'
let hasInitialChainAligned = false;
let lastRenderedSymbol = null;
let persistentTableScrollLeft = null;
let persistentTableScrollTop = null;
let isUserTouchingChain = false;

const METRICS = [
  { id: 'SIGNALS', label: '🎯 SIGNALS', short: 'Buildup Signals' },
  { id: 'OI', label: '📊 OI', short: 'Open Interest' },
  { id: 'PRICE', label: '⚡ PRICE', short: 'LTP & %' },
  { id: 'OICHG', label: '📈 OI CHG', short: 'OI Change' },
  { id: 'VOL', label: '🌊 VOLUME', short: 'Traded Vol' },
  { id: 'DUAL', label: '⚖️ DUAL', short: 'Price + OI' }
];

function fmtNumber(n) {
  if (n === null || n === undefined || isNaN(n) || n === 0) return '-';
  const abs = Math.abs(n);
  if (abs >= 10000000) return (n / 10000000).toFixed(2) + ' Cr';
  if (abs >= 100000) return (n / 100000).toFixed(2) + ' L';
  if (abs >= 1000) return (n / 1000).toFixed(2) + ' K';
  return n.toFixed(0);
}

function getBuildup(pChg, oiChg) {
  if (pChg >= 0 && oiChg >= 0) return { label: '↗ L', name: 'Long Buildup', cls: 'buildup-long' };
  if (pChg >= 0 && oiChg < 0) return { label: '↑ SC', name: 'Short Covering', cls: 'buildup-sc' };
  if (pChg < 0 && oiChg >= 0) return { label: '↘ S', name: 'Short Buildup', cls: 'buildup-short' };
  return { label: '↓ LU', name: 'Long Unwinding', cls: 'buildup-lu' };
}

function getOIChgPct(oi, oiChg) {
  if (!oi && !oiChg) return 0;
  const base = Math.max(0, oi - oiChg);
  if (base > 0) return Math.round((oiChg / base) * 100);
  if (oi > 0) return 100;
  return 0;
}

function getPineScriptSignal(contract, strike, spot, atm, step, otype) {
  if (!contract) return null;

  // 1. If backend has already enriched signal
  if (contract.signal_label) {
    return {
      action: contract.signal || 'HOLD',
      label: contract.signal_label,
      cls: contract.signal_cls || 'sig-hold',
      tooltip: contract.reason || `PineScript OTT: ${contract.ott || '--'}, Buildup: ${contract.buildup || '--'}`
    };
  }

  // 2. Client-side evaluation for ATM +- 2 strikes
  const isAtm2 = Math.abs(strike - atm) <= (2 * step) + 0.1;
  if (!isAtm2) return null;

  const ltp = contract.lastPrice || 0;
  const pChg = contract.pChange || 0;
  const oiChg = contract.changeinOpenInterest || 0;
  const build = getBuildup(pChg, oiChg);
  const ott = contract.ott || 0;
  const isAboveOtt = ott > 0 ? (ltp > ott) : (pChg > 0);

  if (otype === 'CE') {
    if (isAboveOtt && (build.name === 'Long Buildup' || build.name === 'Short Covering')) {
      return {
        action: 'BUY',
        label: '🚀 BUY CE',
        shortLabel: 'BUY CE',
        cls: 'sig-buy-ce',
        tooltip: `CE Breakout above OTT (${ltp.toFixed(1)} > ${ott ? ott.toFixed(1) : 'LTP'}) + ${build.name}`
      };
    } else if (!isAboveOtt && build.name === 'Short Buildup' && strike >= (atm - 0.1)) {
      return {
        action: 'SELL',
        label: '🛡️ SELL CE',
        shortLabel: 'SELL CE',
        cls: 'sig-sell-ce',
        tooltip: `CE Under OTT (${ltp.toFixed(1)} <= ${ott ? ott.toFixed(1) : 'LTP'}) + Call Writer Resistance`
      };
    } else if (!isAboveOtt && build.name === 'Long Unwinding') {
      return {
        action: 'EXIT',
        label: '⚠️ EXIT CE',
        shortLabel: 'EXIT CE',
        cls: 'sig-neutral',
        tooltip: `CE Under OTT + Long Unwinding`
      };
    } else {
      return {
        action: 'HOLD',
        label: 'HOLD',
        shortLabel: 'HOLD',
        cls: 'sig-neutral',
        tooltip: `CE Neutral (${build.name})`
      };
    }
  } else {
    // PE
    if (isAboveOtt && (build.name === 'Long Buildup' || build.name === 'Short Covering')) {
      return {
        action: 'BUY',
        label: '🚀 BUY PE',
        shortLabel: 'BUY PE',
        cls: 'sig-buy-pe',
        tooltip: `PE Breakout above OTT (${ltp.toFixed(1)} > ${ott ? ott.toFixed(1) : 'LTP'}) + ${build.name}`
      };
    } else if (!isAboveOtt && build.name === 'Short Buildup' && strike <= (atm + 0.1)) {
      return {
        action: 'SELL',
        label: '🛡️ SELL PE',
        shortLabel: 'SELL PE',
        cls: 'sig-sell-pe',
        tooltip: `PE Under OTT (${ltp.toFixed(1)} <= ${ott ? ott.toFixed(1) : 'LTP'}) + Put Writer Support Defense`
      };
    } else if (!isAboveOtt && build.name === 'Long Unwinding') {
      return {
        action: 'EXIT',
        label: '⚠️ EXIT PE',
        shortLabel: 'EXIT PE',
        cls: 'sig-neutral',
        tooltip: `PE Under OTT + Long Unwinding`
      };
    } else {
      return {
        action: 'HOLD',
        label: 'HOLD',
        shortLabel: 'HOLD',
        cls: 'sig-neutral',
        tooltip: `PE Neutral (${build.name})`
      };
    }
  }
}

function getCombinedStrikeSignal(ceSig, peSig, strike, atm, step) {
  const isAtm2 = Math.abs(strike - atm) <= (2 * step) + 0.1;
  if (!isAtm2) {
    return { isAtm2: false, label: '-', cls: 'chain-signal-none', tooltip: 'Beyond ATM ± 2 strikes' };
  }

  const ceAct = ceSig ? ceSig.action : 'HOLD';
  const peAct = peSig ? peSig.action : 'HOLD';

  if (ceAct === 'BUY' && peAct === 'SELL') {
    return {
      isAtm2: true,
      label: '🚀 BUY CE / 🛡️ SELL PE',
      isDual: true,
      ceLabel: '🚀 BUY CE',
      peLabel: '🛡️ SELL PE',
      cls: 'sig-buy-ce',
      shortLabel: 'BUY CE / SELL PE',
      tooltip: 'Bullish PineScript: Call Momentum Breakout + Put Writing Support'
    };
  }
  if (peAct === 'BUY' && ceAct === 'SELL') {
    return {
      isAtm2: true,
      label: '🚀 BUY PE / 🛡️ SELL CE',
      isDual: true,
      ceLabel: '🛡️ SELL CE',
      peLabel: '🚀 BUY PE',
      cls: 'sig-buy-pe',
      shortLabel: 'BUY PE / SELL CE',
      tooltip: 'Bearish PineScript: Put Momentum Breakout + Call Writing Resistance'
    };
  }
  if (ceAct === 'BUY') {
    return {
      isAtm2: true,
      label: ceSig.label || '🚀 BUY CE',
      cls: 'sig-buy-ce',
      shortLabel: 'BUY CE',
      tooltip: ceSig.tooltip || 'Call Option Momentum Breakout above OTT'
    };
  }
  if (peAct === 'BUY') {
    return {
      isAtm2: true,
      label: peSig.label || '🚀 BUY PE',
      cls: 'sig-buy-pe',
      shortLabel: 'BUY PE',
      tooltip: peSig.tooltip || 'Put Option Momentum Breakout above OTT'
    };
  }
  if (ceAct === 'SELL') {
    return {
      isAtm2: true,
      label: ceSig.label || '🛡️ SELL CE',
      cls: 'sig-sell-ce',
      shortLabel: 'SELL CE',
      tooltip: ceSig.tooltip || 'Call Option Theta Decay under OTT'
    };
  }
  if (peAct === 'SELL') {
    return {
      isAtm2: true,
      label: peSig.label || '🛡️ SELL PE',
      cls: 'sig-sell-pe',
      shortLabel: 'SELL PE',
      tooltip: peSig.tooltip || 'Put Option Theta Decay under OTT'
    };
  }

  return {
    isAtm2: true,
    label: '⚖️ HOLD',
    cls: 'sig-neutral',
    shortLabel: 'HOLD',
    tooltip: 'Neutral Consolidation / Near OTT without clear edge'
  };
}

function renderStrikeSignalCell(sig) {
  if (!sig || !sig.isAtm2 || sig.label === '-') {
    return `<span class="chain-signal-none" title="Beyond ATM ± 2 strikes">-</span>`;
  }
  if (sig.isDual) {
    return `
      <div class="chain-signal-dual" title="${sig.tooltip}">
        <span class="chain-signal-badge sig-buy-ce">${sig.ceLabel}</span>
        <span class="chain-signal-badge sig-sell-pe">${sig.peLabel}</span>
      </div>
    `;
  }
  return `
    <span class="chain-signal-badge ${sig.cls}" title="${sig.tooltip}">
      ${sig.label}
    </span>
  `;
}

function renderContractHullBadge(contract, optType) {
  if (!contract) return `<span class="hull-sig-pill hull-pill-neutral">-</span>`;

  const state = contract.hull_state;
  const hullVal = contract.hull;
  const ltp = contract.lastPrice || 0;
  const pChange = contract.pChange;

  let isRising = false;
  let isFalling = false;

  if (state === 'BULLISH') {
    isRising = true;
  } else if (state === 'BEARISH') {
    isFalling = true;
  } else if (hullVal && hullVal > 0 && ltp > 0) {
    if (ltp >= hullVal) isRising = true;
    else isFalling = true;
  } else if (pChange !== undefined && pChange !== null && pChange !== 0) {
    if (pChange > 0) isRising = true;
    else if (pChange < 0) isFalling = true;
  }

  const hSt = contract.hull_state ? (contract.hull_state === 'BULLISH' ? '▲ Bull' : (contract.hull_state === 'BEARISH' ? '▼ Bear' : '-')) : '-';
  const atSt = contract.alphatrend_state ? (contract.alphatrend_state === 'BULLISH' ? '▲ Bull' : (contract.alphatrend_state === 'BEARISH' ? '▼ Bear' : '-')) : '-';
  const ottSt = contract.ott_state ? (contract.ott_state === 'BULLISH' ? '▲ Bull' : (contract.ott_state === 'BEARISH' ? '▼ Bear' : '-')) : '-';
  const tdSt = contract.trend_direction_state ? (contract.trend_direction_state === 'BULLISH' ? '▲ Bull' : (contract.trend_direction_state === 'BEARISH' ? '▼ Bear' : '-')) : '-';
  const brkSt = contract.breakout_state ? (contract.breakout_state === 'LONG' ? '▲ Long' : (contract.breakout_state === 'SHORT' ? '▼ Short' : '-')) : '-';
  const tip = `${optType} ₹${ltp.toFixed(2)} (${isRising ? 'Chart Rising' : (isFalling ? 'Chart Falling' : 'Consolidation')}) | Breakout: ${brkSt} | Hull: ${hSt} | AlphaTrend: ${atSt} | OTT: ${ottSt} | Momentum: ${tdSt}`;

  if (isRising) {
    return `<span class="hull-sig-pill hull-pill-bull" title="${tip}">🟢 ▲ UP</span>`;
  } else if (isFalling) {
    return `<span class="hull-sig-pill hull-pill-bear" title="${tip}">🔴 ▼ DN</span>`;
  } else {
    return `<span class="hull-sig-pill hull-pill-neutral" title="${tip}">-</span>`;
  }
}

export function renderChainTable(container, onSelectChainSymbol) {
  // If user is actively touching or scrolling on mobile, pause DOM update to prevent gesture cancellation
  if (isUserTouchingChain) return;

  const state = store.getState();
  const s1 = state.symbol1;
  const s2 = state.symbol2;
  const activeChainSym = state.activeChainSymbol || s1;
  const chainRange = state.chainRange || 10; // Default ATM ± 10 strikes

  // Capture existing scroll positions before updating DOM
  const prevTbl = container.querySelector('#chain-table-container');
  const prevRows = container.querySelector('#mobile-chain-rows');
  const prevScrollLeft = prevTbl ? prevTbl.scrollLeft : null;
  const prevScrollTop = prevTbl ? prevTbl.scrollTop : null;
  const prevRowsScrollTop = prevRows ? prevRows.scrollTop : null;

  if (prevScrollLeft !== null && prevScrollLeft > 0) {
    persistentTableScrollLeft = prevScrollLeft;
  }
  if (prevScrollTop !== null && prevScrollTop > 0) {
    persistentTableScrollTop = prevScrollTop;
  }

  // If active symbol changed, allow one fresh alignment
  if (lastRenderedSymbol !== activeChainSym) {
    lastRenderedSymbol = activeChainSym;
    hasInitialChainAligned = false;
    persistentTableScrollLeft = null;
  }

  // Determine which chain dataset to show
  const isS1 = activeChainSym === s1;
  const chain = isS1 ? (state.optionChain1 || {}) : (state.optionChain2 || {});
  const strikes = chain.strikes || [];
  const spot = chain.spot_price || (isS1 ? state.oiData1?.spot_price : state.oiData2?.spot_price) || 0;
  const atm = chain.atm_strike || 0;
  const maxPain = chain.max_pain || atm;

  // Step size for index
  const step = (activeChainSym === 'BANKNIFTY' || activeChainSym === 'SENSEX') ? 100 : (activeChainSym === 'MIDCPNIFTY' ? 25 : 50);

  // Slice strikes strictly to ATM ± 10 by default
  const atmIdx = strikes.findIndex(r => r.strikePrice === atm);
  let visibleStrikes = strikes;
  if (chainRange !== 'ALL' && atmIdx !== -1) {
    const rNum = parseInt(chainRange, 10) || 10;
    const start = Math.max(0, atmIdx - rNum);
    const end = Math.min(strikes.length, atmIdx + rNum + 1);
    visibleStrikes = strikes.slice(start, end);
  }

  // Compute maxima across visible strikes for heatmap highlighting
  const maxCeVol = Math.max(1, ...visibleStrikes.map(r => r.CE?.totalTradedVolume || 0));
  const maxPeVol = Math.max(1, ...visibleStrikes.map(r => r.PE?.totalTradedVolume || 0));
  const maxCeOI = Math.max(1, ...visibleStrikes.map(r => r.CE?.openInterest || 0));
  const maxPeOI = Math.max(1, ...visibleStrikes.map(r => r.PE?.openInterest || 0));

  // Calculate ATM +- 2 PineScript Signals summary
  let atmBuyingCount = 0;
  let atmSellingCount = 0;
  strikes.forEach(r => {
    const stk = r.strikePrice;
    if (Math.abs(stk - atm) <= (2 * step) + 0.1) {
      const cSig = getPineScriptSignal(r.CE, stk, spot, atm, step, 'CE');
      const pSig = getPineScriptSignal(r.PE, stk, spot, atm, step, 'PE');
      if (cSig?.action === 'BUY') atmBuyingCount++;
      if (pSig?.action === 'BUY') atmBuyingCount++;
      if (cSig?.action === 'SELL') atmSellingCount++;
      if (pSig?.action === 'SELL') atmSellingCount++;
    }
  });

  container.innerHTML = `
    <div class="glass-panel">
      <!-- TOP TOOLBAR & CONTROLS -->
      <div class="panel-header" style="flex-wrap: wrap; gap: 10px;">
        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
          <div class="panel-title">
            <span>⛓️</span>
            <span>OPTION CHAIN MATRIX</span>
          </div>

          <!-- Dual Symbol Switcher -->
          <div class="symbol-selector">
            <button class="pair-btn ${activeChainSym === s1 ? 'active' : ''}" data-chain-toggle="${s1}">
              <span>⚡</span>
              <span>${s1}</span>
            </button>
            <button class="pair-btn ${activeChainSym === s2 ? 'active' : ''}" data-chain-toggle="${s2}">
              <span>⚡</span>
              <span>${s2}</span>
            </button>
          </div>

          <!-- Range Filter Toggle -->
          <div class="chart-controls" style="display: flex; gap: 3px;">
            <button class="chart-mode-btn ${chainRange === 2 ? 'active' : ''}" data-chain-range="2" title="Focus strictly on ATM ± 2 PineScript Signals">🎯 ATM ± 2</button>
            <button class="chart-mode-btn ${chainRange === 10 ? 'active' : ''}" data-chain-range="10">±10</button>
            <button class="chart-mode-btn ${chainRange === 15 ? 'active' : ''}" data-chain-range="15">±15</button>
            <button class="chart-mode-btn ${chainRange === 'ALL' ? 'active' : ''}" data-chain-range="ALL">ALL</button>
          </div>

          <!-- Mobile View Switcher (Centered vs Full Table) -->
          <div class="mobile-only-toggle">
            <button class="chart-mode-btn ${activeMobileViewMode === 'CENTERED' ? 'active' : ''}" id="btn-toggle-m-centered" title="Strikes fixed at center">🎯 Centered</button>
            <button class="chart-mode-btn ${activeMobileViewMode === 'TABLE' ? 'active' : ''}" id="btn-toggle-m-table" title="Full 14-Column Matrix Table">📋 Table</button>
          </div>
        </div>

        <div style="font-family: var(--font-mono); font-size: 11px; display: flex; gap: 12px; color: var(--text-secondary); align-items: center; flex-wrap: wrap;">
          <span>SPOT: <strong style="color: #38bdf8;">${spot ? spot.toLocaleString('en-IN', { minimumFractionDigits: 1 }) : '--'}</strong></span>
          <span>ATM: <strong style="color: #f59e0b;">${atm || '--'}</strong></span>
          <span>PCR: <strong style="color: #10b981;">${chain.pcr ? chain.pcr.toFixed(2) : '--'}</strong></span>
          <span>MAX PAIN: <strong style="color: #fbbf24;">${maxPain || '--'}</strong></span>
          <span style="background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.3); padding: 2px 7px; border-radius: 4px;">ATM ± 2: <strong style="color: #10b981;">${atmBuyingCount} BUYING 🟢</strong> <span style="color: var(--text-muted);">|</span> <strong style="color: #ef4444;">${atmSellingCount} SELLING 🛡️</strong></span>
          <span class="logo-badge" style="color: #10b981;">● ${chain.source || 'FYERS_LIVE'}</span>
        </div>
      </div>

      <!-- ========================================================================= -->
      <!-- MOBILE CENTER-LOCKED STRIKE COMPONENT (Active on screens <= 768px)       -->
      <!-- ========================================================================= -->
      <div class="mobile-chain-wrapper ${activeMobileViewMode === 'TABLE' ? 'hidden-force' : ''}" id="mobile-chain-wrapper">
        <!-- Side Focus Filter Bar: Allows dedicated view of PUT signals with zero Call interference -->
        <div class="m-side-filter-bar">
          <button class="m-side-btn ${activeMobileSide === 'BOTH' ? 'active' : ''}" data-m-side="BOTH" title="Calls on Left, Strike Center, Puts on Right">
            ⚡ BOTH (DUAL)
          </button>
          <button class="m-side-btn m-side-puts ${activeMobileSide === 'PUTS' ? 'active' : ''}" data-m-side="PUTS" title="Focus 100% on Put Signals, OI, and Prices">
            🔴 PUTS FOCUS (Signals & OI)
          </button>
          <button class="m-side-btn m-side-calls ${activeMobileSide === 'CALLS' ? 'active' : ''}" data-m-side="CALLS" title="Focus on Call Signals and OI">
            🟢 CALLS FOCUS
          </button>
        </div>

        <!-- Mobile Metric Quick-Selector Toolbar (for BOTH mode) -->
        <div class="mobile-metric-bar" style="${activeMobileSide !== 'BOTH' ? 'display: none;' : ''}">
          <div class="m-metric-pills">
            ${METRICS.map(m => `
              <button class="m-metric-btn ${activeMobileMetric === m.id ? 'active' : ''}" data-m-metric="${m.id}">
                ${m.label}
              </button>
            `).join('')}
          </div>
          <div class="m-drag-hint">
            <span>Tap any metric pill above to compare under strike</span>
          </div>
        </div>

        <!-- Mobile Option Chain Table Viewport -->
        <div class="mobile-chain-viewport" id="mobile-chain-viewport">
          <!-- Header -->
          <div class="mobile-chain-header ${activeMobileSide === 'PUTS' ? 'm-hdr-puts-focus' : activeMobileSide === 'CALLS' ? 'm-hdr-calls-focus' : ''}">
            ${activeMobileSide === 'PUTS' ? `
              <div class="m-focus-hdr-strike">STRIKE</div>
              <div class="m-focus-hdr-signal">PUT SIGNALS</div>
              <div class="m-focus-hdr-oi">PUT OI</div>
              <div class="m-focus-hdr-ltp">LTP / CHG%</div>
            ` : activeMobileSide === 'CALLS' ? `
              <div class="m-focus-hdr-ltp">LTP / CHG%</div>
              <div class="m-focus-hdr-oi">CALL OI</div>
              <div class="m-focus-hdr-signal">CALL SIGNALS</div>
              <div class="m-focus-hdr-strike">STRIKE</div>
            ` : `
              <div class="m-hdr-call">
                <span>CALLS (CE)</span>
                <span class="m-hdr-sub" id="m-hdr-call-sub">${getActiveMetricLabel(activeMobileMetric)}</span>
              </div>
              <div class="m-hdr-strike">
                <span>STRIKE</span>
              </div>
              <div class="m-hdr-put">
                <span>PUTS (PE)</span>
                <span class="m-hdr-sub" id="m-hdr-put-sub">${getActiveMetricLabel(activeMobileMetric)}</span>
              </div>
            `}
          </div>

          <!-- Rows Container -->
          <div class="mobile-chain-rows" id="mobile-chain-rows">
            ${visibleStrikes.length ? visibleStrikes.map(r => {
              const strike = r.strikePrice;
              const isATM = strike === atm;
              const isMaxPain = strike === maxPain;
              const isCallITM = spot > 0 && strike < spot;
              const isPutITM = spot > 0 && strike > spot;
              const isDeepCallITM = isCallITM && (spot - strike >= 3 * step);
              const isDeepPutITM = isPutITM && (strike - spot >= 3 * step);

              const ce = r.CE || {};
              const pe = r.PE || {};

              const ceVol = ce.totalTradedVolume || 0;
              const ceOI = ce.openInterest || 0;
              const ceOIChg = ce.changeinOpenInterest || 0;
              const ceOIChgPct = getOIChgPct(ceOI, ceOIChg);
              const ceLTP = ce.lastPrice || 0;
              const cePChg = ce.pChange || 0;
              const ceBuild = getBuildup(cePChg, ceOIChg);

              const peVol = pe.totalTradedVolume || 0;
              const peOI = pe.openInterest || 0;
              const peOIChg = pe.changeinOpenInterest || 0;
              const peOIChgPct = getOIChgPct(peOI, peOIChg);
              const peLTP = pe.lastPrice || 0;
              const pePChg = pe.pChange || 0;
              const peBuild = getBuildup(pePChg, peOIChg);

              const ceBarWidth = Math.min(100, Math.max(2, (ceOI / maxCeOI) * 100));
              const peBarWidth = Math.min(100, Math.max(2, (peOI / maxPeOI) * 100));

              const isAtm2 = Math.abs(strike - atm) <= (2 * step) + 0.1;
              const ceSig = getPineScriptSignal(ce, strike, spot, atm, step, 'CE');
              const peSig = getPineScriptSignal(pe, strike, spot, atm, step, 'PE');
              const combinedSig = getCombinedStrikeSignal(ceSig, peSig, strike, atm, step);

              // Dedicated PUTS FOCUS View
              if (activeMobileSide === 'PUTS') {
                return `
                  <div class="mobile-chain-row m-row-focus-puts ${isATM ? 'atm-row' : ''} ${isPutITM ? 'm-row-itm-pe' : ''}" data-strike="${strike}">
                    <!-- Strike Cell -->
                    <div class="m-focus-strike-cell ${isATM ? 'atm-strike-cell' : ''}">
                      <div class="m-strike-num">${strike}</div>
                      ${isATM ? '<span class="m-atm-tag">ATM</span>' : ''}
                      ${isMaxPain ? '<span class="strike-maxpain-tag">Max Pain</span>' : ''}
                    </div>

                    <!-- Put Buildup Signal & PineScript Signal -->
                    <div class="m-focus-signal-cell" style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
                      ${peSig ? `
                        <span class="pinescript-sig-pill ${peSig.cls}" style="font-size: 9.5px; padding: 1.5px 6px;" title="${peSig.tooltip}">
                          ${peSig.label}
                        </span>
                      ` : ''}
                      <span class="buildup-badge ${peBuild.cls}" style="font-size: 10px; padding: 2px 6px; min-width: 70px;">
                        ${peBuild.label} ${peBuild.name.split(' ')[0]}
                      </span>
                    </div>

                    <!-- Put OI & Gauge -->
                    <div class="m-focus-oi-cell oi-cell">
                      <div class="oi-gauge-bar oi-gauge-pe" style="width: ${peBarWidth}%;"></div>
                      <span class="oi-val-text">${fmtNumber(peOI)}</span>
                      <span style="font-size: 9px; color: ${peOIChgPct >= 0 ? '#10b981' : '#ef4444'}; margin-left: 3px;">
                        ${peOIChgPct >= 0 ? '+' : ''}${peOIChgPct}%
                      </span>
                    </div>

                    <!-- Put LTP & % -->
                    <div class="m-focus-ltp-cell">
                      <span class="m-ltp-val">${peLTP ? peLTP.toFixed(2) : '-'}</span>
                      <span class="m-pchg-val ${pePChg >= 0 ? 'text-bull' : 'text-bear'}">
                        ${pePChg >= 0 ? '+' : ''}${pePChg.toFixed(1)}%
                      </span>
                      ${isDeepPutITM ? '<span class="itm-warning" title="Deep In-The-Money (ITM) Strike: Caution - Lower liquidity, wide bid-ask spread & exercise risk" style="cursor: help;">⚠️</span>' : ''}
                    </div>
                  </div>
                `;
              }

              // Dedicated CALLS FOCUS View
              if (activeMobileSide === 'CALLS') {
                return `
                  <div class="mobile-chain-row m-row-focus-calls ${isATM ? 'atm-row' : ''} ${isCallITM ? 'm-row-itm-ce' : ''}" data-strike="${strike}">
                    <!-- Call LTP & % -->
                    <div class="m-focus-ltp-cell" style="justify-content: flex-start;">
                      ${isDeepCallITM ? '<span class="itm-warning" title="Deep In-The-Money (ITM) Strike: Caution - Lower liquidity, wide bid-ask spread & exercise risk" style="cursor: help;">⚠️</span>' : ''}
                      <span class="m-ltp-val">${ceLTP ? ceLTP.toFixed(2) : '-'}</span>
                      <span class="m-pchg-val ${cePChg >= 0 ? 'text-bull' : 'text-bear'}">
                        ${cePChg >= 0 ? '+' : ''}${cePChg.toFixed(1)}%
                      </span>
                    </div>

                    <!-- Call OI & Gauge -->
                    <div class="m-focus-oi-cell oi-cell">
                      <div class="oi-gauge-bar oi-gauge-ce" style="width: ${ceBarWidth}%;"></div>
                      <span class="oi-val-text">${fmtNumber(ceOI)}</span>
                      <span style="font-size: 9px; color: ${ceOIChgPct >= 0 ? '#10b981' : '#ef4444'}; margin-left: 3px;">
                        ${ceOIChgPct >= 0 ? '+' : ''}${ceOIChgPct}%
                      </span>
                    </div>

                    <!-- Call Buildup Signal & PineScript Signal -->
                    <div class="m-focus-signal-cell" style="display: flex; flex-direction: column; align-items: center; gap: 3px;">
                      ${ceSig ? `
                        <span class="pinescript-sig-pill ${ceSig.cls}" style="font-size: 9.5px; padding: 1.5px 6px;" title="${ceSig.tooltip}">
                          ${ceSig.label}
                        </span>
                      ` : ''}
                      <span class="buildup-badge ${ceBuild.cls}" style="font-size: 10px; padding: 2px 6px; min-width: 70px;">
                        ${ceBuild.label} ${ceBuild.name.split(' ')[0]}
                      </span>
                    </div>

                    <!-- Strike Cell -->
                    <div class="m-focus-strike-cell ${isATM ? 'atm-strike-cell' : ''}">
                      <div class="m-strike-num">${strike}</div>
                      ${isATM ? '<span class="m-atm-tag">ATM</span>' : ''}
                      ${isMaxPain ? '<span class="strike-maxpain-tag">Max Pain</span>' : ''}
                    </div>
                  </div>
                `;
              }

              // Dual BOTH View (Strike Centered)
              return `
                <div class="mobile-chain-row ${isATM ? 'atm-row' : ''} ${isCallITM ? 'm-row-itm-ce' : ''} ${isPutITM ? 'm-row-itm-pe' : ''}" data-strike="${strike}">
                  <!-- Left: Call Metric Cell -->
                  <div class="m-call-cell ${isCallITM ? 'itm-call' : ''}">
                    ${renderMobileMetricCell('CE', activeMobileMetric, {
                      ltp: ceLTP, pchg: cePChg, oi: ceOI, oichg: ceOIChg, oichgpct: ceOIChgPct,
                      vol: ceVol, build: ceBuild, sig: ceSig, barW: ceBarWidth, isDeep: isDeepCallITM
                    })}
                  </div>

                  <!-- Center: Strike Cell (Fixed & Anchored) -->
                  <div class="m-strike-cell ${isATM ? 'atm-strike-cell' : ''}">
                    <div class="m-strike-num">${strike}</div>
                    ${isMaxPain ? '<span class="strike-maxpain-tag">Max Pain</span>' : ''}
                    ${isATM ? '<span class="m-atm-tag">ATM</span>' : ''}
                    ${combinedSig && combinedSig.isAtm2 && combinedSig.label !== '-' ? `
                      <span class="m-chain-sig-tag ${combinedSig.cls}" title="${combinedSig.tooltip}">${combinedSig.shortLabel || combinedSig.label}</span>
                    ` : ''}
                  </div>

                  <!-- Right: Put Metric Cell -->
                  <div class="m-put-cell ${isPutITM ? 'itm-put' : ''}">
                    ${renderMobileMetricCell('PE', activeMobileMetric, {
                      ltp: peLTP, pchg: pePChg, oi: peOI, oichg: peOIChg, oichgpct: peOIChgPct,
                      vol: peVol, build: peBuild, sig: peSig, barW: peBarWidth, isDeep: isDeepPutITM
                    })}
                  </div>
                </div>
              `;
            }).join('') : `
              <div style="text-align: center; padding: 40px; color: var(--text-muted); font-size: 12px;">
                Awaiting Option Chain data for ${activeChainSym}...
              </div>
            `}
          </div>
        </div>
      </div>

      <!-- ========================================================================= -->
      <!-- FULL 13-COLUMN MATRIX TABLE VIEW (With ATM ± 2 PineScript Signal Column)   -->
      <!-- ========================================================================= -->
      <div class="chain-table-container ${activeMobileViewMode === 'CENTERED' ? 'desktop-only-table' : ''}" id="chain-table-container">
        <!-- Quick Horizontal Jump Buttons for Mobile Table Mode -->
        <div class="table-quick-nav">
          <button class="table-jump-btn" id="btn-jump-calls">‹ Calls (CE)</button>
          <button class="table-jump-btn" id="btn-jump-strike">• Center Strike & Signals •</button>
          <button class="table-jump-btn" id="btn-jump-puts">Puts (PE) ›</button>
        </div>

        <table class="sensibull-chain-table" id="sensibull-chain-table">
          <thead>
            <!-- Super Header -->
            <tr class="chain-super-header">
              <th colspan="6" class="super-call">Call</th>
              <th class="super-strike">Strike <span style="font-size: 10px;">▲</span></th>
              <th class="super-signal" title="PineScript OTT Indicator Buy/Sell Signals for ATM ± 2 strikes">Signal (ATM±2)</th>
              <th class="super-iv">IV</th>
              <th colspan="6" class="super-put">Put</th>
            </tr>

            <!-- Column Sub-Header -->
            <tr class="chain-col-header">
              <!-- Calls (6 columns) -->
              <th class="col-hull-ce" style="width: 80px; text-align: center;" title="Call Hull Suite (EHMA 34) Trend: Green = Call Chart Rising, Red = Call Chart Falling">HULL</th>
              <th style="width: 65px; text-align: center;">Buildup</th>
              <th style="text-align: right;">Volume</th>
              <th style="text-align: right;">OI Chg%</th>
              <th style="text-align: right;">OI</th>
              <th style="text-align: right;">LTP</th>

              <!-- Center (3 columns) -->
              <th class="col-strike" style="width: 85px;">Strike</th>
              <th class="col-signal" style="min-width: 145px; text-align: center;" title="PineScript OTT & Institutional Buildup Signal for ATM ± 2 strikes">Signal (ATM±2)</th>
              <th class="col-iv" style="width: 50px;">IV</th>

              <!-- Puts (6 columns) -->
              <th style="text-align: left;">LTP</th>
              <th style="text-align: left;">OI</th>
              <th style="text-align: left;">OI Chg%</th>
              <th style="text-align: left;">Volume</th>
              <th style="width: 65px; text-align: center;">Buildup</th>
              <th class="col-hull-pe" style="width: 80px; text-align: center;" title="Put Hull Suite (EHMA 34) Trend: Green = Put Chart Rising, Red = Put Chart Falling">HULL</th>
            </tr>
          </thead>
          <tbody>
            ${visibleStrikes.length ? visibleStrikes.map(r => {
              const strike = r.strikePrice;
              const isATM = strike === atm;
              const isMaxPain = strike === maxPain;
              const isCallITM = spot > 0 && strike < spot;
              const isPutITM = spot > 0 && strike > spot;
              const isDeepCallITM = isCallITM && (spot - strike >= 3 * step);
              const isDeepPutITM = isPutITM && (strike - spot >= 3 * step);

              const ce = r.CE || {};
              const pe = r.PE || {};

              // Call Metrics
              const ceVol = ce.totalTradedVolume || 0;
              const ceOI = ce.openInterest || 0;
              const ceOIChg = ce.changeinOpenInterest || 0;
              const ceOIChgPct = getOIChgPct(ceOI, ceOIChg);
              const ceLTP = ce.lastPrice || 0;
              const cePChg = ce.pChange || 0;
              const ceBuild = getBuildup(cePChg, ceOIChg);

              // Put Metrics
              const peVol = pe.totalTradedVolume || 0;
              const peOI = pe.openInterest || 0;
              const peOIChg = pe.changeinOpenInterest || 0;
              const peOIChgPct = getOIChgPct(peOI, peOIChg);
              const peLTP = pe.lastPrice || 0;
              const pePChg = pe.pChange || 0;
              const peBuild = getBuildup(pePChg, peOIChg);

              // PineScript ATM +- 2 Signals
              const isAtm2 = Math.abs(strike - atm) <= (2 * step) + 0.1;
              const ceSig = getPineScriptSignal(ce, strike, spot, atm, step, 'CE');
              const peSig = getPineScriptSignal(pe, strike, spot, atm, step, 'PE');
              const combinedSig = getCombinedStrikeSignal(ceSig, peSig, strike, atm, step);

              // Heatmap class for Call Volume
              let ceVolClass = '';
              if (ceVol >= maxCeVol * 0.75) ceVolClass = 'vol-heat-heavy-call';
              else if (ceVol >= maxCeVol * 0.45) ceVolClass = 'vol-heat-med-call';
              else if (ceVol >= maxCeVol * 0.25) ceVolClass = 'vol-heat-light-call';

              // Heatmap class for Put Volume
              let peVolClass = '';
              if (peVol >= maxPeVol * 0.75) peVolClass = 'vol-heat-heavy-put';
              else if (peVol >= maxPeVol * 0.45) peVolClass = 'vol-heat-med-put';
              else if (peVol >= maxPeVol * 0.25) peVolClass = 'vol-heat-light-put';

              // Surge class for OI Chg%
              const ceSurgeClass = ceOIChgPct >= 100 ? 'oi-surge-call' : '';
              const peSurgeClass = peOIChgPct >= 100 ? 'oi-surge-put' : '';

              // Relative bar widths for OI
              const ceBarWidth = Math.min(100, Math.max(2, (ceOI / maxCeOI) * 100));
              const peBarWidth = Math.min(100, Math.max(2, (peOI / maxPeOI) * 100));
              const ceIsPeak = ceOI === maxCeOI && ceOI > 0;
              const peIsPeak = peOI === maxPeOI && peOI > 0;

              return `
                <tr class="${isATM ? 'atm-row' : ''} ${isAtm2 ? 'atm2-corridor-row' : ''}">
                  <!-- 0. Call Hull Suite (Far Left) -->
                  <td class="${isCallITM ? 'itm-call' : ''}" style="text-align: center;">
                    ${renderContractHullBadge(ce, 'CE')}
                  </td>

                  <!-- 1. Call Buildup -->
                  <td class="${isCallITM ? 'itm-call' : ''}" style="text-align: center;">
                    <span class="buildup-badge ${ceBuild.cls}" title="${ceBuild.name}">
                      ${ceBuild.label}
                    </span>
                  </td>

                  <!-- 2. Call Volume -->
                  <td class="${isCallITM ? 'itm-call' : ''} ${ceVolClass}" style="text-align: right;">
                    ${fmtNumber(ceVol)}
                  </td>

                  <!-- 3. Call OI Chg% -->
                  <td class="${isCallITM ? 'itm-call' : ''} ${ceSurgeClass}" style="text-align: right; font-weight: 700; color: ${ceOIChgPct >= 0 ? '#10b981' : '#ef4444'};">
                    ${ceOIChgPct >= 0 ? '+' : ''}${ceOIChgPct}%
                  </td>

                  <!-- 4. Call OI with Relative Bar Gauge -->
                  <td class="${isCallITM ? 'itm-call' : ''} oi-cell ${ceIsPeak ? 'oi-peak-ce' : ''}">
                    <div class="oi-gauge-bar oi-gauge-ce" style="width: ${ceBarWidth}%;"></div>
                    <span class="oi-val-text">${fmtNumber(ceOI)}</span>
                  </td>

                  <!-- 5. Call LTP -->
                  <td class="${isCallITM ? 'itm-call' : ''}" style="text-align: right; font-weight: 700;">
                    ${isDeepCallITM ? '<span class="itm-warning" title="Deep In-The-Money (ITM) Strike: Caution - Lower liquidity, wide bid-ask spread & exercise risk" style="cursor: help; margin-right: 3px;">⚠️</span>' : ''}
                    <span>${ceLTP ? ceLTP.toFixed(2) : '-'}</span>
                    <span style="font-size: 9.5px; margin-left: 4px; color: ${cePChg >= 0 ? '#10b981' : '#ef4444'};">
                      ${cePChg >= 0 ? '+' : ''}${cePChg.toFixed(0)}%
                    </span>
                  </td>

                  <!-- 6. Strike Column (Center) -->
                  <td class="chain-strike-cell">
                    <div>${strike}</div>
                    ${isMaxPain ? '<span class="strike-maxpain-tag">Max Pain</span>' : ''}
                  </td>

                  <!-- 7. Signal (ATM+-2) Column (Center) -->
                  <td class="chain-signal-cell" style="text-align: center;">
                    ${renderStrikeSignalCell(combinedSig)}
                  </td>

                  <!-- 8. IV Column (Center) -->
                  <td class="chain-iv-cell">
                    ${ce.impliedVolatility ? ce.impliedVolatility.toFixed(1) : (pe.impliedVolatility ? pe.impliedVolatility.toFixed(1) : '-')}
                  </td>

                  <!-- 9. Put LTP -->
                  <td class="${isPutITM ? 'itm-put' : ''}" style="text-align: left; font-weight: 700;">
                    <span>${peLTP ? peLTP.toFixed(2) : '-'}</span>
                    <span style="font-size: 9.5px; margin-left: 4px; color: ${pePChg >= 0 ? '#10b981' : '#ef4444'};">
                      ${pePChg >= 0 ? '+' : ''}${pePChg.toFixed(0)}%
                    </span>
                    ${isDeepPutITM ? '<span class="itm-warning" title="Deep In-The-Money (ITM) Strike: Caution - Lower liquidity, wide bid-ask spread & exercise risk" style="cursor: help; margin-left: 3px;">⚠️</span>' : ''}
                  </td>

                  <!-- 10. Put OI with Relative Bar Gauge -->
                  <td class="${isPutITM ? 'itm-put' : ''} oi-cell ${peIsPeak ? 'oi-peak-pe' : ''}" style="text-align: left; padding-left: 8px;">
                    <div class="oi-gauge-bar oi-gauge-pe" style="width: ${peBarWidth}%;"></div>
                    <span class="oi-val-text">${fmtNumber(peOI)}</span>
                  </td>

                  <!-- 11. Put OI Chg% -->
                  <td class="${isPutITM ? 'itm-put' : ''} ${peSurgeClass}" style="text-align: left; font-weight: 700; color: ${peOIChgPct >= 0 ? '#10b981' : '#ef4444'};">
                    ${peOIChgPct >= 0 ? '+' : ''}${peOIChgPct}%
                  </td>

                  <!-- 12. Put Volume -->
                  <td class="${isPutITM ? 'itm-put' : ''} ${peVolClass}" style="text-align: left;">
                    ${fmtNumber(peVol)}
                  </td>

                  <!-- 13. Put Buildup -->
                  <td class="${isPutITM ? 'itm-put' : ''}" style="text-align: center;">
                    <span class="buildup-badge ${peBuild.cls}" title="${peBuild.name}">
                      ${peBuild.label}
                    </span>
                  </td>

                  <!-- 14. Put Hull Suite (Far Right) -->
                  <td class="${isPutITM ? 'itm-put' : ''}" style="text-align: center;">
                    ${renderContractHullBadge(pe, 'PE')}
                  </td>
                </tr>
              `;
            }).join('') : `
              <tr>
                <td colspan="15" style="text-align: center; padding: 40px; color: var(--text-muted); font-size: 12px;">
                  Awaiting Option Chain Matrix data for ${activeChainSym}...
                </td>
              </tr>
            `}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Attach Symbol Switcher Listeners
  container.querySelectorAll('[data-chain-toggle]').forEach(btn => {
    btn.addEventListener('click', () => {
      const sym = btn.getAttribute('data-chain-toggle');
      hasInitialChainAligned = false; // Allow fresh alignment for new symbol
      if (onSelectChainSymbol) onSelectChainSymbol(sym);
      store.setState({ activeChainSymbol: sym });
    });
  });

  // Attach Range Filter Listeners (ATM ± 10, ±15, ALL)
  container.querySelectorAll('[data-chain-range]').forEach(btn => {
    btn.addEventListener('click', () => {
      const rVal = btn.getAttribute('data-chain-range');
      store.setState({ chainRange: rVal === 'ALL' ? 'ALL' : parseInt(rVal, 10) });
    });
  });

  // Mobile View Toggle Listeners (Centered vs Table)
  const btnCentered = container.querySelector('#btn-toggle-m-centered');
  const btnTable = container.querySelector('#btn-toggle-m-table');
  const mWrap = container.querySelector('#mobile-chain-wrapper');
  const dTable = container.querySelector('#chain-table-container');

  if (btnCentered && btnTable) {
    btnCentered.addEventListener('click', () => {
      activeMobileViewMode = 'CENTERED';
      btnCentered.classList.add('active');
      btnTable.classList.remove('active');
      if (mWrap) mWrap.classList.remove('hidden-force');
      if (dTable) dTable.classList.add('desktop-only-table');
      scrollMobileATMIntoView(container);
    });

    btnTable.addEventListener('click', () => {
      activeMobileViewMode = 'TABLE';
      btnTable.classList.add('active');
      btnCentered.classList.remove('active');
      if (mWrap) mWrap.classList.add('hidden-force');
      if (dTable) dTable.classList.remove('desktop-only-table');
      // Jump smoothly to strike on mode switch
      const tbl = container.querySelector('#chain-table-container');
      const sc = container.querySelector('.col-strike');
      if (tbl && sc) {
        tbl.scrollLeft = sc.offsetLeft - (tbl.clientWidth / 2) + (sc.clientWidth / 2);
      }
    });
  }

  // Side Filter Listeners ([BOTH], [PUTS], [CALLS])
  container.querySelectorAll('[data-m-side]').forEach(btn => {
    btn.addEventListener('click', () => {
      const side = btn.getAttribute('data-m-side');
      activeMobileSide = side;
      // Re-render table with new side focus
      renderChainTable(container, onSelectChainSymbol);
    });
  });

  // Mobile Metric Pill Buttons
  container.querySelectorAll('[data-m-metric]').forEach(btn => {
    btn.addEventListener('click', () => {
      const metric = btn.getAttribute('data-m-metric');
      setMobileMetric(container, metric, visibleStrikes, spot, atm, maxCeOI, maxPeOI, step);
    });
  });

  // Full Table Quick Jump Buttons (Jump to Calls, Strike, or Puts)
  const btnJumpCalls = container.querySelector('#btn-jump-calls');
  const btnJumpStrike = container.querySelector('#btn-jump-strike');
  const btnJumpPuts = container.querySelector('#btn-jump-puts');
  const tblContainer = container.querySelector('#chain-table-container');

  if (btnJumpCalls && tblContainer) {
    btnJumpCalls.addEventListener('click', () => {
      persistentTableScrollLeft = 0;
      tblContainer.scrollTo({ left: 0, behavior: 'smooth' });
    });
  }
  if (btnJumpStrike && tblContainer) {
    btnJumpStrike.addEventListener('click', () => {
      const sc = tblContainer.querySelector('.col-strike');
      if (sc) {
        const tgt = Math.max(0, sc.offsetLeft - (tblContainer.clientWidth / 2) + (sc.clientWidth / 2));
        persistentTableScrollLeft = tgt;
        tblContainer.scrollTo({ left: tgt, behavior: 'smooth' });
      }
    });
  }
  if (btnJumpPuts && tblContainer) {
    btnJumpPuts.addEventListener('click', () => {
      persistentTableScrollLeft = tblContainer.scrollWidth;
      tblContainer.scrollTo({ left: tblContainer.scrollWidth, behavior: 'smooth' });
    });
  }

  // Active touch and scroll tracking to prevent background polling reset
  if (tblContainer) {
    tblContainer.addEventListener('touchstart', () => { isUserTouchingChain = true; }, { passive: true });
    tblContainer.addEventListener('touchend', () => { 
      isUserTouchingChain = false; 
      if (tblContainer.scrollLeft > 0) persistentTableScrollLeft = tblContainer.scrollLeft;
      persistentTableScrollTop = tblContainer.scrollTop;
    }, { passive: true });
    tblContainer.addEventListener('scroll', () => {
      if (tblContainer.scrollLeft > 0) persistentTableScrollLeft = tblContainer.scrollLeft;
      persistentTableScrollTop = tblContainer.scrollTop;
    }, { passive: true });
  }

  // Attach Touch & Mouse Drag Listeners on Mobile Chain Viewport (for BOTH mode)
  if (activeMobileSide === 'BOTH') {
    attachMobileDragInteractivity(container, visibleStrikes, spot, maxCeOI, maxPeOI, step);
  }

  // =========================================================================
  // SCROLL POSITION MANAGEMENT: NEVER OVERRIDE USER DURING POLLING!
  // =========================================================================
  const targetScrollLeft = persistentTableScrollLeft !== null ? persistentTableScrollLeft : prevScrollLeft;
  const targetScrollTop = persistentTableScrollTop !== null ? persistentTableScrollTop : prevScrollTop;

  if (!hasInitialChainAligned) {
    // Only perform auto-scroll ONCE on initial mount!
    hasInitialChainAligned = true;
    setTimeout(() => {
      scrollMobileATMIntoView(container);
      if (activeMobileViewMode === 'TABLE' && tblContainer) {
        const sc = tblContainer.querySelector('.col-strike');
        if (sc) {
          const initLeft = sc.offsetLeft - (tblContainer.clientWidth / 2) + (sc.clientWidth / 2);
          persistentTableScrollLeft = Math.max(0, initLeft);
          tblContainer.scrollLeft = persistentTableScrollLeft;
        }
      }
    }, 80);
  } else {
    // Background polling update: RESTORE exact user scroll positions!
    // NEVER snap or reorient back to call data!
    if (targetScrollLeft !== null && tblContainer) {
      tblContainer.scrollLeft = targetScrollLeft;
      tblContainer.scrollTop = targetScrollTop || 0;
      requestAnimationFrame(() => {
        if (tblContainer) tblContainer.scrollLeft = targetScrollLeft;
      });
      setTimeout(() => {
        if (tblContainer) tblContainer.scrollLeft = targetScrollLeft;
      }, 50);
      setTimeout(() => {
        if (tblContainer) tblContainer.scrollLeft = targetScrollLeft;
      }, 150);
    }
    if (prevRowsScrollTop !== null) {
      const newRows = container.querySelector('#mobile-chain-rows');
      if (newRows) {
        newRows.scrollTop = prevRowsScrollTop;
      }
    }
  }
}

function getActiveMetricLabel(metricId) {
  const m = METRICS.find(x => x.id === metricId);
  return m ? m.short : metricId;
}

function renderMobileMetricCell(side, metricId, data) {
  const isCE = side === 'CE';
  const align = isCE ? 'flex-end' : 'flex-start';

  if (metricId === 'PRICE') {
    return `
      <div class="m-cell-content" style="justify-content: ${align};">
        ${isCE && data.isDeep ? '<span class="itm-warning" title="Deep In-The-Money (ITM) Strike: Caution - Lower liquidity, wide bid-ask spread & exercise risk" style="cursor: help;">⚠️</span>' : ''}
        <span class="m-ltp-val">${data.ltp ? data.ltp.toFixed(2) : '-'}</span>
        <span class="m-pchg-val ${data.pchg >= 0 ? 'text-bull' : 'text-bear'}">
          ${data.pchg >= 0 ? '+' : ''}${data.pchg.toFixed(0)}%
        </span>
        ${!isCE && data.isDeep ? '<span class="itm-warning" title="Deep In-The-Money (ITM) Strike: Caution - Lower liquidity, wide bid-ask spread & exercise risk" style="cursor: help;">⚠️</span>' : ''}
      </div>
    `;
  }

  if (metricId === 'OI') {
    return `
      <div class="m-cell-content oi-cell" style="justify-content: ${align}; width: 100%;">
        <div class="oi-gauge-bar ${isCE ? 'oi-gauge-ce' : 'oi-gauge-pe'}" style="width: ${data.barW}%;"></div>
        <span class="oi-val-text">${fmtNumber(data.oi)}</span>
      </div>
    `;
  }

  if (metricId === 'OICHG') {
    return `
      <div class="m-cell-content" style="justify-content: ${align};">
        <span style="font-weight: 700; color: ${data.oichgpct >= 0 ? '#10b981' : '#ef4444'};">
          ${data.oichgpct >= 0 ? '+' : ''}${data.oichgpct}%
        </span>
        <span style="font-size: 9.5px; color: var(--text-muted); margin-left: 4px;">
          (${fmtNumber(data.oichg)})
        </span>
      </div>
    `;
  }

  if (metricId === 'SIGNALS') {
    return `
      <div class="m-cell-content" style="justify-content: ${align}; gap: 3px; flex-wrap: wrap;">
        ${data.sig ? `
          <span class="pinescript-sig-pill ${data.sig.cls}" style="font-size: 9px; padding: 1.5px 5px;" title="${data.sig.tooltip}">
            ${data.sig.label}
          </span>
        ` : ''}
        <span class="buildup-badge ${data.build.cls}" title="${data.build.name}">
          ${data.build.label} ${data.build.name.split(' ')[0]}
        </span>
      </div>
    `;
  }

  if (metricId === 'VOL') {
    return `
      <div class="m-cell-content" style="justify-content: ${align};">
        <span style="font-weight: 600;">${fmtNumber(data.vol)}</span>
      </div>
    `;
  }

  // DUAL (Price + OI)
  return `
    <div class="m-cell-content m-dual-cell" style="justify-content: ${align};">
      ${isCE ? `
        <span class="m-dual-sub">${fmtNumber(data.oi)}</span>
        <span class="m-dual-main">${data.ltp ? data.ltp.toFixed(1) : '-'}</span>
      ` : `
        <span class="m-dual-main">${data.ltp ? data.ltp.toFixed(1) : '-'}</span>
        <span class="m-dual-sub">${fmtNumber(data.oi)}</span>
      `}
    </div>
  `;
}

function setMobileMetric(container, metricId, visibleStrikes, spot, atm, maxCeOI, maxPeOI, step) {
  if (activeMobileMetric === metricId) return;
  activeMobileMetric = metricId;

  // Update button active state
  container.querySelectorAll('[data-m-metric]').forEach(btn => {
    if (btn.getAttribute('data-m-metric') === metricId) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  // Update header labels
  const hdrCall = container.querySelector('#m-hdr-call-sub');
  const hdrPut = container.querySelector('#m-hdr-put-sub');
  const label = getActiveMetricLabel(metricId);
  if (hdrCall) hdrCall.textContent = label;
  if (hdrPut) hdrPut.textContent = label;

  // Re-render cells in-place with smooth animation
  const rowsContainer = container.querySelector('#mobile-chain-rows');
  if (!rowsContainer || !visibleStrikes || !visibleStrikes.length) return;

  const rows = rowsContainer.querySelectorAll('.mobile-chain-row');
  rows.forEach((rowEl, i) => {
    const r = visibleStrikes[i];
    if (!r) return;

    const strike = r.strikePrice;
    const isCallITM = spot > 0 && strike < spot;
    const isPutITM = spot > 0 && strike > spot;
    const isDeepCallITM = isCallITM && (spot - strike >= 3 * step);
    const isDeepPutITM = isPutITM && (strike - spot >= 3 * step);

    const ce = r.CE || {};
    const pe = r.PE || {};
    const ceVol = ce.totalTradedVolume || 0;
    const ceOI = ce.openInterest || 0;
    const ceOIChg = ce.changeinOpenInterest || 0;
    const ceOIChgPct = getOIChgPct(ceOI, ceOIChg);
    const ceLTP = ce.lastPrice || 0;
    const cePChg = ce.pChange || 0;
    const ceBuild = getBuildup(cePChg, ceOIChg);

    const peVol = pe.totalTradedVolume || 0;
    const peOI = pe.openInterest || 0;
    const peOIChg = pe.changeinOpenInterest || 0;
    const peOIChgPct = getOIChgPct(peOI, peOIChg);
    const peLTP = pe.lastPrice || 0;
    const pePChg = pe.pChange || 0;
    const peBuild = getBuildup(pePChg, peOIChg);

    const ceBarWidth = Math.min(100, Math.max(2, (ceOI / maxCeOI) * 100));
    const peBarWidth = Math.min(100, Math.max(2, (peOI / maxPeOI) * 100));

    const isAtm2 = Math.abs(strike - atm) <= (2 * step) + 0.1;
    const ceSig = getPineScriptSignal(ce, strike, spot, atm, step, 'CE');
    const peSig = getPineScriptSignal(pe, strike, spot, atm, step, 'PE');

    const callCell = rowEl.querySelector('.m-call-cell');
    const putCell = rowEl.querySelector('.m-put-cell');

    if (callCell) {
      callCell.innerHTML = renderMobileMetricCell('CE', metricId, {
        ltp: ceLTP, pchg: cePChg, oi: ceOI, oichg: ceOIChg, oichgpct: ceOIChgPct,
        vol: ceVol, build: ceBuild, sig: ceSig, barW: ceBarWidth, isDeep: isDeepCallITM
      });
      callCell.classList.add('m-metric-animate');
      setTimeout(() => callCell.classList.remove('m-metric-animate'), 200);
    }

    if (putCell) {
      putCell.innerHTML = renderMobileMetricCell('PE', metricId, {
        ltp: peLTP, pchg: pePChg, oi: peOI, oichg: peOIChg, oichgpct: peOIChgPct,
        vol: peVol, build: peBuild, sig: peSig, barW: peBarWidth, isDeep: isDeepPutITM
      });
      putCell.classList.add('m-metric-animate');
      setTimeout(() => putCell.classList.remove('m-metric-animate'), 200);
    }
  });
}

function attachMobileDragInteractivity(container, visibleStrikes, spot, maxCeOI, maxPeOI, step) {
  const viewport = container.querySelector('#mobile-chain-viewport');
  if (!viewport) return;

  let startX = 0;
  let startY = 0;
  let isDragging = false;
  const threshold = 70; // Strict threshold to prevent accidental switches during vertical scrolling

  const handleStart = (x, y) => {
    startX = x;
    startY = y;
    isDragging = true;
  };

  const handleEnd = (x, y) => {
    if (!isDragging) return;
    isDragging = false;

    const dx = x - startX;
    const dy = y - startY;

    // Only switch metric if clear horizontal swipe intent (horizontal >= 3x vertical)
    if (Math.abs(dx) > threshold && Math.abs(dx) > 3 * Math.abs(dy)) {
      const curIdx = METRICS.findIndex(m => m.id === activeMobileMetric);
      if (dx < 0) {
        // Swipe left -> advance to next metric
        const nextIdx = (curIdx + 1) % METRICS.length;
        setMobileMetric(container, METRICS[nextIdx].id, visibleStrikes, spot, maxCeOI, maxPeOI, step);
      } else {
        // Swipe right -> previous metric
        const prevIdx = (curIdx - 1 + METRICS.length) % METRICS.length;
        setMobileMetric(container, METRICS[prevIdx].id, visibleStrikes, spot, maxCeOI, maxPeOI, step);
      }
    }
  };

  viewport.addEventListener('touchstart', (e) => {
    if (e.touches && e.touches[0]) {
      handleStart(e.touches[0].clientX, e.touches[0].clientY);
    }
  }, { passive: true });

  viewport.addEventListener('touchend', (e) => {
    if (e.changedTouches && e.changedTouches[0]) {
      handleEnd(e.changedTouches[0].clientX, e.changedTouches[0].clientY);
    }
  }, { passive: true });

  viewport.addEventListener('mousedown', (e) => handleStart(e.clientX, e.clientY));
  viewport.addEventListener('mouseup', (e) => handleEnd(e.clientX, e.clientY));
}

function scrollMobileATMIntoView(container) {
  const rowsWrap = container.querySelector('#mobile-chain-rows');
  const atmRow = container.querySelector('.mobile-chain-row.atm-row');
  if (rowsWrap && atmRow) {
    const topPos = atmRow.offsetTop - rowsWrap.offsetTop - (rowsWrap.clientHeight / 2) + (atmRow.clientHeight / 2);
    rowsWrap.scrollTo({ top: Math.max(0, topPos), behavior: 'smooth' });
  }
}
