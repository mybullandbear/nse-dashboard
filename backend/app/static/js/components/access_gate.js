import { ApiClient } from '../api.js';
let unlocked = true;
let pending = null;
export const AccessGate = {
  isUnlocked() { return true; },
  async ensureAuthorized() {
    unlocked = true;
    this.hideGate();
    return true;
  },
  showGate() {
    unlocked = true;
    this.hideGate();
    return Promise.resolve(true);
  },
  hideGate() { document.getElementById('terminal-access-gate')?.remove(); },
  async lockTerminal() { unlocked = true; }
};
window.addEventListener('terminal:unauthorized', () => AccessGate.showGate());
