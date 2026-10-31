/**
 * Fyers Broker API Authentication Modal Component
 */
import { store } from '../state.js';
import { ApiClient } from '../api.js';

export function renderAuthModal(container, onClose) {
  const state = store.getState();
  const fyers = state.fyersStatus || {};

  container.innerHTML = `
    <div class="modal-overlay active" id="fyers-modal-overlay">
      <div class="modal-card">
        <div class="modal-header">
          <div class="modal-title">⚡ Fyers Broker API Integration</div>
          <button class="modal-close" id="modal-close-btn">&times;</button>
        </div>

        <div style="font-family: var(--font-mono); font-size: 11px; padding: 10px; border-radius: 6px; background: ${fyers.has_token ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)'}; border: 1px solid ${fyers.has_token ? '#10b981' : '#f59e0b'};">
          STATUS: <strong>${fyers.has_token ? '● ACTIVE & VERIFIED' : '● TOKEN NOT SET / EXPIRED'}</strong><br/>
          CLIENT ID: <strong>${fyers.client_id || '7BRKBHOFP8-100'}</strong><br/>
          REDIRECT URI: <span style="opacity: 0.8;">${fyers.redirect_uri || 'http://137.23.42.11:8000/api/fyers/callback'}</span>
        </div>

        <!-- 1-Click OAuth Login -->
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <label class="form-label">METHOD 1: AUTOMATIC 3-LEGGED OAUTH</label>
          <a href="/api/fyers/login" class="btn-primary" style="text-align: center; text-decoration: none; display: block;" target="_blank">
            🔑 LOGIN WITH FYERS BROKER
          </a>
          <span style="font-size: 10.5px; color: var(--text-muted); font-family: var(--font-mono);">
            Opens Fyers login page in new tab. Redirects back to complete authentication.
          </span>
        </div>

        <div style="height: 1px; background: var(--border-subtle); margin: 4px 0;"></div>

        <!-- Direct Token Paste -->
        <div class="form-group">
          <label class="form-label">METHOD 2: DIRECT ACCESS TOKEN PASTE</label>
          <input 
            type="password" 
            class="form-input" 
            id="input-access-token" 
            placeholder="Paste your daily Fyers Access Token..."
          />
          <button class="btn-primary" id="btn-save-token" style="background: #1e293b; border: 1px solid rgba(56, 189, 248, 0.4); color: #38bdf8;">
            VERIFY & ACTIVATE TOKEN
          </button>
          <div id="token-status-msg" style="font-family: var(--font-mono); font-size: 11px; display: none;"></div>
        </div>
      </div>
    </div>
  `;

  // Attach handlers
  const closeBtn = container.querySelector('#modal-close-btn');
  const overlay = container.querySelector('#fyers-modal-overlay');

  const doClose = () => {
    container.innerHTML = '';
    if (onClose) onClose();
  };

  closeBtn.addEventListener('click', doClose);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) doClose();
  });

  const saveTokenBtn = container.querySelector('#btn-save-token');
  const tokenInput = container.querySelector('#input-access-token');
  const statusMsg = container.querySelector('#token-status-msg');

  saveTokenBtn.addEventListener('click', async () => {
    const token = tokenInput.value.trim();
    if (!token) return;

    saveTokenBtn.disabled = true;
    saveTokenBtn.innerText = 'VERIFYING WITH FYERS...';
    statusMsg.style.display = 'none';

    try {
      const res = await ApiClient.saveFyersToken(token);
      statusMsg.style.display = 'block';
      statusMsg.style.color = '#10b981';
      statusMsg.innerText = '✓ ' + (res.message || 'Token successfully verified!');
      
      // Refresh status in store
      const newStatus = await ApiClient.fetchFyersStatus();
      if (newStatus) store.setState({ fyersStatus: newStatus });

      setTimeout(() => doClose(), 1500);
    } catch (err) {
      statusMsg.style.display = 'block';
      statusMsg.style.color = '#ef4444';
      statusMsg.innerText = '✕ ' + (err.message || 'Verification failed.');
    } finally {
      saveTokenBtn.disabled = false;
      saveTokenBtn.innerText = 'VERIFY & ACTIVATE TOKEN';
    }
  });
}
