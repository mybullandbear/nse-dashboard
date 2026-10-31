/**
 * API Client & Resilient WebSocket Streaming Manager
 */

export const ApiClient = {
  baseUrl: window.location.origin,

  _getAuthHeaders() {
    return {};
  },

  async get(endpoint) {
    try {
      const headers = this._getAuthHeaders();
      const res = await fetch(`${this.baseUrl}${endpoint}`, { headers, signal: AbortSignal.timeout(15000) });
      if (res.status === 401 && !endpoint.startsWith('/api/access/')) {
        window.dispatchEvent(new CustomEvent('terminal:unauthorized'));
        throw new Error('Unauthorized');
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const data = await res.json();
      if (endpoint.startsWith('/api/market/') && data.source) window.dispatchEvent(new CustomEvent('terminal:data-status', {detail:{source:data.source,age:data.cache_age_seconds}}));
      return data;
    } catch (err) {
      if (endpoint.startsWith("/api/market/")) window.dispatchEvent(new CustomEvent("terminal:data-status", {detail:{error:true}}));
      console.warn(`API GET error on ${endpoint}:`, err);
      return null;
    }
  },

  async post(endpoint, data) {
    try {
      const headers = { 'Content-Type': 'application/json', ...this._getAuthHeaders() };
      const res = await fetch(`${this.baseUrl}${endpoint}`, {
        method: 'POST',
        signal: AbortSignal.timeout(15000),
        headers,
        body: JSON.stringify(data),
      });
      if (res.status === 401 && !endpoint.startsWith('/api/access/')) {
        window.dispatchEvent(new CustomEvent('terminal:unauthorized'));
        throw new Error('Unauthorized');
      }
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (err) {
      console.warn(`API POST error on ${endpoint}:`, err);
      throw err;
    }
  },

  // Terminal Access Gate Authentication
  async verifyPassword(password, rememberDevice = true) {
    const res = await fetch(`${this.baseUrl}/api/access/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        password: password,
        remember_device: !!rememberDevice 
      })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || 'Invalid access key.');
    }
    return data;
  },

  async checkAccess() {
    try {
      const headers = this._getAuthHeaders();
      const res = await fetch(`${this.baseUrl}/api/access/check`, { headers, signal: AbortSignal.timeout(15000) });
      if (!res.ok) return false;
      const data = await res.json();
      return !!data.authenticated;
    } catch (e) {
      return false;
    }
  },

  async logout() {
    localStorage.removeItem('terminal_access_token');
    localStorage.removeItem('terminal_device_trusted');
    sessionStorage.removeItem('terminal_access_token');
    try {
      await fetch(`${this.baseUrl}/api/access/logout`, { method: 'POST' });
    } catch (e) {}
    window.location.reload();
  },

  // Endpoints
  fetchSession() {
    return this.get('/api/market/session');
  },

  fetchIndices() {
    return this.get('/api/market/indices');
  },

  fetchLiveMatrix() {
    return this.get('/api/matrix/live');
  },

  fetchMultiIndexRadar() {
    return this.get('/api/market/multi_index_radar');
  },

  fetchRadarReplay(date = '', timeStr = '') {
    const params = new URLSearchParams();
    if (date) params.append('date', date);
    if (timeStr) params.append('time_str', timeStr);
    const qs = params.toString();
    return this.get(`/api/market/radar_replay${qs ? '?' + qs : ''}`);
  },

  fetchUnifiedReplay(date = '', timeStr = '', symbol = 'NIFTY') {
    const params = new URLSearchParams();
    if (date) params.append('date', date);
    if (timeStr) params.append('time_str', timeStr);
    if (symbol) params.append('symbol', symbol);
    const qs = params.toString();
    return this.get(`/api/market/unified_replay${qs ? '?' + qs : ''}`);
  },

  fetchUnifiedReplaySessions() {
    return this.get('/api/market/unified_replay/sessions');
  },

  triggerRadarPushTest() {
    return this.post('/api/market/radar_push_test');
  },

  fetchOIAnalytics(symbol = 'NIFTY') {
    return this.get(`/api/oi/analytics/${symbol}`);
  },

  async fetchSignals(symbol = 'NIFTY') {
    const res = await this.get(`/api/signals/decision/${symbol}`);
    return res?.data || res;
  },

  async fetchTradingFund() {
    const res = await this.get('/api/signals/fund');
    return res || { total_fund: 50000 };
  },

  async updateTradingFund(amount) {
    const res = await this.post('/api/signals/fund', { total_fund: parseFloat(amount) });
    return res;
  },

  async fetchAtmSignals() {
    const res = await this.get('/api/signals/atm-signals');
    return res?.data || [];
  },

  async fetchOptionConfluence(symbol = 'NIFTY', range = 2) {
    const res = await this.get(`/api/confluence/${symbol}?range=${range}`);
    return res;
  },

  async fetchOptionChart(symbol = 'NIFTY', strike = null, optionType = 'CE') {
    let url = `/api/option-chart/candles/${symbol}?option_type=${optionType}`;
    if (strike) url += `&strike=${strike}`;
    const res = await this.get(url);
    return res?.data || null;
  },

  async fetchActiveOptionStrikes(symbol = 'NIFTY') {
    const res = await this.get(`/api/option-chart/active-strikes/${symbol}`);
    return res?.data || res;
  },

  fetchSmartMoney(symbol = 'NIFTY') {
    return this.get(`/api/signals/smart-money/${symbol}`);
  },

  fetchOptionChain(symbol = 'NIFTY') {
    return this.get(`/api/market/option-chain/${symbol}`);
  },

  fetchSmartOITrend(symbol = 'NIFTY', interval = 5, date = null, range = 'ALL') {
    let url = `/api/smart-oi/trend/${symbol}?interval=${interval}&range_mode=${range}`;
    if (date) url += `&date=${encodeURIComponent(date)}`;
    return this.get(url);
  },

  fetchSmartOIDates(symbol = 'NIFTY') {
    return this.get(`/api/smart-oi/dates/${symbol}`);
  },

  fetchStrikeBuildup(symbol = 'NIFTY', range = 5, timeStr = null, tradeDate = null) {
    let url = `/api/buildup-lab/strikes/${symbol}?range=${range}`;
    if (timeStr) url += `&time_str=${encodeURIComponent(timeStr)}`;
    if (tradeDate) url += `&trade_date=${encodeURIComponent(tradeDate)}`;
    return this.get(url);
  },

  fetchStrikeTimeline(symbol = 'NIFTY', range = 5, tradeDate = null) {
    let url = `/api/buildup-lab/timeline/${symbol}?range=${range}`;
    if (tradeDate) url += `&trade_date=${encodeURIComponent(tradeDate)}`;
    return this.get(url);
  },

  fetchStrikeDates(symbol = 'NIFTY') {
    return this.get(`/api/buildup-lab/dates/${symbol}`);
  },

  fetchPriceVsOIData(symbol = 'NIFTY', strike = null, date = null, interval = 1, mode = 'AUTO') {
    let url = `/api/price-vs-oi/data/${symbol}?interval=${interval}&mode=${mode}`;
    if (strike) url += `&strike=${encodeURIComponent(strike)}`;
    if (date) url += `&trade_date=${encodeURIComponent(date)}`;
    return this.get(url);
  },

  fetchPriceVsOIDates(symbol = 'NIFTY') {
    return this.get(`/api/price-vs-oi/dates/${symbol}`);
  },

  fetchFyersStatus() {
    return this.get('/api/fyers/status');
  },

  saveFyersToken(token) {
    return this.post('/api/fyers/token', { access_token: token });
  },

  saveFyersCredentials(clientId, secretKey, redirectUri) {
    return this.post('/api/fyers/credentials', {
      client_id: clientId,
      secret_key: secretKey,
      redirect_uri: redirectUri
    });
  },

  // ShonyaBot & Live Terminal Endpoints
  fetchShonyaStatus() {
    return this.get('/api/shonya/status');
  },

  fetchShonyaMatrix() {
    return this.get('/api/shonya/matrix');
  },

  toggleShonyaBot(active) {
    return this.post('/api/shonya/toggle', { active: Boolean(active) });
  },

  setShonyaMode(mode) {
    return this.post('/api/shonya/mode', { mode: mode });
  },

  updateShonyaCapital(capital) {
    return this.post('/api/shonya/capital', { capital: parseFloat(capital) });
  },

  fetchShonyaCapital() {
    return this.get('/api/shonya/capital');
  },

  updateShonyaSymbols(symbols) {
    return this.post('/api/shonya/symbols', { symbols: symbols });
  },

  fetchShonyaSymbols() {
    return this.get('/api/shonya/symbols');
  },

  fetchShonyaPositions() {
    return this.get('/api/shonya/positions');
  },

  placeManualTrade(tradeData) {
    return this.post('/api/shonya/trade/manual', tradeData);
  },

  modifyShonyaPosition(tradeId, data) {
    return this.post(`/api/shonya/position/${encodeURIComponent(tradeId)}/modify`, data);
  },

  exitShonyaPosition(tradeId, reason = 'MANUAL_EXIT') {
    return this.post(`/api/shonya/position/${encodeURIComponent(tradeId)}/exit?reason=${encodeURIComponent(reason)}`, {});
  },

  squareoffAllShonya() {
    return this.post('/api/shonya/squareoff_all', {});
  },

  fetchShonyaHistory(limit = 50) {
    return this.get(`/api/shonya/history?limit=${limit}`);
  },

  fetchFyersFunds() {
    return this.get('/api/shonya/fyers/funds');
  },

  fetchGrokRecommendation(symbol = 'NIFTY') {
    return this.get(`/api/shonya/ai/recommendation/${symbol}`);
  },

  fetchAIRecommendation(symbol = 'NIFTY') {
    return this.get(`/api/shonya/ai/recommendation/${symbol}`);
  },

  fetchAIMarketOverview(symbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']) {
    return this.post('/api/shonya/ai/market_overview', { symbols });
  },

  executeGrokTrade(symbol = 'NIFTY') {
    return this.post('/api/shonya/ai/execute', { symbol: symbol });
  },

  executeAITrade(symbol = 'NIFTY') {
    return this.post('/api/shonya/ai/execute', { symbol: symbol });
  },

  fetchLiveMatrix() {
    return this.get('/api/matrix/live');
  },

  fetchMatrixTimeseries(symbol = 'NIFTY') {
    return this.get(`/api/matrix/timeseries/${encodeURIComponent(symbol)}`);
  }
};

/**
 * WebSocket Streaming Client with auto-reconnect
 */
export class StreamClient {
  constructor(onMessage, onStatusChange) {
    this.onMessage = onMessage;
    this.onStatusChange = onStatusChange;
    this.ws = null;
    this.activeSymbol = 'NIFTY';
    this.reconnectTimer = null;
    this.retryCount = 0;
    window.addEventListener('terminal:unlocked', () => {
      if (!this.ws || this.ws.readyState > WebSocket.OPEN) this.connect();
    });
  }

  connect() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${window.location.host}/ws/live`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.retryCount = 0;
        clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = setInterval(() => {
          if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({action:'ping'}));
        }, 25000);
        if (this.onStatusChange) this.onStatusChange(true);
        this.subscribe(this.activeSymbol);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (this.onMessage) this.onMessage(data);
        } catch (e) {
          console.debug('WS parse error', e);
        }
      };

      this.ws.onclose = (event) => {
        clearInterval(this.heartbeatTimer);
        if (this.onStatusChange) this.onStatusChange(false);
        if (event.code === 1008) { window.dispatchEvent(new CustomEvent("terminal:unauthorized")); return; }
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this.ws.close();
      };
    } catch (e) {
      this.scheduleReconnect();
    }
  }

  subscribe(symbol) {
    this.activeSymbol = symbol;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'subscribe', symbol: symbol }));
    }
  }

  scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), Math.min(30000, 1000 * 2 ** this.retryCount++) + Math.random() * 1000);
  }
}
