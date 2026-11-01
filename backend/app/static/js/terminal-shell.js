import { AccessGate } from './components/access_gate.js';
const views = {
  dashboard: ['Market overview','Index alignment, option positioning and market context'],
  'option-confluence': ['Option confluence','Inspect signal agreement and the underlying evidence'],
  'shonya-terminal': ['ShonyaBot workspace','Paper positions, risk controls and execution journal'],
  'oi-analytics': ['Call vs Put OI','Compare positioning, changes in open interest and price'],
  chain: ['Option chain matrix','Strike-level call and put data in one workspace']
};
function updateView(tab) {
  const view = views[tab] || views.dashboard;
  document.getElementById('workspace-title').textContent = view[0];
  document.getElementById('workspace-subtitle').textContent = view[1];
  document.querySelectorAll('[data-tab]').forEach(button => button.setAttribute('aria-current', button.dataset.tab === tab ? 'page' : 'false'));
}
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => updateView(button.dataset.tab)));
updateView(new URLSearchParams(location.search).get('tab') || location.hash.slice(1) || 'dashboard');
document.getElementById('toggle-replay').addEventListener('click', event => {
  const collapsed = document.body.classList.toggle('replay-collapsed');
  event.currentTarget.setAttribute('aria-expanded', String(!collapsed));
});
document.getElementById('terminal-lock').addEventListener('click', () => AccessGate.lockTerminal());
const network = document.getElementById('network-state');
function connectivity() {
  network.textContent = navigator.onLine ? 'Network connected' : 'Offline · trading unavailable';
  network.dataset.state = navigator.onLine ? 'ok' : 'error';
}
window.addEventListener('online', connectivity);window.addEventListener('offline', connectivity);connectivity();
let receivedAt = 0;
window.addEventListener('terminal:data-status', ({detail}) => {
  const label = document.getElementById('data-freshness');
  if (detail.error) { label.textContent = 'Market data unavailable'; label.dataset.state = 'error'; receivedAt = 0; return; }
  if (detail.source) {
    label.textContent = detail.source.replaceAll('_',' ') + (detail.age != null ? ` · ${Math.round(detail.age)}s old` : '');
    label.dataset.state = /STALE|CLOSED|UNAVAILABLE|SIMULATOR|FROZEN/.test(detail.source) ? 'stale' : 'ok';
    receivedAt = Date.now();
  }
});
setInterval(() => {
  if (receivedAt && Date.now() - receivedAt > 30000) {
    const label = document.getElementById('data-freshness');
    label.textContent = 'Snapshot not refreshed · check connection'; label.dataset.state = 'stale';
  }
}, 5000);
