/**
 * Option Confluence Analysis Dashboard Component (ATM +- 2 Strikes)
 * ═══════════════════════════════════════════════════════════════════════
 * Professional Trading Terminal Table integrating:
 * Layer 1: Raw Option Chain metrics (OI, ΔOI, LTP, Vol, IV, PCR)
 * Layer 2: Derived Positioning & Flow (Writing, Unwinding, Long/Short Buildup)
 * Layer 3: Price Confirmation (AlphaTrend, TrendDirection, Shonya, Proximity)
 * Layer 4: Mathematical Multi-Dimensional Confluence Score & Signals
 *
 * MOBILE-FIRST ARCHITECTURE:
 * - Sticky/Fixed Strike Anchor Column (horizontal scroll for metrics)
 * - Dynamic ATM Row Highlighting with glowing borders
 * - Symmetrical corridor expansion (ATM +- 2 default, +-3, +-5)
 * - 1-Click deep link to TradingView 5-min Option Candlestick Chart
 */
import { ApiClient } from '../api.js';
import { store } from '../state.js';

let currentSymbol = 'NIFTY';       // 'NIFTY' | 'BANKNIFTY' | 'FINNIFTY' | 'MIDCPNIFTY'
let currentRange  = 2;             // 2 (ATM +- 2), 3 (ATM +- 3), 5 (ATM +- 5)
let currentFilter = 'ALL';           // 'ALL' | 'BULLISH' | 'BEARISH' | 'HIGH_SCORE'
let pollTimer     = null;
let isFetching    = false;
let lastData      = null;

// Replay State for Whole-Day Institutional Command Radar
let isRadarReplayMode = false;
let radarReplayData = null;
let radarReplayIdx = 0;
let radarPlayInterval = null;

export async function renderOptionConfluence(container) {
  // If the frame already exists in DOM, update in-place without wiping out scroll state
  const existingWrap = container.querySelector('.option-confluence-container');
  if (existingWrap) {
    await _loadAndRender(container);
    return;
  }

  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  // 1. Write the static frame
  container.innerHTML = `
    <div class="option-confluence-container" style="padding: 16px;">

      <!-- Top Control Bar: Title, Symbol Switcher, Range Selector, Filters -->
      <div class="glass-panel" style="padding: 16px; margin-bottom: 16px; border: 1px solid rgba(56, 189, 248, 0.28); border-radius: 12px; background: linear-gradient(180deg, rgba(15, 23, 42, 0.95) 0%, rgba(10, 15, 30, 0.98) 100%); box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
        <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 14px;">
          
          <!-- Left: Title & Subtitle -->
          <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 28px;">🎯</span>
            <div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <h2 style="margin: 0; font-size: 16px; font-weight: 800; letter-spacing: 0.5px; color: #f8fafc;">
                  OPTION CONFLUENCE ANALYSIS (ATM ± 2)
                </h2>
                <span id="confluence-live-badge" class="badge-active" style="font-size: 10px; padding: 2px 8px; border-radius: 9999px;">
                  ● LIVE STREAMING
                </span>
              </div>
              <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 3px;">
                Multi-layer institutional analysis: <strong>Raw Option Chain + Derived Buildups + AlphaTrend &amp; TrendDirection Momentum + Confluence Score</strong>
              </div>
            </div>
          </div>

          <!-- Right: Controls -->
          <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 10px;">
            
            <!-- Index Selector -->
            <div style="display: flex; align-items: center; gap: 4px; background: rgba(0, 0, 0, 0.45); padding: 4px 6px; border-radius: 8px; border: 1px solid rgba(56, 189, 248, 0.2);">
              <span style="font-size: 10px; font-weight: 800; color: #94a3b8; margin-right: 4px;">INDEX:</span>
              ${['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX'].map(s => `
                <button class="conf-sym-btn ${s === currentSymbol ? 'active' : ''}" data-sym="${s}" style="padding: 4px 10px; font-size: 11px; font-weight: 800; border-radius: 5px; border: none; cursor: pointer;">
                  ${s}
                </button>
              `).join('')}
            </div>

            <!-- Corridor Range Selector -->
            <div style="display: flex; align-items: center; gap: 4px; background: rgba(0, 0, 0, 0.45); padding: 4px 6px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08);">
              <span style="font-size: 10px; font-weight: 800; color: #94a3b8; margin-right: 4px;">CORRIDOR:</span>
              <button class="conf-range-btn ${currentRange === 2 ? 'active' : ''}" data-range="2" style="padding: 4px 8px; font-size: 10.5px; font-weight: 700; border-radius: 4px; border: none; cursor: pointer;" title="ATM +- 2 strikes (Top 5 active strikes)">
                ATM ± 2 (5)
              </button>
              <button class="conf-range-btn ${currentRange === 3 ? 'active' : ''}" data-range="3" style="padding: 4px 8px; font-size: 10.5px; font-weight: 700; border-radius: 4px; border: none; cursor: pointer;" title="ATM +- 3 strikes (7 strikes)">
                ± 3 (7)
              </button>
              <button class="conf-range-btn ${currentRange === 5 ? 'active' : ''}" data-range="5" style="padding: 4px 8px; font-size: 10.5px; font-weight: 700; border-radius: 4px; border: none; cursor: pointer;" title="ATM +- 5 strikes (11 strikes)">
                ± 5 (11)
              </button>
            </div>

            <!-- Signal Filter Pills -->
            <div style="display: flex; align-items: center; gap: 4px; background: rgba(0, 0, 0, 0.45); padding: 4px 6px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08);">
              <button class="conf-filter-btn ${currentFilter === 'ALL' ? 'active' : ''}" data-filter="ALL" style="padding: 4px 8px; font-size: 10.5px; font-weight: 700; border-radius: 4px; border: none; cursor: pointer;">
                ALL
              </button>
              <button class="conf-filter-btn ${currentFilter === 'BULLISH' ? 'active' : ''}" data-filter="BULLISH" style="padding: 4px 8px; font-size: 10.5px; font-weight: 700; border-radius: 4px; border: none; cursor: pointer;">
                🟢 BULLISH
              </button>
              <button class="conf-filter-btn ${currentFilter === 'BEARISH' ? 'active' : ''}" data-filter="BEARISH" style="padding: 4px 8px; font-size: 10.5px; font-weight: 700; border-radius: 4px; border: none; cursor: pointer;">
                🔴 BEARISH
              </button>
              <button class="conf-filter-btn ${currentFilter === 'HIGH_SCORE' ? 'active' : ''}" data-filter="HIGH_SCORE" style="padding: 4px 8px; font-size: 10.5px; font-weight: 700; border-radius: 4px; border: none; cursor: pointer;" title="High Confluence Score >= 65">
                ⚡ HIGH CONVICTION
              </button>
            </div>

          </div>
        </div>
      </div>

      <!-- Mount: Compact Executive Summary Panel -->
      <div id="confluence-summary-mount" style="margin-bottom: 16px;"></div>

      <!-- Mount: Dedicated 5-Pillar Quantitative & PineScript Indicators Matrix -->
      <div id="confluence-indicators-mount" style="margin-bottom: 16px;"></div>

      <!-- Mount: Primary Analytical Table -->
      <div id="confluence-table-mount" style="margin-bottom: 20px;"></div>
    </div>
  `;

  _attachListeners(container);

  // Initial fetch
  await _loadAndRender(container);

  // Continuous live update every 4.5 seconds
  pollTimer = setInterval(async () => {
    if (document.hidden) return;
    if (!document.body.contains(container)) {
      clearInterval(pollTimer);
      pollTimer = null;
      return;
    }
    if (store.isReplayActive()) return;
    await _loadAndRender(container);
  }, 4500);
}

