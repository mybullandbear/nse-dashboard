/**
 * Reactive State Store for NSE Options Terminal
 * Supports Simultaneous Dual-Symbol Pairs:
 * - Pair 1: NIFTY & BANKNIFTY (Default)
 * - Pair 2: FINNIFTY & MIDCPNIFTY
 */

class AppStore {
  constructor() {
    this.state = {
      // Dual Pair View: 'NIFTY_BANKNIFTY' (default) | 'FINNIFTY_MIDCPNIFTY' | 'SINGLE'
      viewMode: 'PAIR', 
      activePair: 'NIFTY_BANKNIFTY',
      symbol1: 'NIFTY',
      symbol2: 'BANKNIFTY',
      activeSymbol: 'NIFTY', // for single views or quick selection
      activeChainSymbol: 'NIFTY',
      chainRange: 10, // Default ATM ± 10 strikes
      
      activeTab: 'dashboard', // 'dashboard' (default 5-index overview) | 'option-confluence' | 'shonya-terminal' | 'oi-analytics' | 'chain'
      
      // Chart Modes per symbol
      chartMode1: 'total', // 'total' | 'change' | 'diff'
      chartMode2: 'total',
      strikeChartMode1: 'composite', // 'composite' (Change + Total) | 'change' | 'total'
      strikeChartMode2: 'composite',
      strikeRange1: 15, // 10 | 15 | 20 strikes from ATM
      strikeRange2: 15,

      session: {
        session_state: 'INITIALIZING',
        is_market_open: false,
        current_time_ist: '--:--:--'
      },
      indices: [],
      vix: { current: 0.0, change: 0.0 },
      breadth: { advances: 0, declines: 0 },

      // Datasets for Symbol 1
      oiData1: null,
      signals1: null,
      smartMoney1: null,
      optionChain1: null,

      // Datasets for Symbol 2
      oiData2: null,
      signals2: null,
      smartMoney2: null,
      optionChain2: null,

      fyersStatus: { is_configured: false, has_token: false },
      totalFund: 50000.0,
      lastUpdated: null,
      dataSource: 'FYERS_LIVE',
      isLoading: false,

      // Master Dashboard-Wide Historical Replay State (Zero Repetition)
      replay: {
        active: false,
        selectedDate: '2026-10-12',
        selectedTime: '09:15',
        isPlaying: false,
        speed: 1,
        availableDates: [],
        timeline: [],
        snapshot: null
      }
    };

    this.subscribers = new Set();
  }

  isReplayActive() {
    return Boolean(this.state.replay && this.state.replay.active);
  }

  getState() {
    return this.state;
  }

  setState(updates) {
    this.state = { ...this.state, ...updates };
    this.notify();
  }

  subscribe(listener) {
    this.subscribers.add(listener);
    return () => this.subscribers.delete(listener);
  }

  notify() {
    for (const listener of this.subscribers) {
      try {
        listener(this.state);
      } catch (e) {
        console.error('State subscriber error', e);
      }
    }
  }
}

export const store = new AppStore();
export const state = store.state;
