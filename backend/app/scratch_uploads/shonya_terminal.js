/**
 * ShonyaBot & Live Web Trading Terminal Component
 * Features:
 * - Real Broker Fyers Integration & Live Broker P&L Tracking (Zero Theoretical Guesswork)
 * - Safe Mode Switch: Paper Simulator vs Live Fyers Broker
 * - Manual Option Trading Cockpit (Buy CE / Buy PE directly from chart setup)
 * - MyBullAndBear AI System Integration & One-Click Execution
 * - Dynamic On-The-Fly Target 1, Target 2 & Stop-Loss Modification
 * - Automated Breakeven Armor (SL Ratchet to Entry + 1%)
 * - Emergency "Square Off All" Kill Switch
 */

import { ApiClient } from '../api.js';
import { store } from '../state.js';

let refreshTimer = null;
let currentSymbol = 'NIFTY';
let selectedStrike = null;
let selectedOptionType = 'CE';
let selectedLots = 1;
let currentSpot = 0;
let chainStrikes = [];
let aiSignal = null;
let selectedOverviewIndices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'];
let lastOverviewData = null;

const LOT_SIZES = {
  NIFTY: 65,
  BANKNIFTY: 30,
  FINNIFTY: 60,
  MIDCPNIFTY: 120
};

export async function renderShonyaTerminal(container) {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }

  container.innerHTML = `
    <div class="shonya-terminal-root" style="padding: 16px; max-width: 1600px; margin: 0 auto; color: #f1f5f9; font-family: 'Inter', -apple-system, sans-serif;">
      
      <!-- Top Command Bar: Status, Mode Switch, Broker Funds & Kill Switch -->
      <div class="shonya-top-bar" style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 12px; padding: 14px 20px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); margin-bottom: 20px;">
        <div style="display: flex; align-items: center; gap: 14px;">
          <div style="width: 42px; height: 42px; border-radius: 10px; background: linear-gradient(135deg, #8b5cf6, #3b82f6); display: flex; align-items: center; justify-content: center; font-size: 22px; box-shadow: 0 0 15px rgba(139,92,246,0.5);">
            🤖
          </div>
          <div>
            <div style="font-size: 18px; font-weight: 800; letter-spacing: 0.5px; display: flex; align-items: center; gap: 8px;">
              <span>SHONYA BOT</span>
              <span id="shonya-power-badge" class="badge" style="background: #334155; color: #94a3b8; font-size: 11px; padding: 2px 8px; border-radius: 6px;">CHECKING...</span>
            </div>
            <div style="font-size: 12px; color: #94a3b8;">MyBullAndBear AI Institutional Execution Engine & Manual Terminal</div>
          </div>
        </div>

        <div style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap;">
          <!-- Master Power Toggle -->
          <button id="btn-toggle-power" class="btn" style="background: #1e293b; border: 1px solid #475569; color: #f8fafc; font-weight: 600; padding: 8px 16px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; gap: 8px;">
            <span id="power-icon">⚡</span>
            <span id="power-text">Toggle Bot</span>
          </button>

          <!-- Execution Mode Toggle (Paper vs Live Fyers) -->
          <div style="display: flex; align-items: center; background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 4px;">
            <button id="btn-mode-paper" style="background: #0284c7; color: #fff; border: none; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer; transition: 0.2s;">
              📝 PAPER
            </button>
            <button id="btn-mode-live" style="background: transparent; color: #64748b; border: none; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer; transition: 0.2s;">
              🔥 LIVE FYERS
            </button>
          </div>

          <!-- Fyers Broker Status & Balance -->
          <div id="fyers-hud-box" style="background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 6px 14px; font-size: 12px; display: flex; flex-direction: column; justify-content: center;">
            <div style="color: #94a3b8; display: flex; align-items: center; gap: 6px;">
              <span id="fyers-dot" style="width: 8px; height: 8px; border-radius: 50%; background: #eab308; display: inline-block;"></span>
              <span id="fyers-status-label">Broker: Connecting</span>
            </div>
            <div style="font-weight: 700; color: #38bdf8;" id="fyers-balance-label">Avail: ₹--</div>
          </div>

          <!-- Emergency Square Off All Kill-Switch -->
          <button id="btn-squareoff-all" style="background: linear-gradient(135deg, #ef4444, #b91c1c); color: #fff; border: none; font-weight: 800; font-size: 12px; padding: 10px 18px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; gap: 6px; box-shadow: 0 4px 15px rgba(239,68,68,0.4); transition: transform 0.15s;">
            <span>🚨</span>
            <span>SQUARE OFF ALL</span>
          </button>
        </div>
      </div>

      <!-- Live Institutional Signal Decision Matrix Mount -->
      <div id="shonya-signal-matrix-card" style="margin-bottom: 22px;"></div>

      <!-- Institutional AI Multi-Index Market Intelligence Card -->
      <div id="ai-market-overview-card" style="background: linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 27, 75, 0.9)); border: 1px solid rgba(139, 92, 246, 0.4); border-radius: 14px; padding: 18px 22px; margin-bottom: 22px; box-shadow: 0 10px 35px rgba(0,0,0,0.45);">
        
        <!-- Top Bar: Title & Model Badges -->
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <div style="width: 40px; height: 40px; border-radius: 10px; background: linear-gradient(135deg, #8b5cf6, #3b82f6); display: flex; align-items: center; justify-content: center; font-size: 20px; box-shadow: 0 0 18px rgba(139,92,246,0.6);">
              🧠
            </div>
            <div>
              <div style="font-size: 16px; font-weight: 800; letter-spacing: 0.5px; color: #f8fafc; display: flex; align-items: center; gap: 8px;">
                <span>INSTITUTIONAL AI MARKET INTELLIGENCE</span>
                <span style="font-size: 10px; background: rgba(139, 92, 246, 0.25); color: #c4b5fd; padding: 2px 8px; border-radius: 6px; border: 1px solid rgba(139, 92, 246, 0.4); font-weight: 700;">CROSS-ASSET DEEP DIVE</span>
              </div>
              <div style="font-size: 12px; color: #94a3b8;">
                Real-Time Multi-Index Synthesis: Broker OHLC Trajectory + Strike OI Changes + PCR + Confluence Alignment
              </div>
            </div>
          </div>

          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 11px; color: #94a3b8; background: rgba(0,0,0,0.3); padding: 5px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.06); font-family: 'JetBrains Mono', monospace;">
              ⚡ LPU Accelerated Engine
            </span>
          </div>
        </div>

        <!-- Controls: Multi-Index Selector Pills & Action Button -->
        <div style="background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.07); border-radius: 10px; padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
          
          <!-- Index Selection Pills -->
          <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
            <span style="font-size: 12px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;">MONITORED INDICES:</span>
            
            <div id="ai-overview-pills-container" style="display: flex; gap: 8px; flex-wrap: wrap;">
              ${['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'].map(sym => `
                <button class="ai-overview-pill" data-sym="${sym}" style="background: rgba(139, 92, 246, 0.25); color: #f1f5f9; border: 1px solid #8b5cf6; padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: all 0.15s;">
                  <span class="pill-check" style="color: #34d399;">✓</span>
                  <span>${sym}</span>
                </button>
              `).join('')}
            </div>

            <button id="btn-overview-select-all" style="background: transparent; color: #38bdf8; border: 1px dashed rgba(56, 189, 248, 0.4); padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer;">
              Select All
            </button>
            <button id="btn-overview-clear" style="background: transparent; color: #64748b; border: 1px dashed rgba(100, 116, 139, 0.4); padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer;">
              Clear
            </button>
          </div>

          <!-- Primary Action Button -->
          <button id="btn-get-ai-overview" style="background: linear-gradient(135deg, #8b5cf6, #3b82f6); color: #fff; border: none; font-weight: 800; font-size: 13px; padding: 10px 22px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; gap: 8px; box-shadow: 0 4px 18px rgba(139,92,246,0.45); transition: transform 0.15s, box-shadow 0.15s;">
            <span id="ai-overview-btn-icon" style="font-size: 15px;">🔮</span>
            <span id="ai-overview-btn-text">Get AI Market View</span>
          </button>
        </div>

        <!-- Output Container -->
        <div id="ai-market-overview-mount" style="margin-top: 16px;">
          <div style="background: rgba(0,0,0,0.18); border: 1px dashed rgba(255,255,255,0.08); border-radius: 10px; padding: 22px; text-align: center; color: #94a3b8; font-size: 13px;">
            <div style="font-size: 26px; margin-bottom: 6px;">📊 🧠 📈</div>
            <div style="font-weight: 700; color: #e2e8f0; font-size: 14px; margin-bottom: 6px;">Ready to Synthesize Cross-Asset Market Intelligence</div>
            <div>Select your target indices above and click <strong style="color: #c4b5fd;">"Get AI Market View"</strong> to share live broker OHLC trajectory, strike-level Put/Call additions, PCR, and confluence directives with the institutional AI engine.</div>
          </div>
        </div>

      </div>

      <!-- Main Grid: Cockpit & MyBullAndBear AI Card on Left, Live Positions on Right -->
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
        
        <!-- LEFT COLUMN: Chart Setup, Manual Trading Cockpit & AI Signal -->
        <div style="display: flex; flex-direction: column; gap: 20px;">
          
          <!-- Symbol & Strike Selection Bar -->
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
              <div style="display: flex; gap: 8px;">
                ${['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'].map(sym => `
                  <button class="sym-selector-btn ${sym === currentSymbol ? 'active' : ''}" data-sym="${sym}" style="background: ${sym === currentSymbol ? '#8b5cf6' : '#1e293b'}; color: #fff; border: 1px solid ${sym === currentSymbol ? '#a78bfa' : '#334155'}; padding: 6px 12px; border-radius: 6px; font-weight: 700; font-size: 12px; cursor: pointer;">
                    ${sym}
                  </button>
                `).join('')}
              </div>
              <div style="text-align: right;">
                <div style="font-size: 11px; color: #94a3b8;">SPOT PRICE</div>
                <div id="spot-price-label" style="font-size: 18px; font-weight: 800; color: #38bdf8;">--</div>
              </div>
            </div>

            <!-- ATM Strike Quick Strip -->
            <div style="margin-bottom: 12px;">
              <div style="font-size: 11px; color: #94a3b8; margin-bottom: 6px; font-weight: 600;">QUICK STRIKE SELECTOR (ATM ± 2):</div>
              <div id="quick-strikes-container" style="display: flex; gap: 6px; flex-wrap: wrap;">
                <span style="font-size: 12px; color: #64748b;">Loading strikes...</span>
              </div>
            </div>
          </div>

          <!-- MyBullAndBear AI Institutional Intelligence Card -->
          <div id="ai-advisor-card" style="background: linear-gradient(135deg, rgba(30, 27, 75, 0.7), rgba(15, 23, 42, 0.85)); border: 1px solid rgba(139, 92, 246, 0.4); border-radius: 12px; padding: 16px; box-shadow: 0 4px 20px rgba(139,92,246,0.15);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 18px;">🧠</span>
                <span style="font-weight: 800; font-size: 14px; color: #c4b5fd;">MYBULLANDBEAR AI ADVISOR RECOMMENDATION</span>
              </div>
              <span id="ai-conviction-badge" class="badge" style="background: #334155; color: #cbd5e1; font-weight: 700; font-size: 11px; padding: 3px 8px; border-radius: 6px;">
                ANALYZING...
              </span>
            </div>

            <div id="ai-content-body">
              <div style="color: #94a3b8; font-size: 13px; line-height: 1.5; margin-bottom: 12px;" id="ai-thesis-text">
                Fetching institutional thesis from MyBullAndBear AI System...
              </div>

              <div id="ai-params-strip" style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 8px; margin-bottom: 12px; font-size: 12px;">
                <div>
                  <div style="color: #64748b;">ACTION</div>
                  <div id="ai-action-val" style="font-weight: 800; color: #e2e8f0;">STANDBY</div>
                </div>
                <div>
                  <div style="color: #64748b;">STRIKE</div>
                  <div id="ai-strike-val" style="font-weight: 800; color: #e2e8f0;">--</div>
                </div>
                <div>
                  <div style="color: #64748b;">ENTRY / T1</div>
                  <div id="ai-targets-val" style="font-weight: 800; color: #10b981;">--</div>
                </div>
                <div>
                  <div style="color: #64748b;">STOP LOSS</div>
                  <div id="ai-sl-val" style="font-weight: 800; color: #ef4444;">--</div>
                </div>
              </div>

              <button id="btn-execute-ai" style="width: 100%; background: linear-gradient(135deg, #8b5cf6, #6366f1); color: #fff; border: none; padding: 10px; border-radius: 8px; font-weight: 800; font-size: 13px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; box-shadow: 0 4px 15px rgba(139,92,246,0.3);">
                <span>⚡</span>
                <span>EXECUTE MYBULLANDBEAR AI SIGNAL NOW</span>
              </button>
            </div>
          </div>

          <!-- Manual Chart Trading Cockpit -->
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 18px;">
            <div style="font-size: 15px; font-weight: 800; margin-bottom: 14px; display: flex; align-items: center; gap: 8px;">
              <span>🕹️</span>
              <span>MANUAL TRADING COCKPIT (DIRECT FROM CHART)</span>
            </div>

            <!-- Strike & Option Type Selector -->
            <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 12px; margin-bottom: 14px;">
              <div>
                <label style="font-size: 11px; color: #94a3b8; display: block; margin-bottom: 4px;">CONTRACT STRIKE</label>
                <select id="manual-strike-select" style="width: 100%; background: #1e293b; border: 1px solid #475569; color: #fff; padding: 8px 10px; border-radius: 8px; font-weight: 600; font-size: 13px;">
                  <option value="">Select Strike</option>
                </select>
              </div>

              <div>
                <label style="font-size: 11px; color: #94a3b8; display: block; margin-bottom: 4px;">LOTS (1 Lot = <span id="lot-size-text">65</span>)</label>
                <div style="display: flex; align-items: center; gap: 4px;">
                  <button id="btn-lot-minus" style="background: #334155; color: #fff; border: none; width: 32px; height: 35px; border-radius: 6px; font-weight: 800; cursor: pointer;">-</button>
                  <input type="number" id="manual-lots-input" value="1" min="1" max="10" style="width: 50px; background: #1e293b; border: 1px solid #475569; color: #fff; text-align: center; border-radius: 6px; padding: 6px; font-weight: 700;" />
                  <button id="btn-lot-plus" style="background: #334155; color: #fff; border: none; width: 32px; height: 35px; border-radius: 6px; font-weight: 800; cursor: pointer;">+</button>
                </div>
              </div>
            </div>

            <!-- Risk Management: T1, T2, SL Inputs with presets -->
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 16px;">
              <div>
                <label style="font-size: 11px; color: #34d399; font-weight: 700; display: block; margin-bottom: 4px;">TARGET 1 (Scalp)</label>
                <input type="number" id="manual-t1-input" step="0.5" placeholder="e.g. +14%" style="width: 100%; background: #1e293b; border: 1px solid #059669; color: #fff; padding: 8px; border-radius: 6px; font-size: 13px; font-weight: 600;" />
                <div style="font-size: 10px; color: #6ee7b7; margin-top: 3px;">Auto-Breakeven at T1</div>
              </div>

              <div>
                <label style="font-size: 11px; color: #38bdf8; font-weight: 700; display: block; margin-bottom: 4px;">TARGET 2 (Runner)</label>
                <input type="number" id="manual-t2-input" step="0.5" placeholder="e.g. +35%" style="width: 100%; background: #1e293b; border: 1px solid #0284c7; color: #fff; padding: 8px; border-radius: 6px; font-size: 13px; font-weight: 600;" />
                <div style="font-size: 10px; color: #7dd3fc; margin-top: 3px;">Full Exit Target</div>
              </div>

              <div>
                <label style="font-size: 11px; color: #f87171; font-weight: 700; display: block; margin-bottom: 4px;">STOP LOSS</label>
                <input type="number" id="manual-sl-input" step="0.5" placeholder="e.g. -14%" style="width: 100%; background: #1e293b; border: 1px solid #dc2626; color: #fff; padding: 8px; border-radius: 6px; font-size: 13px; font-weight: 600;" />
                <div style="font-size: 10px; color: #fca5a5; margin-top: 3px;">Hard Cut Protection</div>
              </div>
            </div>

            <!-- Big Action Execution Buttons: BUY CE and BUY PE -->
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
              <button id="btn-buy-ce" style="background: linear-gradient(135deg, #10b981, #059669); color: #fff; border: none; padding: 14px; border-radius: 10px; font-weight: 900; font-size: 15px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 4px; box-shadow: 0 4px 20px rgba(16,185,129,0.3); transition: transform 0.1s;">
                <span>🚀 BUY CE (CALL)</span>
                <span style="font-size: 11px; font-weight: 600; opacity: 0.9;">BULLISH MOMENTUM</span>
              </button>

              <button id="btn-buy-pe" style="background: linear-gradient(135deg, #ef4444, #dc2626); color: #fff; border: none; padding: 14px; border-radius: 10px; font-weight: 900; font-size: 15px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 4px; box-shadow: 0 4px 20px rgba(239,68,68,0.3); transition: transform 0.1s;">
                <span>🔻 BUY PE (PUT)</span>
                <span style="font-size: 11px; font-weight: 600; opacity: 0.9;">BEARISH BREAKDOWN</span>
              </button>
            </div>
          </div>
        </div>

        <!-- RIGHT COLUMN: Active Positions HUD & Trade Journal -->
        <div style="display: flex; flex-direction: column; gap: 20px;">
          
          <!-- Active Positions Real-Time HUD (Broker Direct P&L) -->
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 18px; min-height: 280px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 16px;">📊</span>
                <span style="font-weight: 800; font-size: 15px;">LIVE ACTIVE POSITIONS</span>
                <span id="pos-count-badge" class="badge" style="background: #334155; color: #fff; font-size: 11px; padding: 2px 7px; border-radius: 6px;">0 OPEN</span>
              </div>
              <div style="font-size: 11px; color: #94a3b8;">
                Real-Time Broker Telemetry <span style="color: #10b981;">● Active</span>
              </div>
            </div>

            <!-- Positions Container -->
            <div id="positions-container" style="display: flex; flex-direction: column; gap: 12px;">
              <div style="text-align: center; padding: 40px; color: #64748b; font-size: 13px;">
                No active positions open. Use the Manual Cockpit or MyBullAndBear AI signal to enter.
              </div>
            </div>
          </div>

          <!-- Trade Performance Journal & Metrics -->
          <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
              <div style="font-weight: 800; font-size: 14px; display: flex; align-items: center; gap: 6px;">
                <span>📜</span>
                <span>CLOSED TRADES JOURNAL</span>
              </div>
              <div id="journal-metrics-strip" style="display: flex; gap: 12px; font-size: 12px; font-weight: 700;">
                <span style="color: #94a3b8;">Win Rate: <strong id="metric-win-rate" style="color: #38bdf8;">--%</strong></span>
                <span style="color: #94a3b8;">Net P&L: <strong id="metric-net-pnl" style="color: #10b981;">₹--</strong></span>
              </div>
            </div>

            <div style="max-height: 240px; overflow-y: auto;">
              <table style="width: 100%; border-collapse: collapse; font-size: 12px; text-align: left;">
                <thead>
                  <tr style="border-bottom: 1px solid #334155; color: #64748b;">
                    <th style="padding: 6px;">TIME</th>
                    <th style="padding: 6px;">CONTRACT</th>
                    <th style="padding: 6px;">ENTRY</th>
                    <th style="padding: 6px;">EXIT</th>
                    <th style="padding: 6px;">REASON</th>
                    <th style="padding: 6px; text-align: right;">NET P&L</th>
                  </tr>
                </thead>
                <tbody id="journal-tbody">
                  <tr>
                    <td colspan="6" style="text-align: center; padding: 20px; color: #64748b;">Loading trade history...</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

      </div>

    </div>
  `;

  // Attach event listeners
  setupEventListeners(container);

  // Initial symbol strike and AI signal load
  await loadStrikesForSymbol(currentSymbol);
  await loadAISignalForSymbol(currentSymbol);

  // Initial data poll
  await refreshShonyaData();

  // Start polling loop every 2 seconds
  refreshTimer = setInterval(refreshShonyaData, 2000);
}