// ─────────────────────────────────────────────────────────────────────────────
// DATA FETCH & RENDERING ORCHESTRATOR
// ─────────────────────────────────────────────────────────────────────────────
async function _loadAndRender(container) {
  if (isFetching) return;
  isFetching = true;
  try {
    // 1. Fetch & render detailed ATM +- 2 Option Confluence
    const state = store.getState();
    if (store.isReplayActive() && state?.replay?.snapshot?.confluence_corridor) {
      const data = state.replay.snapshot.confluence_corridor;
      lastData = data;
      _renderSummary(container, data);
      _renderIndicatorsSection(container, data);
      _renderTable(container, data);
    } else {
      const data = await ApiClient.fetchOptionConfluence(currentSymbol, currentRange);
      if (data && data.success) {
        lastData = data;
        _renderSummary(container, data);
        _renderIndicatorsSection(container, data);
        _renderTable(container, data);
      }
    }
  } catch (err) {
    console.debug('Option confluence polling tick error:', err);
  } finally {
    isFetching = false;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 0. MULTI-INDEX INSTITUTIONAL COMMAND RADAR (CROSS-ASSET CONFLUENCE & REPLAY)
// ─────────────────────────────────────────────────────────────────────────────
function _renderSignalArrow(val, label) {
  const v = (val || '').toUpperCase();
  if (v === 'BULLISH' || v === 'UP' || v === 'BUY' || v === 'GREEN' || v === 'LONG') {
    return `<div style="display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 8px; background: rgba(16,185,129,0.18); border: 1px solid rgba(16,185,129,0.5); color: #10b981; font-size: 16px; font-weight: 900; box-shadow: 0 0 10px rgba(16,185,129,0.25);" title="${label}: UP / BULLISH">▲</div>`;
  }
  if (v === 'BEARISH' || v === 'DOWN' || v === 'SELL' || v === 'RED' || v === 'SHORT') {
    return `<div style="display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 8px; background: rgba(239,68,68,0.18); border: 1px solid rgba(239,68,68,0.5); color: #ef4444; font-size: 16px; font-weight: 900; box-shadow: 0 0 10px rgba(239,68,68,0.25);" title="${label}: DOWN / BEARISH">▼</div>`;
  }
  return `<div style="display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 8px; background: rgba(234,179,8,0.18); border: 1px solid rgba(234,179,8,0.5); color: #eab308; font-size: 14px; font-weight: 900; box-shadow: 0 0 10px rgba(234,179,8,0.2);" title="${label}: FLAT / SIDEWAYS">►</div>`;
}

function _buildRadarRowHtml(idx) {
  const isSelected = idx.symbol === currentSymbol;
  const pchange = idx.spot_pchange || 0;
  const pchangeColor = pchange > 0 ? '#10b981' : (pchange < 0 ? '#ef4444' : '#94a3b8');
  const pchangeSign = pchange > 0 ? '+' : '';
  const pchangeArrow = pchange > 0 ? '▲' : (pchange < 0 ? '▼' : '■');

  // 1. Total OI Color Coding (Green = Put Heavy Support, Red = Call Heavy Resistance, Yellow = Balanced)
  const totCe = idx.tot_ce_oi_lakhs || ((idx.tot_ce_oi || 0) / 100000) || 1;
  const totPe = idx.tot_pe_oi_lakhs || ((idx.tot_pe_oi || 0) / 100000) || 1;
  const netDiffLakhs = Math.abs(totPe - totCe).toFixed(1);

  let totOiHtml = '';
  if (idx.tot_oi_bias === 'PE_DOMINANT' || totPe > totCe * 1.08) {
    totOiHtml = `
      <div style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 6px; background: rgba(16,185,129,0.18); border: 1px solid rgba(16,185,129,0.5); color: #34d399; font-weight: 800; font-size: 11px;">
        🟢 PUT HEAVY (+${netDiffLakhs}L)
      </div>
      <div style="font-size: 10px; color: #94a3b8; font-family: monospace; margin-top: 3px;">
        <span style="color: #f87171;">CE ${totCe.toFixed(1)}L</span> | <span style="color: #34d399; font-weight: 700;">PE ${totPe.toFixed(1)}L</span>
      </div>
    `;
  } else if (idx.tot_oi_bias === 'CE_DOMINANT' || totCe > totPe * 1.08) {
    totOiHtml = `
      <div style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 6px; background: rgba(239,68,68,0.18); border: 1px solid rgba(239,68,68,0.5); color: #f87171; font-weight: 800; font-size: 11px;">
        🔴 CALL HEAVY (-${netDiffLakhs}L)
      </div>
      <div style="font-size: 10px; color: #94a3b8; font-family: monospace; margin-top: 3px;">
        <span style="color: #f87171; font-weight: 700;">CE ${totCe.toFixed(1)}L</span> | <span style="color: #34d399;">PE ${totPe.toFixed(1)}L</span>
      </div>
    `;
  } else {
    totOiHtml = `
      <div style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 6px; background: rgba(234,179,8,0.18); border: 1px solid rgba(234,179,8,0.5); color: #fde047; font-weight: 800; font-size: 11px;">
        🟡 BALANCED (±${netDiffLakhs}L)
      </div>
      <div style="font-size: 10px; color: #cbd5e1; font-family: monospace; margin-top: 3px;">
        CE ${totCe.toFixed(1)}L | PE ${totPe.toFixed(1)}L
      </div>
    `;
  }

  // 2. Change in OI Intraday Flow
  let oiChgHtml = '';
  const peChg = idx.pe_oi_change_k || 0;
  const ceChg = idx.ce_oi_change_k || 0;
  if (idx.oi_bias === 'PUT_SUPPORT') {
    oiChgHtml = `
      <div style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 6px; background: rgba(16,185,129,0.18); border: 1px solid rgba(16,185,129,0.5); color: #34d399; font-weight: 800; font-size: 10.5px;">
        🟢 PUT SUPPORT (+${peChg}k)
      </div>
      <div style="font-size: 10px; color: #94a3b8; font-family: monospace; margin-top: 3px;">
        CE ${ceChg >= 0 ? '+' : ''}${ceChg}k | PE +${peChg}k
      </div>
    `;
  } else if (idx.oi_bias === 'CALL_RESISTANCE') {
    oiChgHtml = `
      <div style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 6px; background: rgba(239,68,68,0.18); border: 1px solid rgba(239,68,68,0.5); color: #f87171; font-weight: 800; font-size: 10.5px;">
        🔴 CALL RESIST (+${ceChg}k)
      </div>
      <div style="font-size: 10px; color: #94a3b8; font-family: monospace; margin-top: 3px;">
        CE +${ceChg}k | PE ${peChg >= 0 ? '+' : ''}${peChg}k
      </div>
    `;
  } else {
    oiChgHtml = `
      <div style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 6px; background: rgba(234,179,8,0.18); border: 1px solid rgba(234,179,8,0.5); color: #fde047; font-weight: 800; font-size: 10.5px;">
        🟡 BALANCED FLOW
      </div>
      <div style="font-size: 10px; color: #cbd5e1; font-family: monospace; margin-top: 3px;">
        CE ${ceChg >= 0 ? '+' : ''}${ceChg}k | PE ${peChg >= 0 ? '+' : ''}${peChg}k
      </div>
    `;
  }

  // 3. Key Walls & Max Pain
  const sup = idx.key_support ? Math.round(idx.key_support).toLocaleString('en-IN') : (idx.put_floor ? Math.round(idx.put_floor).toLocaleString('en-IN') : '—');
  const res = idx.key_resistance ? Math.round(idx.key_resistance).toLocaleString('en-IN') : (idx.call_ceiling ? Math.round(idx.call_ceiling).toLocaleString('en-IN') : '—');
  const maxPain = idx.max_pain ? Math.round(idx.max_pain).toLocaleString('en-IN') : '—';

  const wallsHtml = `
    <div style="font-family: monospace; font-size: 11.5px; font-weight: 700;">
      <span style="color: #34d399;" title="Put Support Wall">S: ${sup}</span>
      <span style="color: #64748b; margin: 0 4px;">|</span>
      <span style="color: #f87171;" title="Call Resistance Wall">R: ${res}</span>
    </div>
    <div style="font-size: 10px; color: #c4b5fd; font-family: monospace; margin-top: 2px;">
      Max Pain: <span style="font-weight: 700; color: #e9d5ff;">${maxPain}</span>
    </div>
  `;

  // 4. PCR & Sentiment
  const pcr = idx.pcr || 1.0;
  let pcrColor = '#eab308';
  let pcrTag = 'NEUTRAL';
  let pcrTagColor = '#fde047';

  if (pcr >= 1.20) {
    pcrColor = '#10b981';
    pcrTag = 'BULLISH';
    pcrTagColor = '#34d399';
  } else if (pcr <= 0.80) {
    pcrColor = '#ef4444';
    pcrTag = 'BEARISH';
    pcrTagColor = '#f87171';
  }

  const pcrHtml = `
    <div style="font-weight: 800; font-family: monospace; font-size: 13px; color: ${pcrColor};">
      ${pcr.toFixed(2)}
    </div>
    <div style="font-size: 9.5px; font-weight: 800; color: ${pcrTagColor}; margin-top: 2px;">
      ${pcrTag}
    </div>
  `;

  // 5. Confluence Score & Progress Meter
  const conf = idx.confluence_score || 50;
  const confColor = conf >= 65 ? '#10b981' : (conf <= 35 ? '#ef4444' : '#38bdf8');
  const confBarColor = conf >= 65 ? 'linear-gradient(90deg, #059669, #10b981)' : (conf <= 35 ? 'linear-gradient(90deg, #dc2626, #ef4444)' : 'linear-gradient(90deg, #0284c7, #38bdf8)');

  let cleanRegime = (idx.market_regime || 'RANGE-BOUND')
    .replace(/CONFLUENCE|REGIME/gi, '')
    .replace(/\/ TWO-SIDED/gi, '')
    .trim();
  if (!cleanRegime) cleanRegime = 'BALANCED';

  const confHtml = `
    <div style="font-weight: 800; font-size: 13.5px; color: ${confColor}; font-family: monospace;">
      ${conf.toFixed(1)} <span style="font-size: 9.5px; color: #64748b; font-weight: 600;">/ 100</span>
    </div>
    <div style="width: 70px; height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; margin: 4px auto 3px; overflow: hidden;">
      <div style="width: ${Math.min(100, Math.max(5, conf))}%; height: 100%; background: ${confBarColor}; border-radius: 2px;"></div>
    </div>
    <div style="font-size: 9.5px; color: #94a3b8; font-weight: 700; letter-spacing: 0.3px; white-space: nowrap;">
      ${cleanRegime}
    </div>
  `;

  // 6. Action Directive
  let actionHtml = '';
  if (idx.action === 'BUY_CALL') {
    actionHtml = `<span class="badge" style="background: #10b981; color: #ffffff; font-weight: 800; font-size: 11px; padding: 4px 9px; border-radius: 6px; box-shadow: 0 0 10px rgba(16,185,129,0.35);">BUY CE</span>`;
  } else if (idx.action === 'BUY_PUT') {
    actionHtml = `<span class="badge" style="background: #ef4444; color: #ffffff; font-weight: 800; font-size: 11px; padding: 4px 9px; border-radius: 6px; box-shadow: 0 0 10px rgba(239,68,68,0.35);">BUY PE</span>`;
  } else {
    actionHtml = `<span class="badge" style="background: #334155; color: #94a3b8; font-weight: 700; font-size: 10px; padding: 4px 9px; border-radius: 6px;">STANDBY</span>`;
  }

  return `
    <tr class="radar-row ${isSelected ? 'active-index-row' : ''}" data-sym="${idx.symbol}" style="cursor: pointer; transition: all 0.2s ease; background: ${isSelected ? 'rgba(56, 189, 248, 0.12)' : 'transparent'}; border-bottom: 1px solid rgba(255,255,255,0.06); outline: ${isSelected ? '1px solid rgba(56, 189, 248, 0.4)' : 'none'};">
      <td class="radar-sticky-col" style="padding: 10px 12px; text-align: left; min-width: 140px; width: 140px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="badge" style="background: ${isSelected ? '#38bdf8' : '#1e293b'}; color: ${isSelected ? '#0f172a' : '#f1f5f9'}; font-weight: 800; font-size: 11px; padding: 3px 7px; border-radius: 5px;">
            ${idx.symbol}
          </span>
          <span style="font-weight: 700; font-size: 11.5px; color: #cbd5e1;">${idx.name}</span>
        </div>
      </td>
      <td style="padding: 10px 12px; font-family: monospace; font-size: 12.5px;">
        <div style="font-weight: 800; color: #f8fafc;">${(idx.spot_price || 0).toLocaleString('en-IN', {minimumFractionDigits: 1, maximumFractionDigits: 1})}</div>
        <div style="color: ${pchangeColor}; font-size: 11px; font-weight: 700;">${pchangeArrow} ${pchangeSign}${pchange.toFixed(2)}%</div>
      </td>
      <td style="padding: 10px 12px;">${totOiHtml}</td>
      <td style="padding: 10px 12px;">${oiChgHtml}</td>
      <td style="padding: 10px 12px;">${wallsHtml}</td>
      <td style="padding: 10px 12px;">${pcrHtml}</td>
      <td style="padding: 10px 10px;">${_renderSignalArrow(idx.alphatrend, 'AlphaTrend')}</td>
      <td style="padding: 10px 10px;">${_renderSignalArrow(idx.trend_direction, 'Trend Direction')}</td>
      <td style="padding: 10px 10px;">${_renderSignalArrow(idx.hull_state, 'Hull Suite')}</td>
      <td style="padding: 10px 10px;">${_renderSignalArrow(idx.breakout_tracker || idx.brk_state, 'Breakout Tracker')}</td>
      <td style="padding: 10px 12px;">${confHtml}</td>
      <td style="padding: 10px 12px;">${actionHtml}</td>
    </tr>
  `;
}

async function _renderMultiIndexRadar(container) {
  const mount = container.querySelector('#multi-index-radar-mount');
  if (!mount) return;

  try {
    let indices = [];
    let timeStr = new Date().toLocaleTimeString();
    let regimeBadge = 'REAL-TIME SYNC';
    let regimeBadgeStyle = 'background: rgba(139, 92, 246, 0.2); color: #c4b5fd; border: 1px solid rgba(139, 92, 246, 0.4);';

    // ─────────────────────────────────────────────────────────
    // A. REPLAY MODE
    // ─────────────────────────────────────────────────────────
    if (isRadarReplayMode && !store.isReplayActive()) {
      if (!radarReplayData) {
        mount.innerHTML = `<div style="padding: 24px; text-align: center; color: #c4b5fd; font-weight: 700;">⏳ Loading historical session timeline...</div>`;
        radarReplayData = await ApiClient.fetchRadarReplay();
        if (radarReplayData?.timeline_steps?.length) {
          radarReplayIdx = radarReplayData.timeline_steps.length - 1;
        }
      }

      if (!radarReplayData || !radarReplayData.timeline_steps || radarReplayData.timeline_steps.length === 0) {
        mount.innerHTML = `<div style="padding: 24px; text-align: center; color: #f87171;">⚠️ No historical timeline available for this session.</div>`;
        return;
      }

      const totalSteps = radarReplayData.timeline_steps.length;
      if (radarReplayIdx >= totalSteps) radarReplayIdx = totalSteps - 1;
      if (radarReplayIdx < 0) radarReplayIdx = 0;

      const currentStep = radarReplayData.timeline_steps[radarReplayIdx];
      indices = currentStep.indices || [];
      timeStr = `${currentStep.time} IST`;

      const reg = currentStep.regime || 'NEUTRAL';
      if (reg.includes('BULLISH')) {
        regimeBadge = `🟢 ${reg.replace(/_/g, ' ')}`;
        regimeBadgeStyle = 'background: rgba(16,185,129,0.25); color: #34d399; border: 1px solid rgba(16,185,129,0.5);';
      } else if (reg.includes('BEARISH')) {
        regimeBadge = `🔴 ${reg.replace(/_/g, ' ')}`;
        regimeBadgeStyle = 'background: rgba(239,68,68,0.25); color: #f87171; border: 1px solid rgba(239,68,68,0.5);';
      } else if (reg.includes('DIVERGENCE')) {
        regimeBadge = `⚠️ DIVERGENCE CHOP`;
        regimeBadgeStyle = 'background: rgba(234,179,8,0.25); color: #fde047; border: 1px solid rgba(234,179,8,0.5);';
      } else {
        regimeBadge = `⚪ STANDBY / NEUTRAL`;
        regimeBadgeStyle = 'background: rgba(148,163,184,0.2); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.4);';
      }

      const rStats = radarReplayData.ribbon_stats || { bullish_pct: 0, bearish_pct: 0, chop_pct: 100 };
      const dateOptions = (radarReplayData.available_dates || [radarReplayData.selected_date]).map(d => `
        <option value="${d}" ${d === radarReplayData.selected_date ? 'selected' : ''}>Session: ${d}</option>
      `).join('');

      mount.innerHTML = `
        <div class="glass-panel" style="padding: 16px; border: 1px solid rgba(139, 92, 246, 0.45); border-radius: 12px; background: linear-gradient(135deg, rgba(17, 24, 39, 0.98) 0%, rgba(10, 15, 30, 0.99) 100%); box-shadow: 0 10px 30px rgba(0,0,0,0.65);">
          
          <!-- Header Bar: Title + Mode Switcher -->
          <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 22px;">🌐</span>
              <div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <h3 style="margin: 0; font-size: 14px; font-weight: 800; letter-spacing: 0.5px; color: #f8fafc;">
                    MULTI-INDEX INSTITUTIONAL COMMAND RADAR (CROSS-ASSET CONFLUENCE)
                  </h3>
                  <span class="badge" style="${regimeBadgeStyle} font-size: 10px; font-weight: 800; padding: 3px 8px; border-radius: 9999px;">
                    ${regimeBadge}
                  </span>
                </div>
                <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">
                  Visual Whole-Day Replay &amp; Intraday Audit: Scrub minute-by-minute or play back historical sessions!
                </div>
              </div>
            </div>

            <!-- Mode Switcher -->
            <div style="display: flex; align-items: center; gap: 8px;">
              <button id="radar-push-test-btn" title="Send a test notification to your phone (topic: mybull_radar_alerts_2026)" style="padding: 4px 10px; font-size: 10.5px; font-weight: 700; border-radius: 6px; border: 1px solid rgba(56, 189, 248, 0.4); background: rgba(56, 189, 248, 0.15); color: #38bdf8; cursor: pointer;">
                📱 Test Phone Alert
              </button>
              <div style="display: flex; align-items: center; gap: 6px; background: rgba(0,0,0,0.5); padding: 3px 5px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1);">
                <button id="radar-mode-live-btn" style="padding: 4px 10px; font-size: 10.5px; font-weight: 700; border-radius: 5px; border: none; cursor: pointer; background: transparent; color: #94a3b8;">
                  ● LIVE SYNC
                </button>
                <button id="radar-mode-replay-btn" style="padding: 4px 10px; font-size: 10.5px; font-weight: 800; border-radius: 5px; border: none; cursor: pointer; background: #8b5cf6; color: #ffffff; box-shadow: 0 0 10px rgba(139,92,246,0.5);">
                  ▶ WHOLE-DAY REPLAY
                </button>
              </div>
            </div>
          </div>

          <!-- REPLAY TOOLBAR & TIMELINE SCRUBBER -->
          <div style="background: rgba(0,0,0,0.45); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 10px; padding: 12px 14px; margin-bottom: 14px;">
            <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 10px;">
              
              <!-- Left: Date Selector + Play Button -->
              <div style="display: flex; align-items: center; gap: 8px;">
                <select id="radar-replay-date-select" style="background: #1e293b; color: #f8fafc; border: 1px solid #475569; border-radius: 6px; padding: 5px 10px; font-size: 11.5px; font-weight: 700; outline: none; cursor: pointer;">
                  ${dateOptions}
                </select>

                <button id="radar-replay-play-btn" style="background: ${radarPlayInterval ? '#ef4444' : '#8b5cf6'}; color: #ffffff; border: none; border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 800; cursor: pointer; display: flex; align-items: center; gap: 5px;">
                  ${radarPlayInterval ? '⏸ PAUSE' : '▶ PLAY'}
                </button>
              </div>

              <!-- Center: Scrub Time Display -->
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 11px; color: #94a3b8; font-weight: 700;">SCRUB TIME:</span>
                <span style="font-family: monospace; font-size: 14px; font-weight: 900; color: #38bdf8; background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.4); padding: 3px 10px; border-radius: 6px;">
                  🕒 ${currentStep.time} IST
                </span>
                <span style="font-size: 10px; color: #64748b; font-family: monospace;">(${radarReplayIdx + 1}/${totalSteps} min)</span>
              </div>

              <!-- Right: Quick Jump Buttons -->
              <div style="display: flex; align-items: center; gap: 4px;">
                <span style="font-size: 10px; color: #64748b; font-weight: 700; margin-right: 2px;">JUMP:</span>
                ${['09:30', '11:00', '12:30', '14:00', '15:15'].map(t => `
                  <button class="radar-jump-btn" data-time="${t}" style="background: #1e293b; color: #cbd5e1; border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; padding: 3px 7px; font-size: 10px; font-family: monospace; cursor: pointer;">
                    ${t}
                  </button>
                `).join('')}
              </div>
            </div>

            <!-- Range Scrubber Slider -->
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 10px; font-family: monospace; color: #64748b;">09:15</span>
              <input type="range" id="radar-replay-slider" min="0" max="${totalSteps - 1}" value="${radarReplayIdx}" style="flex: 1; accent-color: #8b5cf6; cursor: pointer; height: 6px;">
              <span style="font-size: 10px; font-family: monospace; color: #64748b;">15:30</span>
            </div>

            <!-- Health Ribbon Bar -->
            <div style="margin-top: 10px; display: flex; align-items: center; justify-content: space-between; font-size: 10.5px; color: #94a3b8; font-weight: 700;">
              <div>SESSION REGIME DISTRIBUTION:</div>
              <div style="display: flex; gap: 12px; font-family: monospace;">
                <span style="color: #34d399;">🟢 Bullish Unison: ${rStats.bullish_pct}%</span>
                <span style="color: #f87171;">🔴 Bearish Unison: ${rStats.bearish_pct}%</span>
                <span style="color: #fde047;">🟡 Divergence / Chop: ${rStats.chop_pct}%</span>
              </div>
            </div>
            <div style="height: 5px; width: 100%; border-radius: 3px; display: flex; overflow: hidden; margin-top: 5px; background: #334155;">
              <div style="width: ${rStats.bullish_pct}%; background: #10b981;" title="Bullish Unison: ${rStats.bullish_pct}%"></div>
              <div style="width: ${rStats.chop_pct}%; background: #eab308;" title="Divergence/Chop: ${rStats.chop_pct}%"></div>
              <div style="width: ${rStats.bearish_pct}%; background: #ef4444;" title="Bearish Unison: ${rStats.bearish_pct}%"></div>
            </div>
          </div>

          <!-- Indices Radar Table -->
          <div style="overflow-x: auto;">
            <table class="terminal-table" style="width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; text-align: center;">
              <thead>
                <tr style="background: rgba(0, 0, 0, 0.5); color: #94a3b8; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.5px;">
                  <th style="padding: 10px 12px; text-align: left; border-top-left-radius: 8px;">INDEX</th>
                  <th style="padding: 10px 12px;">SPOT & DAY %</th>
                  <th style="padding: 10px 12px;">TOTAL OI BIAS</th>
                  <th style="padding: 10px 12px;">OI FLOW (INTRADAY)</th>
                  <th style="padding: 10px 12px;">KEY WALLS & MAX PAIN</th>
                  <th style="padding: 10px 12px;">PCR & BIAS</th>
                  <th style="padding: 10px 10px;" title="AlphaTrend Momentum">ALPHATREND</th>
                  <th style="padding: 10px 10px;" title="Trend Direction">TREND DIR</th>
                  <th style="padding: 10px 10px;" title="Hull Suite Trend Filter">HULL SUITE</th>
                  <th style="padding: 10px 10px;" title="Breakout Tracker Confirmed Pivot Expansion">BREAKOUT</th>
                  <th style="padding: 10px 12px;">CONFLUENCE</th>
                  <th style="padding: 10px 12px; border-top-right-radius: 8px;">DIRECTIVE</th>
                </tr>
              </thead>
              <tbody>
                ${indices.map(idx => _buildRadarRowHtml(idx)).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `;

      // Attach Replay Event Listeners
      const slider = mount.querySelector('#radar-replay-slider');
      if (slider) {
        slider.addEventListener('input', (e) => {
          radarReplayIdx = parseInt(e.target.value, 10);
          _renderMultiIndexRadar(container);
        });
      }

      const dateSelect = mount.querySelector('#radar-replay-date-select');
      if (dateSelect) {
        dateSelect.addEventListener('change', async (e) => {
          const newDate = e.target.value;
          if (radarPlayInterval) { clearInterval(radarPlayInterval); radarPlayInterval = null; }
          mount.innerHTML = `<div style="padding: 24px; text-align: center; color: #c4b5fd;">⏳ Loading session ${newDate}...</div>`;
          radarReplayData = await ApiClient.fetchRadarReplay(newDate);
          radarReplayIdx = 0;
          _renderMultiIndexRadar(container);
        });
      }

      const playBtn = mount.querySelector('#radar-replay-play-btn');
      if (playBtn) {
        playBtn.addEventListener('click', () => {
          if (radarPlayInterval) {
            clearInterval(radarPlayInterval);
            radarPlayInterval = null;
            _renderMultiIndexRadar(container);
          } else {
            radarPlayInterval = setInterval(() => {
              if (!radarReplayData || !radarReplayData.timeline_steps) return;
              radarReplayIdx = (radarReplayIdx + 1) % radarReplayData.timeline_steps.length;
              _renderMultiIndexRadar(container);
            }, 1000);
            _renderMultiIndexRadar(container);
          }
        });
      }

      mount.querySelectorAll('.radar-jump-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const targetT = btn.getAttribute('data-time');
          if (radarReplayData?.timeline_steps) {
            let foundIdx = radarReplayData.timeline_steps.findIndex(s => s.time >= targetT);
            if (foundIdx === -1) foundIdx = radarReplayData.timeline_steps.length - 1;
            radarReplayIdx = foundIdx;
            _renderMultiIndexRadar(container);
          }
        });
      });

    } 
    // ─────────────────────────────────────────────────────────
    // B. LIVE OR MASTER REPLAY SYNC MODE
    // ─────────────────────────────────────────────────────────
    else {
      const state = store.getState();
      if (store.isReplayActive() && state?.replay?.snapshot?.multi_index_radar) {
        indices = state.replay.snapshot.multi_index_radar;
        timeStr = `${state.replay.selectedTime} IST`;
        const reg = state.replay.snapshot.market_regime || 'NEUTRAL';
        regimeBadge = `⏰ REPLAY: ${state.replay.selectedDate} ${state.replay.selectedTime} (${reg})`;
        regimeBadgeStyle = 'background: rgba(139, 92, 246, 0.25); color: #c4b5fd; border: 1px solid rgba(139, 92, 246, 0.5);';
      } else {
        const res = await ApiClient.fetchMultiIndexRadar();
        if (!res || !res.indices || res.indices.length === 0) return;

        indices = res.indices;
        timeStr = res.timestamp || new Date().toLocaleTimeString();
      }

      const existingTbody = mount.querySelector('#radar-live-tbody');
      const existingScrollWrapper = mount.querySelector('#radar-live-scroll-wrapper');
      const timeBadgeEl = mount.querySelector('#radar-live-time-str');

      // If user is actively touching or dragging on mobile, skip DOM update to prevent gesture cancellation
      if (window._isUserTouchingRadar) return;

      // FLICKER-FREE & SCROLL-PRESERVING UPDATE:
      // If table already exists, update ONLY tbody rows without destroying the scroll wrapper!
      // This guarantees horizontal scroll position (Confluence, Directives) NEVER snaps back!
      if (existingTbody && existingScrollWrapper) {
        if (existingScrollWrapper.scrollLeft > 0) {
          window._radarScrollLeft = existingScrollWrapper.scrollLeft;
        }
        existingTbody.innerHTML = indices.map(idx => _buildRadarRowHtml(idx)).join('');
        if (timeBadgeEl) timeBadgeEl.textContent = `UPDATED: ${timeStr}`;
        if (window._radarScrollLeft > 0) {
          existingScrollWrapper.scrollLeft = window._radarScrollLeft;
        }
        _attachRadarRowClicks(mount, container);
        return;
      }

      mount.innerHTML = `
        <div class="glass-panel" style="padding: 16px; border: 1px solid rgba(139, 92, 246, 0.35); border-radius: 12px; background: linear-gradient(135deg, rgba(17, 24, 39, 0.95) 0%, rgba(10, 15, 30, 0.98) 100%); box-shadow: 0 10px 30px rgba(0,0,0,0.6);">
          <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 22px;">🌐</span>
              <div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <h3 style="margin: 0; font-size: 14px; font-weight: 800; letter-spacing: 0.5px; color: #f8fafc;">
                    MULTI-INDEX INSTITUTIONAL COMMAND RADAR (CROSS-ASSET CONFLUENCE)
                  </h3>
                  <span id="radar-regime-badge" class="badge" style="${regimeBadgeStyle} font-size: 9.5px; font-weight: 800; padding: 2px 7px; border-radius: 9999px;">
                    ${regimeBadge}
                  </span>
                </div>
                <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">
                  Instant cross-asset market view: Spot, Total OI, OI Flow, Key Walls & Max Pain, Indicator Arrows & Directives. Click any row to inspect!
                </div>
              </div>
            </div>

            <div style="display: flex; align-items: center; gap: 8px;">
              <button id="radar-push-test-btn" title="Send a test notification to your phone (topic: mybull_radar_alerts_2026)" style="padding: 4px 10px; font-size: 10.5px; font-weight: 700; border-radius: 6px; border: 1px solid rgba(56, 189, 248, 0.4); background: rgba(56, 189, 248, 0.15); color: #38bdf8; cursor: pointer;">
                📱 Test Phone Alert
              </button>

              <div id="radar-live-time-str" style="font-size: 11px; color: #64748b; font-family: monospace;">
                UPDATED: ${timeStr}
              </div>
            </div>
          </div>

          <div id="radar-live-scroll-wrapper" class="radar-scroll-wrapper" style="overflow-x: auto; -webkit-overflow-scrolling: touch; position: relative;">
            <table class="terminal-table" style="width: 100%; min-width: 1250px; border-collapse: separate; border-spacing: 0; font-size: 12px; text-align: center;">
              <thead>
                <tr style="background: rgba(0, 0, 0, 0.5); color: #94a3b8; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.5px;">
                  <th class="radar-sticky-col" style="padding: 10px 12px; text-align: left; border-top-left-radius: 8px; min-width: 140px; width: 140px;">INDEX</th>
                  <th style="padding: 10px 12px; min-width: 110px;">SPOT & DAY %</th>
                  <th style="padding: 10px 12px; min-width: 120px;">TOTAL OI BIAS</th>
                  <th style="padding: 10px 12px; min-width: 125px;">OI FLOW (INTRADAY)</th>
                  <th style="padding: 10px 12px; min-width: 135px;">KEY WALLS & MAX PAIN</th>
                  <th style="padding: 10px 12px; min-width: 95px;">PCR & BIAS</th>
                  <th style="padding: 10px 10px; min-width: 65px;" title="AlphaTrend Momentum">ALPHATREND</th>
                  <th style="padding: 10px 10px;" title="Trend Direction">TREND DIR</th>
                  <th style="padding: 10px 10px;" title="Hull Suite Trend Filter">HULL SUITE</th>
                  <th style="padding: 10px 10px;" title="Breakout Tracker Confirmed Pivot Expansion">BREAKOUT</th>
                  <th style="padding: 10px 12px; min-width: 120px;">CONFLUENCE</th>
                  <th style="padding: 10px 12px; border-top-right-radius: 8px; min-width: 135px;">DIRECTIVE</th>
                </tr>
              </thead>
              <tbody id="radar-live-tbody">
                ${indices.map(idx => _buildRadarRowHtml(idx)).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `;

      const newScroll = mount.querySelector('#radar-live-scroll-wrapper');
      if (newScroll) {
        newScroll.addEventListener('scroll', () => {
          window._radarScrollLeft = newScroll.scrollLeft;
        }, { passive: true });
        newScroll.addEventListener('touchstart', () => {
          window._isUserTouchingRadar = true;
        }, { passive: true });
        newScroll.addEventListener('touchend', () => {
          setTimeout(() => { window._isUserTouchingRadar = false; }, 800);
        }, { passive: true });
        newScroll.addEventListener('touchcancel', () => {
          setTimeout(() => { window._isUserTouchingRadar = false; }, 800);
        }, { passive: true });

        if (window._radarScrollLeft > 0) {
          newScroll.scrollLeft = window._radarScrollLeft;
        }
      }
    }

    // Attach Test Phone Alert Listener
    const testAlertBtn = mount.querySelector('#radar-push-test-btn');
    if (testAlertBtn) {
      testAlertBtn.addEventListener('click', async () => {
        testAlertBtn.textContent = '⏳ Sending...';
        try {
          const res = await ApiClient.triggerRadarPushTest();
          if (res && res.success) {
            testAlertBtn.textContent = '✅ Alert Sent!';
            setTimeout(() => { testAlertBtn.textContent = '📱 Test Phone Alert'; }, 3000);
          } else {
            testAlertBtn.textContent = '❌ Failed';
            setTimeout(() => { testAlertBtn.textContent = '📱 Test Phone Alert'; }, 3000);
          }
        } catch (e) {
          testAlertBtn.textContent = '❌ Error';
          setTimeout(() => { testAlertBtn.textContent = '📱 Test Phone Alert'; }, 3000);
        }
      });
    }



    // Attach row click listeners to switch active index below
    mount.querySelectorAll('.radar-row').forEach(rowEl => {
      rowEl.addEventListener('click', async () => {
        const sym = rowEl.getAttribute('data-sym');
        if (sym && sym !== currentSymbol) {
          currentSymbol = sym;
          container.querySelectorAll('.conf-sym-btn').forEach(b => {
            if (b.getAttribute('data-sym') === sym) b.classList.add('active');
            else b.classList.remove('active');
          });
          const data = await ApiClient.fetchOptionConfluence(currentSymbol, currentRange);
          if (data && data.success) {
            lastData = data;
            _renderSummary(container, data);
            _renderTable(container, data);
          }
          _renderMultiIndexRadar(container);
        }
      });
    });

  } catch (err) {
    console.debug('Multi-Index Radar render error:', err);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 1. SUMMARY PANEL RENDERING
// ─────────────────────────────────────────────────────────────────────────────
function _renderSummary(container, data) {
  const mount = container.querySelector('#confluence-summary-mount');
  if (!mount) return;

  const s = data.summary || {};
  const spot = data.spot_price || 0;
  const atm = data.atm_strike || 0;
  const score = s.confluence_score || 50;
  const bias = s.overall_bias || 'NEUTRAL';
  const biasCls = s.overall_bias_class || 'badge-neutral';
  const ind1 = s.indicator_1 || {};
  const ind2 = s.indicator_2 || {};
  const ind3 = s.indicator_3 || {};
  const ind4 = s.indicator_4 || {};

  const isBull = bias.includes('BULLISH');
  const isBear = bias.includes('BEARISH');
  const scoreColor = score >= 65 ? '#10b981' : (score <= 35 ? '#ef4444' : '#f59e0b');

  mount.innerHTML = `
    <div class="glass-panel" style="padding: 14px 18px; border: 1px solid rgba(255, 255, 255, 0.08); background: rgba(10, 15, 28, 0.75); border-radius: 10px;">
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; align-items: center;">
        
        <!-- Spot & ATM -->
        <div>
          <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
            ${data.symbol} UNDERLYING SPOT
          </div>
          <div style="display: flex; align-items: baseline; gap: 6px; margin-top: 2px;">
            <strong style="font-size: 18px; font-family: var(--font-mono); color: #f8fafc;">
              ₹${spot.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
            </strong>
            <span style="font-size: 11px; color: #38bdf8; font-weight: 800; font-family: var(--font-mono);">
              (ATM: ${atm})
            </span>
          </div>
          <div style="font-size: 10px; color: var(--text-muted); margin-top: 1px;">
            Step: ${data.strike_step} pts | Scope: ATM ± ${data.range}
          </div>
        </div>

        <!-- Overall Bias & Confluence Score -->
        <div>
          <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
            OVERALL CORRIDOR CONFLUENCE
          </div>
          <div style="display: flex; align-items: center; gap: 8px; margin-top: 4px;">
            <span class="badge ${biasCls}" style="font-size: 11px; font-weight: 800; padding: 3px 9px; border-radius: 5px;">
              ${bias}
            </span>
            <div style="display: flex; align-items: baseline; gap: 3px;">
              <strong style="font-size: 16px; font-family: var(--font-mono); color: ${scoreColor};">
                ${score}
              </strong>
              <span style="font-size: 10px; color: var(--text-muted); font-family: var(--font-mono);">/100</span>
            </div>
          </div>
          <div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">
            PCR: <strong style="color: ${s.corridor_pcr >= 1 ? '#10b981' : '#ef4444'};">${s.corridor_pcr || '1.0'}</strong> | Net ΔOI: <strong>${s.corridor_oi_chg_diff_formatted || '0'}</strong>
          </div>
        </div>

        <!-- Support & Resistance Anchors -->
        <div>
          <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
            KEY ANCHORS (ATM CORRIDOR)
          </div>
          <div style="font-size: 11.5px; margin-top: 3px; font-family: var(--font-mono);">
            <span style="color: #10b981; font-weight: 700;">🟢 Strong Support:</span>
            <strong style="color: #f8fafc;">₹${s.strong_support || '--'}</strong>
          </div>
          <div style="font-size: 11.5px; margin-top: 2px; font-family: var(--font-mono);">
            <span style="color: #ef4444; font-weight: 700;">🔴 Strong Resistance:</span>
            <strong style="color: #f8fafc;">₹${s.strong_resistance || '--'}</strong>
          </div>
        </div>

        <!-- Institutional Positioning -->
        <div>
          <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
            CE &amp; PE POSITIONING FLOW
          </div>
          <div style="font-size: 11px; color: #cbd5e1; margin-top: 3px; font-weight: 600;">
            CE: <span style="color: ${s.ce_positioning.includes('Unwinding') ? '#34d399' : '#f87171'};">${s.ce_positioning}</span>
          </div>
          <div style="font-size: 11px; color: #cbd5e1; margin-top: 2px; font-weight: 600;">
            PE: <span style="color: ${s.pe_positioning.includes('Writing') ? '#34d399' : '#f87171'};">${s.pe_positioning}</span>
          </div>
        </div>

        <!-- Contract Price Movement & Indicators (CE & PE) -->
        <div>
          <div style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">
            CONTRACT DIRECTION &amp; INDICATORS
          </div>
          <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px;">
            <span style="font-size: 10.5px; padding: 2px 7px; border-radius: 4px; font-weight: 800; font-family: var(--font-mono); ${ind1.ce_state === 'BULLISH' ? 'background: rgba(16,185,129,0.18); color: #34d399; border: 1px solid rgba(16,185,129,0.4);' : (ind1.ce_state === 'BEARISH' ? 'background: rgba(239,68,68,0.18); color: #f87171; border: 1px solid rgba(239,68,68,0.4);' : 'background: rgba(245,158,11,0.15); color: #f59e0b;')}">
              CE: ${ind1.ce_state || 'NEUTRAL'} (${ind1.ce_state === 'BULLISH' ? '▲ RISING' : (ind1.ce_state === 'BEARISH' ? '▼ DECAY' : 'HOLD')})
            </span>
            <span style="font-size: 10.5px; padding: 2px 7px; border-radius: 4px; font-weight: 800; font-family: var(--font-mono); ${ind1.pe_state === 'BULLISH' ? 'background: rgba(244,63,94,0.18); color: #fb7185; border: 1px solid rgba(244,63,94,0.4);' : (ind1.pe_state === 'BEARISH' ? 'background: rgba(16,185,129,0.18); color: #34d399; border: 1px solid rgba(16,185,129,0.4);' : 'background: rgba(245,158,11,0.15); color: #f59e0b;')}">
              PE: ${ind1.pe_state || 'NEUTRAL'} (${ind1.pe_state === 'BULLISH' ? '▲ RISING' : (ind1.pe_state === 'BEARISH' ? '▼ DECAY' : 'HOLD')})
            </span>
          </div>
          <div style="font-size: 9.5px; color: var(--text-muted); margin-top: 3px;">
            Gravity: <strong>${ind3.state || 'NEUTRAL'}</strong> | Corridor Px: <strong>${ind4.per ? ind4.per.toFixed(0) + '%' : '50%'}</strong>
          </div>
        </div>

      </div>
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────────────────────
// 1.5. DEDICATED 6-PILLAR QUANTITATIVE & PINESCRIPT INDICATORS MATRIX
// ─────────────────────────────────────────────────────────────────────────────
function _renderIndicatorsSection(container, data) {
  const mount = container.querySelector('#confluence-indicators-mount');
  if (!mount) return;

  const s = data.summary || {};
  const ind1 = s.indicator_1 || (s.indicators && s.indicators.ind1) || {};
  const ind2 = s.indicator_2 || (s.indicators && s.indicators.ind2) || {};
  const ind3 = s.indicator_3 || (s.indicators && s.indicators.ind3) || {};
  const ind4 = s.indicator_4 || (s.indicators && s.indicators.ind4) || {};
  const ind5 = s.indicator_5 || (s.indicators && s.indicators.ind5) || {};
  const ind6 = s.indicator_6 || s.indicator_breakout || (s.indicators && (s.indicators.ind6 || s.indicators.ind_brk)) || {};

  const spot = data.spot_price || 0;
  const atm = data.atm_strike || 0;

  // 1. AlphaTrend (ATR 1.0)
  const atState = (ind1.state || 'NEUTRAL').toUpperCase();
  const atVal = ind1.value ? Number(ind1.value).toFixed(1) : (spot ? spot.toFixed(1) : '—');
  const atDiff = spot && ind1.value ? (spot - Number(ind1.value)) : 0;
  const isAtBull = atState === 'BULLISH' || atDiff > 0;
  const isAtBear = atState === 'BEARISH' || atDiff < 0;
  const atPillCls = isAtBull ? 'pill-bull' : (isAtBear ? 'pill-bear' : 'pill-neut');
  const atBadgeText = isAtBull ? '▲ BULLISH (CALL ADVANTAGED)' : (isAtBear ? '▼ BEARISH (PUT ADVANTAGED)' : '● PIVOT / NEUTRAL');

  // 2. TrendDirection (Logistic Momentum & Velocity)
  const tdState = (ind2.state || 'NEUTRAL').toUpperCase();
  const tdStrength = ind2.strength !== undefined ? Number(ind2.strength) : 0.0;
  const tdDesc = ind2.desc || (tdStrength >= 0.2 ? 'Strong Acceleration' : (tdStrength <= -0.2 ? 'Downside Force' : 'Consolidation'));
  const isTdBull = tdStrength > 0.05 || tdState.includes('BULL');
  const isTdBear = tdStrength < -0.05 || tdState.includes('BEAR');
  const tdPillCls = isTdBull ? 'pill-bull' : (isTdBear ? 'pill-bear' : 'pill-neut');
  const tdSign = tdStrength > 0 ? '+' : '';

  // 3. Hull Suite (EHMA 34x2)
  const hullState = (ind5.state || 'NEUTRAL').toUpperCase();
  const hullVal = ind5.value ? Number(ind5.value).toFixed(1) : '—';
  const isHullBull = hullState === 'BULLISH' || hullState === 'GREEN';
  const isHullBear = hullState === 'BEARISH' || hullState === 'RED';
  const hullPillCls = isHullBull ? 'pill-bull' : (isHullBear ? 'pill-bear' : 'pill-neut');
  const hullBadgeText = isHullBull ? '🟢 GREEN (UPWARD ACCEL)' : (isHullBear ? '🔴 RED (DOWNWARD SLOPE)' : '🟡 BALANCED EHMA');

  // 4. Shonya Gravity Center
  const shonyaState = (ind3.state || 'NEUTRAL').toUpperCase();
  const shonyaBasis = ind3.basis ? `₹${Number(ind3.basis).toFixed(1)}` : `ATM (₹${atm})`;
  const isShonyaAt = shonyaState.includes('AT') || shonyaState === 'NEUTRAL';
  const isShonyaAbove = shonyaState.includes('ABOVE');
  const isShonyaBelow = shonyaState.includes('BELOW');
  const shonyaPillCls = isShonyaAbove ? 'pill-bull' : (isShonyaBelow ? 'pill-bear' : 'pill-cyan');

  // 5. Proximity MAPO & Wall Range
  const proxPer = ind4.per !== undefined ? Number(ind4.per) : 50;
  const proxState = (ind4.state || 'NEUTRAL').toUpperCase();
  const proxZone = proxPer >= 65 ? 'Near Resistance Ceiling' : (proxPer <= 35 ? 'Near Support Floor' : 'Mid-Corridor Equilibrium');
  const proxPillCls = proxPer >= 65 ? 'pill-warn' : (proxPer <= 35 ? 'pill-cyan' : 'pill-neut');

  // 6. Breakout Tracker (Confirmed ATR Pivots & Dynamic Trailing Bands)
  const brkState = (ind6.state || 'FLAT').toUpperCase();
  const brkBias = (ind6.bias || 'NEUTRAL').toUpperCase();
  const brkSig = (ind6.signal || 'HOLD').toUpperCase();
  const brkLvl = ind6.breakout_level !== undefined && ind6.breakout_level !== null ? Number(ind6.breakout_level).toFixed(1) : null;
  const brkFail = ind6.fail_level !== undefined && ind6.fail_level !== null ? Number(ind6.fail_level).toFixed(1) : null;
  const brkTrail = ind6.trail_level !== undefined && ind6.trail_level !== null ? Number(ind6.trail_level).toFixed(1) : null;
  const brkPnl = ind6.open_pnl_atr !== undefined && ind6.open_pnl_atr !== null ? Number(ind6.open_pnl_atr) : 0.0;
  const brkRes = ind6.res_level !== undefined && ind6.res_level !== null ? Number(ind6.res_level).toFixed(1) : null;
  const brkSup = ind6.sup_level !== undefined && ind6.sup_level !== null ? Number(ind6.sup_level).toFixed(1) : null;

  const isBrkBull = brkState === 'LONG' || brkBias === 'BULLISH';
  const isBrkBear = brkState === 'SHORT' || brkBias === 'BEARISH';
  const brkPillCls = isBrkBull ? 'pill-bull' : (isBrkBear ? 'pill-bear' : 'pill-neut');
  const brkBadgeText = isBrkBull 
    ? (brkSig === 'BUY' ? '🚀 BUY BREAKOUT (EXPANDING)' : '🟢 LONG ACTIVE (ABOVE RES)') 
    : (isBrkBear 
      ? (brkSig === 'SELL' ? '💥 SELL BREAKDOWN (EXPANDING)' : '🔴 SHORT ACTIVE (UNDER SUP)') 
      : '⏸️ RANGE CONSOLIDATION');

  // Overall Consensus Calculation
  const consensus = s.consensus || {};
  let bullVotes = consensus.bull_votes !== undefined ? consensus.bull_votes : (isAtBull ? 1 : 0) + (isTdBull ? 1 : 0) + (isHullBull ? 1 : 0) + (isShonyaAbove ? 1 : 0) + (proxState.includes('BULL') ? 1 : 0) + (isBrkBull ? 1 : 0);
  let bearVotes = consensus.bear_votes !== undefined ? consensus.bear_votes : (isAtBear ? 1 : 0) + (isTdBear ? 1 : 0) + (isHullBear ? 1 : 0) + (isShonyaBelow ? 1 : 0) + (proxState.includes('BEAR') ? 1 : 0) + (isBrkBear ? 1 : 0);

  let consensusBadgeHtml = '';
  if (bullVotes >= 4) {
    consensusBadgeHtml = `
      <div style="display: flex; align-items: center; gap: 8px; background: rgba(16,185,129,0.18); border: 1px solid rgba(16,185,129,0.5); padding: 6px 12px; border-radius: 8px; box-shadow: 0 0 15px rgba(16,185,129,0.25);">
        <span style="font-size: 16px;">🟢</span>
        <div>
          <div style="font-size: 11px; font-weight: 800; color: #34d399; font-family: var(--font-mono);">
            ${bullVotes}/6 BULLISH CONSENSUS
          </div>
          <div style="font-size: 9.5px; color: #cbd5e1;">High probability upside momentum confirmation</div>
        </div>
      </div>
    `;
  } else if (bearVotes >= 4) {
    consensusBadgeHtml = `
      <div style="display: flex; align-items: center; gap: 8px; background: rgba(239,68,68,0.18); border: 1px solid rgba(239,68,68,0.5); padding: 6px 12px; border-radius: 8px; box-shadow: 0 0 15px rgba(239,68,68,0.25);">
        <span style="font-size: 16px;">🔴</span>
        <div>
          <div style="font-size: 11px; font-weight: 800; color: #fb7185; font-family: var(--font-mono);">
            ${bearVotes}/6 BEARISH CONSENSUS
          </div>
          <div style="font-size: 9.5px; color: #cbd5e1;">High probability downside expansion confirmation</div>
        </div>
      </div>
    `;
  } else {
    consensusBadgeHtml = `
      <div style="display: flex; align-items: center; gap: 8px; background: rgba(234,179,8,0.18); border: 1px solid rgba(234,179,8,0.5); padding: 6px 12px; border-radius: 8px; box-shadow: 0 0 15px rgba(234,179,8,0.2);">
        <span style="font-size: 16px;">🟡</span>
        <div>
          <div style="font-size: 11px; font-weight: 800; color: #fde047; font-family: var(--font-mono);">
            CONVERGENCE / RANGE CHOP (${bullVotes}B / ${bearVotes}S)
          </div>
          <div style="font-size: 9.5px; color: #cbd5e1;">Awaiting breakout expansion from corridor</div>
        </div>
      </div>
    `;
  }

  // Find ATM strike for contract-level check
  const atmRow = (data.strikes || []).find(r => r.is_atm) || (data.strikes || [])[0] || {};
  const ceAtm = atmRow.CE || {};
  const peAtm = atmRow.PE || {};

  mount.innerHTML = `
    <div class="glass-panel" style="padding: 16px; border: 1px solid rgba(56, 189, 248, 0.28); border-radius: 12px; background: linear-gradient(180deg, rgba(12, 19, 35, 0.95) 0%, rgba(8, 12, 24, 0.98) 100%); box-shadow: 0 8px 28px rgba(0,0,0,0.45);">
      
      <!-- Top Title Bar -->
      <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid rgba(255, 255, 255, 0.08);">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-size: 24px;">📊</span>
          <div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <h3 style="margin: 0; font-size: 14px; font-weight: 800; color: #f8fafc; letter-spacing: 0.5px;">
                6-PILLAR QUANTITATIVE &amp; PINESCRIPT INDICATORS MATRIX
              </h3>
              <span class="badge" style="background: rgba(56,189,248,0.18); color: #38bdf8; border: 1px solid rgba(56,189,248,0.4); font-size: 10px; padding: 2px 7px;">
                ${data.symbol} SPOT &amp; ATM
              </span>
            </div>
            <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">
              Continuous multi-session indicators: <strong>AlphaTrend (ATR 1.0)</strong>, <strong>TrendDirection</strong>, <strong>Hull Suite (EHMA)</strong>, <strong>Shonya Gravity</strong>, <strong>Proximity MAPO</strong> &amp; <strong>Breakout Tracker (BRK-TRK)</strong>
            </div>
          </div>
        </div>

        <div>
          ${consensusBadgeHtml}
        </div>
      </div>

      <!-- 6 Indicator Pillar Cards Grid -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 12px; margin-bottom: 14px;">
        
        <!-- 1. AlphaTrend -->
        <div class="indicator-pillar-card" style="border-top: 3px solid ${isAtBull ? '#10b981' : (isAtBear ? '#ef4444' : '#f59e0b')};">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="font-size: 10px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">INDICATOR 1</div>
              <strong style="font-size: 12.5px; color: #f8fafc;">AlphaTrend (5M)</strong>
            </div>
            <span class="indicator-mini-pill ${atPillCls}">${atState}</span>
          </div>
          <div style="margin: 8px 0;">
            <div style="font-size: 11px; font-weight: 800; color: ${isAtBull ? '#34d399' : (isAtBear ? '#fb7185' : '#fde047')};">
              ${atBadgeText}
            </div>
            <div style="font-size: 10px; color: #94a3b8; font-family: var(--font-mono); margin-top: 3px;">
              Band Level: <strong style="color: #f8fafc;">₹${atVal}</strong> (${atDiff >= 0 ? '+' : ''}${atDiff.toFixed(1)} pts)
            </div>
          </div>
          <div style="font-size: 9.5px; color: #64748b; line-height: 1.2;">
            Dynamic ATR trailing momentum stop
          </div>
        </div>

        <!-- 2. TrendDirection -->
        <div class="indicator-pillar-card" style="border-top: 3px solid ${isTdBull ? '#10b981' : (isTdBear ? '#ef4444' : '#38bdf8')};">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="font-size: 10px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">INDICATOR 2</div>
              <strong style="font-size: 12.5px; color: #f8fafc;">Trend Direction</strong>
            </div>
            <span class="indicator-mini-pill ${tdPillCls}">${tdSign}${tdStrength.toFixed(2)}</span>
          </div>
          <div style="margin: 8px 0;">
            <div style="font-size: 11px; font-weight: 800; color: ${isTdBull ? '#34d399' : (isTdBear ? '#fb7185' : '#94a3b8')};">
              ${tdDesc}
            </div>
            <div style="width: 100%; height: 5px; background: rgba(255,255,255,0.08); border-radius: 3px; margin-top: 6px; overflow: hidden; position: relative;">
              <div style="position: absolute; left: 50%; width: ${Math.min(50, Math.abs(tdStrength) * 50)}%; height: 100%; background: ${tdStrength >= 0 ? '#10b981' : '#ef4444'}; transform: ${tdStrength < 0 ? 'translateX(-100%)' : 'none'}; border-radius: 3px;"></div>
            </div>
          </div>
          <div style="font-size: 9.5px; color: #64748b; line-height: 1.2;">
            Normalized logistic momentum rate-of-change
          </div>
        </div>

        <!-- 3. Hull Suite -->
        <div class="indicator-pillar-card" style="border-top: 3px solid ${isHullBull ? '#10b981' : (isHullBear ? '#ef4444' : '#eab308')};">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="font-size: 10px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">INDICATOR 3</div>
              <strong style="font-size: 12.5px; color: #f8fafc;">Hull Suite (EHMA)</strong>
            </div>
            <span class="indicator-mini-pill ${hullPillCls}">${hullState}</span>
          </div>
          <div style="margin: 8px 0;">
            <div style="font-size: 11px; font-weight: 800; color: ${isHullBull ? '#34d399' : (isHullBear ? '#fb7185' : '#fde047')};">
              ${hullBadgeText}
            </div>
            <div style="font-size: 10px; color: #94a3b8; font-family: var(--font-mono); margin-top: 3px;">
              EHMA Axis: <strong style="color: #f8fafc;">₹${hullVal}</strong>
            </div>
          </div>
          <div style="font-size: 9.5px; color: #64748b; line-height: 1.2;">
            Zero-lag exponential Hull curve smoothing
          </div>
        </div>

        <!-- 4. Shonya Gravity -->
        <div class="indicator-pillar-card" style="border-top: 3px solid #38bdf8;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="font-size: 10px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">INDICATOR 4</div>
              <strong style="font-size: 12.5px; color: #f8fafc;">Shonya Gravity</strong>
            </div>
            <span class="indicator-mini-pill ${shonyaPillCls}">${shonyaState}</span>
          </div>
          <div style="margin: 8px 0;">
            <div style="font-size: 11px; font-weight: 800; color: #38bdf8;">
              ${isShonyaAt ? '⚖️ AT EQUILIBRIUM' : (isShonyaAbove ? '▲ EXPANSION OVER GRAV' : '▼ COMPRESSION UNDER GRAV')}
            </div>
            <div style="font-size: 10px; color: #94a3b8; font-family: var(--font-mono); margin-top: 3px;">
              Gravity Anchor: <strong style="color: #f8fafc;">${shonyaBasis}</strong>
            </div>
          </div>
          <div style="font-size: 9.5px; color: #64748b; line-height: 1.2;">
            Mean-reversion zero-point gravitational balance
          </div>
        </div>

        <!-- 5. Proximity MAPO -->
        <div class="indicator-pillar-card" style="border-top: 3px solid ${proxPillCls.includes('warn') ? '#f59e0b' : '#38bdf8'};">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="font-size: 10px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">INDICATOR 5</div>
              <strong style="font-size: 12.5px; color: #f8fafc;">Proximity MAPO</strong>
            </div>
            <span class="indicator-mini-pill ${proxPillCls}">${proxPer.toFixed(0)}%</span>
          </div>
          <div style="margin: 8px 0;">
            <div style="font-size: 11px; font-weight: 800; color: #cbd5e1;">
              ${proxZone}
            </div>
            <div style="width: 100%; height: 5px; background: rgba(255,255,255,0.08); border-radius: 3px; margin-top: 6px; overflow: hidden;">
              <div style="width: ${Math.min(100, Math.max(0, proxPer))}%; height: 100%; background: ${proxPer >= 65 ? '#f59e0b' : (proxPer <= 35 ? '#38bdf8' : '#10b981')}; border-radius: 3px;"></div>
            </div>
          </div>
          <div style="font-size: 9.5px; color: #64748b; line-height: 1.2;">
            Moving Average Proximity Oscillator vs bounds
          </div>
        </div>

        <!-- 6. Breakout Tracker (BRK-TRK) -->
        <div class="indicator-pillar-card" style="border-top: 3px solid ${isBrkBull ? '#10b981' : (isBrkBear ? '#ef4444' : '#a855f7')};">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="font-size: 10px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">INDICATOR 6</div>
              <strong style="font-size: 12.5px; color: #f8fafc;">Breakout Tracker</strong>
            </div>
            <span class="indicator-mini-pill ${brkPillCls}">${brkState}</span>
          </div>
          <div style="margin: 8px 0;">
            <div style="font-size: 11px; font-weight: 800; color: ${isBrkBull ? '#34d399' : (isBrkBear ? '#fb7185' : '#c084fc')};">
              ${brkBadgeText}
            </div>
            <div style="font-size: 10px; color: #94a3b8; font-family: var(--font-mono); margin-top: 3px;">
              ${brkLvl ? `Trigger: <strong style="color: #f8fafc;">₹${brkLvl}</strong> | Fail: <strong style="color: #fb7185;">₹${brkFail || '—'}</strong>` : `Res: <strong style="color: #38bdf8;">₹${brkRes || '—'}</strong> | Sup: <strong style="color: #38bdf8;">₹${brkSup || '—'}</strong>`}
            </div>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 9.5px; color: #64748b; line-height: 1.2;">
            <span>Trail SL: <strong style="color: #f8fafc;">${brkTrail ? `₹${brkTrail}` : '—'}</strong></span>
            <span>Open PnL: <strong style="color: ${brkPnl >= 0 ? '#34d399' : '#fb7185'};">${brkPnl > 0 ? '+' : ''}${brkPnl.toFixed(2)} ATR</strong></span>
          </div>
        </div>

      </div>

      <!-- Contract-Level Micro-Indicator Shelf (ATM Strike: ${atm}) -->
      <div style="background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 10px 14px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 14px;">🎛️</span>
          <span style="font-size: 11px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">
            ATM Strike (${atm}) Contract Indicators:
          </span>
        </div>

        <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 16px;">
          <!-- CE Contract Status -->
          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="font-size: 10.5px; font-weight: 800; color: #34d399;">ATM CALL (CE):</span>
            <span class="indicator-mini-pill ${ceAtm.bias === 'BULLISH' || (ceAtm.alphatrend_state || '').includes('BULL') ? 'pill-bull' : 'pill-neut'}">
              AT: ${(ceAtm.alphatrend_state || ind1.ce_state || 'NEUTRAL').slice(0, 4)}
            </span>
            <span class="indicator-mini-pill ${(ceAtm.trend_dir_strength || 0) > 0 ? 'pill-bull' : 'pill-neut'}">
              TD: ${(ceAtm.trend_dir_strength || 0) > 0 ? '+' : ''}${Number(ceAtm.trend_dir_strength || 0).toFixed(1)}
            </span>
            <span class="indicator-mini-pill ${(ceAtm.hull_state || '').includes('BULL') ? 'pill-bull' : 'pill-neut'}">
              H: ${(ceAtm.hull_state || ind5.ce_state || 'NEUT').slice(0, 4)}
            </span>
            <span class="indicator-mini-pill ${(ceAtm.breakout_state || ind6.state) === 'LONG' ? 'pill-bull' : 'pill-neut'}">
              BT: ${(ceAtm.breakout_state || ind6.state || 'FLAT').slice(0, 4)}
            </span>
            <span class="badge" style="background: rgba(16,185,129,0.18); color: #34d399; border: 1px solid rgba(16,185,129,0.4); font-size: 9.5px; padding: 2px 6px;">
              ${ceAtm.action_signal || 'CE HOLD'}
            </span>
          </div>

          <!-- Divider -->
          <span style="color: #334155;">|</span>

          <!-- PE Contract Status -->
          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="font-size: 10.5px; font-weight: 800; color: #fb7185;">ATM PUT (PE):</span>
            <span class="indicator-mini-pill ${peAtm.bias === 'BEARISH' || (peAtm.alphatrend_state || '').includes('BULL') ? 'pill-bear' : 'pill-neut'}">
              AT: ${(peAtm.alphatrend_state || ind1.pe_state || 'NEUTRAL').slice(0, 4)}
            </span>
            <span class="indicator-mini-pill ${(peAtm.trend_dir_strength || 0) > 0 ? 'pill-bear' : 'pill-neut'}">
              TD: ${(peAtm.trend_dir_strength || 0) > 0 ? '+' : ''}${Number(peAtm.trend_dir_strength || 0).toFixed(1)}
            </span>
            <span class="indicator-mini-pill ${(peAtm.hull_state || '').includes('BULL') ? 'pill-bear' : 'pill-neut'}">
              H: ${(peAtm.hull_state || ind5.pe_state || 'NEUT').slice(0, 4)}
            </span>
            <span class="indicator-mini-pill ${(peAtm.breakout_state || ind6.state) === 'SHORT' ? 'pill-bear' : 'pill-neut'}">
              BT: ${(peAtm.breakout_state || ind6.state || 'FLAT').slice(0, 4)}
            </span>
            <span class="badge" style="background: rgba(239,68,68,0.18); color: #fb7185; border: 1px solid rgba(239,68,68,0.4); font-size: 9.5px; padding: 2px 6px;">
              ${peAtm.action_signal || 'PE HOLD'}
            </span>
          </div>
        </div>
      </div>

    </div>
  `;
}


// ─────────────────────────────────────────────────────────────────────────────
// 2. PRIMARY TABLE RENDERING (MOBILE-STICKY STRIKE ANCHOR & SCROLL PRESERVATION)
// ─────────────────────────────────────────────────────────────────────────────
let _confluenceScrollLeft = null;
let _isUserTouchingConfluence = false;

function _renderTable(container, data) {
  const mount = container.querySelector('#confluence-table-mount');
  if (!mount) return;

  // If user is actively touching or dragging on mobile, skip DOM update to prevent gesture cancellation
  if (_isUserTouchingConfluence) return;

  const strikes = data.strikes || [];
  const spot = data.spot_price || 0;
  const atm = data.atm_strike || 0;

  // Apply filters if selected
  let rows = strikes;
  if (currentFilter === 'BULLISH') {
    rows = strikes.filter(s => s.confluence.final_bias.includes('BULLISH'));
  } else if (currentFilter === 'BEARISH') {
    rows = strikes.filter(s => s.confluence.final_bias.includes('BEARISH'));
  } else if (currentFilter === 'HIGH_SCORE') {
    rows = strikes.filter(s => s.confluence.score >= 65 || s.confluence.score <= 35);
  }

  const scrollWrapper = mount.querySelector('#confluence-table-scroll-wrapper');
  const existingTbody = mount.querySelector('#confluence-table-body');

  // FLICKER-FREE & SCROLL-PRESERVING UPDATE:
  // If table already exists, update ONLY tbody rows without touching the scroll wrapper!
  // This ensures the browser NEVER resets scrollLeft to 0 (Call data) during background polling!
  if (scrollWrapper && existingTbody) {
    if (scrollWrapper.scrollLeft > 0) {
      _confluenceScrollLeft = scrollWrapper.scrollLeft;
    }
    existingTbody.innerHTML = rows.length > 0 
      ? rows.map(r => _renderRow(data.symbol, r, spot, atm)).join('') 
      : `<tr><td colspan="22" style="text-align: center; padding: 30px; color: var(--text-muted);">No strikes matched the active filter "${currentFilter}".</td></tr>`;
    _attachChartClickLinks(mount);
    return;
  }

  // Full Initial Render of Table Container
  mount.innerHTML = `
    <div class="glass-panel" style="padding: 12px; border: 1px solid rgba(255, 255, 255, 0.08); background: rgba(5, 10, 20, 0.7); border-radius: 12px; overflow: hidden;">
      
      <!-- Table Title Header & Telemetry -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding: 2px 4px; flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-size: 22px;">⛓️</span>
          <div>
            <div style="font-size: 15px; font-weight: 800; color: #f8fafc; letter-spacing: 0.5px;">
              OPTION CHAIN MATRIX &amp; ACTIONABLE INTERPRETATION (${data.symbol})
            </div>
            <div style="font-size: 11px; color: #94a3b8;">
              Live Strike Corridor • Spot: <strong style="color: #38bdf8;">₹${spot.toLocaleString('en-IN', {minimumFractionDigits: 1})}</strong> | ATM: <strong style="color: #f59e0b;">${atm}</strong> | Scroll Horizontally to View Full Confluence &amp; Interpretation ➔
            </div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 11px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.35); padding: 3px 10px; border-radius: 6px; font-weight: 700;">
            ALL 22 PARAMETERS ACTIVE
          </span>
        </div>
      </div>

      <!-- Mobile Quick Jump Bar (For easy 1-tap navigation between Call, Strike, Put, and Confluence) -->
      <div class="conf-quick-jump-bar" style="display: flex; gap: 6px; margin-bottom: 10px; overflow-x: auto; padding-bottom: 4px;">
        <span style="font-size: 10px; font-weight: 800; color: #94a3b8; align-self: center; margin-right: 4px;">QUICK VIEW:</span>
        <button class="conf-jump-btn" id="conf-jump-calls" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(16,185,129,0.4); background: rgba(16,185,129,0.15); color: #34d399; cursor: pointer; white-space: nowrap;">
          🟢 Calls (CE + Indicators)
        </button>
        <button class="conf-jump-btn" id="conf-jump-strike" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(56,189,248,0.4); background: rgba(56,189,248,0.15); color: #38bdf8; cursor: pointer; white-space: nowrap;">
          ⚓ Strike Corridor
        </button>
        <button class="conf-jump-btn" id="conf-jump-puts" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(239,68,68,0.4); background: rgba(239,68,68,0.15); color: #f87171; cursor: pointer; white-space: nowrap;">
          🔴 Puts (PE + Indicators)
        </button>
        <button class="conf-jump-btn" id="conf-jump-verdict" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(139,92,246,0.4); background: rgba(139,92,246,0.15); color: #c084fc; cursor: pointer; white-space: nowrap;">
          🎯 Confluence Verdict
        </button>
      </div>

      <!-- Responsive Table Container with Horizontal Scroll & Sticky Anchor -->
      <div id="confluence-table-scroll-wrapper" style="width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; position: relative;">
        <table class="terminal-table confluence-table" style="width: 100%; min-width: 1750px; border-collapse: separate; border-spacing: 0 4px; font-size: 11.5px;">
          
          <!-- Super Header Grouping -->
          <thead>
            <tr style="background: rgba(255, 255, 255, 0.03); font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">
              <!-- Sticky Strike Super-Header -->
              <th class="sticky-strike-cell" style="padding: 8px 10px; text-align: left; border-right: 1px solid rgba(56, 189, 248, 0.3); background: #0f172a; position: sticky; left: 0; z-index: 20; min-width: 125px; width: 125px;">
                STRIKE (ANCHOR)
              </th>

              <!-- CE Super-Header with Integrated Indicators (7 cols) -->
              <th colspan="7" id="super-hdr-ce" style="padding: 8px; text-align: center; color: #34d399; background: rgba(16, 185, 129, 0.08); border-right: 1px solid rgba(255, 255, 255, 0.08);">
                CALL (CE) CONTRACT, POSITIONING &amp; PINESCRIPT INDICATORS
              </th>

              <!-- Corridor Flow & Gravity Super-Header (3 cols) -->
              <th colspan="3" id="super-hdr-flow" style="padding: 8px; text-align: center; color: #38bdf8; background: rgba(56, 189, 248, 0.08); border-right: 1px solid rgba(255, 255, 255, 0.08);">
                CORRIDOR FLOW &amp; GRAVITY
              </th>

              <!-- PE Super-Header with Integrated Indicators (7 cols) -->
              <th colspan="7" id="super-hdr-pe" style="padding: 8px; text-align: center; color: #f87171; background: rgba(239, 68, 68, 0.08); border-right: 1px solid rgba(255, 255, 255, 0.08);">
                PUT (PE) CONTRACT, POSITIONING &amp; PINESCRIPT INDICATORS
              </th>

              <!-- Confluence Super-Header (3 cols: Score, Bias, Actionable Signal) -->
              <th colspan="3" id="super-hdr-confluence" style="padding: 8px; text-align: center; color: #f8fafc; background: rgba(56, 189, 248, 0.15); border-right: 1px solid rgba(56, 189, 248, 0.3);">
                FINAL CONFLUENCE &amp; VERDICT
              </th>

              <!-- 5m Chart link (1 col) -->
              <th style="padding: 8px; text-align: center; color: var(--text-muted); background: rgba(255, 255, 255, 0.02); min-width: 100px; width: 100px;">
                CHART
              </th>
            </tr>

            <!-- Detailed Sub-Headers (22 columns total) -->
            <tr style="background: rgba(255, 255, 255, 0.02); font-size: 9.5px; color: var(--text-muted); text-transform: uppercase;">
              <!-- Sticky Strike Sub-Header -->
              <th class="sticky-strike-cell" style="padding: 8px 10px; text-align: left; position: sticky; left: 0; background: #0f172a; z-index: 20; border-right: 1px solid rgba(56, 189, 248, 0.3); min-width: 125px; width: 125px;">
                PRICE / TAG
              </th>

              <!-- CE Sub-Headers (7 cols) -->
              <th style="padding: 6px 8px; text-align: right; min-width: 65px;" title="Call Open Interest">OI</th>
              <th style="padding: 6px 8px; text-align: right; min-width: 65px;" title="Change in Call Open Interest">ΔOI</th>
              <th style="padding: 6px 8px; text-align: right; min-width: 85px;" title="Call Option Premium & % Change">LTP</th>
              <th style="padding: 6px 8px; text-align: center; min-width: 140px; background: rgba(16, 185, 129, 0.05);" title="Call Contract Price Movement & PineScript Indicators (AlphaTrend, TrendDir, Hull, Proximity)">CE MOMENTUM &amp; DIRECTION</th>
              <th style="padding: 6px 8px; text-align: right; min-width: 60px;" title="Call Volume">VOL</th>
              <th style="padding: 6px 8px; text-align: center; min-width: 45px;" title="Call Implied Volatility">IV</th>
              <th style="padding: 6px 8px; text-align: left; min-width: 130px; border-right: 1px solid rgba(255, 255, 255, 0.08);" title="Call Institutional Flow / Buildup">FLOW / VIEW</th>

              <!-- Flow & Gravity Sub-Headers (3 cols) -->
              <th style="padding: 6px 8px; text-align: right; min-width: 70px;" title="Net Difference in OI (PE OI - CE OI)">ΔDIFF</th>
              <th style="padding: 6px 8px; text-align: center; min-width: 55px;" title="Strike PCR (PE OI / CE OI)">PCR</th>
              <th style="padding: 6px 8px; text-align: center; min-width: 75px; border-right: 1px solid rgba(255, 255, 255, 0.08);" title="Shonya Gravity Equilibrium Zone">SHONYA</th>

              <!-- PE Sub-Headers (7 cols) -->
              <th style="padding: 6px 8px; text-align: left; min-width: 130px;" title="Put Institutional Flow / Buildup">FLOW / VIEW</th>
              <th style="padding: 6px 8px; text-align: center; min-width: 45px;" title="Put Implied Volatility">IV</th>
              <th style="padding: 6px 8px; text-align: right; min-width: 60px;" title="Put Volume">VOL</th>
              <th style="padding: 6px 8px; text-align: center; min-width: 140px; background: rgba(239, 68, 68, 0.05);" title="Put Contract Price Movement & PineScript Indicators (AlphaTrend, TrendDir, Hull, Proximity)">PE MOMENTUM &amp; DIRECTION</th>
              <th style="padding: 6px 8px; text-align: right; min-width: 85px;" title="Put Option Premium & % Change">LTP</th>
              <th style="padding: 6px 8px; text-align: right; min-width: 65px;" title="Change in Put Open Interest">ΔOI</th>
              <th style="padding: 6px 8px; text-align: right; min-width: 65px; border-right: 1px solid rgba(255, 255, 255, 0.08);" title="Put Open Interest">OI</th>

              <!-- Final Confluence Sub-Headers (3 cols) -->
              <th style="padding: 6px 8px; text-align: center; min-width: 60px;" title="Multi-Factor Strike Confluence Score (0 - 100)">SCORE</th>
              <th style="padding: 6px 8px; text-align: center; min-width: 100px;" title="Strike Mathematical Bias">BIAS</th>
              <th style="padding: 6px 10px; text-align: left; width: 260px; min-width: 260px; max-width: 260px; border-right: 1px solid rgba(56, 189, 248, 0.3);" title="Actionable Institutional Signal">ACTIONABLE SIGNAL &amp; INTERPRETATION</th>

              <!-- 5m Option Chart Link (1 col) -->
              <th style="padding: 6px 8px; text-align: center; min-width: 100px; width: 100px;">5M CHART</th>
            </tr>
          </thead>

          <!-- Table Body -->
          <tbody id="confluence-table-body">
            ${rows.length > 0 ? rows.map(r => _renderRow(data.symbol, r, spot, atm)).join('') : `
              <tr>
                <td colspan="22" style="text-align: center; padding: 30px; color: var(--text-muted);">
                  No strikes matched the active filter "${currentFilter}".
                </td>
              </tr>
            `}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Attach touch listeners to prevent gesture cancellation during active mobile swipe
  const newScrollWrapper = mount.querySelector('#confluence-table-scroll-wrapper');
  if (newScrollWrapper) {
    newScrollWrapper.addEventListener('touchstart', () => { _isUserTouchingConfluence = true; }, { passive: true });
    newScrollWrapper.addEventListener('touchend', () => { 
      _isUserTouchingConfluence = false; 
      _confluenceScrollLeft = newScrollWrapper.scrollLeft;
    }, { passive: true });
    newScrollWrapper.addEventListener('scroll', () => {
      _confluenceScrollLeft = newScrollWrapper.scrollLeft;
    }, { passive: true });

    // Restore previous scroll position if known
    if (_confluenceScrollLeft !== null) {
      newScrollWrapper.scrollLeft = _confluenceScrollLeft;
      requestAnimationFrame(() => { newScrollWrapper.scrollLeft = _confluenceScrollLeft; });
      setTimeout(() => { newScrollWrapper.scrollLeft = _confluenceScrollLeft; }, 50);
    }
  }

  // Quick jump listeners
  const btnJumpCalls = mount.querySelector('#conf-jump-calls');
  const btnJumpStrike = mount.querySelector('#conf-jump-strike');
  const btnJumpPuts = mount.querySelector('#conf-jump-puts');
  const btnJumpVerdict = mount.querySelector('#conf-jump-verdict');

  if (newScrollWrapper) {
    btnJumpCalls?.addEventListener('click', () => {
      newScrollWrapper.scrollTo({ left: 0, behavior: 'smooth' });
    });
    btnJumpStrike?.addEventListener('click', () => {
      const el = mount.querySelector('#super-hdr-flow');
      if (el) newScrollWrapper.scrollTo({ left: Math.max(0, el.offsetLeft - 80), behavior: 'smooth' });
    });
    btnJumpPuts?.addEventListener('click', () => {
      const el = mount.querySelector('#super-hdr-pe');
      if (el) newScrollWrapper.scrollTo({ left: el.offsetLeft - 40, behavior: 'smooth' });
    });
    btnJumpVerdict?.addEventListener('click', () => {
      newScrollWrapper.scrollTo({ left: newScrollWrapper.scrollWidth, behavior: 'smooth' });
    });
  }

  _attachChartClickLinks(mount);
}

