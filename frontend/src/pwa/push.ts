import { api } from '../api/client';
import { isStandalone, pushSupported } from './install';

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export type PushState = 'unsupported' | 'needs-install' | 'denied' | 'ready' | 'subscribed';

export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return 'unsupported';
  if (!isStandalone()) return 'needs-install';
  if (Notification.permission === 'denied') return 'denied';
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  return sub ? 'subscribed' : 'ready';
}

export async function subscribeToPush(): Promise<PushState> {
  if ((await pushState()) === 'unsupported') return 'unsupported';
  if (!isStandalone()) return 'needs-install';

  const perm = await Notification.requestPermission();
  if (perm !== 'granted') return 'denied';

  const { public_key } = await api.get<{ public_key: string }>('/push/vapid-key');
  if (!public_key) return 'ready'; // server has no VAPID keys configured

  const reg = await navigator.serviceWorker.ready;
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
    }));

  await api.post('/push/subscribe', sub.toJSON());
  return 'subscribed';
}

export async function unsubscribeFromPush(): Promise<PushState> {
  if (!pushSupported()) return 'unsupported';
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return (await pushState()) as PushState;
  // Drop the server's copy first: a subscription it keeps pushing to after the browser has
  // dropped it is dead weight that only clears when the endpoint starts returning 410.
  await api.del(`/push/subscribe?endpoint=${encodeURIComponent(sub.endpoint)}`);
  await sub.unsubscribe();
  return 'ready';
}
