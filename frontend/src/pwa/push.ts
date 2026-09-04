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

export interface PushTestResult {
  status: string;
  devices: number;
  error: string | null;
}

export async function sendTestPush(): Promise<PushTestResult> {
  return api.post<PushTestResult>('/push/test');
}

/** Plain English for a status the server reports — the whole point of the test button.
 *  Ordered by what has to be fixed first: a server with no keys sends nothing to anyone, so
 *  it outranks "no device subscribed", which the server cannot even see until keys exist. */
export function describeTest(r: PushTestResult): { ok: boolean; text: string } {
  if (r.status === 'skipped')
    return {
      ok: false,
      text: 'The server has no VAPID keys, so nothing was sent. Generate a pair with `just vapid-keys` and restart the api and worker — see docs/notifications.md.',
    };
  if (r.status === 'no_subs' || r.devices === 0)
    return {
      ok: false,
      text: 'No device is subscribed for you yet — turn notifications on, on each device you want them.',
    };
  if (r.status === 'sent')
    return {
      ok: true,
      text: `Sent to ${r.devices} device${r.devices === 1 ? '' : 's'}. If nothing appears within a few seconds, check this device’s notification settings.`,
    };
  return {
    ok: false,
    text: r.error ? `The push service refused it: ${r.error}` : 'The send failed.',
  };
}