function _attachChartClickLinks(mount) {
  mount.querySelectorAll('.conf-chart-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const sym = btn.getAttribute('data-sym');
      const stk = parseFloat(btn.getAttribute('data-stk'));
      const otype = btn.getAttribute('data-type');

      // Dispatch global event for option chart
      window.dispatchEvent(new CustomEvent('open-option-chart', {
        detail: { symbol: sym, strike: stk, optionType: otype }
      }));

      // Switch to option-chart tab
      const chartTab = document.querySelector('.tab-btn[data-tab="option-chart"]');
      if (chartTab) chartTab.click();
    });
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. ROW RENDERING (WITH STICKY ANCHOR & ATM HIGHLIGHT)
// ─────────────────────────────────────────────────────────────────────────────
function _renderRow(symbol, row, spot, atm) {
  const stk = row.strike;
  const isAtm = row.step_tag === 'ATM';
  const ce = row.ce || {};
  const pe = row.pe || {};
  const conf = row.confluence || {};
  const ind = row.indicators || {};
  const ind1 = ind.ind1 || {};
  const ind2 = ind.ind2 || {};
  const ind3 = ind.ind3 || {};
  const ind4 = ind.ind4 || {};
  const ind5 = ind.ind5 || {};
  const ind6 = ind.ind6 || ind.ind_brk || {};

  // Row background styling: prominent highlight if ATM
  const rowBg = isAtm 
    ? 'background: rgba(56, 189, 248, 0.08); border-left: 3px solid #38bdf8;' 
    : 'background: rgba(255, 255, 255, 0.015);';

  // Sticky cell background (must be opaque so scrolling cells slide under it cleanly)
  const stickyBg = isAtm ? 'background: #112240;' : 'background: #0f172a;';

  // Tag styling
  let tagColor = '#94a3b8';
  let tagBg = 'rgba(255, 255, 255, 0.06)';
  if (isAtm) {
    tagColor = '#38bdf8';
    tagBg = 'rgba(56, 189, 248, 0.25)';
  } else if (row.step_tag.includes('-')) {
    tagColor = '#34d399';
    tagBg = 'rgba(16, 185, 129, 0.15)';
  } else {
    tagColor = '#fbbf24';
    tagBg = 'rgba(245, 158, 11, 0.15)';
  }

  // Score styling
  const score = conf.score || 50;
  const scoreCol = score >= 65 ? '#10b981' : (score <= 35 ? '#ef4444' : '#f59e0b');

  return `
    <tr style="${rowBg} border-bottom: 1px solid rgba(255, 255, 255, 0.04); transition: background 0.15s ease;">
      
      <!-- 1. STICKY STRIKE ANCHOR COLUMN -->
      <td class="sticky-strike-cell" style="padding: 8px 10px; white-space: nowrap; position: sticky; left: 0; z-index: 10; ${stickyBg} border-right: 1px solid rgba(56, 189, 248, 0.3); box-shadow: 2px 0 6px rgba(0,0,0,0.5); min-width: 125px; width: 125px;">
        <div style="display: flex; align-items: center; gap: 6px;">
          <strong style="font-size: 13px; font-family: var(--font-mono); color: #f8fafc;">
            ${stk.toLocaleString('en-IN')}
          </strong>
          <span style="font-size: 9px; font-weight: 800; padding: 1px 5px; border-radius: 4px; background: ${tagBg}; color: ${tagColor}; border: 1px solid ${tagColor};">
            ${row.step_tag}
          </span>
        </div>
        <div style="font-size: 9.5px; font-family: var(--font-mono); color: var(--text-muted); margin-top: 1px;">
          ${row.distance_pts > 0 ? '+' : ''}${row.distance_pts} pts | CE:${row.moneyness_ce} PE:${row.moneyness_pe}
        </div>
      </td>

      <!-- 2. CALL (CE) METRICS (6 cols) -->
      <td style="padding: 6px 8px; text-align: right; font-family: var(--font-mono); color: #cbd5e1; min-width: 65px;">
        ${ce.oi_formatted}
      </td>
      <td style="padding: 6px 8px; text-align: right; font-family: var(--font-mono); font-weight: 700; color: ${ce.oi_chg >= 0 ? '#10b981' : '#ef4444'}; min-width: 65px;">
        ${ce.oi_chg_formatted}
      </td>
      <td style="padding: 6px 8px; text-align: right; font-family: var(--font-mono); min-width: 85px;">
        <span style="color: #38bdf8; font-weight: 700;">₹${ce.ltp.toFixed(1)}</span>
        <span style="font-size: 9px; color: ${ce.pchange >= 0 ? '#10b981' : '#ef4444'};">(${ce.pchange >= 0 ? '+' : ''}${ce.pchange.toFixed(1)}%)</span>
      </td>
      <!-- MERGED: Call (CE) Direction & PineScript Momentum -->
      ${(() => {
        const ceAtSt = ce.alphatrend_state || ind1.ce_state || 'NEUTRAL';
        const ceTdSt = ce.trend_dir_state || ind2.ce_state || 'NEUTRAL';
        const ceHullSt = ce.hull_state || ind5.ce_state || 'NEUTRAL';
        const ceBrkSt = ce.breakout_state || ind6.state || 'FLAT';

        // Use genuine contract-level actionable signal
        const ceSigText = ce.action_signal || (ceAtSt === 'BULLISH' ? '🚀 BUY CE' : (ceAtSt === 'BEARISH' ? '▼ CE DECAY' : '— CE HOLD —'));
        const ceBadgeBg = ceSigText.includes('BUY') || ceSigText.includes('COVERING')
          ? 'background: rgba(16,185,129,0.22); color: #34d399; border: 1px solid rgba(16,185,129,0.45);'
          : (ceSigText.includes('WRITE') || ceSigText.includes('RESISTANCE') || ceSigText.includes('DECAY') || ceSigText.includes('UNWINDING')
            ? 'background: rgba(239,68,68,0.22); color: #f87171; border: 1px solid rgba(239,68,68,0.45);'
            : 'background: rgba(148,163,184,0.15); color: #94a3b8; border: 1px solid rgba(148,163,184,0.3);');

        const ceBadge = `<span class="badge" style="${ceBadgeBg} font-size: 9.5px; padding: 2px 7px; font-weight: 800; white-space: nowrap;">${ceSigText}</span>`;

        const ceProxVal = (ce.proximity !== undefined && ce.proximity !== null) ? `${ce.proximity}%` : ((ind4.per !== undefined) ? `${ind4.per}%` : '50%');
        const ceTdStr = (ce.trend_dir_strength !== undefined && ce.trend_dir_strength !== null) ? `${ce.trend_dir_strength > 0 ? '+' : ''}${ce.trend_dir_strength}` : (ind2.ce_strength !== undefined ? `${ind2.ce_strength}` : '0.0');
        const ceAtSym = ceAtSt === 'BULLISH' ? '▲' : (ceAtSt === 'BEARISH' ? '▼' : '—');
        const ceHullSym = ceHullSt === 'BULLISH' ? '▲' : (ceHullSt === 'BEARISH' ? '▼' : '—');
        const ceBrkSym = ceBrkSt === 'LONG' ? '▲' : (ceBrkSt === 'SHORT' ? '▼' : '—');

        const ceAtPillCls = ceAtSt === 'BULLISH' ? 'pill-bull' : (ceAtSt === 'BEARISH' ? 'pill-bear' : 'pill-neut');
        const ceTdPillCls = parseFloat(ceTdStr) > 0 ? 'pill-bull' : (parseFloat(ceTdStr) < 0 ? 'pill-bear' : 'pill-neut');
        const ceHullPillCls = ceHullSt === 'BULLISH' ? 'pill-bull' : (ceHullSt === 'BEARISH' ? 'pill-bear' : 'pill-neut');
        const ceBrkPillCls = ceBrkSt === 'LONG' ? 'pill-bull' : (ceBrkSt === 'SHORT' ? 'pill-bear' : 'pill-neut');
        const ceProxPillCls = parseFloat(ceProxVal) >= 65 ? 'pill-warn' : 'pill-cyan';

        return `
          <td style="padding: 6px 8px; text-align: center; font-family: var(--font-mono); min-width: 155px; background: rgba(16, 185, 129, 0.03);">
            <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
              ${ceBadge}
              <div class="indicator-mini-matrix" style="margin-top: 2px;">
                <span class="indicator-mini-pill ${ceAtPillCls}" title="Call AlphaTrend: ${ceAtSt}">AT:${ceAtSym}</span>
                <span class="indicator-mini-pill ${ceTdPillCls}" title="Call TrendDirection: ${ceTdStr}">TD:${ceTdStr}</span>
                <span class="indicator-mini-pill ${ceHullPillCls}" title="Call Hull Suite: ${ceHullSt}">H:${ceHullSym}</span>
                <span class="indicator-mini-pill ${ceBrkPillCls}" title="Call Breakout Tracker: ${ceBrkSt}">BT:${ceBrkSym}</span>
                <span class="indicator-mini-pill ${ceProxPillCls}" title="Call Proximity: ${ceProxVal}">PX:${ceProxVal}</span>
              </div>
            </div>
          </td>
        `;
      })()}
      <td style="padding: 6px 8px; text-align: right; font-family: var(--font-mono); color: var(--text-muted); font-size: 10px; min-width: 60px;">
        ${ce.volume_formatted}
      </td>
      <td style="padding: 6px 8px; text-align: center; font-family: var(--font-mono); color: var(--text-secondary); font-size: 10px; min-width: 45px;">
        ${ce.iv ? ce.iv.toFixed(1) : '--'}
      </td>
      <td style="padding: 6px 8px; text-align: left; border-right: 1px solid rgba(255, 255, 255, 0.08); min-width: 140px;">
        <div style="display: flex; flex-direction: column; gap: 2px;">
          <span class="badge ${ce.bias === 'BULLISH' ? 'badge-bull' : (ce.bias === 'BEARISH' ? 'badge-bear' : 'badge-neutral')}" style="font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: 800; align-self: flex-start;">
            ${ce.buildup ? ce.buildup.replace('_', ' ') : 'NEUTRAL'}
          </span>
          <span style="font-size: 9.5px; color: ${ce.bias === 'BULLISH' ? '#34d399' : (ce.bias === 'BEARISH' ? '#f87171' : 'var(--text-muted)')}; line-height: 1.15;">
            ${ce.action_directive || ce.interpretation}
          </span>
        </div>
      </td>

      <!-- 3. CORRIDOR FLOW & GRAVITY (3 cols) -->
      <td style="padding: 6px 8px; text-align: right; font-family: var(--font-mono); font-weight: 700; color: ${row.oi_diff >= 0 ? '#10b981' : '#ef4444'}; min-width: 70px;">
        ${row.oi_diff_formatted}
      </td>
      <td style="padding: 6px 8px; text-align: center; font-family: var(--font-mono); font-weight: 800; color: ${row.pcr >= 1 ? '#10b981' : '#ef4444'}; min-width: 55px;">
        ${row.pcr.toFixed(2)}
      </td>
      <td style="padding: 6px 8px; text-align: center; font-family: var(--font-mono); min-width: 75px; border-right: 1px solid rgba(255, 255, 255, 0.08);" title="Shonya Gravity Equilibrium Position">
        <span style="font-size: 9.5px; padding: 2px 5px; border-radius: 3px; font-weight: 800; ${ind3.state === 'ABOVE' ? 'background: rgba(16,185,129,0.18); color: #34d399; border: 1px solid rgba(16,185,129,0.3);' : (ind3.state === 'BELOW' ? 'background: rgba(239,68,68,0.18); color: #f87171; border: 1px solid rgba(239,68,68,0.3);' : 'background: rgba(56,189,248,0.18); color: #38bdf8; border: 1px solid rgba(56,189,248,0.3);')}">
          ${ind3.detail || ind3.state || 'AT GRAV'}
        </span>
      </td>

      <!-- 4. PUT (PE) METRICS & MERGED INDICATORS (7 cols) -->
      <td style="padding: 6px 8px; text-align: left; min-width: 140px;">
        <div style="display: flex; flex-direction: column; gap: 2px;">
          <span class="badge ${pe.bias === 'BULLISH' ? 'badge-bull' : (pe.bias === 'BEARISH' ? 'badge-bear' : 'badge-neutral')}" style="font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: 800; align-self: flex-start;">
            ${pe.buildup ? pe.buildup.replace('_', ' ') : 'NEUTRAL'}
          </span>
          <span style="font-size: 9.5px; color: ${pe.bias === 'BULLISH' ? '#34d399' : (pe.bias === 'BEARISH' ? '#f87171' : 'var(--text-muted)')}; line-height: 1.15;">
            ${pe.action_directive || pe.interpretation}
          </span>
        </div>
      </td>
      <td style="padding: 6px 8px; text-align: center; font-family: var(--font-mono); color: var(--text-secondary); font-size: 10px; min-width: 45px;">
        ${pe.iv ? pe.iv.toFixed(1) : '--'}
      </td>
      <td style="padding: 6px 8px; text-align: right; font-family: var(--font-mono); color: var(--text-muted); font-size: 10px; min-width: 60px;">
        ${pe.volume_formatted}
      </td>
      <!-- MERGED: Put (PE) Direction & PineScript Momentum -->
      ${(() => {
        const peAtSt = pe.alphatrend_state || ind1.pe_state || 'NEUTRAL';
        const peTdSt = pe.trend_dir_state || ind2.pe_state || 'NEUTRAL';
        const peHullSt = pe.hull_state || ind5.pe_state || 'NEUTRAL';
        const peBrkSt = pe.breakout_state || ind6.state || 'FLAT';

        // Use genuine contract-level actionable signal
        const peSigText = pe.action_signal || (peAtSt === 'BULLISH' ? '💥 BUY PE' : (peAtSt === 'BEARISH' ? '▼ PE DECAY' : '— PE HOLD —'));
        const peBadgeBg = peSigText.includes('BUY') || peSigText.includes('RUNNING')
          ? 'background: rgba(244,63,94,0.22); color: #fb7185; border: 1px solid rgba(244,63,94,0.45);'
          : (peSigText.includes('WRITE') || peSigText.includes('SUPPORT')
            ? 'background: rgba(16,185,129,0.22); color: #34d399; border: 1px solid rgba(16,185,129,0.45);'
            : (peSigText.includes('DECAY') || peSigText.includes('UNWINDING')
              ? 'background: rgba(239,68,68,0.22); color: #f87171; border: 1px solid rgba(239,68,68,0.45);'
              : 'background: rgba(148,163,184,0.15); color: #94a3b8; border: 1px solid rgba(148,163,184,0.3);'));

        const peBadge = `<span class="badge" style="${peBadgeBg} font-size: 9.5px; padding: 2px 7px; font-weight: 800; white-space: nowrap;">${peSigText}</span>`;

        const peProxVal = (pe.proximity !== undefined && pe.proximity !== null) ? `${pe.proximity}%` : ((ind4.per !== undefined) ? `${ind4.per}%` : '50%');
        const peTdStr = (pe.trend_dir_strength !== undefined && pe.trend_dir_strength !== null) ? `${pe.trend_dir_strength > 0 ? '+' : ''}${pe.trend_dir_strength}` : (ind2.pe_strength !== undefined ? `${ind2.pe_strength}` : '0.0');
        const peAtSym = peAtSt === 'BULLISH' ? '▲' : (peAtSt === 'BEARISH' ? '▼' : '—');
        const peHullSym = peHullSt === 'BULLISH' ? '▲' : (peHullSt === 'BEARISH' ? '▼' : '—');
        const peBrkSym = peBrkSt === 'SHORT' ? '▲' : (peBrkSt === 'LONG' ? '▼' : '—');

        const peAtPillCls = peAtSt === 'BULLISH' ? 'pill-bear' : (peAtSt === 'BEARISH' ? 'pill-bull' : 'pill-neut');
        const peTdPillCls = parseFloat(peTdStr) > 0 ? 'pill-bear' : (parseFloat(peTdStr) < 0 ? 'pill-bull' : 'pill-neut');
        const peHullPillCls = peHullSt === 'BULLISH' ? 'pill-bear' : (peHullSt === 'BEARISH' ? 'pill-bull' : 'pill-neut');
        const peBrkPillCls = peBrkSt === 'SHORT' ? 'pill-bear' : (peBrkSt === 'LONG' ? 'pill-bull' : 'pill-neut');
        const peProxPillCls = parseFloat(peProxVal) >= 65 ? 'pill-warn' : 'pill-cyan';

        return `
          <td style="padding: 6px 8px; text-align: center; font-family: var(--font-mono); min-width: 155px; background: rgba(239, 68, 68, 0.03);">
            <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
              ${peBadge}
              <div class="indicator-mini-matrix" style="margin-top: 2px;">
                <span class="indicator-mini-pill ${peAtPillCls}" title="Put AlphaTrend: ${peAtSt}">AT:${peAtSym}</span>
                <span class="indicator-mini-pill ${peTdPillCls}" title="Put TrendDirection: ${peTdStr}">TD:${peTdStr}</span>
                <span class="indicator-mini-pill ${peHullPillCls}" title="Put Hull Suite: ${peHullSt}">H:${peHullSym}</span>
                <span class="indicator-mini-pill ${peBrkPillCls}" title="Put Breakout Tracker: ${peBrkSt}">BT:${peBrkSym}</span>
                <span class="indicator-mini-pill ${peProxPillCls}" title="Put Proximity: ${peProxVal}">PX:${peProxVal}</span>
              </div>
            </div>
          </td>
        `;
      })()}
      <td style="padding: 6px 8px; text-align: right; font-family: var(--font-mono); min-width: 85px;">
        <span style="color: #f87171; font-weight: 700;">₹${pe.ltp.toFixed(1)}</span>
        <span style="font-size: 9px; color: ${pe.pchange >= 0 ? '#10b981' : '#ef4444'};">(${pe.pchange >= 0 ? '+' : ''}${pe.pchange.toFixed(1)}%)</span>
      </td>
      <td style="padding: 6px 8px; text-align: right; font-family: var(--font-mono); font-weight: 700; color: ${pe.oi_chg >= 0 ? '#10b981' : '#ef4444'}; min-width: 65px;">
        ${pe.oi_chg_formatted}
      </td>
      <td style="padding: 6px 8px; text-align: right; font-family: var(--font-mono); color: #cbd5e1; min-width: 65px; border-right: 1px solid rgba(255, 255, 255, 0.08);">
        ${pe.oi_formatted}
      </td>

      <!-- 5. FINAL CONFLUENCE & ACTIONABLE VERDICT (3 cols) -->
      <td style="padding: 6px 8px; text-align: center; font-family: var(--font-mono); min-width: 60px;">
        <strong style="font-size: 13px; color: ${scoreCol};">
          ${score}
        </strong>
      </td>
      <td style="padding: 6px 8px; text-align: center; min-width: 100px;">
        <span class="badge ${conf.bias_class || 'badge-neutral'}" style="font-size: 9.5px; padding: 2px 6px; border-radius: 4px; font-weight: 800; white-space: nowrap;">
          ${conf.final_bias}
        </span>
      </td>
      <td style="padding: 6px 10px; text-align: left; width: 260px; min-width: 260px; max-width: 260px; border-right: 1px solid rgba(56, 189, 248, 0.3); box-sizing: border-box; overflow: hidden;">
        <div style="width: 100%; max-width: 240px; box-sizing: border-box;">
          <div style="font-size: 11px; font-weight: 800; color: ${conf.score >= 60 ? '#34d399' : (conf.score <= 40 ? '#f87171' : '#f59e0b')}; line-height: 1.25; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${conf.signal}">
            ${conf.signal}
          </div>
          <div style="font-size: 9.5px; color: #94a3b8; line-height: 1.25; margin-top: 2px; white-space: normal; word-break: break-word; overflow-wrap: break-word;" title="${conf.interpretation}">
            ${conf.interpretation}
          </div>
        </div>
      </td>

      <!-- 7. 5M OPTION CHART QUICK-LINK (1 col) -->
      <td style="padding: 6px 8px; text-align: center; min-width: 100px; width: 100px; white-space: nowrap;">
        <div style="display: flex; gap: 4px; justify-content: center; align-items: center; white-space: nowrap;">
          <button class="conf-chart-btn" data-sym="${symbol}" data-stk="${stk}" data-type="CE" style="padding: 3px 6px; font-size: 9.5px; font-weight: 800; border-radius: 3px; border: 1px solid rgba(16,185,129,0.4); background: rgba(16,185,129,0.15); color: #34d399; cursor: pointer; white-space: nowrap;" title="Open 5m Call Chart for ₹${stk}">
            CE 🕯️
          </button>
          <button class="conf-chart-btn" data-sym="${symbol}" data-stk="${stk}" data-type="PE" style="padding: 3px 6px; font-size: 9.5px; font-weight: 800; border-radius: 3px; border: 1px solid rgba(239,68,68,0.4); background: rgba(239,68,68,0.15); color: #f87171; cursor: pointer; white-space: nowrap;" title="Open 5m Put Chart for ₹${stk}">
            PE 🕯️
          </button>
        </div>
      </td>

    </tr>
  `;
}

