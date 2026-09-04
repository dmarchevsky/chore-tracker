// The one place notifications get turned on, for both roles. It was a kid-only card in
// me/Settings.tsx; the parent needs the same five branches (and the same iOS install
// walk-through — Web Push reaches a Home Screen app or nothing, spec §14.5), so it lives
// here and takes its copy from the caller rather than being duplicated.
import { useEffect, useState } from 'react';
import { Button, Card, Spinner } from '../shared/ui';
import { isIos } from './install';
import {
  describeTest,
  pushState,
  sendTestPush,
  subscribeToPush,
  unsubscribeFromPush,
  type PushState,
} from './push';

export function PushCard({
  heading,
  pitch,
  installReason,
  offerTest = false,
}: {
  heading: string;
  pitch: string;
  installReason: string;
  /** Show the "Send a test notification" button. A push that silently never arrives is the
   *  failure this catches, and the parent is the one who has to diagnose it for the whole
   *  household. Shown in every push state, not only when subscribed — see below. */
  offerTest?: boolean;
}) {
  const [push, setPush] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    void pushState().then(setPush);
  }, []);

  async function turnOn() {
    setBusy(true);
    setPush(await subscribeToPush());
    setBusy(false);
  }

  async function turnOff() {
    setBusy(true);
    setTest(null);
    setPush(await unsubscribeFromPush());
    setBusy(false);
  }

  async function runTest() {
    setBusy(true);
    setTest(null);
    try {
      setTest(describeTest(await sendTestPush()));
    } catch (e) {
      // A network or auth failure never reached the sender at all, which is a different
      // diagnosis from a push the server tried and could not deliver.
      setTest({ ok: false, text: `Couldn’t ask the server to send: ${(e as Error).message}` });
    }
    setBusy(false);
  }

  return (
    <Card>
      <h2 className="font-semibold">{heading}</h2>
      {push === null ? (
        <Spinner />
      ) : push === 'subscribed' ? (
        <>
          <p className="mt-1 text-sm text-emerald-400">Notifications are on for this device.</p>
          <Button
            className="mt-3 min-h-0 px-3 py-2 text-sm"
            variant="ghost"
            onClick={() => void turnOff()}
            disabled={busy}
          >
            Turn off
          </Button>
        </>
      ) : push === 'denied' ? (
        // subscribeToPush cannot recover from a denial, so don't offer a button that
        // would silently do nothing.
        <p className="mt-1 text-sm text-slate-400">
          Notifications are blocked. Turn them back on for ChoreKeeper in your device’s settings,
          then come back here.
        </p>
      ) : push === 'unconfigured' ? (
        // Server-side, and the same for everyone in the household — so say what to do rather
        // than sending the parent to hunt through their phone's settings.
        <div className="mt-1 text-sm text-amber-400">
          <p>This ChoreKeeper has no notification keys, so nothing can be sent to any device.</p>
          <p className="mt-2 text-slate-400">
            On the machine running ChoreKeeper: <code>just vapid-keys</code>, paste both lines into{' '}
            <code>env.production</code>, then restart the api and worker. See docs/notifications.md.
          </p>
        </div>
      ) : push === 'unsupported' ? (
        <p className="mt-1 text-sm text-slate-400">
          This browser can’t show notifications. Try Chrome or Safari.
        </p>
      ) : push === 'needs-install' ? (
        <div className="mt-1 text-sm text-slate-300">
          <p className="text-slate-400">{installReason}</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-slate-300">
            {isIos() ? (
              <>
                <li>Tap the Share button at the bottom of Safari.</li>
                <li>Scroll down and tap “Add to Home Screen”.</li>
                <li>Open ChoreKeeper from your Home Screen and come back here.</li>
              </>
            ) : (
              <>
                <li>Open your browser’s menu.</li>
                <li>Choose “Install app” (or “Add to Home screen”).</li>
                <li>Open ChoreKeeper from your Home Screen and come back here.</li>
              </>
            )}
          </ol>
        </div>
      ) : (
        <>
          <p className="mt-1 text-sm text-slate-400">{pitch}</p>
          <Button
            className="mt-3 min-h-0 px-3 py-2 text-sm"
            onClick={() => void turnOn()}
            disabled={busy}
          >
            Turn on notifications
          </Button>
        </>
      )}

      {/* Outside the state branches on purpose. This is the diagnostic, and the states that
          most need diagnosing are the ones where nothing is subscribed — hiding it there (as
          it was first shipped) made it invisible exactly when a parent reaches for it. The
          server's answer is useful from any state: it knows whether it has VAPID keys at all,
          and whether any of this parent's *other* devices are registered. */}
      {offerTest && push !== null && (
        <div className="mt-3 border-t border-slate-800 pt-3">
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="ghost"
            onClick={() => void runTest()}
            disabled={busy}
          >
            Send a test notification
          </Button>
          {test ? (
            <p className={`mt-2 text-sm ${test.ok ? 'text-emerald-400' : 'text-amber-400'}`}>
              {test.text}
            </p>
          ) : (
            <p className="mt-2 text-xs text-slate-500">
              Sends to your own devices and reports what happened.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
