import { useState } from 'react';
import { Button, Card } from '../shared/ui';

interface Props {
  onSubmit: (geo: { lat: number; lon: number; accuracy: number }) => Promise<void>;
  busy: boolean;
}

// Active check-in, not tracking (spec §6.2). The Geolocation API only fires while the
// page is open — that's fine, the kid taps this when they arrive.
export function LocationCheckin({ onSubmit, busy }: Props) {
  const [state, setState] = useState<'idle' | 'locating' | 'error'>('idle');
  const [acc, setAcc] = useState<number | null>(null);

  function checkIn() {
    if (!navigator.geolocation) return setState('error');
    setState('locating');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setAcc(Math.round(pos.coords.accuracy));
        setState('idle');
        void onSubmit({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
      },
      () => setState('error'),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  }

  return (
    <Card>
      <p className="font-semibold">Are you there?</p>
      <p className="mt-1 text-sm text-slate-400">
        Tap the button when you arrive and we’ll check your location.
      </p>
      {acc !== null && (
        <p className="mt-1 text-xs text-slate-500">
          Location accuracy: ±{acc} m{acc > 100 ? ' — a parent may need to confirm this' : ''}
        </p>
      )}
      {state === 'error' && (
        <p className="mt-1 text-sm text-rose-400">
          Couldn’t get your location. Turn on location for this site and try again.
        </p>
      )}
      <Button className="mt-3 w-full" disabled={busy || state === 'locating'} onClick={checkIn}>
        {state === 'locating' ? 'Finding you…' : busy ? 'Sending…' : "I'm here"}
      </Button>
    </Card>
  );
}
