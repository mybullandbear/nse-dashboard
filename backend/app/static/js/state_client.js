/**
 * Single Shared Frontend Market State Client (WebSocket + Fallback REST Snapshot)
 * ══════════════════════════════════════════════════════════════════════════════
 * Replaces ALL independent component polling timers with a single canonical stream.
 */

class SharedMarketStateClient {
  constructor() {
    this.state = {
      version: 0,
      timestamp: Date.now(),
      activeSymbol: 'NIFTY',
      indices: { indices: [], vix: { last: 13.5, change: 0, pChange: 0 } },
      directional: {},
      confluence: {},
      oi_analytics: {},
      strike_buildup: {},
      price_vs_oi: {},
      shonya: { mode: 'PAPER', active: false, positions: [] }
    };

    this.listeners = new Set();
    this.ws = null;
    this.reconnectTimer = null;
    this.fallbackPollTimer = null;
    this.isConnected = false;
  }

  init() {
    this.connectWebSocket();
    this.fetchInitialSnapshot();

    // Pause polling when browser tab is hidden to save battery & data
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        this.pause();
      } else {
        this.resume();
      }
    });
  }

  subscribe(listener) {
    this.listeners.add(listener);
    // Call immediately with existing state
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  notify() {
    for (const listener of this.listeners) {
      try {
        listener(this.state);
      } catch (e) {
        console.error('Error in state subscriber:', e);
      }
    }
  }

  setSymbol(symbol) {
    if (this.state.activeSymbol !== symbol) {
      this.state.activeSymbol = symbol;
      this.fetchSnapshotForSymbol(symbol);
    }
  }

  connectWebSocket() {
    if (this.ws) {
      try { this.ws.close(); } catch (e) {}
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/ws`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.isConnected = true;
        console.log('⚡ Connected to Central Market Push Gateway');
        if (this.fallbackPollTimer) {
          clearInterval(this.fallbackPollTimer);
          this.fallbackPollTimer = null;
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'SNAPSHOT' && msg.data) {
            this.applySnapshot(msg.data);
          }
        } catch (e) {
          console.error('Error parsing WS message:', e);
        }
      };

      this.ws.onclose = () => {
        this.isConnected = false;
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this.isConnected = false;
        try { this.ws.close(); } catch (e) {}
      };
    } catch (e) {
      this.scheduleReconnect();
    }
  }

  scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connectWebSocket();
    }, 4000);

    // Fallback: If WS is disconnected, poll snapshot every 6s
    if (!this.fallbackPollTimer) {
      this.fallbackPollTimer = setInterval(() => {
        if (!this.isConnected) {
          this.fetchSnapshotForSymbol(this.state.activeSymbol);
        }
      }, 6000);
    }
  }

  async fetchInitialSnapshot() {
    await this.fetchSnapshotForSymbol(this.state.activeSymbol);
  }

  async fetchSnapshotForSymbol(sym) {
    try {
      const res = await fetch(`/api/market/state/${sym}?version=${this.state.version}`);
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'OK' && json.data) {
        this.applySnapshot(json.data);
      }
    } catch (e) {
      console.warn('REST snapshot fallback error:', e);
    }
  }

  applySnapshot(data) {
    this.state = {
      ...this.state,
      version: data.version || this.state.version + 1,
      timestamp: data.timestamp || Date.now(),
      indices: data.indices || this.state.indices,
      directional: data.directional || this.state.directional,
      confluence: data.confluence || this.state.confluence,
      oi_analytics: data.oi_analytics || this.state.oi_analytics,
      strike_buildup: data.strike_buildup || this.state.strike_buildup,
      price_vs_oi: data.price_vs_oi || this.state.price_vs_oi,
      shonya: data.shonya || this.state.shonya
    };
    this.notify();
  }

  pause() {
    if (this.fallbackPollTimer) {
      clearInterval(this.fallbackPollTimer);
      this.fallbackPollTimer = null;
    }
  }

  resume() {
    if (!this.isConnected) {
      this.connectWebSocket();
      this.fetchSnapshotForSymbol(this.state.activeSymbol);
    }
  }
}

export const marketClient = new SharedMarketStateClient();
