// Turning the append-only ledger into a statement a parent can read (spec §9).
//
// One decision can write three rows. Approving a chore the model failed reverses the
// penalty *and* pays the earning, so the occurrence carries `-$5, +$5, +$5` — and since a
// reversal's reason is the parent's own decision text ("approved: Ok"), the two credits are
// indistinguishable line by line. It reads like being paid twice for one chore.
//
// The ledger is right and must stay verbatim, so the fix is in the reading: fold every row
// that belongs to one occurrence into a single group, show the net, and keep the individual
// rows underneath for anyone who wants the audit trail.

import type { LedgerEntry } from '../api/types';
import { isManualPenalty } from './status';

export type StatementOutcome = 'earned' | 'missed' | 'excused' | 'payout' | 'penalty' | 'adjusted';

export interface StatementGroup {
  /** Stable React key: the occurrence, or the entry itself when there is no occurrence. */
  key: string;
  occurrence_id: string | null;
  chore_title: string | null;
  occurrence_due_at: string | null;
  /** Every row, each original immediately followed by the reversal that undid it. */
  entries: LedgerEntry[];
  net_cents: number;
  /** Newest `created_at` in the group — what the statement sorts on. */
  at: string;
  outcome: StatementOutcome;
  /** The unreversed penalty this group offers to excuse or undo, if any. */
  live_penalty: LedgerEntry | null;
}

// Truthiness, not `=== null`: an absent field must read as "still standing", never as
// reversed — mistaking a live charge for a cancelled one hides money that was taken.
const live = (e: LedgerEntry) => !e.reversed_by_entry_id;

/** Original, then its reversal, then the next original.
 *
 * Not sortable by time: a reversal and the earning that replaces it are written in one
 * transaction and share a timestamp, so `created_at` leaves them in an arbitrary order and
 * the reversal can float above the charge it undoes.
 */
function threadReversals(entries: LedgerEntry[]): LedgerEntry[] {
  const byOriginal = new Map<string, LedgerEntry[]>();
  for (const e of entries) {
    if (!e.reverses_entry_id) continue;
    const list = byOriginal.get(e.reverses_entry_id) ?? [];
    list.push(e);
    byOriginal.set(e.reverses_entry_id, list);
  }
  const out: LedgerEntry[] = [];
  for (const e of entries) {
    if (e.reverses_entry_id && entries.some((o) => o.id === e.reverses_entry_id)) continue;
    out.push(e, ...(byOriginal.get(e.id) ?? []));
  }
  return out;
}

/** What happened to this chore, read off the money rather than off any reason text.
 *
 * Deliberately not string-matching the reason: those are free text a parent typed, prefixed
 * by the decision (`review.py`). The money is unambiguous — excuse is the only decision that
 * reverses without posting anything new, so "every charge and reward undone, nothing put
 * back" can only be an excused occurrence.
 */
function outcomeOf(entries: LedgerEntry[], net: number): StatementOutcome {
  if (entries.some((e) => e.kind === 'payout')) return 'payout';
  if (entries.some(isManualPenalty)) return 'penalty';

  const earned = entries.some((e) => live(e) && e.kind === 'earning');
  const charged = entries.some((e) => live(e) && e.kind === 'penalty');
  if (earned && !charged) return 'earned';
  if (charged && !earned) return 'missed';

  // Every charge and reward on this chore has been undone. Not conditioned on the net
  // being zero: a date filter can put the charge inside the window and the reversal that
  // cancelled it outside, and the group is still an excused chore either way.
  const decided = entries.filter((e) => e.kind === 'earning' || e.kind === 'penalty');
  if (decided.length > 0 && decided.every((e) => !live(e))) return 'excused';
  // The mirror of that: the window caught the reversal but not what it reversed.
  if (decided.length === 0 && entries.every((e) => e.reverses_entry_id)) return 'excused';

  // A re-graded tier posts its new amount as an adjustment (spec §9), so the sign of the
  // net is all there is to go on.
  if (net > 0) return 'earned';
  if (net < 0) return 'missed';
  return 'adjusted';
}

/** The line under the title: what the parent or the model actually said.
 *
 * The newest entry that still stands, so a re-decided chore quotes the decision in force
 * rather than the one it replaced. Falls back to the newest row when everything was undone
 * — on an excused chore the reversal's own reason ("excused: we were away") is the answer.
 */
export function groupNote(g: StatementGroup): string {
  const standing = [...g.entries].reverse();
  return (
    standing.find((e) => live(e) && e.reason)?.reason ??
    standing.find((e) => e.reason)?.reason ??
    ''
  );
}

/**
 * Fold a statement into one group per chore-occurrence, newest first.
 *
 * Entries with no occurrence — payouts, hand-applied penalty rules (spec §4.8), hand-entered
 * adjustments — are each their own group: there is nothing for them to fold into, and a
 * payout is already one line that means one thing.
 */
export function groupStatement(entries: LedgerEntry[]): StatementGroup[] {
  const byOccurrence = new Map<string, LedgerEntry[]>();
  const order: string[] = [];

  for (const e of entries) {
    const key = e.occurrence_id ?? `entry:${e.id}`;
    if (!byOccurrence.has(key)) {
      byOccurrence.set(key, []);
      order.push(key);
    }
    byOccurrence.get(key)!.push(e);
  }

  const groups = order.map((key) => {
    const raw = byOccurrence.get(key)!;
    const threaded = threadReversals(raw);
    const net = raw.reduce((sum, e) => sum + e.amount_cents, 0);
    const named = raw.find((e) => e.chore_title) ?? raw[0];
    return {
      key,
      occurrence_id: raw[0].occurrence_id,
      chore_title: named.chore_title,
      occurrence_due_at: named.occurrence_due_at,
      entries: threaded,
      net_cents: net,
      at: raw.reduce(
        (newest, e) => (e.created_at > newest ? e.created_at : newest),
        raw[0].created_at,
      ),
      outcome: outcomeOf(raw, net),
      live_penalty: raw.find((e) => e.kind === 'penalty' && live(e)) ?? null,
    } satisfies StatementGroup;
  });

  // Newest first: the parent is looking for what just happened, not for the oldest chore
  // they ever paid for. The API returns oldest-first (and CSV keeps that).
  return groups.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
}

/** What the parent takes home over the range on screen, as distinct from the all-time
 *  balance beside it — those are two different questions and two different numbers. */
export const netOfRange = (entries: LedgerEntry[]): number =>
  entries.reduce((sum, e) => sum + e.amount_cents, 0);
