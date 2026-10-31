/**
 * PWA Install Prompt Handler
 */
let deferredPrompt = null;

export function initPWAInstaller() {
  const banner = document.getElementById('pwa-install-banner');
  const installBtn = document.getElementById('pwa-install-btn');

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (banner) {
      banner.classList.add('visible');
    }
  });

  if (installBtn) {
    installBtn.addEventListener('click', async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      console.log(`User install response: ${outcome}`);
      deferredPrompt = null;
      if (banner) {
        banner.classList.remove('visible');
      }
    });
  }

  // Register Service Worker
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js')
        .then((reg) => console.log('PWA ServiceWorker registered:', reg.scope))
        .catch((err) => console.warn('PWA ServiceWorker registration failed:', err));
    });
  }
}