// ─────────────────────────────────────────────────────────────────────────────
// 4. EVENT LISTENERS
// ─────────────────────────────────────────────────────────────────────────────
function _attachListeners(container) {
  // Symbol switch
  container.querySelectorAll('.conf-sym-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const sym = btn.getAttribute('data-sym');
      if (sym && sym !== currentSymbol) {
        currentSymbol = sym;
        container.querySelectorAll('.conf-sym-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        await _loadAndRender(container);
      }
    });
  });

  // Range switch
  container.querySelectorAll('.conf-range-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const rng = parseInt(btn.getAttribute('data-range'), 10);
      if (rng && rng !== currentRange) {
        currentRange = rng;
        container.querySelectorAll('.conf-range-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        await _loadAndRender(container);
      }
    });
  });

  // Filter switch
  container.querySelectorAll('.conf-filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const flt = btn.getAttribute('data-filter');
      if (flt && flt !== currentFilter) {
        currentFilter = flt;
        container.querySelectorAll('.conf-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (lastData) {
          _renderTable(container, lastData);
        }
      }
    });
  });
}

/**
 * Standalone Option Chain Matrix Exporter
 * Allows embedding the exact 22-parameter Option Chain Matrix with live
 * Actionable Signals & Interpretation directly inside any container (e.g. at the bottom of the Trading Dashboard).
 */
