import type { LedgerEntry } from '../api/types';
import { isManualPenalty } from '../shared/status';

/** Penalties a parent charged by hand (spec §4.8), newest first.
 *
 * A charge for a missed chore already has a row of its own — the occurrence it hangs off —
 * so only the hand-applied ones need showing here, or the kid reads the same miss twice.
 * A penalty that has been undone is no longer charged, so it drops out entirely; the
 * statement on the Money tab is where the full append-only history stays visible (spec §9).
 */
export function chargedPenalties(
  entries: LedgerEntry[] | undefined,
  { since, until }: { since?: Date; until?: Date } = {},
): LedgerEntry[] {
  return (entries ?? [])
    .filter((e) => isManualPenalty(e) && !e.reversed_by_entry_id)
    .filter((e) => {
      const at = +new Date(e.created_at);
      return (!since || at >= +since) && (!until || at < +until);
    })
    .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
}
