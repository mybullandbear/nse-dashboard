/**
 * Index Overview Ticker Bar Component
 * FLICKER-FREE: card structure built once; price/pct/range patched in-place.
 */
import { store } from '../state.js';

let _tickerBuilt  = false;
let _lastSymbols  = '';        // "s1|s2" to detect active-pair highlight change
let _lastSymList  = '';        // symbol names fingerprint to detect structural change

const DEFAULT_LIST = [
  { symbol: 'NIFTY',      name: 'NIFTY 50',     last: 23240.80,  change: 104.90, percent_change: 0.45, low: 23116.1, high: 23281.15 },
  { symbol: 'BANKNIFTY',  name: 'BANK NIFTY',   last: 56171.85,  change: 339.05, percent_change: 0.61, low: 55800.0, high: 56350.0  },
  { symbol: 'FINNIFTY',   name: 'FIN NIFTY',    last: 25216.15,  change: 136.75, percent_change: 0.55, low: 25050.0, high: 25290.0  },
  { symbol: 'MIDCPNIFTY', name: 'MIDCAP NIFTY', last: 14283.05,  change:  14.70, percent_change: 0.10, low: 14200.0, high: 14320.0  },
  { symbol: 'SENSEX',     name: 'BSE SENSEX',   last: 81520.50,  change: 185.20, percent_change: 0.23, low: 81200.0, high: 81750.0  },
];

export function renderTickerBar(container, onSelectSymbol) {
  const state   = store.getState();
  const indices = state.indices || [];
  const s1      = state.symbol1;
  const s2      = state.symbol2;
  const cards   = indices.length >= 4 ? indices : DEFAULT_LIST;

  const symKey  = `${s1}|${s2}`;
  const symList = cards.map(c => c.symbol).join(',');

  // ── Build DOM structure only once (or when symbol list changes) ──────────
  if (!_tickerBuilt || symList !== _lastSymList || !container.querySelector('.ticker-grid')) {
    _tickerBuilt = true;
    _lastSymList = symList;

    const cardHtml = cards.map(item => {
      const isActive = (item.symbol === s1 || item.symbol === s2);
      return [
        `<div class="ticker-card ${isActive ? 'active' : ''}" data-symbol="${item.symbol}">`,
        '  <div class="ticker-card-header">',
        `    <span class="ticker-name">${item.name || item.symbol}</span>`,
        `    <span class="ticker-badge badge-bull" data-badge="${item.symbol}">`,
        `      \u25b2 +${Math.abs(item.percent_change || 0).toFixed(2)}%`,
        '    </span>',
        '  </div>',
        '  <div class="ticker-price-row">',
        `    <span class="ticker-price" data-price="${item.symbol}">`,
        `      ${_fmtPrice(item.last)}`,
        '    </span>',
        `    <span class="ticker-change text-bull" data-change="${item.symbol}">`,
        `      +${(item.change || 0).toFixed(2)}`,
        '    </span>',
        '  </div>',
        `  <div class="ticker-range-bar" data-range-tip="${item.symbol}" title="">`,
        `    <div class="ticker-range-fill" data-range-fill="${item.symbol}" style="width:50%;"></div>`,
        '  </div>',
        '</div>',
      ].join('\n');
    }).join('\n');

    container.innerHTML = `<div class="ticker-grid">${cardHtml}</div>`;

    container.querySelectorAll('.ticker-card').forEach(card => {
      card.addEventListener('click', () => {
        const sym = card.getAttribute('data-symbol');
        if (onSelectSymbol) onSelectSymbol(sym);
      });
    });

    _lastSymbols = ''; // force active-pair highlight update after rebuild
  }

  // ── Patch values in-place every call ────────────────────────────────────
  cards.forEach(item => {
    const isBull   = (item.percent_change || 0) >= 0;
    const low      = item.low  || item.last * 0.995;
    const high     = item.high || item.last * 1.005;
    const rangeSpan = Math.max(1, high - low);
    const pct      = Math.min(100, Math.max(0, ((item.last - low) / rangeSpan) * 100));

    const badgeEl  = container.querySelector(`[data-badge="${item.symbol}"]`);
    const priceEl  = container.querySelector(`[data-price="${item.symbol}"]`);
    const changeEl = container.querySelector(`[data-change="${item.symbol}"]`);
    const fillEl   = container.querySelector(`[data-range-fill="${item.symbol}"]`);
    const tipEl    = container.querySelector(`[data-range-tip="${item.symbol}"]`);

    if (badgeEl) {
      const newBadge = `${isBull ? '\u25b2 +' : '\u25bc '}${Math.abs(item.percent_change).toFixed(2)}%`;
      badgeEl.className = `ticker-badge ${isBull ? 'badge-bull' : 'badge-bear'}`;
      _setText(badgeEl, newBadge);
    }
    if (priceEl)  _setText(priceEl,  _fmtPrice(item.last));
    if (changeEl) {
      const chgTxt = `${isBull ? '+' : ''}${(item.change || 0).toFixed(2)}`;
      changeEl.className = `ticker-change ${isBull ? 'text-bull' : 'text-bear'}`;
      _setText(changeEl, chgTxt);
    }
    if (fillEl) fillEl.style.width = `${pct}%`;
    if (tipEl)  tipEl.title = `Low: ${low.toFixed(1)} | High: ${high.toFixed(1)}`;
  });

  // Update active-pair highlight only when pair changes
  if (symKey !== _lastSymbols) {
    _lastSymbols = symKey;
    container.querySelectorAll('.ticker-card').forEach(card => {
      const sym = card.getAttribute('data-symbol');
      card.classList.toggle('active', sym === s1 || sym === s2);
    });
  }
}

function _fmtPrice(v) {
  return v ? v.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 2 }) : '--';
}
function _setText(el, text) {
  if (el && el.textContent !== text) el.textContent = text;
}
