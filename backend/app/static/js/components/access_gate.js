import { ApiClient } from '../api.js';
let unlocked = false;
let pending;
export const AccessGate = {
  isUnlocked() { return unlocked; },
  async ensureAuthorized() {
    if (await ApiClient.checkAccess()) { unlocked = true; this.hideGate(); return true; }
    return this.showGate();
  },
  showGate() {
    unlocked = false;
    if (pending) return pending;
    pending = new Promise(resolve => {
      const gate = document.createElement('dialog');
      gate.id = 'terminal-access-gate';
      gate.innerHTML = `<form><h1>MYBULLANDBEAR</h1><p>Sign in to your trading terminal</p><label>Access password<input name="password" type="password" autocomplete="current-password" required maxlength="256"></label><button type="submit">Unlock terminal</button><p role="alert"></p></form>`;
      document.body.append(gate); gate.showModal();
      gate.addEventListener('cancel', e => e.preventDefault());
      gate.querySelector('form').addEventListener('submit', async e => {
        e.preventDefault(); const btn = gate.querySelector('button'); btn.disabled = true;
        try { await ApiClient.verifyPassword(gate.querySelector('input').value, false); unlocked = true; gate.remove(); pending = null; window.dispatchEvent(new CustomEvent("terminal:unlocked")); resolve(true); }
        catch (err) { gate.querySelector('[role=alert]').textContent = err.message; }
        finally { btn.disabled = false; }
      });
    });
    return pending;
  },
  hideGate() { document.getElementById('terminal-access-gate')?.remove(); },
  async lockTerminal() { unlocked = false; await ApiClient.logout(); }
};
window.addEventListener('terminal:unauthorized', () => AccessGate.showGate());
