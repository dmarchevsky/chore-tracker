/** A geofence centre, as the chore stores it. */
export interface LatLon {
  lat: number;
  lon: number;
}

export interface Geofence extends LatLon {
  radius_m: number;
  arrive_before?: string | null;
}

/** Somewhere to start before the parent places the pin; the first move replaces it. */
export const DEFAULT_FENCE: Geofence = { lat: 37.7749, lon: -122.4194, radius_m: 120 };

const PATTERNS = [
  /@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/, // google maps /@37.77,-122.41,17z
  /[?&]q=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/, // ?q=37.77,-122.41 (maps, apple)
  /[?&]ll=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/, // apple maps ?ll=
  /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/, // google place URLs
  /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/, // a plain "37.77, -122.41"
];

/**
 * Pull a coordinate pair out of whatever a parent pasted — a map link or the bare
 * numbers. Local string work only: geocoding an address would mean shipping the
 * household's address to a third-party service.
 */
export function parseCoords(text: string): LatLon | null {
  for (const re of PATTERNS) {
    const m = re.exec(text);
    if (!m) continue;
    const lat = Number(m[1]);
    const lon = Number(m[2]);
    if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180) return { lat, lon };
  }
  return null;
}

/** Mirrors backend/app/services/geo.py — keep the two in step. */
export function haversineM(a: LatLon, b: LatLon): number {
  const R = 6_371_008.8;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
