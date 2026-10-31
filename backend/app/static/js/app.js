/**
 * Master Application Orchestrator
 * MyBullAndBear Institutional NSE Options & Signal Command Center
 * Supports:
 * - 7 Retained Specialized Views (Option Confluence, ShonyaBot, Signal Radar, OI Analytics, Strike Lab, Price vs OI, Option Chain)
 * - Persistent Telemetry: Top Header, Index Ticker Bar, Directional Weightage Bar
 * - Mobile-First PWA Responsive Layout (Desktop Tabs + Mobile Bottom Nav)
 * - Simultaneous Dual-View Data Synchronization (NIFTY & BANKNIFTY / FINNIFTY & MIDCAP)
 * - WebSocket Real-Time Push Gateway + Intelligent Polling Fallback
 * - Flicker-Free Selective State DOM Patching
 */
import { store } from './state.js';
import { ApiClient, StreamClient } from './api.js';
import { initPWAInstaller } from './pwa_installer.js';
import { renderHeader } from './components/header.js';
import { renderTickerBar } from './components/ticker_bar.js';
import { renderDirectionalWeightageBar } from './components/directional_weightage_bar.js';
import { renderDashboardView } from './components/dashboard_view.js';
import { renderOptionConfluence } from './components/option_confluence.js';
import { renderShonyaTerminal } from './components/shonya_terminal.js';
import { renderOICharts } from './components/oi_charts.js';
import { renderChainTable } from './components/chain_table.js';
import { renderAuthModal } from './components/auth_modal.js';
import { AccessGate } from './components/access_gate.js';
import { initMasterReplay, renderMasterReplayBar } from './components/master_replay_bar.js';

// State slices used by render guards for flicker-free performance
let _prevHeaderKey = '';
let _prevTickerKey = '';
let _prevTab = '';
let _contentMounted = false;

function _headerKey(s) {
  return [
    s.session?.session_state,
    s.session?.current_time_ist,
    s.fyersStatus?.has_token,
    s.dataSource,
    s.activePair,
    s.viewMode,
  ].join('|');
}

function _tickerKey(s) {
  return (s.indices || []).map(i => `${i.symbol}:${i.last}`).join(',')
       + `|${s.symbol1}|${s.symbol2}`;
}

function _contentDataKey(s) {
  switch (s.activeTab) {
    case 'oi-analytics':
      return JSON.stringify([
        s.oiData1?.timestamp || s.oiData1?.spot_price,
        s.oiData2?.timestamp || s.oiData2?.spot_price,
        s.symbol1,
        s.symbol2,
        s.chartMode1,
        s.chartMode2,
        s.strikeChartMode1,
        s.strikeChartMode2
      ]);
    case 'chain':
      return JSON.stringify([
        s.activeChainSymbol,
        s.optionChain1?.spot_price,
        s.optionChain1?.strikes?.length || 0,
        s.optionChain2?.spot_price,
        s.optionChain2?.strikes?.length || 0
      ]);
    default:
      return s.lastUpdated?.toISOString() || '';
  }
}

class TerminalApp {
  constructor() {
    this.headerMount = document.getElementById('header-mount');
    this.tickerMount = document.getElementById('ticker-mount');
    this.weightageMount = document.getElementById('directional-weightage-mount');
    this.contentMount = document.getElementById('content-mount');
    this.modalMount = document.getElementById('modal-mount');

    this.streamClient = null;
    this.pollingTimer = null;
    this._servicesStarted = false;
    this._prevContentKey = '';
  }

  async init() {
    // Initialize PWA install prompt support
    try {
      initPWAInstaller();
    } catch (e) {
      console.debug('PWA installer init:', e);
    }

    // 0. Enforce Security Gate
    const isAuthorized = await AccessGate.ensureAuthorized();
    if (!isAuthorized) {
      window.addEventListener('terminal:unlocked', () => {
        this._startTerminalServices();
      }, { once: true });
      return;
    }

    this._startTerminalServices();
  }

