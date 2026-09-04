import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { subscribeToPush } from './push';
import { api } from '../api/client';

vi.mock('../api/client', () => ({ api: { get: vi.fn(), post: vi.fn(), del: vi.fn() } }));

// A minimally believable installed PWA: standalone, permission grantable, a registration
// whose pushManager records what key it was handed.
function installApp(key: string) {
  const subscribe = vi.fn().mockResolvedValue({
    endpoint: 'https://push.example/abc',
    toJSON: () => ({ endpoint: 'https://push.example/abc', keys: {} }),
  });
  vi.stubGlobal('matchMedia', () => ({ matches: true }));
  vi.stubGlobal('Notification', {
    permission: 'default',
    requestPermission: async () => 'granted',
  });
  vi.stubGlobal('PushManager', class {});
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: {
      ready: Promise.resolve({
        pushManager: { getSubscription: async () => null, subscribe },
      }),
    },
  });
  vi.mocked(api.get).mockResolvedValue({ public_key: key });
  return subscribe;
}

// A real key from `just vapid-keys`: an uncompressed P-256 point, 65 bytes, base64url.
const GOOD =
  'BEVzCDlTPcFtfgyi8EiY6sqFkt6T_Oyxp5VCmOxsUxt2vg8TSoemYHVMa4qj3xZkKBtAPjBtqCFZrwilrkAGpSk';

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe('the VAPID key the server hands back', () => {
  it('subscribes with the decoded 65-byte point when it is well formed', async () => {
    const subscribe = installApp(GOOD);

    expect(await subscribeToPush()).toBe('subscribed');
    expect(subscribe.mock.calls[0][0].applicationServerKey).toHaveLength(65);
  });

  it('tolerates the trailing newline an env file loves to add', async () => {
    const subscribe = installApp(GOOD + '\n');

    expect(await subscribeToPush()).toBe('subscribed');
    expect(subscribe.mock.calls[0][0].applicationServerKey).toHaveLength(65);
  });

  it('names the key when it is not base64url at all', async () => {
    // e.g. a PEM block pasted in whole. Previously atob threw InvalidCharacterError from
    // inside a helper, which reached the card as an unhandled rejection and looked like the
    // button doing nothing.
    installApp('-----BEGIN PUBLIC KEY-----\nMFkwEw==\n-----END PUBLIC KEY-----');

    await expect(subscribeToPush()).rejects.toThrow(/VAPID_PUBLIC_KEY/);
  });

  it('names the key when it decodes to the wrong shape', async () => {
    // Valid base64url, wrong thing — the private key, say. The push service would otherwise
    // reject this much later with something far vaguer.
    installApp('aGVsbG8td29ybGQ');

    await expect(subscribeToPush()).rejects.toThrow(/65/);
  });

  it('reports an unconfigured server rather than pretending it is ready', async () => {
    installApp('');

    expect(await subscribeToPush()).toBe('unconfigured');
  });
});