function setupEventListeners(container) {
  // Symbol switch
  container.querySelectorAll('.sym-selector-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const sym = e.target.dataset.sym;
      if (!sym) return;
      currentSymbol = sym;
      container.querySelectorAll('.sym-selector-btn').forEach(b => {
        b.style.background = (b.dataset.sym === sym) ? '#8b5cf6' : '#1e293b';
        b.style.borderColor = (b.dataset.sym === sym) ? '#a78bfa' : '#334155';
      });
      const lotSizeEl = document.getElementById('lot-size-text');
      if (lotSizeEl) lotSizeEl.textContent = LOT_SIZES[sym] || 65;

      // Show immediate loading indicator in strikes container
      const qContainer = document.getElementById('quick-strikes-container');
      if (qContainer) qContainer.innerHTML = '<span style="font-size: 12px; color: #94a3b8;">Loading strikes for ' + sym + '...</span>';

      await loadStrikesForSymbol(sym);
      await loadAISignalForSymbol(sym);
    });
  });

  // Lot increment/decrement
  const lotInput = document.getElementById('manual-lots-input');
  document.getElementById('btn-lot-plus')?.addEventListener('click', () => {
    let v = parseInt(lotInput.value) || 1;
    if (v < 10) lotInput.value = v + 1;
    selectedLots = parseInt(lotInput.value);
  });
  document.getElementById('btn-lot-minus')?.addEventListener('click', () => {
    let v = parseInt(lotInput.value) || 1;
    if (v > 1) lotInput.value = v - 1;
    selectedLots = parseInt(lotInput.value);
  });
  lotInput?.addEventListener('change', () => {
    selectedLots = Math.max(1, Math.min(10, parseInt(lotInput.value) || 1));
  });

  // Toggle Bot Power
  document.getElementById('btn-toggle-power')?.addEventListener('click', async () => {
    const status = await ApiClient.fetchShonyaStatus();
    const currentState = status?.is_active ?? false;
    const res = await ApiClient.toggleShonyaBot(!currentState);
    if (res?.success) {
      await refreshShonyaData();
    }
  });

  // Mode: Paper vs Live
  document.getElementById('btn-mode-paper')?.addEventListener('click', async () => {
    await ApiClient.setShonyaMode('PAPER');
    await refreshShonyaData();
  });
  document.getElementById('btn-mode-live')?.addEventListener('click', async () => {
    const confirmLive = confirm(
      "⚠️ WARNING: You are switching to LIVE FYERS EXECUTION MODE!\n\n" +
      "Actual orders will be submitted to the Fyers exchange gateway with real capital.\n" +
      "Are you sure you want to enable LIVE mode?"
    );
    if (confirmLive) {
      try {
        const res = await ApiClient.setShonyaMode('LIVE');
        if (res?.success) {
          await refreshShonyaData();
        }
      } catch (err) {
        alert("Failed to switch to LIVE mode: " + (err.message || err));
      }
    }
  });

  // Square Off All
  document.getElementById('btn-squareoff-all')?.addEventListener('click', async () => {
    const confirmExit = confirm("🚨 EMERGENCY ACTION: Square off ALL open positions immediately?");
    if (confirmExit) {
      try {
        const res = await ApiClient.squareoffAllShonya();
        alert(res?.message || "All positions squared off!");
        await refreshShonyaData();
      } catch (err) {
        alert("Square off error: " + (err.message || err));
      }
    }
  });

  // Execute MyBullAndBear AI Signal
  document.getElementById('btn-execute-ai')?.addEventListener('click', async () => {
    try {
      const res = await ApiClient.executeGrokTrade(currentSymbol);
      if (res?.success) {
        alert(`MyBullAndBear AI Signal Executed: ${res.message}`);
        await refreshShonyaData();
      }
    } catch (err) {
      alert("Execution failed: " + (err.message || err));
    }
  });

  // Buy CE
  document.getElementById('btn-buy-ce')?.addEventListener('click', () => {
    executeManualOrder('CE');
  });

  // Buy PE
  document.getElementById('btn-buy-pe')?.addEventListener('click', () => {
    executeManualOrder('PE');
  });

  // AI Multi-Index Overview Controls
  container.querySelectorAll('.ai-overview-pill').forEach(pill => {
    pill.addEventListener('click', (e) => {
      const btn = e.currentTarget;
      const sym = btn.dataset.sym;
      if (!sym) return;
      const idx = selectedOverviewIndices.indexOf(sym);
      if (idx > -1) {
        if (selectedOverviewIndices.length === 1) {
          alert("At least one index must be selected.");
          return;
        }
        selectedOverviewIndices.splice(idx, 1);
        btn.style.background = '#1e293b';
        btn.style.borderColor = '#334155';
        btn.style.color = '#94a3b8';
        const check = btn.querySelector('.pill-check');
        if (check) {
          check.textContent = '○';
          check.style.color = '#64748b';
        }
      } else {
        selectedOverviewIndices.push(sym);
        btn.style.background = 'rgba(139, 92, 246, 0.25)';
        btn.style.borderColor = '#8b5cf6';
        btn.style.color = '#f1f5f9';
        const check = btn.querySelector('.pill-check');
        if (check) {
          check.textContent = '✓';
          check.style.color = '#34d399';
        }
      }
    });
  });

  // Select All Indices
  document.getElementById('btn-overview-select-all')?.addEventListener('click', () => {
    selectedOverviewIndices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'];
    container.querySelectorAll('.ai-overview-pill').forEach(btn => {
      btn.style.background = 'rgba(139, 92, 246, 0.25)';
      btn.style.borderColor = '#8b5cf6';
      btn.style.color = '#f1f5f9';
      const check = btn.querySelector('.pill-check');
      if (check) {
        check.textContent = '✓';
        check.style.color = '#34d399';
      }
    });
  });

  // Clear Indices (resets to current symbol)
  document.getElementById('btn-overview-clear')?.addEventListener('click', () => {
    selectedOverviewIndices = [currentSymbol];
    container.querySelectorAll('.ai-overview-pill').forEach(btn => {
      const sym = btn.dataset.sym;
      const check = btn.querySelector('.pill-check');
      if (sym === currentSymbol) {
        btn.style.background = 'rgba(139, 92, 246, 0.25)';
        btn.style.borderColor = '#8b5cf6';
        btn.style.color = '#f1f5f9';
        if (check) {
          check.textContent = '✓';
          check.style.color = '#34d399';
        }
      } else {
        btn.style.background = '#1e293b';
        btn.style.borderColor = '#334155';
        btn.style.color = '#94a3b8';
        if (check) {
          check.textContent = '○';
          check.style.color = '#64748b';
        }
      }
    });
  });

  // Fetch AI Market View Button
  document.getElementById('btn-get-ai-overview')?.addEventListener('click', async () => {
    await executeFetchAIMarketOverview();
  });
}

