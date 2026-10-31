/**
 * Institutional Smart Signal Tracker & Paper Trading Bot Component
 * Standalone UI Component:
 * - Real-time Marked-to-Market (MTM) Positions with MFE / MAE Excursion Tracking
 * - Separate Buying Profit & Selling Profit Deck (Gross vs Net after Rs 100 Brokerage)
 * - Trade Quality Score (TQS) Badges & Institutional Filters
 * - Circuit Breaker, Daily Loss Limit & Cooldown Risk Monitors
 * - Category-Wise P&L Breakdown (Symbol-wise and Session-wise)
 * - Bot Pause / Resume & Instant Manual Squareoff Controls
 * - Live PineScript OTT Trend Badges & ADX Velocity Meters
 */

const defaultFetch = async (url, opts = {}) => {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? (typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body)) : undefined
  });
  return res.json();
};

const Api = {
  get: (url) => defaultFetch(url, { method: 'GET' }),
  post: (url, data) => defaultFetch(url, { method: 'POST', body: data })
};

let trackerDashboardData = null;
let trackerHistoryData = null;

export async function renderTradeTracker(container, apiOverride = null) {
  const apiClient = apiOverride || Api;

  try {
    const [dashRes, histRes] = await Promise.all([
      apiClient.get('/api/tracker/dashboard'),
      apiClient.get('/api/tracker/history?limit=30')
    ]);
    trackerDashboardData = dashRes?.data || dashRes || {};
    trackerHistoryData = histRes?.data || histRes?.trades || [];
  } catch (err) {
    console.warn('Tracker fetch error:', err);
  }

  const d = trackerDashboardData || {};
  const isActive = d.is_active !== undefined ? d.is_active : true;
  const summary = d.summary || {};
  const byRole = summary.by_role || {};
  const bySymbol = summary.by_symbol || {};
  const bySession = summary.by_session || {};
  const openTrades = d.active_positions || [];
  const learning = d.learning || {};
  const risk = d.risk_status || {};
  const concurrency = d.concurrency || { active_count: 0, max_concurrent: 4 };

  const totalGrossRealized = summary.total_gross_realized_pnl_inr || 0;
  const totalNetRealized = summary.total_net_realized_pnl_inr || 0;
  const totalBrokerage = summary.total_brokerage_inr || 0;
  const totalNetUnrealized = summary.total_net_unrealized_pnl_inr || 0;
  const netCombined = summary.net_combined_pnl_inr || (totalNetRealized + totalNetUnrealized);
  const grossCombined = summary.gross_combined_pnl_inr || totalGrossRealized;
  const winRate = summary.overall_win_rate_pct || 0;
  const profitFactor = summary.profit_factor || 1.0;
  const totalTrades = summary.total_trades || 0;
  const rollingExpectancy = summary.rolling_expectancy_inr || 0;
  const maxDrawdown = summary.max_drawdown_inr || 0;

  const sellerStats = byRole.SELLER || { gross_pnl: 0, net_pnl: 0, brokerage: 0, trades: 0, win_rate: 0, profit_factor: 1.0 };
  const buyerStats = byRole.BUYER || { gross_pnl: 0, net_pnl: 0, brokerage: 0, trades: 0, win_rate: 0, profit_factor: 1.0 };

  const circuitBreakerTripped = risk.circuit_breaker_tripped || false;
  const todayLoss = risk.today_realized_pnl_inr || 0;
  const dailyLimit = risk.daily_loss_limit_inr || 3500;

  container.innerHTML = `
    <div class="tracker-container">
      <!-- Top Bot Control & Risk Circuit Breaker Bar -->
      <div class="tracker-top-bar glass-panel">
        <div class="bot-status-indicator">
          <span class="status-pulse ${circuitBreakerTripped ? 'pulse-bear' : (isActive ? 'pulse-green' : 'pulse-amber')}"></span>
          <div style="display: flex; flex-direction: column;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="bot-title">INSTITUTIONAL SMART TRADE BOT</span>
              <span class="bot-badge ${circuitBreakerTripped ? 'badge-paused' : (isActive ? 'badge-active' : 'badge-paused')}">
                ${circuitBreakerTripped ? '🚨 CIRCUIT BREAKER TRIPPED' : (isActive ? '● RUNNING' : '⏸ PAUSED')}
              </span>
            </div>
            <span class="bot-subtext">
              Hours: 09:15 - 15:40 IST | Auto-Squareoff: 15:35 IST | Brokerage: Flat ₹100/lot (₹50 buy + ₹50 sell)
            </span>
          </div>
        </div>

        <div class="bot-controls">
          <div class="concurrency-pill" style="border-color: ${circuitBreakerTripped ? '#ef4444' : 'rgba(255,255,255,0.1)'};">
            <span>DAY P&L:</span>
            <strong class="${todayLoss >= 0 ? 'text-bull' : 'text-bear'}">₹${todayLoss.toLocaleString('en-IN')}</strong>
            <span style="color: var(--text-muted); font-size: 10px;">/ Limit: ₹${dailyLimit.toLocaleString('en-IN')}</span>
          </div>
          <div class="concurrency-pill">
            <span>CONCURRENCY:</span>
            <strong>${concurrency.active_count} / ${concurrency.max_concurrent} ACTIVE</strong>
          </div>
          <button class="bot-toggle-btn ${isActive ? 'btn-pause' : 'btn-resume'}" id="bot-toggle-btn">
            ${isActive ? '⏸ Pause Bot' : '▶ Enable Bot'}
          </button>
        </div>
      </div>

      <!-- Portfolio KPI Dashboard Deck -->
      <div class="tracker-kpi-deck">
        <div class="glass-panel kpi-card">
          <div class="kpi-lbl">NET COMBINED P&L (AFTER BROKERAGE)</div>
          <div class="kpi-val ${netCombined >= 0 ? 'text-bull' : 'text-bear'}">
            ₹${netCombined.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
          <div class="kpi-sub">
            Gross: ₹${grossCombined.toLocaleString('en-IN')} | Brokerage: -₹${totalBrokerage.toLocaleString('en-IN')} | MTM: ₹${totalNetUnrealized.toLocaleString('en-IN')}
          </div>
        </div>

        <div class="glass-panel kpi-card">
          <div class="kpi-lbl">OVERALL WIN RATE & EXPECTANCY</div>
          <div class="kpi-val text-bull">
            ${winRate.toFixed(1)}%
          </div>
          <div class="kpi-sub">
            Expectancy: ₹${rollingExpectancy.toFixed(0)}/trade | PF: ${profitFactor} | Max DD: ₹${maxDrawdown.toLocaleString('en-IN')}
          </div>
        </div>

        <div class="glass-panel kpi-card" style="border: 1px solid rgba(56, 189, 248, 0.35); background: linear-gradient(135deg, rgba(56, 189, 248, 0.08) 0%, rgba(15, 23, 42, 0.6) 100%);">
          <div class="kpi-lbl" style="color: #38bdf8; font-weight: 800;">🚀 BUYER REGIME PROFIT (MOMENTUM)</div>
          <div class="kpi-val ${buyerStats.net_pnl >= 0 ? 'text-bull' : 'text-bear'}">
            ₹${buyerStats.net_pnl.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
          </div>
          <div class="kpi-sub" style="color: #94a3b8;">
            Gross: ₹${buyerStats.gross_pnl.toLocaleString('en-IN')} | Brok: -₹${buyerStats.brokerage.toLocaleString('en-IN')} | ${buyerStats.trades} Trades (${buyerStats.win_rate}% Win)
          </div>
        </div>

        <div class="glass-panel kpi-card">
          <div class="kpi-lbl">🛡️ SELLER REGIME PROFIT (THETA DECAY)</div>
          <div class="kpi-val ${sellerStats.net_pnl >= 0 ? 'text-bull' : 'text-bear'}">
            ₹${sellerStats.net_pnl.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
          </div>
          <div class="kpi-sub">
            Gross: ₹${sellerStats.gross_pnl.toLocaleString('en-IN')} | Brok: -₹${sellerStats.brokerage.toLocaleString('en-IN')} | ${sellerStats.trades} Trades (${sellerStats.win_rate}% Win)
          </div>
        </div>
      </div>

      <!-- Category-Wise Index Performance Breakdown -->
      <div class="glass-panel" style="padding: 14px;">
        <div class="panel-header" style="margin-bottom: 10px;">
          <div class="panel-title">
            <span>📊</span>
            <span>CATEGORY-WISE P&L BY INDEX (1 CONCURRENT TRADE PER SYMBOL)</span>
          </div>
          <span style="font-size: 11px; color: var(--text-muted);">
            Enforces strict concurrency: Max 1 active trade per index simultaneously
          </span>
        </div>
        <div class="symbol-pnl-grid">
          ${renderSymbolPnlCard('NIFTY', bySymbol.NIFTY, 75, openTrades, d.technical_indicators?.NIFTY)}
          ${renderSymbolPnlCard('BANKNIFTY', bySymbol.BANKNIFTY, 30, openTrades, d.technical_indicators?.BANKNIFTY)}
          ${renderSymbolPnlCard('FINNIFTY', bySymbol.FINNIFTY, 65, openTrades, d.technical_indicators?.FINNIFTY)}
          ${renderSymbolPnlCard('MIDCPNIFTY', bySymbol.MIDCPNIFTY, 120, openTrades, d.technical_indicators?.MIDCPNIFTY)}
        </div>
      </div>

      <!-- Time of Day Session Performance Breakdown -->
      <div class="glass-panel" style="padding: 14px;">
        <div class="panel-header" style="margin-bottom: 10px;">
          <div class="panel-title">
            <span>⏱️</span>
            <span>TIME-OF-DAY SESSION PERFORMANCE (NET P&L)</span>
          </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px;">
          <div class="session-box">
            <span class="session-title">🌅 MORNING (09:15 - 11:30)</span>
            <strong class="session-val ${(bySession.MORNING?.net_pnl || 0) >= 0 ? 'text-bull' : 'text-bear'}">
              ₹${(bySession.MORNING?.net_pnl || 0).toLocaleString('en-IN')}
            </strong>
            <span class="session-sub">${bySession.MORNING?.trades || 0} Trades | ${bySession.MORNING?.win_rate || 0}% Win Rate</span>
          </div>
          <div class="session-box">
            <span class="session-title">☕ MIDDAY (11:30 - 13:30)</span>
            <strong class="session-val ${(bySession.MIDDAY?.net_pnl || 0) >= 0 ? 'text-bull' : 'text-bear'}">
              ₹${(bySession.MIDDAY?.net_pnl || 0).toLocaleString('en-IN')}
            </strong>
            <span class="session-sub">${bySession.MIDDAY?.trades || 0} Trades | Strict Chop Filter</span>
          </div>
          <div class="session-box">
            <span class="session-title">⚡ AFTERNOON (13:30 - 15:35)</span>
            <strong class="session-val ${(bySession.AFTERNOON?.net_pnl || 0) >= 0 ? 'text-bull' : 'text-bear'}">
              ₹${(bySession.AFTERNOON?.net_pnl || 0).toLocaleString('en-IN')}
            </strong>
            <span class="session-sub">${bySession.AFTERNOON?.trades || 0} Trades | Momentum Expansion</span>
          </div>
        </div>
      </div>

      <!-- Active Open Positions -->
      <div class="glass-panel" style="padding: 14px;">
        <div class="panel-header" style="margin-bottom: 12px;">
          <div class="panel-title">
            <span>⚡</span>
            <span>ACTIVE LIVE POSITIONS (${openTrades.length} / 4 CONCURRENT)</span>
          </div>
          <span style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">
            Auto-Updates Live with Real Option Chain Ticks & Trailing SL
          </span>
        </div>

        ${openTrades.length === 0 ? `
          <div class="no-positions-box">
            <span style="font-size: 28px;">🛡️</span>
            <div style="font-weight: 700; color: #f1f5f9;">No Active Positions Currently Open</div>
            <div style="font-size: 12px; color: var(--text-muted); max-width: 480px; text-align: center;">
              Bot evaluates live ticks with TQS >= 70, persistence checks, ATM/1-ITM preference, and rejects low-premium junk.
            </div>
          </div>
        ` : `
          <div class="active-positions-list">
            ${openTrades.map(tr => renderActivePositionCard(tr)).join('')}
          </div>
        `}
      </div>

      <!-- Self-Learning & Adaptive Intelligence Deck -->
      <div class="glass-panel learning-box">
        <div class="panel-header" style="margin-bottom: 8px;">
          <div class="panel-title" style="font-size: 12px;">
            <span>🧠</span>
            <span>ADAPTIVE LEARNING & INSTITUTIONAL QUALITY GATES</span>
          </div>
          <span class="pop-pill">ITERATION #${learning.learning_iterations || 0}</span>
        </div>
        <div class="learning-grid">
          <div class="learning-metric">
            <span class="l-lbl">Buyer Min TQS Score</span>
            <strong class="l-val text-accent">${(learning.buyer_min_tqs || 70).toFixed(0)} / 100</strong>
            <span class="l-sub">ATM/1-ITM + Momentum + Liquidity</span>
          </div>
          <div class="learning-metric">
            <span class="l-lbl">Seller Min TQS Score</span>
            <strong class="l-val text-bull">${(learning.seller_min_tqs || 66).toFixed(0)} / 100</strong>
            <span class="l-sub">Wall defense & Theta yield</span>
          </div>
          <div class="learning-metric">
            <span class="l-lbl">Daily Loss Circuit Breaker</span>
            <strong class="l-val" style="color: #ef4444;">-₹${(learning.daily_loss_limit_inr || 3500).toLocaleString('en-IN')}</strong>
            <span class="l-sub">Auto-halts bot if breached</span>
          </div>
          <div class="learning-metric">
            <span class="l-lbl">PineScript ADX Floor</span>
            <strong class="l-val" style="color: #38bdf8;">ADX ≥ 18.0</strong>
            <span class="l-sub">Filters low-volatility theta drag</span>
          </div>
          <div class="learning-metric">
            <span class="l-lbl">PineScript OTT Channel</span>
            <strong class="l-val" style="color: #c084fc;">VAR (CMO) + 0.3%</strong>
            <span class="l-sub">Blocks counter-trend false breakouts</span>
          </div>
        </div>
      </div>

      <!-- Closed Trades History / Journal with MFE / MAE Excursions -->
      <div class="glass-panel" style="padding: 14px;">
        <div class="panel-header" style="margin-bottom: 12px;">
          <div class="panel-title">
            <span>📜</span>
            <span>COMPLETED TRADES JOURNAL (GROSS VS NET AFTER ₹100 BROKERAGE)</span>
          </div>
        </div>

        <div class="table-container">
          <table class="journal-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Role</th>
                <th>Strategy Name</th>
                <th>Time (In/Out)</th>
                <th style="text-align: right;">Entry ₹</th>
                <th style="text-align: right;">Exit ₹</th>
                <th style="text-align: center;">TQS</th>
                <th style="text-align: right;">Peak (MFE)</th>
                <th style="text-align: right;">Max DD (MAE)</th>
                <th style="text-align: right;">Gross P&L</th>
                <th style="text-align: right;">Brokerage</th>
                <th style="text-align: right;">Net P&L</th>
                <th>Exit Reason</th>
              </tr>
            </thead>
            <tbody>
              ${trackerHistoryData && trackerHistoryData.length ? trackerHistoryData.map(tr => renderJournalRow(tr)).join('') : `
                <tr>
                  <td colspan="13" style="text-align: center; color: var(--text-muted); padding: 24px;">
                    No closed trades recorded yet. As trades reach Target, Trailing SL, or EOD Close (15:35), they will appear here with full MFE/MAE analysis.
                  </td>
                </tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;

  // Attach Toggle Button Event
  const toggleBtn = container.querySelector('#bot-toggle-btn');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', async () => {
      const nextState = !isActive;
      try {
        await apiClient.post('/api/tracker/toggle', { active: nextState });
        renderTradeTracker(container, apiClient);
      } catch (e) {
        alert('Failed to toggle bot state: ' + e.message);
      }
    });
  }

  // Attach Squareoff Buttons
  container.querySelectorAll('.btn-squareoff').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tid = btn.getAttribute('data-trade-id');
      if (tid && confirm(`Are you sure you want to manually square off position ${tid}?`)) {
        try {
          await apiClient.post(`/api/tracker/squareoff/${tid}`, {});
          renderTradeTracker(container, apiClient);
        } catch (e) {
          alert('Squareoff failed: ' + e.message);
        }
      }
    });
  });
}

