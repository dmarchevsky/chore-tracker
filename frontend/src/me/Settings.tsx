// Where the app itself is set up, rather than the chores. This exists because the install
// prompt used to be a banner on every screen: it nagged, and it had no room to explain why
// installing is required at all (iOS delivers Web Push only to a Home Screen app, spec §14.5).
import { Card, Button } from '../shared/ui';
import { useAuth } from '../auth/AuthContext';
import { isStandalone } from '../pwa/install';
import { PushCard } from '../pwa/PushCard';

export function Settings() {
  const { me, logout } = useAuth();

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">Settings</h1>

      <PushCard
        heading="Reminders"
        pitch="Get a nudge when a chore opens, when it’s nearly due, and when a parent replies."
        installReason="Reminders only work once ChoreKeeper is on your Home Screen."
      />

      <Card>
        <h2 className="font-semibold">This device</h2>
        <p className="mt-1 text-sm text-slate-400">
          {isStandalone() ? 'Installed on your Home Screen.' : 'Running in a browser tab.'}
        </p>
      </Card>

      <Card>
        <h2 className="font-semibold">Account</h2>
        {/* Kids sign in with a Google account now, so there is a real identity to leave —
            and on a shared tablet, leaving it is the whole point. */}
        <p className="mt-1 text-sm text-slate-400">Signed in as {me?.email ?? me?.display_name}.</p>
        <Button
          className="mt-3 min-h-0 px-3 py-2 text-sm"
          variant="ghost"
          onClick={() => void logout()}
        >
          Sign out
        </Button>
      </Card>
    </div>
  );
}
