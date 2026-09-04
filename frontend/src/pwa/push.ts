import { api } from '../api/client';
import { isStandalone, pushSupported } from './install';

/** Decode the server's VAPID public key into the raw P-256 point pushManager wants.
 *
 *  Validated rather than trusted: the key is pasted into an env file by hand, and every way
 *  of getting it wrong — a trailing newline, standard base64 instead of base64url, a PEM
 *  block, the private key by mistake — surfaces as `atob` throwing InvalidCharacterError or
 *  as the push service refusing the subscription much later. Both read as "the button does
 *  nothing". Fail here instead, naming the key. */
function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const clean = base64.trim();
  if (!/^[A-Za-z0-9_-]+=*$/.test(clean))
    throw new Error(
      'the server’s VAPID public key is not base64url — check VAPID_PUBLIC_KEY for stray characters or line breaks',
    );
  const padding = '='.repeat((4 - (clean.length % 4)) % 4);
  const raw = atob((clean + padding).replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  // An uncompressed P-256 point: 0x04 then two 32-byte coordinates. Anything else is a
  // different kind of key, and the push service would reject it with a far vaguer error.
  if (out.length !== 65 || out[0] !== 0x04)
    throw new Error(
      `the server’s VAPID public key is ${out.length} bytes, not the expected 65 — regenerate it with \`just vapid-keys\``,
    );
  return out;
}

export type PushState =
  | 'unsupported'
  | 'needs-install'
  | 'denied'
  /** The server has no VAPID keys, so there is nothing to subscribe to. Used to be
   *  indistinguishable from 'ready', which is why turning them on appeared to no-op. */
  | 'unconfigured'
  | 'ready'
  | 'subscribed';

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
  // Nothing to subscribe to. This used to return 'ready', which renders as the same
  // "Turn on notifications" button the person just pressed — the app appeared to do nothing
  // at all, and the one fact that explains it was known right here and thrown away.
  if (!public_key) return 'unconfigured';

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