async function executeManualOrder(optionType) {
  const strikeSelect = document.getElementById('manual-strike-select');
  const strike = parseFloat(strikeSelect.value);
  if (!strike || strike <= 0) {
    alert("Please select a strike price before placing the trade.");
    return;
  }

  const lots = parseInt(document.getElementById('manual-lots-input').value) || 1;
  const t1 = parseFloat(document.getElementById('manual-t1-input').value) || null;
  const t2 = parseFloat(document.getElementById('manual-t2-input').value) || null;
  const sl = parseFloat(document.getElementById('manual-sl-input').value) || null;

  try {
    const res = await ApiClient.placeManualTrade({
      symbol: currentSymbol,
      strike: strike,
      option_type: optionType,
      lots: lots,
      target1: t1,
      target2: t2,
      stop_loss: sl,
      thesis: `Manual ${optionType} Order from Chart Setup`
    });

    if (res?.success) {
      alert(`Trade Placed: ${res.message}`);
      await refreshShonyaData();
    }
  } catch (err) {
    alert("Order placement failed: " + (err.message || err));
  }
}

async function loadStrikesForSymbol(symbol) {
  try {
    const chainRes = await ApiClient.fetchOptionChain(symbol);
    if (!chainRes) return;

    // Correctly resolve spot price from either spot_price or records.underlyingValue
    currentSpot = parseFloat(chainRes.spot_price || chainRes.records?.underlyingValue || 0);
    const spotEl = document.getElementById('spot-price-label');
    if (spotEl) {
      spotEl.textContent = currentSpot > 0 ? `₹${currentSpot.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}` : '--';
    }

    // Correctly extract strikes from strikes array or records.data
    let rawStrikes = [];
    if (Array.isArray(chainRes.strikes) && chainRes.strikes.length > 0) {
      rawStrikes = chainRes.strikes.map(s => parseFloat(s.strikePrice || s.strike)).filter(s => s > 0);
    } else if (chainRes.records && Array.isArray(chainRes.records.data)) {
      rawStrikes = chainRes.records.data.map(d => parseFloat(d.strikePrice)).filter(s => s > 0);
    }

    chainStrikes = Array.from(new Set(rawStrikes)).sort((a, b) => a - b);
    if (chainStrikes.length === 0) {
      console.warn('No strikes parsed for', symbol);
      return;
    }

    // Resolve ATM strike
    const atmStrike = parseFloat(chainRes.atm_strike || 0);
    let closest = chainStrikes[0];
    let minDiff = 999999;
    chainStrikes.forEach(s => {
      const diff = Math.abs(s - (atmStrike > 0 ? atmStrike : currentSpot));
      if (diff < minDiff) {
        minDiff = diff;
        closest = s;
      }
    });

    // Populate strike select dropdown
    const select = document.getElementById('manual-strike-select');
    if (select) {
      const atmIdx = chainStrikes.indexOf(closest);
      const start = Math.max(0, atmIdx - 8);
      const end = Math.min(chainStrikes.length, atmIdx + 9);
      const subset = chainStrikes.slice(start, end);

      select.innerHTML = subset.map(s => `
        <option value="${s}" ${s === closest ? 'selected' : ''}>
          ${s} ${s === closest ? '(★ ATM)' : (s < closest ? '(ITM CE / OTM PE)' : '(OTM CE / ITM PE)')}
        </option>
      `).join('');
      selectedStrike = closest;
    }

    // Populate Quick Chips (ATM ± 2 strikes)
    const quickContainer = document.getElementById('quick-strikes-container');
    if (quickContainer) {
      const atmIdx = chainStrikes.indexOf(closest);
      const quickSubset = chainStrikes.slice(Math.max(0, atmIdx - 2), Math.min(chainStrikes.length, atmIdx + 3));
      quickContainer.innerHTML = quickSubset.map(s => {
        const isAtm = (s === closest);
        return `
          <button class="quick-stk-chip" data-stk="${s}" style="background: ${isAtm ? '#8b5cf6' : '#1e293b'}; color: #fff; border: 1px solid ${isAtm ? '#a78bfa' : '#334155'}; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; transition: 0.15s;">
            ${s} ${isAtm ? '★ ATM' : ''}
          </button>
        `;
      }).join('');

      quickContainer.querySelectorAll('.quick-stk-chip').forEach(chip => {
        chip.addEventListener('click', (e) => {
          const stk = parseFloat(e.target.dataset.stk);
          if (stk && select) {
            select.value = stk;
            selectedStrike = stk;
            quickContainer.querySelectorAll('.quick-stk-chip').forEach(c => {
              const matches = parseFloat(c.dataset.stk) === stk;
              c.style.background = matches ? '#8b5cf6' : '#1e293b';
              c.style.borderColor = matches ? '#a78bfa' : '#334155';
            });
          }
        });
      });
    }
  } catch (err) {
    console.warn('Error loading strikes for Shonya:', err);
  }
}