function renderSymbolPnlCard(symbol, stats, lotSize, openTrades, tech) {
  const s = stats || { gross_pnl: 0, net_pnl: 0, brokerage: 0, trades: 0, win_rate: 0 };
  const isOpen = openTrades.some(t => t.symbol === symbol);
  const ottTrend = tech?.ott_trend || 'NEUTRAL';
  const adxVal = tech?.adx !== undefined ? tech.adx.toFixed(1) : '--';
  const isTrending = (tech?.adx || 0) >= 18.0;
  const isBull = ottTrend === 'BULLISH';
  const isBear = ottTrend === 'BEARISH';

  return `
    <div class="symbol-pnl-card">
      <div class="sym-pnl-header">
        <span class="sym-name">${symbol}</span>
        <div style="display: flex; gap: 4px; align-items: center;">
          <span class="sym-tech-tag ${isBull ? 'tech-bull' : (isBear ? 'tech-bear' : 'tech-neutral')}" title="PineScript OTT Trend Filter">
            ${isBull ? '▲ OTT BULL' : (isBear ? '▼ OTT BEAR' : '— OTT')}
          </span>
          <span class="sym-status-tag ${isOpen ? 'tag-open' : 'tag-idle'}">
            ${isOpen ? '● 1 OPEN' : 'IDLE'}
          </span>
        </div>
      </div>
      <div class="sym-pnl-val ${s.net_pnl >= 0 ? 'text-bull' : 'text-bear'}">
        ₹${s.net_pnl.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
      </div>
      <div class="sym-pnl-meta">
        <span>${s.trades} Trades | ${s.win_rate}% Win</span>
        <span style="font-weight: 700; color: ${isTrending ? '#38bdf8' : '#94a3b8'};">
          ADX ${adxVal} ${isTrending ? '🔥' : '💤'}
        </span>
      </div>
    </div>
  `;
}

