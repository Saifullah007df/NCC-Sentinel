// Registration is best effort; no authenticated pages are cached by the service worker.
if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", {scope:"/"}).catch(() => {});
  });
}