async function loadAISignalForSymbol(symbol) {
  try {
    const res = await ApiClient.fetchGrokRecommendation(symbol);
    if (!res?.recommendation) return;

    const rec = res.recommendation;
    aiSignal = rec;

    const convictionBadge = document.getElementById('ai-conviction-badge');
    const thesisText = document.getElementById('ai-thesis-text');
    const actionVal = document.getElementById('ai-action-val');
    const strikeVal = document.getElementById('ai-strike-val');
    const targetsVal = document.getElementById('ai-targets-val');
    const slVal = document.getElementById('ai-sl-val');

    if (convictionBadge) {
      convictionBadge.textContent = `${rec.ai_conviction_pct || 75}% CONVICTION`;
      convictionBadge.style.background = (rec.action === 'STANDBY') ? '#334155' : '#8b5cf6';
    }

    if (thesisText) {
      const rawThesis = rec.institutional_thesis || 'Market telemetry evaluated. No immediate trigger.';
      if (rawThesis.includes('TACTICAL REGIME:') || rawThesis.includes('TACTICAL BRIEF:') || rawThesis.includes('PLAYBOOK:')) {
        let formatted = rawThesis
          .replace(/\n/g, '<br/>')
          .replace(/TACTICAL (REGIME|BRIEF):/g, '<div style="margin-bottom: 6px;"><span style="color: #38bdf8; font-weight: 800; letter-spacing: 0.3px;">TACTICAL $1:</span>')
          .replace(/PLAYBOOK:/g, '</div><div style="margin-top: 6px;"><span style="color: #c084fc; font-weight: 800; letter-spacing: 0.3px;">PLAYBOOK:</span></div><div style="margin-top: 4px; display: flex; flex-direction: column; gap: 4px;">')
          .replace(/[•\s]*BULL TRIGGER:/g, '<div style="background: rgba(16,185,129,0.08); padding: 4px 8px; border-radius: 4px; border-left: 2px solid #10b981;"><span style="color: #34d399; font-weight: 700;">• BULL TRIGGER:</span>')
          .replace(/[•\s]*BEAR TRIGGER:/g, '</div><div style="background: rgba(239,68,68,0.08); padding: 4px 8px; border-radius: 4px; border-left: 2px solid #ef4444;"><span style="color: #f87171; font-weight: 700;">• BEAR TRIGGER:</span>')
          .replace(/[•\s]*STATUS:\s*(STANDBY[^\.]*)/gi, '</div><div style="margin-top: 4px; color: #94a3b8; font-weight: 700;"><span style="color: #cbd5e1;">• STATUS:</span> $1</div>')
          .replace(/[•\s]*STATUS:\s*(BUY CALL[^\.]*)/gi, '</div><div style="margin-top: 4px; color: #10b981; font-weight: 700;"><span style="color: #10b981;">• STATUS:</span> $1</div>')
          .replace(/[•\s]*STATUS:\s*(BUY PUT[^\.]*)/gi, '</div><div style="margin-top: 4px; color: #ef4444; font-weight: 700;"><span style="color: #ef4444;">• STATUS:</span> $1</div>')
          .replace(/->/g, '➔');
        thesisText.innerHTML = formatted;
      } else {
        thesisText.textContent = rawThesis;
      }
    }

    if (actionVal) {
      actionVal.textContent = rec.action || 'STANDBY';
      actionVal.style.color = (rec.action === 'BUY_CALL') ? '#10b981' : (rec.action === 'BUY_PUT' ? '#ef4444' : '#94a3b8');
    }

    if (strikeVal) strikeVal.textContent = `${rec.strike || '--'} ${rec.option_type || ''}`;
    if (targetsVal) targetsVal.textContent = `₹${rec.entry_price || 0} → ₹${rec.scalp_target1 || 0}`;
    if (slVal) slVal.textContent = `₹${rec.stop_loss || 0}`;

    // Auto-populate manual inputs if blank
    const t1Input = document.getElementById('manual-t1-input');
    const t2Input = document.getElementById('manual-t2-input');
    const slInput = document.getElementById('manual-sl-input');
    if (t1Input && !t1Input.value && rec.scalp_target1) t1Input.value = rec.scalp_target1;
    if (t2Input && !t2Input.value && rec.runner_target2) t2Input.value = rec.runner_target2;
    if (slInput && !slInput.value && rec.stop_loss) slInput.value = rec.stop_loss;

  } catch (err) {
    console.debug('Error loading AI signal:', err);
  }
}