  _startTerminalServices() {
    if (this._servicesStarted) return;
    this._servicesStarted = true;

    console.log('⚡ Starting MyBullAndBear Terminal — Authorized Session');

    store.subscribe((state) => this.render(state));

    // Desktop and Mobile tab selectors
    document.querySelectorAll('[data-tab]').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.getAttribute('data-tab');
        this.switchTab(tab);
      });
    });

    window.addEventListener('terminal:unauthorized', () => {
      AccessGate.showGate();
    });

    const urlParams = new URLSearchParams(window.location.search);
    const initialTab = urlParams.get('tab') || window.location.hash.replace('#', '') || store.getState().activeTab || 'dashboard';
    this.switchTab(initialTab);

    // Initial render
    this.render(store.getState());

    // Initialize Master Dashboard-Wide Historical Replay Controller
    initMasterReplay();

    // Listen for unified historical replay synchronization events
    window.addEventListener('terminal:replay-sync', (e) => {
      const res = e.detail;
      if (!res) return;

      // 1. Synchronize Top Ticker Cards with historical spots
      if (res.ticker_cards) {
        const indList = Object.values(res.ticker_cards).map(c => ({
          symbol: c.symbol,
          name: c.name,
          last: c.ltp,
          change: c.change,
          percent_change: c.pChange,
          low: c.low,
          high: c.high
        }));
        store.setState({ indices: indList });
      }

      // 2. Synchronize active Option Chain with historical strike snapshot
      if (res.option_chain) {
        store.setState({ optionChain1: res.option_chain });
      }

      // 3. Immediately re-render active tab view with replayed dataset
      const curTab = store.getState().activeTab;
      if (curTab === 'option-confluence') {
        renderOptionConfluence(this.contentMount);
      } else if (curTab === 'chain') {
        renderChainTable(this.contentMount, (sym) => store.setState({ activeChainSymbol: sym }));
      } else if (curTab === 'strike-lab') {
        renderStrikeBuildupLab(this.contentMount);
      } else if (curTab === 'price-vs-oi') {
        renderPriceVsOIMatrix(this.contentMount);
      }
    });

    window.addEventListener('terminal:live-sync', () => {
      this.fetchDualPairData();
      this.render(store.getState());
      const curTab = store.getState().activeTab;
      if (curTab === 'option-confluence') {
        renderOptionConfluence(this.contentMount);
      }
    });

    // Fetch initial fund and dual-pair telemetry
    ApiClient.fetchTradingFund().then(res => {
      if (res && res.total_fund) store.setState({ totalFund: res.total_fund });
    }).catch(err => console.debug('Fund fetch error:', err));

    this.fetchDualPairData().catch(err => console.debug('Dual fetch error:', err));

    // Connect WebSocket stream
    this.streamClient = new StreamClient(
      (msg) => this.handleStreamMessage(msg),
      (connected) => console.log(`WebSocket connected: ${connected}`)
    );
    this.streamClient.connect();

    this.startPolling();
  }

  async fetchDualPairData() {
    const state = store.getState();
    const s1 = state.symbol1 || 'NIFTY';
    const s2 = state.symbol2 || 'BANKNIFTY';

    try {
      const [
        session, indices, fyersStatus,
        oiData1, oiData2,
        signals1, signals2,
        chain1, chain2
      ] = await Promise.all([
        ApiClient.fetchSession().catch(() => null),
        ApiClient.fetchIndices().catch(() => null),
        ApiClient.fetchFyersStatus().catch(() => null),
        ApiClient.fetchOIAnalytics(s1).catch(() => null),
        ApiClient.fetchOIAnalytics(s2).catch(() => null),
        ApiClient.fetchSignals(s1).catch(() => null),
        ApiClient.fetchSignals(s2).catch(() => null),
        ApiClient.fetchOptionChain(s1).catch(() => null),
        ApiClient.fetchOptionChain(s2).catch(() => null)
      ]);

      store.setState({
        session:       session || store.getState().session,
        indices:       indices?.indices || [],
        vix:           indices?.vix || { current: 13.5, change: 0.0 },
        breadth:       indices?.breadth || { advances: 30, declines: 20 },
        dataSource:    indices?.source || oiData1?.source || 'REAL_MARKET',
        fyersStatus:   fyersStatus || { is_configured: false, has_token: false },
        oiData1:       oiData1 || null,
        oiData2:       oiData2 || null,
        signals1:      signals1 || null,
        signals2:      signals2 || null,
        optionChain1:  chain1 || null,
        optionChain2:  chain2 || null,
        lastUpdated:   new Date()
      });
    } catch (e) {
      console.error('Error in dual data fetch:', e);
    }
  }

  async switchPair(pairName) {
    let s1 = 'NIFTY', s2 = 'BANKNIFTY';
    if (pairName === 'FINNIFTY_MIDCPNIFTY') { s1 = 'FINNIFTY'; s2 = 'MIDCPNIFTY'; }

    store.setState({
      activePair: pairName,
      viewMode: 'PAIR',
      symbol1: s1,
      symbol2: s2,
      activeSymbol: s1,
      activeChainSymbol: s1
    });

    if (this.streamClient) this.streamClient.subscribe(s1);
    await this.fetchDualPairData();
  }

  handleSymbolClick(sym) {
    if (sym === 'NIFTY' || sym === 'BANKNIFTY') {
      this.switchPair('NIFTY_BANKNIFTY');
    } else if (sym === 'FINNIFTY' || sym === 'MIDCPNIFTY') {
      this.switchPair('FINNIFTY_MIDCPNIFTY');
    } else {
      store.setState({
        activePair: 'SINGLE',
        viewMode: 'SINGLE',
        symbol1: sym,
        symbol2: sym,
        activeSymbol: sym,
        activeChainSymbol: sym
      });
      if (this.streamClient) this.streamClient.subscribe(sym);
      this.fetchDualPairData();
    }
    store.setState({ activeChainSymbol: sym, activeSymbol: sym });
  }

  startPolling() {
    if (this.pollingTimer) clearInterval(this.pollingTimer);

    this._isPolling = false;
    this.pollingTimer = setInterval(async () => {
      if (this._isPolling) return;
      // Do not allow live polling ticks to overwrite historical replay scrub
      if (store.isReplayActive()) return;

      this._isPolling = true;

      const state = store.getState();
      const s1 = state.symbol1;
      const s2 = state.symbol2;

      try {
        // Refresh index ticks (ticker bar & market hours)
        const indices = await ApiClient.fetchIndices();
        if (indices) {
          store.setState({
            indices:    indices.indices || state.indices,
            vix:        indices.vix || state.vix,
            dataSource: indices.source || state.dataSource
          });
        }

        // Active tab targeted refresh
        if (state.activeTab === 'oi-analytics') {
          const [d1, d2] = await Promise.all([
            ApiClient.fetchOIAnalytics(s1),
            ApiClient.fetchOIAnalytics(s2)
          ]);
          store.setState({ oiData1: d1 || state.oiData1, oiData2: d2 || state.oiData2 });
        } else if (state.activeTab === 'signals') {
          const [sig1, sig2] = await Promise.all([
            ApiClient.fetchSignals(s1),
            ApiClient.fetchSignals(s2)
          ]);
          store.setState({ signals1: sig1 || state.signals1, signals2: sig2 || state.signals2 });
        } else if (state.activeTab === 'chain') {
          const [c1, c2] = await Promise.all([
            ApiClient.fetchOptionChain(s1),
            ApiClient.fetchOptionChain(s2)
          ]);
          store.setState({ optionChain1: c1 || state.optionChain1, optionChain2: c2 || state.optionChain2 });
        }
      } catch (err) {
        console.debug('Polling tick error', err);
      } finally {
        this._isPolling = false;
      }
    }, 4000);
  }

  handleStreamMessage(msg) {
    if (msg.type === 'heartbeat') {
      store.setState({
        session: msg.session,
        fyersStatus: { ...store.getState().fyersStatus, has_token: msg.fyers_active }
      });
    }
  }

  switchTab(tab) {
    if (_prevTab !== tab) {
      if (this.contentMount) this.contentMount.innerHTML = '';
      _contentMounted = false;
      this._prevContentKey = '';
    }
    store.setState({ activeTab: tab });

    // Update active tab buttons on both Desktop and Mobile nav
    document.querySelectorAll('[data-tab]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tab);
    });

    // If replay is active, render immediately using current replayed telemetry without firing live REST calls
    if (store.isReplayActive()) {
      this.render(store.getState());
      return;
    }

    // Immediate tab data fetch
    if (tab === 'chain' && !store.getState().optionChain1) {
      const s1 = store.getState().symbol1;
      const s2 = store.getState().symbol2;
      Promise.all([ApiClient.fetchOptionChain(s1), ApiClient.fetchOptionChain(s2)]).then(([c1, c2]) => {
        store.setState({ optionChain1: c1 || store.getState().optionChain1, optionChain2: c2 || store.getState().optionChain2 });
      }).catch(err => console.debug('Immediate chain fetch error:', err));
    }

    if (tab === 'oi-analytics' && (!store.getState().oiData1 || !store.getState().oiData2)) {
      const s1 = store.getState().symbol1 || 'NIFTY';
      const s2 = store.getState().symbol2 || 'BANKNIFTY';
      Promise.all([
        ApiClient.fetchOIAnalytics(s1).catch(() => null),
        ApiClient.fetchOIAnalytics(s2).catch(() => null)
      ]).then(([d1, d2]) => {
        if (d1 || d2) {
          store.setState({
            oiData1: d1 || store.getState().oiData1,
            oiData2: d2 || store.getState().oiData2
          });
        }
      }).catch(err => console.debug('Immediate OI fetch error:', err));
    }
  }

  render(state) {
    // ── 1. Top Header ────────────────────────────────────────────────────────
    const hKey = _headerKey(state);
    if (hKey !== _prevHeaderKey) {
      _prevHeaderKey = hKey;
      renderHeader(
        this.headerMount,
        (pair) => this.switchPair(pair),
        (sym)  => this.handleSymbolClick(sym),
        ()     => renderAuthModal(this.modalMount),
        ()     => this.fetchDualPairData()
      );
    }

    // ── 2. Ticker Bar (Optional fallback if mounted) ───────────────────────
    if (this.tickerMount) {
      const tKey = _tickerKey(state);
      if (tKey !== _prevTickerKey) {
        _prevTickerKey = tKey;
        renderTickerBar(this.tickerMount, (sym) => this.handleSymbolClick(sym));
      }
    }

    // ── 2.5. Directional Weightage Bar (Mount once) ──────────────────────────
    if (this.weightageMount && !this._weightageMounted) {
      this._weightageMounted = true;
      renderDirectionalWeightageBar(this.weightageMount);
    }

    // ── 3. Active Tab Content (The 7 Retained Views) ─────────────────────────
    const tab = state.activeTab;
    const tabChanged = tab !== _prevTab;
    if (tabChanged) _prevTab = tab;

    // Self-contained tabs: mount once, let them manage inner updates
    if (tab === 'dashboard') {
      if (!_contentMounted || tabChanged) {
        _contentMounted = true;
        renderDashboardView(this.contentMount);
      }
      return;
    }
    if (tab === 'shonya-terminal') {
      if (!_contentMounted || tabChanged) {
        _contentMounted = true;
        renderShonyaTerminal(this.contentMount);
      }
      return;
    }
    if (tab === 'option-confluence') {
      if (!_contentMounted || tabChanged) {
        _contentMounted = true;
        renderOptionConfluence(this.contentMount);
      }
      return;
    }

    // Data-driven tabs
    const cKey = _contentDataKey(state);
    const dataChanged = cKey !== this._prevContentKey;
    if (!_contentMounted || tabChanged || dataChanged) {
      _contentMounted = true;
      this._prevContentKey = cKey;

      if (tab === 'oi-analytics') {
        renderOICharts(
          this.contentMount,
          (m1)  => store.setState({ chartMode1: m1 }),
          (m2)  => store.setState({ chartMode2: m2 }),
          (sm1) => store.setState({ strikeChartMode1: sm1 }),
          (sm2) => store.setState({ strikeChartMode2: sm2 })
        );
      } else if (tab === 'chain') {
        renderChainTable(this.contentMount, (chainSym) => store.setState({ activeChainSymbol: chainSym }));
      }
    }
  }
}

// Bootstrap on DOM Ready
function _bootstrapTerminal() {
  const app = new TerminalApp();
  window.appInstance = app;
  window.store = store;
  app.init();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _bootstrapTerminal);
} else {
  _bootstrapTerminal();
}
