// Lazy chunk: the only part of the app that talks to a third party. Tiles come from
// tile.openstreetmap.org, which learns which coordinates a parent is looking at — a
// deliberate, scoped exception to spec §1 goal 6, and the reason this is loaded only
// when a location chore's editor is open. Leaflet itself is bundled from npm, so
// script-src 'self' is untouched; only img-src opens, and only to the tile host.

import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

// Leaflet's default icon resolves paths relative to the CSS, which 404s under a
// bundler. Point it at the assets Vite emitted so the pin loads from our own origin.
L.Icon.Default.mergeOptions({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
});

interface Props {
  lat: number;
  lon: number;
  radiusM: number;
  onMove: (lat: number, lon: number) => void;
}

export default function FenceMap({ lat, lon, radiusM, onMove }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const pin = useRef<L.Marker | null>(null);
  const ring = useRef<L.Circle | null>(null);
  // Keep the newest callback without re-running the setup effect.
  const move = useRef(onMove);
  move.current = onMove;

  useEffect(() => {
    if (!host.current || map.current) return;
    const m = L.map(host.current).setView([lat, lon], 16);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      // Required by the OSM tile usage policy.
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(m);

    ring.current = L.circle([lat, lon], { radius: radiusM, color: '#0ea5e9' }).addTo(m);
    pin.current = L.marker([lat, lon], { draggable: true }).addTo(m);

    pin.current.on('dragend', () => {
      const p = pin.current!.getLatLng();
      move.current(p.lat, p.lng);
    });
    m.on('click', (e: L.LeafletMouseEvent) => move.current(e.latlng.lat, e.latlng.lng));

    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
    // Set up once; the effects below track prop changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    pin.current?.setLatLng([lat, lon]);
    ring.current?.setLatLng([lat, lon]);
    if (map.current && !map.current.getBounds().contains([lat, lon])) {
      map.current.setView([lat, lon]);
    }
  }, [lat, lon]);

  useEffect(() => {
    ring.current?.setRadius(radiusM);
  }, [radiusM]);

  return <div ref={host} className="h-64 w-full rounded-xl" />;
}