async function refreshShonyaData() {
  try {
    const status = await ApiClient.fetchShonyaStatus();
    if (!status) return;

    // Power toggle & badge
    const powerBadge = document.getElementById('shonya-power-badge');
    const powerBtn = document.getElementById('btn-toggle-power');
    const powerIcon = document.getElementById('power-icon');
    const powerText = document.getElementById('power-text');

    if (powerBadge && powerBtn) {
      if (status.is_active) {
        powerBadge.textContent = 'ACTIVE';
        powerBadge.style.background = '#10b981';
        powerBadge.style.color = '#fff';
        if (powerIcon) powerIcon.textContent = '⏸️';
        if (powerText) powerText.textContent = 'Pause Bot';
      } else {
        powerBadge.textContent = 'PAUSED';
        powerBadge.style.background = '#334155';
        powerBadge.style.color = '#94a3b8';
        if (powerIcon) powerIcon.textContent = '▶️';
        if (powerText) powerText.textContent = 'Activate Bot';
      }
    }

    // Execution Mode buttons
    const btnPaper = document.getElementById('btn-mode-paper');
    const btnLive = document.getElementById('btn-mode-live');
    if (btnPaper && btnLive) {
      if (status.trading_mode === 'LIVE') {
        btnLive.style.background = '#8b5cf6';
        btnLive.style.color = '#fff';
        btnPaper.style.background = 'transparent';
        btnPaper.style.color = '#64748b';
      } else {
        btnPaper.style.background = '#0284c7';
        btnPaper.style.color = '#fff';
        btnLive.style.background = 'transparent';
        btnLive.style.color = '#64748b';
      }
    }

    // Fyers HUD
    const fyersDot = document.getElementById('fyers-dot');
    const fyersStatus = document.getElementById('fyers-status-label');
    const fyersBal = document.getElementById('fyers-balance-label');

    if (fyersDot && fyersStatus && fyersBal) {
      if (status.fyers_connected) {
        fyersDot.style.background = '#10b981';
        fyersStatus.textContent = 'Fyers: Connected';
        fyersBal.textContent = `Avail: ₹${(status.fyers_available_balance || 0).toLocaleString('en-IN')}`;
      } else {
        fyersDot.style.background = '#ef4444';
        fyersStatus.textContent = 'Fyers: Disconnected';
        fyersBal.textContent = 'Avail: ₹--';
      }
    }

    // Positions render
    const posRes = await ApiClient.fetchShonyaPositions();
    const positions = posRes?.positions || [];
    renderPositions(positions);

    // Closed Journal & metrics
    const historyRes = await ApiClient.fetchShonyaHistory(20);
    renderJournal(historyRes?.history || [], status.metrics || {});

    // Fetch and render Institutional Signal Decision Matrix
    try {
      const matrixRes = await ApiClient.fetchShonyaMatrix();
      if (matrixRes && matrixRes.matrix) {
        _renderSignalDecisionMatrix(document.getElementById('shonya-signal-matrix-card'), matrixRes);
      }
    } catch (eMat) {
      console.debug('Error refreshing signal matrix:', eMat);
    }

  } catch (err) {
    console.debug('Error refreshing Shonya terminal:', err);
  }
}