function renderActivePositionCard(tr) {
  const isSeller = tr.role === 'SELLER';
  const grossPnl = tr.gross_unrealized_pnl_inr || 0;
  const netPnl = tr.unrealized_pnl_inr || (grossPnl - 100);
  const entry = tr.entry_net_price || 0;
  const curr = tr.current_net_price || entry;
  const target = tr.target_price || 0;
  const sl = tr.trailing_stop_price || tr.stop_loss_price || 0;
  const tqs = tr.tqs_score || 0;
  const mfe = tr.mfe_inr || 0;
  const mae = tr.mae_inr || 0;

  let progressPct = 0;
  if (isSeller) {
    const totalDist = entry - target;
    const covered = entry - curr;
    progressPct = totalDist > 0 ? Math.min(100, Math.max(0, (covered / totalDist) * 100)) : 0;
  } else {
    const totalDist = target - entry;
    const covered = curr - entry;
    progressPct = totalDist > 0 ? Math.min(100, Math.max(0, (covered / totalDist) * 100)) : 0;
  }

  return `
    <div class="active-position-card ${isSeller ? 'card-seller' : 'card-buyer'}">
      <div class="pos-header">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="pos-role-badge ${isSeller ? 'badge-seller' : 'badge-buyer'}">
            ${isSeller ? '🛡️ SELLER' : '🚀 BUYER'}
          </span>
          <span class="pos-sym">${tr.symbol}</span>
          <span class="pos-strat">${tr.strategy_type.replace(/_/g, ' ')}</span>
          ${tqs > 0 ? `<span class="tqs-pill">TQS ${tqs.toFixed(0)}</span>` : ''}
        </div>
        <button class="btn-squareoff" data-trade-id="${tr.id}" title="Immediately exit at current market price">
          ⚡ Square Off
        </button>
      </div>

      <div class="pos-legs">
        ${(tr.legs || []).map(l => `
          <span class="pos-leg-pill">
            <strong>${l.action}</strong> ${l.strike} ${l.option_type} @ ₹${(l.current_ltp || l.entry_ltp || 0).toFixed(2)}
          </span>
        `).join('')}
      </div>

      <div class="pos-metrics-grid">
        <div class="pos-param">
          <span class="p-lbl">ENTRY</span>
          <span class="p-val">₹${entry.toFixed(2)}</span>
        </div>
        <div class="pos-param">
          <span class="p-lbl">CURRENT CMP</span>
          <span class="p-val" style="color: #38bdf8;">₹${curr.toFixed(2)}</span>
        </div>
        <div class="pos-param">
          <span class="p-lbl">TARGET</span>
          <span class="p-val text-bull">₹${target.toFixed(2)}</span>
        </div>
        <div class="pos-param">
          <span class="p-lbl">TRAILING SL</span>
          <span class="p-val text-bear">₹${sl.toFixed(2)}</span>
        </div>
        <div class="pos-param">
          <span class="p-lbl">NET P&L (₹100 BROK)</span>
          <span class="p-val ${netPnl >= 0 ? 'text-bull' : 'text-bear'}" style="font-size: 14px; font-weight: 800;">
            ${netPnl >= 0 ? '+' : ''}₹${netPnl.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
          </span>
        </div>
      </div>

      <div style="display: flex; gap: 10px; margin-top: 8px; font-size: 11px;">
        <span style="color: #10b981; background: rgba(16, 185, 129, 0.1); padding: 2px 8px; border-radius: 4px;">
          📈 Peak Gain (MFE): +₹${mfe.toLocaleString('en-IN')}
        </span>
        <span style="color: #ef4444; background: rgba(239, 68, 68, 0.1); padding: 2px 8px; border-radius: 4px;">
          📉 Max Drawdown (MAE): -₹${Math.abs(mae).toLocaleString('en-IN')}
        </span>
      </div>

      <div class="pos-progress-wrapper" style="margin-top: 8px;">
        <div class="progress-bar-header">
          <span>PROGRESS TO TARGET</span>
          <span>${progressPct.toFixed(0)}%</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill ${netPnl >= 0 ? 'fill-bull' : 'fill-bear'}" style="width: ${progressPct}%;"></div>
        </div>
      </div>
    </div>
  `;
}

