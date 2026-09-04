// The one place notifications get turned on, for both roles. It was a kid-only card in
// me/Settings.tsx; the parent needs the same five branches (and the same iOS install
// walk-through — Web Push reaches a Home Screen app or nothing, spec §14.5), so it lives
// here and takes its copy from the caller rather than being duplicated.
import { useEffect, useState } from 'react';
import { Button, Card, Spinner } from '../shared/ui';
import { isIos } from './install';
import { pushState, subscribeToPush, unsubscribeFromPush, type PushState } from './push';

export function PushCard({
  heading,
  pitch,
  installReason,
}: {
  heading: string;
  pitch: string;
  installReason: string;
}) {
  const [push, setPush] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);

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
    setPush(await unsubscribeFromPush());
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
    </Card>
  );
}
