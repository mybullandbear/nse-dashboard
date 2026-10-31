/**
 * Institutional Access Gateway & Password Gate Component
 * [TEMPORARILY DISABLED FOR PUBLIC / FRIEND REVIEW]
 */
import { ApiClient } from '../api.js';

let _gateElement = null;
let _isUnlocked = true;

export const AccessGate = {
  /**
   * Password protection bypassed for public review.
   */
  async ensureAuthorized() {
    _isUnlocked = true;
    this.hideGate();
    return true;
  },

  isUnlocked() {
    return true;
  },

  showGate() {
    // Intentionally disabled for public review
    _isUnlocked = true;
    this.hideGate();
  },

  hideGate() {
    document.documentElement.classList.remove('terminal-locked');
    if (document.body) document.body.classList.remove('terminal-locked');

    if (_gateElement && document.body && document.body.contains(_gateElement)) {
      _gateElement.style.transition = 'opacity 0.2s ease';
      _gateElement.style.opacity = '0';
      setTimeout(() => {
        if (_gateElement && document.body && document.body.contains(_gateElement)) {
          document.body.removeChild(_gateElement);
        }
      }, 200);
    }
  },

  async lockTerminal() {
    console.log('Password protection is currently disabled for public review.');
  }
};