function renderJournalRow(tr) {
  const grossPnl = tr.gross_realized_pnl_inr || 0;
  const netPnl = tr.realized_pnl_inr || (grossPnl - 100);
  const brokerage = tr.brokerage_inr || 100.0;
  const entryNet = tr.entry_net_price || 0;
  const exitNet = tr.exit_net_price || 0;
  const isSeller = tr.role === 'SELLER';
  const tqs = tr.tqs_score || 0;
  const mfe = tr.mfe_inr || 0;
  const mae = tr.mae_inr || 0;

  const entryTime = tr.entry_time ? tr.entry_time.slice(11, 16) : '--';
  const exitTime = tr.exit_time ? tr.exit_time.slice(11, 16) : '--';

  return `
    <tr>
      <td><strong>${tr.symbol}</strong></td>
      <td>
        <span class="${isSeller ? 'text-bull' : 'text-accent'}" style="font-weight: 700; font-size: 11px;">
          ${isSeller ? '🛡️ SELLER' : '🚀 BUYER'}
        </span>
      </td>
      <td style="font-size: 11px; max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
        ${tr.strategy_type.replace(/_/g, ' ')}
      </td>
      <td style="font-family: var(--font-mono); font-size: 11px;">${entryTime} → ${exitTime}</td>
      <td style="text-align: right; font-family: var(--font-mono);">₹${entryNet.toFixed(1)}</td>
      <td style="text-align: right; font-family: var(--font-mono);">₹${exitNet.toFixed(1)}</td>
      <td style="text-align: center;">
        <span class="tqs-pill" style="font-size: 10px;">${tqs > 0 ? tqs.toFixed(0) : '--'}</span>
      </td>
      <td style="text-align: right; font-family: var(--font-mono); color: #10b981; font-size: 11px;">
        +₹${mfe.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
      </td>
      <td style="text-align: right; font-family: var(--font-mono); color: #ef4444; font-size: 11px;">
        -₹${Math.abs(mae).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
      </td>
      <td style="text-align: right; font-family: var(--font-mono); color: ${grossPnl >= 0 ? '#10b981' : '#ef4444'};">
        ₹${grossPnl.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
      </td>
      <td style="text-align: right; font-family: var(--font-mono); color: var(--text-muted); font-size: 11px;">
        -₹${brokerage.toFixed(0)}
      </td>
      <td style="text-align: right; font-family: var(--font-mono); font-weight: 800; color: ${netPnl >= 0 ? '#10b981' : '#ef4444'};">
        ${netPnl >= 0 ? '+' : ''}₹${netPnl.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
      </td>
      <td>
        <span class="reason-tag ${netPnl >= 0 ? 'reason-win' : 'reason-loss'}">
          ${tr.exit_reason || 'CLOSED'}
        </span>
      </td>
    </tr>
  `;
}
