import type { Occurrence } from '../api/types';

/** Keep the first occurrence per key — apply to a due-sorted list, so that's the next one.
 *  The kid's screen keys on the chore alone; a parent sees every kid, so it keys on both. */
export function firstPerKey(keyOf: (o: Occurrence) => string) {
  const seen = new Set<string>();
  return (o: Occurrence) => {
    const k = keyOf(o);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  };
}
