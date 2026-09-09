// Date-range filter helpers, shared by the History and Money filter bars so the two can't
// disagree about what "last 30 days" means.

/** `n` days ago as `YYYY-MM-DD` — the shape an `<input type="date">` wants. */
export function daysAgo(n: number): string {
  return new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);
}

/** Start of that local day as an ISO instant, for a `from` bound. */
export function startOfDay(yyyyMmDd: string): string | undefined {
  if (!yyyyMmDd) return undefined;
  const d = new Date(yyyyMmDd);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

/** End of that local day as an ISO instant, for a `to` bound.
 *
 * The API filters `created_at <= to`, and a bare `YYYY-MM-DD` parses to midnight — so
 * passing the raw input value silently drops everything that happened on the day the parent
 * asked for. Push it to the last millisecond instead.
 */
export function endOfDay(yyyyMmDd: string): string | undefined {
  if (!yyyyMmDd) return undefined;
  const d = new Date(yyyyMmDd);
  if (Number.isNaN(d.getTime())) return undefined;
  d.setTime(d.getTime() + 86_400_000 - 1);
  return d.toISOString();
}

/** How far back a statement reaches. Days, or `null` for all time. */
export type RangeDays = number | null;

export const DEFAULT_RANGE_DAYS = 30;

export interface Range {
  /** ISO instant, or undefined for "no bound on this end". */
  from?: string;
  to?: string;
}

/** The `?from&to` a preset or a hand-picked pair of dates comes to. Hand-picked wins: a
 *  window and a preset answer the same question, and only one can be in force. */
export function toRange(days: RangeDays, from: string, to: string): Range {
  if (from || to) return { from: startOfDay(from), to: endOfDay(to) };
  return days === null ? {} : { from: startOfDay(daysAgo(days)) };
}