function _renderSignalDecisionMatrix(container, matrixPayload) {
  if (!container) return;
  const rows = matrixPayload?.matrix || [];
  const timeStr = matrixPayload?.current_time_ist || '';
  const isMarketOpen = matrixPayload?.market_open;
  const botActive = matrixPayload?.bot_active;
  const tradingMode = matrixPayload?.trading_mode || 'PAPER';

  const getColorStyle = (state) => {
    if (state === 'CALL') {
      return {
        bg: 'rgba(16, 185, 129, 0.16)',
        border: '1px solid rgba(16, 185, 129, 0.45)',
        text: '#34d399',
        badge: 'background: #059669; color: #fff;'
      };
    } else if (state === 'PUT') {
      return {
        bg: 'rgba(239, 68, 68, 0.16)',
        border: '1px solid rgba(239, 68, 68, 0.45)',
        text: '#f87171',
        badge: 'background: #dc2626; color: #fff;'
      };
    } else {
      // DILEMMA (yellow / white)
      return {
        bg: 'rgba(234, 179, 8, 0.12)',
        border: '1px solid rgba(234, 179, 8, 0.35)',
        text: '#facc15',
        badge: 'background: #ca8a04; color: #000;'
      };
    }
  };

  let rowsHtml = rows.map(r => {
    const cConf = getColorStyle(r.confluence?.state);
    const cAlpha = getColorStyle(r.alphatrend?.state);
    const cAdx = getColorStyle(r.adx?.state);
    const cSm = getColorStyle(r.smart_money?.state);
    const cTime = getColorStyle(r.time_filter?.state);

    const actionBadge = r.overall_action?.badge || 'WAIT';
    const actionReason = r.overall_action?.reason || '';
    const isCall = r.overall_action?.state === 'CALL';
    const isPut = r.overall_action?.state === 'PUT';
    const isHolding = r.overall_action?.action === 'HOLDING_POS';

    let actionBtnStyle = 'padding: 8px 14px; border-radius: 8px; font-weight: 800; font-size: 12px; display: inline-flex; align-items: center; gap: 6px;';
    if (isCall) {
      actionBtnStyle += ' background: linear-gradient(135deg, #10b981, #059669); color: #fff; box-shadow: 0 0 15px rgba(16,185,129,0.5);';
    } else if (isPut) {
      actionBtnStyle += ' background: linear-gradient(135deg, #ef4444, #b91c1c); color: #fff; box-shadow: 0 0 15px rgba(239,68,68,0.5);';
    } else if (isHolding) {
      actionBtnStyle += ' background: rgba(56, 189, 248, 0.2); border: 1px solid #38bdf8; color: #7dd3fc;';
    } else {
      actionBtnStyle += ' background: rgba(234, 179, 8, 0.15); border: 1px solid rgba(234, 179, 8, 0.4); color: #facc15;';
    }

    return `
      <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); transition: background 0.15s;" onmouseover="this.style.background='rgba(255,255,255,0.02)'" onmouseout="this.style.background='transparent'">
        
        <!-- Symbol & Spot -->
        <td style="padding: 14px 12px; font-weight: 800; font-size: 13px; color: #f8fafc; font-family: 'JetBrains Mono', monospace;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="font-size: 14px; color: #c4b5fd;">${r.symbol}</span>
            ${r.has_open_position ? '<span style="font-size: 9px; background: #38bdf8; color: #000; padding: 1px 5px; border-radius: 4px; font-weight: 800;">1 POS OPEN</span>' : ''}
          </div>
          <div style="font-size: 11px; color: #94a3b8; font-weight: 600; margin-top: 2px;">
            Spot: ₹${(r.spot_price || 0).toLocaleString('en-IN', { maximumFractionDigits: 1 })}
          </div>
        </td>

        <!-- Confluence Score (ATM +- 2) -->
        <td style="padding: 10px 8px; text-align: center;">
          <div style="background: ${cConf.bg}; border: ${cConf.border}; color: ${cConf.text}; padding: 6px 10px; border-radius: 8px; font-weight: 700; font-size: 12px; font-family: 'JetBrains Mono', monospace;">
            ${r.confluence?.text || '--'}
          </div>
        </td>

        <!-- AlphaTrend (5M) -->
        <td style="padding: 10px 8px; text-align: center;">
          <div style="background: ${cAlpha.bg}; border: ${cAlpha.border}; color: ${cAlpha.text}; padding: 6px 10px; border-radius: 8px; font-weight: 700; font-size: 12px;">
            ${r.alphatrend?.text || '--'}
          </div>
        </td>

        <!-- ADX (14) Filter -->
        <td style="padding: 10px 8px; text-align: center;">
          <div style="background: ${cAdx.bg}; border: ${cAdx.border}; color: ${cAdx.text}; padding: 6px 10px; border-radius: 8px; font-weight: 700; font-size: 12px; font-family: 'JetBrains Mono', monospace;">
            ${r.adx?.text || '--'}
          </div>
        </td>

        <!-- Smart Money Flow -->
        <td style="padding: 10px 8px; text-align: center;">
          <div style="background: ${cSm.bg}; border: ${cSm.border}; color: ${cSm.text}; padding: 6px 10px; border-radius: 8px; font-weight: 700; font-size: 12px; font-family: 'JetBrains Mono', monospace;">
            ${r.smart_money?.text || '--'}
          </div>
        </td>

        <!-- Time Window -->
        <td style="padding: 10px 8px; text-align: center;">
          <div style="background: ${cTime.bg}; border: ${cTime.border}; color: ${cTime.text}; padding: 6px 10px; border-radius: 8px; font-weight: 700; font-size: 11px;">
            ${r.time_filter?.text || '--'}
          </div>
        </td>

        <!-- Recommended 1-ITM Strike -->
        <td style="padding: 10px 8px; text-align: center;">
          <div style="background: rgba(139, 92, 246, 0.15); border: 1px solid rgba(139, 92, 246, 0.35); color: #c4b5fd; padding: 6px 10px; border-radius: 8px; font-weight: 800; font-size: 12px; font-family: 'JetBrains Mono', monospace;">
            ${r.recommended_strike?.text || '--'}
          </div>
        </td>

        <!-- Bot Decision & Action -->
        <td style="padding: 10px 12px;">
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <div>
              <span style="${actionBtnStyle}">
                ${actionBadge}
              </span>
            </div>
            <div style="font-size: 10px; color: #94a3b8; line-height: 1.3;">
              ${actionReason}
            </div>
          </div>
        </td>

      </tr>
    `;
  }).join('');

  container.innerHTML = `
    <div style="background: linear-gradient(135deg, rgba(15, 23, 42, 0.98), rgba(24, 24, 54, 0.95)); border: 1px solid rgba(139, 92, 246, 0.45); border-radius: 14px; padding: 18px 22px; box-shadow: 0 10px 35px rgba(0,0,0,0.5);">
      
      <!-- Top Title & Color Legend Bar -->
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px; margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 14px;">
        <div style="display: flex; align-items: center; gap: 12px;">
          <div style="width: 40px; height: 40px; border-radius: 10px; background: linear-gradient(135deg, #10b981, #06b6d4); display: flex; align-items: center; justify-content: center; font-size: 22px; box-shadow: 0 0 16px rgba(16,185,129,0.4);">
            ⚡
          </div>
          <div>
            <div style="font-size: 16px; font-weight: 800; color: #f8fafc; letter-spacing: 0.5px; display: flex; align-items: center; gap: 10px;">
              <span>INSTITUTIONAL SIGNAL DECISION MATRIX (ATM ± 1 STRATEGY)</span>
              <span style="font-size: 10px; background: ${botActive ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.25)'}; color: ${botActive ? '#34d399' : '#f87171'}; border: 1px solid ${botActive ? '#10b981' : '#ef4444'}; padding: 2px 8px; border-radius: 6px; font-weight: 800;">
                ${botActive ? '● BOT ACTIVE (PAPER MODE)' : '⏸ BOT PAUSED'}
              </span>
            </div>
            <div style="font-size: 12px; color: #94a3b8; margin-top: 2px;">
              Live Rule Gates: 1-ITM Selection | ADX ≥ 20 Trend Expansion | AlphaTrend & Confluence Alignment | Midday Chop Shield
            </div>
          </div>
        </div>

        <!-- Legend Pills -->
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <span style="font-size: 11px; color: #94a3b8; font-weight: 600; margin-right: 4px;">SIGNAL MATRIX LEGEND:</span>
          <span style="background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px;">
            <span>🟢</span> <span>GREEN = CALL TRADE</span>
          </span>
          <span style="background: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px;">
            <span>🔴</span> <span>RED = PUT TRADE</span>
          </span>
          <span style="background: rgba(234, 179, 8, 0.15); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.4); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px;">
            <span>🟡</span> <span>YELLOW = DILEMMA / WAIT</span>
          </span>
        </div>
      </div>

      <!-- Matrix Table -->
      <div style="overflow-x: auto;">
        <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 12px;">
          <thead>
            <tr style="border-bottom: 2px solid rgba(255,255,255,0.1); color: #94a3b8; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;">
              <th style="padding: 10px 12px;">INDEX / SPOT</th>
              <th style="padding: 10px 8px; text-align: center;">CONFLUENCE (ATM±2)</th>
              <th style="padding: 10px 8px; text-align: center;">ALPHATREND (5M)</th>
              <th style="padding: 10px 8px; text-align: center;">ADX (14) FILTER</th>
              <th style="padding: 10px 8px; text-align: center;">SMART MONEY FLOW</th>
              <th style="padding: 10px 8px; text-align: center;">TIME WINDOW</th>
              <th style="padding: 10px 8px; text-align: center;">RECOMMENDED 1-ITM</th>
              <th style="padding: 10px 12px;">BOT DECISION & ACTION</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      </div>

      <!-- Footer Policy Note -->
      <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06); display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: #94a3b8; flex-wrap: wrap; gap: 10px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="color: #10b981;">🛡️ Strict Concurrency:</span>
          <span>Max 1 active trade per index segment (zero overlap)</span>
          <span style="color: #64748b;">|</span>
          <span style="color: #38bdf8;">Exit Architecture:</span>
          <span>Target 1 (+18% Breakeven Armor) | Target 2 (+35%) | Hard Stop (-14%) | EOD Squareoff (15:25 IST)</span>
        </div>
        <div style="font-family: 'JetBrains Mono', monospace; color: #c4b5fd;">
          Telemetry Clock: ${timeStr}
        </div>
      </div>

    </div>
  `;
}