export async function renderOptionChainMatrixStandalone(mount, symbol = 'NIFTY', range = 2, filter = 'ALL') {
  if (!mount) return;
  try {
    const data = await ApiClient.fetchOptionConfluence(symbol, range);
    if (!data || !data.success) return;

    const strikes = data.strikes || [];
    const spot = data.spot_price || 0;
    const atm = data.atm_strike || 0;

    let rows = strikes;
    if (filter === 'BULLISH') {
      rows = strikes.filter(s => s.confluence.final_bias.includes('BULLISH'));
    } else if (filter === 'BEARISH') {
      rows = strikes.filter(s => s.confluence.final_bias.includes('BEARISH'));
    } else if (filter === 'HIGH_SCORE') {
      rows = strikes.filter(s => s.confluence.score >= 65 || s.confluence.score <= 35);
    }

    const scrollWrapper = mount.querySelector('#confluence-standalone-scroll-wrapper');
    const existingTbody = mount.querySelector('#confluence-standalone-tbody');

    if (scrollWrapper && existingTbody) {
      existingTbody.innerHTML = rows.length > 0
        ? rows.map(r => _renderRow(data.symbol, r, spot, atm)).join('')
        : `<tr><td colspan="22" style="text-align: center; padding: 30px; color: var(--text-muted);">No strikes matched the active filter.</td></tr>`;
      _attachChartClickLinks(mount);
      return;
    }

    mount.innerHTML = `
      <div class="glass-panel" style="padding: 14px; border: 1px solid rgba(56, 189, 248, 0.3); background: rgba(10, 15, 30, 0.85); border-radius: 12px; overflow: hidden; margin-top: 10px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
        
        <!-- Table Title Header & Telemetry -->
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding: 2px 4px; flex-wrap: wrap; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <div style="width: 36px; height: 36px; border-radius: 8px; background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.35); display: flex; align-items: center; justify-content: center; font-size: 18px;">
              ⛓️
            </div>
            <div>
              <div style="font-size: 15px; font-weight: 800; color: #f8fafc; letter-spacing: 0.5px;">
                OPTION CHAIN MATRIX &amp; ACTIONABLE INTERPRETATION (${data.symbol})
              </div>
              <div style="font-size: 11px; color: #94a3b8;">
                Real-Time Strike Corridor • Spot: <strong style="color: #38bdf8;">₹${spot.toLocaleString('en-IN', {minimumFractionDigits: 1})}</strong> | ATM: <strong style="color: #f59e0b;">${atm}</strong> | Scroll Horizontally to View Full Confluence &amp; Interpretation ➔
              </div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 11px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.35); padding: 3px 10px; border-radius: 6px; font-weight: 700;">
              ALL 22 PARAMETERS ACTIVE
            </span>
          </div>
        </div>

        <!-- Quick Jump Navigation -->
        <div class="conf-quick-jump-bar" style="display: flex; gap: 6px; margin-bottom: 10px; overflow-x: auto; padding-bottom: 4px;">
          <span style="font-size: 10px; font-weight: 800; color: #94a3b8; align-self: center; margin-right: 4px;">QUICK VIEW:</span>
          <button class="conf-jump-btn" id="conf-standalone-calls" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(16,185,129,0.4); background: rgba(16,185,129,0.15); color: #34d399; cursor: pointer; white-space: nowrap;">
            🟢 Calls (CE + Indicators)
          </button>
          <button class="conf-jump-btn" id="conf-standalone-strike" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(56,189,248,0.4); background: rgba(56,189,248,0.15); color: #38bdf8; cursor: pointer; white-space: nowrap;">
            ⚓ Strike Corridor
          </button>
          <button class="conf-jump-btn" id="conf-standalone-puts" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(239,68,68,0.4); background: rgba(239,68,68,0.15); color: #f87171; cursor: pointer; white-space: nowrap;">
            🔴 Puts (PE + Indicators)
          </button>
          <button class="conf-jump-btn" id="conf-standalone-verdict" style="padding: 4px 10px; font-size: 11px; font-weight: 700; border-radius: 5px; border: 1px solid rgba(139,92,246,0.4); background: rgba(139,92,246,0.15); color: #c084fc; cursor: pointer; white-space: nowrap;">
            🎯 Confluence &amp; Interpretation ➔
          </button>
        </div>

        <!-- Scrollable Table -->
        <div id="confluence-standalone-scroll-wrapper" style="width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; position: relative;">
          <table class="terminal-table confluence-table" style="width: 100%; min-width: 1750px; border-collapse: separate; border-spacing: 0 4px; font-size: 11.5px;">
            <thead>
              <tr style="background: rgba(255, 255, 255, 0.03); font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">
                <th class="sticky-strike-cell" style="padding: 8px 10px; text-align: left; border-right: 1px solid rgba(56, 189, 248, 0.3); background: #0f172a; position: sticky; left: 0; z-index: 20; min-width: 125px; width: 125px;">
                  STRIKE (ANCHOR)
                </th>
                <th colspan="7" id="super-hdr-ce-standalone" style="padding: 8px; text-align: center; color: #34d399; background: rgba(16, 185, 129, 0.08); border-right: 1px solid rgba(255, 255, 255, 0.08);">
                  CALL (CE) CONTRACT, POSITIONING &amp; PINESCRIPT INDICATORS
                </th>
                <th colspan="3" id="super-hdr-flow-standalone" style="padding: 8px; text-align: center; color: #38bdf8; background: rgba(56, 189, 248, 0.08); border-right: 1px solid rgba(255, 255, 255, 0.08);">
                  CORRIDOR FLOW &amp; GRAVITY
                </th>
                <th colspan="7" id="super-hdr-pe-standalone" style="padding: 8px; text-align: center; color: #f87171; background: rgba(239, 68, 68, 0.08); border-right: 1px solid rgba(255, 255, 255, 0.08);">
                  PUT (PE) CONTRACT, POSITIONING &amp; PINESCRIPT INDICATORS
                </th>
                <th colspan="3" id="super-hdr-confluence-standalone" style="padding: 8px; text-align: center; color: #f8fafc; background: rgba(56, 189, 248, 0.15); border-right: 1px solid rgba(56, 189, 248, 0.3);">
                  FINAL CONFLUENCE &amp; VERDICT
                </th>
                <th style="padding: 8px; text-align: center; color: var(--text-muted); background: rgba(255, 255, 255, 0.02); min-width: 100px; width: 100px;">
                  CHART
                </th>
              </tr>
              <tr style="background: rgba(255, 255, 255, 0.02); font-size: 9.5px; color: var(--text-muted); text-transform: uppercase;">
                <th class="sticky-strike-cell" style="padding: 8px 10px; text-align: left; position: sticky; left: 0; background: #0f172a; z-index: 20; border-right: 1px solid rgba(56, 189, 248, 0.3); min-width: 125px; width: 125px;">
                  PRICE / TAG
                </th>
                <th style="padding: 6px 8px; text-align: right; min-width: 65px;" title="Call Open Interest">OI</th>
                <th style="padding: 6px 8px; text-align: right; min-width: 65px;" title="Change in Call Open Interest">ΔOI</th>
                <th style="padding: 6px 8px; text-align: right; min-width: 85px;" title="Call Option Premium & % Change">LTP</th>
                <th style="padding: 6px 8px; text-align: center; min-width: 140px; background: rgba(16, 185, 129, 0.05);" title="Call Momentum & Indicators">CE MOMENTUM &amp; DIRECTION</th>
                <th style="padding: 6px 8px; text-align: right; min-width: 60px;" title="Call Volume">VOL</th>
                <th style="padding: 6px 8px; text-align: center; min-width: 45px;" title="Call Implied Volatility">IV</th>
                <th style="padding: 6px 8px; text-align: left; min-width: 130px; border-right: 1px solid rgba(255, 255, 255, 0.08);" title="Call Institutional Flow / Buildup">FLOW / VIEW</th>
                <th style="padding: 6px 8px; text-align: right; min-width: 70px;" title="Net Difference in OI (PE OI - CE OI)">ΔDIFF</th>
                <th style="padding: 6px 8px; text-align: center; min-width: 55px;" title="Strike PCR (PE OI / CE OI)">PCR</th>
                <th style="padding: 6px 8px; text-align: center; min-width: 75px; border-right: 1px solid rgba(255, 255, 255, 0.08);" title="Shonya Gravity Equilibrium Zone">SHONYA</th>
                <th style="padding: 6px 8px; text-align: left; min-width: 130px;" title="Put Institutional Flow / Buildup">FLOW / VIEW</th>
                <th style="padding: 6px 8px; text-align: center; min-width: 45px;" title="Put Implied Volatility">IV</th>
                <th style="padding: 6px 8px; text-align: right; min-width: 60px;" title="Put Volume">VOL</th>
                <th style="padding: 6px 8px; text-align: center; min-width: 140px; background: rgba(239, 68, 68, 0.05);" title="Put Momentum & Indicators">PE MOMENTUM &amp; DIRECTION</th>
                <th style="padding: 6px 8px; text-align: right; min-width: 85px;" title="Put Option Premium & % Change">LTP</th>
                <th style="padding: 6px 8px; text-align: right; min-width: 65px;" title="Change in Put Open Interest">ΔOI</th>
                <th style="padding: 6px 8px; text-align: right; min-width: 65px; border-right: 1px solid rgba(255, 255, 255, 0.08);" title="Put Open Interest">OI</th>
                <th style="padding: 6px 8px; text-align: center; min-width: 60px;" title="Multi-Factor Strike Confluence Score (0 - 100)">SCORE</th>
                <th style="padding: 6px 8px; text-align: center; min-width: 100px;" title="Strike Mathematical Bias">BIAS</th>
                <th style="padding: 6px 10px; text-align: left; width: 260px; min-width: 260px; max-width: 260px; border-right: 1px solid rgba(56, 189, 248, 0.3);" title="Actionable Institutional Signal">ACTIONABLE SIGNAL &amp; INTERPRETATION</th>
                <th style="padding: 6px 8px; text-align: center; min-width: 100px; width: 100px;">5M CHART</th>
              </tr>
            </thead>
            <tbody id="confluence-standalone-tbody">
              ${rows.length > 0 ? rows.map(r => _renderRow(data.symbol, r, spot, atm)).join('') : `
                <tr>
                  <td colspan="22" style="text-align: center; padding: 30px; color: var(--text-muted);">
                    No strikes matched the active filter.
                  </td>
                </tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    `;

    const wrap = mount.querySelector('#confluence-standalone-scroll-wrapper');
    if (wrap) {
      mount.querySelector('#conf-standalone-calls')?.addEventListener('click', () => {
        wrap.scrollTo({ left: 0, behavior: 'smooth' });
      });
      mount.querySelector('#conf-standalone-strike')?.addEventListener('click', () => {
        const el = mount.querySelector('#super-hdr-flow-standalone');
        if (el) wrap.scrollTo({ left: Math.max(0, el.offsetLeft - 80), behavior: 'smooth' });
      });
      mount.querySelector('#conf-standalone-puts')?.addEventListener('click', () => {
        const el = mount.querySelector('#super-hdr-pe-standalone');
        if (el) wrap.scrollTo({ left: el.offsetLeft - 40, behavior: 'smooth' });
      });
      mount.querySelector('#conf-standalone-verdict')?.addEventListener('click', () => {
        wrap.scrollTo({ left: wrap.scrollWidth, behavior: 'smooth' });
      });
    }

    _attachChartClickLinks(mount);
  } catch (err) {
    console.debug('Error in renderOptionChainMatrixStandalone:', err);
  }
}
