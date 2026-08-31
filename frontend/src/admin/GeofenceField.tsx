import { lazy, Suspense, useState } from 'react';
import { Button, Spinner } from '../shared/ui';
import { DEFAULT_FENCE, haversineM, parseCoords, type Geofence } from '../shared/coords';

const FenceMap = lazy(() => import('./FenceMap'));

interface Props {
  value: Geofence | null;
  onChange: (fence: Geofence) => void;
}

export function GeofenceField({ value, onChange }: Props) {
  const fence = value ?? DEFAULT_FENCE;
  const [locating, setLocating] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [paste, setPaste] = useState('');

  function set(patch: Partial<Geofence>) {
    onChange({ ...fence, ...patch });
  }

  function useMyLocation() {
    if (!navigator.geolocation) {
      // Geolocation needs a secure context, same as the kid's camera — over plain LAN
      // http it simply isn't there.
      return setNote('This browser won’t share a location here. Type or paste one below.');
    }
    setLocating(true);
    setNote(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        set({ lat: +pos.coords.latitude.toFixed(6), lon: +pos.coords.longitude.toFixed(6) });
        setNote(`Placed where you are now, ±${Math.round(pos.coords.accuracy)} m.`);
      },
      () => {
        setLocating(false);
        setNote('Couldn’t get your location. Allow location for this site, or paste one below.');
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  }

  function applyPaste(text: string) {
    setPaste(text);
    const found = parseCoords(text);
    if (found) {
      set(found);
      setNote(null);
      setPaste('');
    } else if (text.trim()) {
      setNote('Couldn’t find coordinates in that. Paste a map link or “37.7749, -122.4194”.');
    }
  }

  function testFromHere() {
    if (!navigator.geolocation) return setNote('This browser won’t share a location here.');
    setNote('Checking where you are…');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const here = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        const d = haversineM(here, fence);
        // The same rule the backend applies (app/services/geo.py).
        const passes = d - pos.coords.accuracy <= fence.radius_m;
        setNote(
          `You are ${Math.round(d)} m from the middle, ±${Math.round(pos.coords.accuracy)} m — ` +
            (passes ? 'a check-in here would pass.' : 'a check-in here would need review.'),
        );
      },
      () => setNote('Couldn’t get your location.'),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-800 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-slate-300">Where is it?</span>
        <Button
          className="min-h-0 px-3 py-1 text-xs"
          variant="ghost"
          disabled={locating}
          onClick={useMyLocation}
        >
          {locating ? 'Finding you…' : 'Use my current location'}
        </Button>
      </div>

      <Suspense fallback={<Spinner label="Loading map…" />}>
        <FenceMap
          lat={fence.lat}
          lon={fence.lon}
          radiusM={fence.radius_m}
          onMove={(lat, lon) => set({ lat: +lat.toFixed(6), lon: +lon.toFixed(6) })}
        />
      </Suspense>
      <p className="text-xs text-slate-500">
        Tap the map or drag the pin. Map tiles come from openstreetmap.org — the only thing this app
        fetches from outside your network.
      </p>

      <input
        className="inp"
        placeholder="…or paste a map link / “37.7749, -122.4194”"
        value={paste}
        onChange={(e) => applyPaste(e.target.value)}
      />

      <div className="flex gap-2">
        <label className="flex flex-1 flex-col gap-1 text-xs text-slate-400">
          Latitude
          <input
            className="inp"
            type="number"
            step="0.000001"
            value={fence.lat}
            onChange={(e) => set({ lat: parseFloat(e.target.value || '0') })}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-xs text-slate-400">
          Longitude
          <input
            className="inp"
            type="number"
            step="0.000001"
            value={fence.lon}
            onChange={(e) => set({ lon: parseFloat(e.target.value || '0') })}
          />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-xs text-slate-400">
        How close counts: {fence.radius_m} m
        <div className="flex items-center gap-2">
          <input
            className="flex-1"
            type="range"
            min="25"
            max="1000"
            step="5"
            value={fence.radius_m}
            onChange={(e) => set({ radius_m: Number(e.target.value) })}
          />
          <input
            className="inp w-24"
            type="number"
            min="1"
            max="5000"
            value={fence.radius_m}
            onChange={(e) => set({ radius_m: Number(e.target.value || 0) })}
          />
        </div>
      </label>
      <p className="text-xs text-slate-500">
        A phone is often 20–50 m out, and more indoors — a check-in counts when the distance minus
        that error is inside the circle, so be generous. 100–150 m suits a school building.
      </p>

      <div>
        <Button className="min-h-0 px-3 py-1 text-xs" variant="ghost" onClick={testFromHere}>
          Test from where I am now
        </Button>
      </div>
      {note && <p className="text-xs text-sky-300">{note}</p>}
    </div>
  );
}