function renderPositions(positions) {
  const container = document.getElementById('positions-container');
  const countBadge = document.getElementById('pos-count-badge');
  if (!container) return;

  if (countBadge) {
    countBadge.textContent = `${positions.length} OPEN`;
    countBadge.style.background = positions.length > 0 ? '#10b981' : '#334155';
  }

  if (positions.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 40px; color: #64748b; font-size: 13px;">
        No active positions open. Use the Manual Cockpit or MyBullAndBear AI signal to enter.
      </div>
    `;
    return;
  }

  container.innerHTML = positions.map(pos => {
    const isLive = (pos.execution_mode === 'LIVE');
    const netPnl = parseFloat(pos.net_pnl) || 0;
    const isProfit = netPnl >= 0;
    const pnlColor = isProfit ? '#10b981' : '#ef4444';
    const entryP = parseFloat(pos.entry_price) || 0;
    const currP = parseFloat(pos.current_price) || 0;
    const t1 = parseFloat(pos.target1) || 0;
    const t2 = parseFloat(pos.target2) || 0;
    const sl = parseFloat(pos.stop_loss) || 0;
    const beLocked = Boolean(pos.breakeven_locked);

    // Calculate progress towards T1
    const totalDist = Math.max(1, t1 - entryP);
    const currDist = Math.max(0, currP - entryP);
    const pctToT1 = Math.min(100, Math.round((currDist / totalDist) * 100));

    return `
      <div class="pos-card" data-id="${pos.id}" style="background: rgba(30, 41, 59, 0.7); border: 1px solid ${isProfit ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}; border-radius: 10px; padding: 14px; position: relative;">
        
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
          <div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 16px; font-weight: 800; color: #f8fafc;">
                ${pos.symbol} ${pos.strike} ${pos.option_type}
              </span>
              <span class="badge" style="background: ${isLive ? '#8b5cf6' : '#0284c7'}; color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700;">
                ${isLive ? '🔥 LIVE FYERS' : '📝 PAPER'}
              </span>
              ${beLocked ? '<span class="badge" style="background: #10b981; color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700;">🛡️ BREAKEVEN ARMOR</span>' : ''}
            </div>
            <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">
              Qty: ${pos.quantity} (${pos.lots} lot) | Entry: ₹${entryP.toFixed(1)} | LTP: ₹${currP.toFixed(1)}
            </div>
          </div>

          <div style="text-align: right;">
            <div style="font-size: 11px; color: #94a3b8;">${isLive ? 'BROKER NET P&L' : 'NET P&L (₹75 fee)'}</div>
            <div style="font-size: 20px; font-weight: 900; color: ${pnlColor};">
              ${isProfit ? '+' : ''}₹${netPnl.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
            </div>
          </div>
        </div>

        <!-- Progress to Target 1 -->
        <div style="margin-bottom: 12px;">
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8; margin-bottom: 3px;">
            <span>Entry: ₹${entryP.toFixed(1)}</span>
            <span>Target 1: ₹${t1.toFixed(1)} (${pctToT1}%)</span>
          </div>
          <div style="width: 100%; height: 5px; background: #0f172a; border-radius: 3px; overflow: hidden;">
            <div style="width: ${pctToT1}%; height: 100%; background: linear-gradient(90deg, #3b82f6, #10b981); transition: width 0.3s;"></div>
          </div>
        </div>

        <!-- Inline Modify Target & SL Strip -->
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; background: rgba(15, 23, 42, 0.6); padding: 8px 10px; border-radius: 8px; font-size: 11px; flex-wrap: wrap;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="color: #6ee7b7; font-weight: 700;">T1:</span>
            <input type="number" step="0.5" class="edit-t1-val" value="${t1}" style="width: 55px; background: #1e293b; border: 1px solid #334155; color: #fff; padding: 2px 4px; border-radius: 4px; font-size: 11px;" />
          </div>

          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="color: #7dd3fc; font-weight: 700;">T2:</span>
            <input type="number" step="0.5" class="edit-t2-val" value="${t2}" style="width: 55px; background: #1e293b; border: 1px solid #334155; color: #fff; padding: 2px 4px; border-radius: 4px; font-size: 11px;" />
          </div>

          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="color: #fca5a5; font-weight: 700;">SL:</span>
            <input type="number" step="0.5" class="edit-sl-val" value="${sl}" style="width: 55px; background: #1e293b; border: 1px solid #334155; color: #fff; padding: 2px 4px; border-radius: 4px; font-size: 11px;" />
          </div>

          <button class="btn-save-modify" data-id="${pos.id}" style="background: #3b82f6; color: #fff; border: none; padding: 4px 8px; border-radius: 4px; font-weight: 700; cursor: pointer;">
            Save
          </button>

          <button class="btn-exit-pos" data-id="${pos.id}" style="background: #ef4444; color: #fff; border: none; padding: 4px 10px; border-radius: 4px; font-weight: 700; cursor: pointer; margin-left: auto;">
            Exit Position
          </button>
        </div>

      </div>
    `;
  }).join('');

  // Attach dynamic modification listeners
  container.querySelectorAll('.btn-save-modify').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const id = e.target.dataset.id;
      const card = e.target.closest('.pos-card');
      const t1 = parseFloat(card.querySelector('.edit-t1-val').value);
      const t2 = parseFloat(card.querySelector('.edit-t2-val').value);
      const sl = parseFloat(card.querySelector('.edit-sl-val').value);

      try {
        const res = await ApiClient.modifyShonyaPosition(id, { target1: t1, target2: t2, stop_loss: sl });
        if (res?.success) {
          alert("Target & Stop Loss updated successfully!");
          await refreshShonyaData();
        }
      } catch (err) {
        alert("Failed to update: " + (err.message || err));
      }
    });
  });

  // Attach Exit Position listeners
  container.querySelectorAll('.btn-exit-pos').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const id = e.target.dataset.id;
      const confirmExit = confirm("Exit this active position at current market price?");
      if (confirmExit) {
        try {
          const res = await ApiClient.exitShonyaPosition(id, 'MANUAL_EXIT');
          if (res?.success) {
            alert(`Position exited at ₹${res.exit_price}! Net PnL: ₹${res.net_pnl}`);
            await refreshShonyaData();
          }
        } catch (err) {
          alert("Exit error: " + (err.message || err));
        }
      }
    });
  });
}

function renderJournal(history, metrics) {
  const tbody = document.getElementById('journal-tbody');
  const winRateEl = document.getElementById('metric-win-rate');
  const netPnlEl = document.getElementById('metric-net-pnl');

  if (winRateEl) winRateEl.textContent = `${metrics.win_rate_pct || 0}% (${metrics.winning_trades || 0}W / ${metrics.losing_trades || 0}L)`;
  if (netPnlEl) {
    const net = metrics.net_pnl_inr || 0;
    netPnlEl.textContent = `${net >= 0 ? '+' : ''}₹${net.toLocaleString('en-IN')}`;
    netPnlEl.style.color = net >= 0 ? '#10b981' : '#ef4444';
  }

  if (!tbody) return;

  if (history.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; padding: 20px; color: #64748b;">No closed trades recorded yet.</td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = history.map(t => {
    const net = parseFloat(t.net_pnl) || 0;
    const isProfit = net >= 0;
    const timeStr = (t.exit_time || t.entry_time || '').split(' ')[1] || t.exit_time || '--';

    return `
      <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
        <td style="padding: 6px; color: #94a3b8;">${timeStr}</td>
        <td style="padding: 6px; font-weight: 700; color: #f8fafc;">${t.symbol} ${t.strike} ${t.option_type}</td>
        <td style="padding: 6px;">₹${parseFloat(t.entry_price || 0).toFixed(1)}</td>
        <td style="padding: 6px;">₹${parseFloat(t.exit_price || 0).toFixed(1)}</td>
        <td style="padding: 6px; font-size: 11px; color: #cbd5e1;">${t.exit_reason || 'CLOSED'}</td>
        <td style="padding: 6px; text-align: right; font-weight: 800; color: ${isProfit ? '#10b981' : '#ef4444'};">
          ${isProfit ? '+' : ''}₹${net.toFixed(1)}
        </td>
      </tr>
    `;
  }).join('');
}

async function executeFetchAIMarketOverview() {
  const mount = document.getElementById('ai-market-overview-mount');
  const btnIcon = document.getElementById('ai-overview-btn-icon');
  const btnText = document.getElementById('ai-overview-btn-text');

  if (!selectedOverviewIndices || selectedOverviewIndices.length === 0) {
    alert("Please select at least one index to analyze.");
    return;
  }

  if (btnIcon) btnIcon.textContent = '⏳';
  if (btnText) btnText.textContent = 'Analyzing Market...';

  if (mount) {
    mount.innerHTML = `
      <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 12px; padding: 30px 20px; text-align: center;">
        <div style="font-size: 32px; animation: pulse 1.5s infinite; margin-bottom: 12px;">🧠 ⚡ 📊</div>
        <div style="font-size: 15px; font-weight: 800; color: #c4b5fd; margin-bottom: 8px;">
          Synthesizing Cross-Asset Telemetry for ${selectedOverviewIndices.join(', ')}...
        </div>
        <div style="font-size: 12px; color: #94a3b8; max-width: 600px; margin: 0 auto; line-height: 1.6;">
          Extracting live broker OHLC price ranges, tracking Call vs Put writing velocity, calculating cross-market confluence scores, and generating an institutional tape reading...
        </div>
      </div>
    `;
  }

  try {
    const res = await ApiClient.fetchAIMarketOverview(selectedOverviewIndices);
    if (res && res.success) {
      lastOverviewData = res;
      renderAIMarketOverviewContent(res);
    } else {
      if (mount) {
        mount.innerHTML = `
          <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 10px; padding: 18px; color: #fca5a5; font-size: 13px;">
            ⚠️ <strong>Failed to retrieve AI Market Overview:</strong> ${res?.message || 'Server error'}
          </div>
        `;
      }
    }
  } catch (err) {
    if (mount) {
      mount.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 10px; padding: 18px; color: #fca5a5; font-size: 13px;">
          ⚠️ <strong>Error contacting AI Intelligence Engine:</strong> ${err.message || err}
        </div>
      `;
    }
  } finally {
    if (btnIcon) btnIcon.textContent = '🔮';
    if (btnText) btnText.textContent = 'Get AI Market View';
  }
}

