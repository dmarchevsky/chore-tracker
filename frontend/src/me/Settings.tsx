// Where the app itself is set up, rather than the chores. This exists because the install
// prompt used to be a banner on every screen: it nagged, and it had no room to explain why
// installing is required at all (iOS delivers Web Push only to a Home Screen app, spec §14.5).
import { useEffect, useState } from 'react';
import { Card, Button, Spinner } from '../shared/ui';
import { isIos, isStandalone } from '../pwa/install';
import { pushState, subscribeToPush, type PushState } from '../pwa/push';

export function Settings() {
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

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">Settings</h1>

      <Card>
        <h2 className="font-semibold">Reminders</h2>
        {push === null ? (
          <Spinner />
        ) : push === 'subscribed' ? (
          <p className="mt-1 text-sm text-emerald-400">
            Reminders are on — you’ll hear about chores when they’re due.
          </p>
        ) : push === 'denied' ? (
          // subscribeToPush cannot recover from a denial, so don't offer a button that
          // would silently do nothing.
          <p className="mt-1 text-sm text-slate-400">
            Notifications are blocked. Turn them back on for ChoreKeeper in your phone’s settings,
            then come back here.
          </p>
        ) : push === 'unsupported' ? (
          <p className="mt-1 text-sm text-slate-400">
            This browser can’t send reminders. Ask a parent about using Chrome or Safari.
          </p>
        ) : push === 'needs-install' ? (
          <div className="mt-1 text-sm text-slate-300">
            <p className="text-slate-400">
              Reminders only work once ChoreKeeper is on your Home Screen.
            </p>
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
            <p className="mt-1 text-sm text-slate-400">
              Get a nudge when a chore opens, when it’s nearly due, and when a parent replies.
            </p>
            <Button className="mt-3 min-h-0 px-3 py-2 text-sm" onClick={turnOn} disabled={busy}>
              Turn on reminders
            </Button>
          </>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold">This device</h2>
        <p className="mt-1 text-sm text-slate-400">
          {isStandalone() ? 'Installed on your Home Screen.' : 'Running in a browser tab.'}
        </p>
      </Card>
    </div>
  );
}
