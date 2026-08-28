// iOS delivers Web Push ONLY to a PWA on the Home Screen (spec §14.5). Detect the plain
// browser tab so onboarding can walk the kid through installing.

export function isStandalone(): boolean {
  const mm = window.matchMedia?.('(display-mode: standalone)').matches ?? false;
  // iOS Safari exposes navigator.standalone instead of the media query.
  const iosStandalone = (navigator as unknown as { standalone?: boolean }).standalone === true;
  return mm || iosStandalone;
}

export function isIos(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}
