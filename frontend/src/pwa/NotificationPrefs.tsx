// What each person wants to hear about. Sits under PushCard on both Settings screens:
// PushCard is the per-device switch ("can this phone receive anything at all"), this is the
// per-person one, and the API hands each role only its own categories.
import { useState } from 'react';
import { Card, Spinner, Toggle } from '../shared/ui';
import { usePushSettings, useSetPushSettings } from './prefs';

export function NotificationPrefs() {
  const settings = usePushSettings();
  const save = useSetPushSettings();
  const [error, setError] = useState<string | null>(null);

  if (settings.isLoading) return <Spinner />;
  // Nothing to offer — an older server, or a failed load. Say nothing rather than taking the
  // rest of the Settings page down with an empty card.
  const categories = settings.data?.categories ?? [];
  if (categories.length === 0) return null;

  // Optimistic only while the save is in flight: if it fails, the switch has to go back to
  // what the server actually holds rather than sitting on a setting nobody stored.
  const muted = new Set(
    save.isPending && save.variables ? save.variables : (settings.data?.muted ?? []),
  );

  // Saved on the flip rather than behind a Save button: it is one boolean, and PushCard
  // above it already switches on the press.
  function set(key: string, on: boolean) {
    const next = new Set(muted);
    if (on) next.delete(key);
    else next.add(key);
    setError(null);
    save.mutate([...next], { onError: (e) => setError((e as Error).message) });
  }

  return (
    <Card>
      <h2 className="font-semibold">What to send me</h2>
      <p className="mt-1 text-sm text-slate-400">
        This is per person, not per device — turning one off silences it everywhere you are signed
        in.
      </p>
      <div className="mt-2 flex flex-col divide-y divide-slate-800">
        {categories.map((c) => (
          <Toggle
            key={c.key}
            label={c.label}
            checked={!muted.has(c.key)}
            disabled={save.isPending}
            onChange={(on) => set(c.key, on)}
          />
        ))}
      </div>
      {error && <p className="mt-2 text-sm text-rose-400">{error}</p>}
    </Card>
  );
}