function renderAIMarketOverviewContent(data) {
  const mount = document.getElementById('ai-market-overview-mount');
  if (!mount) return;

  const tone = (data.market_tone || 'NEUTRAL').toUpperCase();
  const toneColor = tone === 'BULLISH' ? '#10b981' : (tone === 'BEARISH' ? '#ef4444' : '#f59e0b');
  const toneBg = tone === 'BULLISH' ? 'rgba(16, 185, 129, 0.15)' : (tone === 'BEARISH' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(245, 158, 11, 0.15)');
  const toneBorder = tone === 'BULLISH' ? 'rgba(16, 185, 129, 0.4)' : (tone === 'BEARISH' ? 'rgba(239, 68, 68, 0.4)' : 'rgba(245, 158, 11, 0.4)');

  const analyses = data.index_analyses || [];
  const engine = data.ai_engine || 'MyBullAndBear AI Engine';

  mount.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 16px; animation: fadeIn 0.3s ease-in;">
      
      <!-- Top Macro Summary Card -->
      <div style="background: ${toneBg}; border: 1px solid ${toneBorder}; border-radius: 12px; padding: 18px 22px; box-shadow: 0 4px 20px rgba(0,0,0,0.25);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 10px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span style="font-size: 18px;">${tone === 'BULLISH' ? '🟢' : (tone === 'BEARISH' ? '🔴' : '🟡')}</span>
            <span style="font-size: 15px; font-weight: 800; color: #f8fafc; letter-spacing: 0.5px;">
              ${data.market_regime_headline || 'INSTITUTIONAL MARKET OVERVIEW'}
            </span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="background: ${toneColor}; color: #000; font-weight: 800; font-size: 11px; padding: 3px 10px; border-radius: 6px; letter-spacing: 0.5px;">
              ${tone} REGIME
            </span>
            <span style="font-size: 11px; color: #94a3b8; font-family: 'JetBrains Mono', monospace;">
              ${data.timestamp || ''}
            </span>
          </div>
        </div>

        <div style="font-size: 13px; line-height: 1.6; color: #e2e8f0; margin-bottom: 12px;">
          ${data.macro_executive_summary || ''}
        </div>

        ${data.cross_index_divergence ? `
          <div style="background: rgba(0,0,0,0.25); border-left: 3px solid #38bdf8; border-radius: 4px; padding: 8px 12px; font-size: 12px; color: #7dd3fc; line-height: 1.5;">
            <strong>⚖️ Relative Strength & Divergence:</strong> ${data.cross_index_divergence}
          </div>
        ` : ''}
      </div>

      <!-- Index-by-Index Deep Dive Grid -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 14px;">
        ${analyses.map(item => {
          const vColor = item.verdict_color === 'green' ? '#10b981' : (item.verdict_color === 'red' ? '#ef4444' : '#f59e0b');
          const vBg = item.verdict_color === 'green' ? 'rgba(16, 185, 129, 0.12)' : (item.verdict_color === 'red' ? 'rgba(239, 68, 68, 0.12)' : 'rgba(245, 158, 11, 0.12)');
          const infl = item.inflection_levels || {};

          return `
            <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(255,255,255,0.08); border-top: 3px solid ${vColor}; border-radius: 12px; padding: 16px; display: flex; flex-direction: column; gap: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.3);">
              
              <!-- Index Header -->
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="font-size: 16px; font-weight: 800; color: #f8fafc;">${item.symbol}</span>
                  <span style="background: ${vBg}; color: ${vColor}; border: 1px solid ${vColor}; font-size: 10px; font-weight: 800; padding: 2px 7px; border-radius: 5px;">
                    ${item.verdict || 'ANALYSIS'}
                  </span>
                </div>
                <div style="font-size: 11px; font-weight: 700; color: #38bdf8;">
                  DIRECTIVE: ${item.tactical_directive ? item.tactical_directive.split(':')[0] : 'ACTIVE'}
                </div>
              </div>

              <!-- Price & OHLC Tape Reading -->
              <div style="background: rgba(0,0,0,0.25); border-radius: 8px; padding: 10px; font-size: 12px; line-height: 1.5; color: #cbd5e1;">
                <div style="color: #38bdf8; font-weight: 700; font-size: 11px; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                  <span>🕯️</span>
                  <span>PRICE ACTION & OHLC TRAJECTORY</span>
                </div>
                <div>${item.ohlc_tape_reading || ''}</div>
              </div>

              <!-- Option Chain & OI Battlefield -->
              <div style="background: rgba(0,0,0,0.25); border-radius: 8px; padding: 10px; font-size: 12px; line-height: 1.5; color: #cbd5e1;">
                <div style="color: #a78bfa; font-weight: 700; font-size: 11px; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                  <span>🧱</span>
                  <span>STRIKE OI & WRITER DEFENSE WALLS</span>
                </div>
                <div>${item.oi_battlefield || ''}</div>
              </div>

              <!-- Technical & Confluence Alignment -->
              <div style="background: rgba(0,0,0,0.25); border-radius: 8px; padding: 10px; font-size: 12px; line-height: 1.5; color: #cbd5e1;">
                <div style="color: #34d399; font-weight: 700; font-size: 11px; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                  <span>🏹</span>
                  <span>TECHNICAL & CONFLUENCE ALIGNMENT</span>
                </div>
                <div>${item.technical_alignment || ''}</div>
              </div>

              <!-- Tactical Action & Directives -->
              <div style="background: ${vBg}; border: 1px solid ${vColor}; border-radius: 8px; padding: 10px; font-size: 12px; font-weight: 700; color: #f8fafc;">
                <div style="color: ${vColor}; font-size: 11px; margin-bottom: 3px;">🎯 TACTICAL DIRECTIVE:</div>
                <div>${item.tactical_directive || ''}</div>
              </div>

              <!-- Inflection Trigger Levels -->
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 11px; background: rgba(0,0,0,0.3); padding: 8px 10px; border-radius: 6px;">
                <div>
                  <span style="color: #6ee7b7; font-weight: 700;">▲ Bull Trigger:</span>
                  <div style="color: #e2e8f0; font-weight: 600;">${infl.bull_trigger || '--'}</div>
                </div>
                <div>
                  <span style="color: #fca5a5; font-weight: 700;">▼ Invalidation:</span>
                  <div style="color: #e2e8f0; font-weight: 600;">${infl.bear_invalidation || '--'}</div>
                </div>
              </div>

            </div>
          `;
        }).join('')}
      </div>

      <!-- Actionable Institutional Playbook & Traps -->
      <div style="background: rgba(15, 23, 42, 0.9); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 12px; padding: 16px 20px;">
        <div style="font-size: 13px; font-weight: 800; color: #c4b5fd; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
          <span>⚡</span>
          <span>ACTIONABLE INSTITUTIONAL PLAYBOOK & RISK DISCIPLINE</span>
        </div>
        <div style="font-size: 12px; color: #cbd5e1; line-height: 1.6; white-space: pre-line; margin-bottom: 10px;">
          ${data.actionable_institutional_playbook || ''}
        </div>
        ${data.risk_warnings ? `
          <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; padding: 8px 12px; font-size: 11px; color: #fca5a5;">
            <strong>⚠️ Risk Warning:</strong> ${data.risk_warnings}
          </div>
        ` : ''}
      </div>

      <!-- Footer Bar: Engine Credit, Timestamp, Copy & Refresh -->
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; padding: 4px 6px;">
        <div style="font-size: 11px; color: #64748b;">
          Engine: <strong style="color: #94a3b8;">${engine}</strong> | Telemetry: Live Broker Quotes & Option Chain
        </div>

        <div style="display: flex; gap: 10px;">
          <button id="btn-copy-ai-overview" style="background: #1e293b; color: #e2e8f0; border: 1px solid #475569; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px;">
            <span>📋</span>
            <span id="copy-overview-text">Copy Summary</span>
          </button>
          <button id="btn-refresh-ai-overview" style="background: #1e293b; color: #38bdf8; border: 1px solid #0284c7; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px;">
            <span>🔄</span>
            <span>Refresh</span>
          </button>
        </div>
      </div>

    </div>
  `;

  // Attach button listeners
  document.getElementById('btn-copy-ai-overview')?.addEventListener('click', () => {
    copyAIMarketOverviewToClipboard(data);
  });
  document.getElementById('btn-refresh-ai-overview')?.addEventListener('click', async () => {
    await executeFetchAIMarketOverview();
  });
}

function copyAIMarketOverviewToClipboard(data) {
  const lines = [
    `🧠 INSTITUTIONAL AI MARKET VIEW [${data.timestamp || ''}]`,
    `REGIME: ${data.market_regime_headline || ''} (${data.market_tone || ''})`,
    ``,
    `MACRO SUMMARY:`,
    `${data.macro_executive_summary || ''}`,
    ``,
    `RELATIVE STRENGTH & DIVERGENCE:`,
    `${data.cross_index_divergence || ''}`,
    ``,
    `INDEX DIRECTIVES:`
  ];

  (data.index_analyses || []).forEach(idx => {
    lines.push(`• ${idx.symbol}: ${idx.verdict || ''} -> ${idx.tactical_directive || ''}`);
  });

  lines.push(``);
  lines.push(`TACTICAL PLAYBOOK:`);
  lines.push(`${data.actionable_institutional_playbook || ''}`);
  if (data.risk_warnings) {
    lines.push(`\nRISK WARNING:\n${data.risk_warnings}`);
  }

  const textToCopy = lines.join('\n');
  navigator.clipboard.writeText(textToCopy).then(() => {
    const copyLabel = document.getElementById('copy-overview-text');
    if (copyLabel) {
      copyLabel.textContent = '✓ Copied!';
      setTimeout(() => {
        copyLabel.textContent = 'Copy Summary';
      }, 2000);
    }
  }).catch(() => {
    alert("Copied to clipboard!");
  });
}

