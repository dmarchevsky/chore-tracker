// Turning a chore's schedule columns into something a person reads. The kid's rules screen
// and the parent's chore form both need this, so it lives here rather than in either one.
//
// The grammar mirrored below is the backend parser's (app/services/cadence.py); anything it
// doesn't recognise is handed back untouched rather than thrown over, because `custom_rule`
// is accepted by the column and unimplemented by the parser.

const WEEKLY_RE = /^weekly\(on=\[([a-z,]+)\]\)$/;
const MONTHLY_RE = /^monthly\(day=(\d{1,2})\)$/;
const ONCE_RE = /^once\((\d{4}-\d{2}-\d{2})\)$/;

const DAY_NAMES: Record<string, string> = {
  mon: 'Mon',
  tue: 'Tue',
  wed: 'Wed',
  thu: 'Thu',
  fri: 'Fri',
  sat: 'Sat',
  sun: 'Sun',
};

const normalise = (cadence: string) => cadence.trim().toLowerCase().replace(/\s+/g, '');

/** A one-off carries its date inside the cadence: once(YYYY-MM-DD). Null for a recurring one. */
export function onceDate(cadence: string): string | null {
  return ONCE_RE.exec(normalise(cadence))?.[1] ?? null;
}

/** An ordinal a kid reads without stumbling: 1st, 2nd, 3rd, 15th, 21st. */
function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${['th', 'st', 'nd', 'rd'][n % 10] ?? 'th'}`;
}

/** "Mon, Wed and Fri" — an Oxford-comma-free list, which is how you'd say it out loud. */
function joinDays(days: string[]): string {
  if (days.length === 1) return days[0];
  return `${days.slice(0, -1).join(', ')} and ${days[days.length - 1]}`;
}

/** The cadence string in plain English. Unknown input comes back verbatim. */
export function formatCadence(cadence: string): string {
  const c = normalise(cadence);
  if (c === 'daily') return 'Every day';
  if (c === 'weekdays') return 'Every weekday';
  if (c === 'weekends') return 'Every weekend';

  const weekly = WEEKLY_RE.exec(c);
  if (weekly) {
    const days = weekly[1]
      .split(',')
      .filter(Boolean)
      .map((d) => DAY_NAMES[d]);
    if (days.every(Boolean) && days.length) return `Every ${joinDays(days)}`;
  }

  const monthly = MONTHLY_RE.exec(c);
  if (monthly) {
    const day = Number(monthly[1]);
    // The backend clamps a day past the end of a short month rather than skipping it.
    if (day >= 29) return `The ${ordinal(day)} of each month (or the last day, in a short month)`;
    if (day >= 1) return `The ${ordinal(day)} of each month`;
  }

  const once = onceDate(c);
  // Parsed as local midnight so the date doesn't slip a day west of UTC.
  if (once) return `Just once, on ${new Date(`${once}T00:00`).toLocaleDateString()}`;

  return cadence;
}

/** A stored HH:MM:SS wall clock as the device would write it. No Date, so no timezone shift. */
export function formatClock(dueTime: string): string {
  const [h, m] = dueTime.split(':').map(Number);
  if (!Number.isFinite(h) || !Number.isFinite(m)) return dueTime;
  return new Date(2000, 0, 3, h, m).toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** What the window offset means on the clock, which is what anyone actually pictures. */
export function opensAt(dueTime: string, offsetSecs: number): string {
  const [h, m] = dueTime.split(':').map(Number);
  const due = new Date(2000, 0, 3, h || 0, m || 0); // an arbitrary date; only the clock matters
  const open = new Date(due.getTime() + offsetSecs * 1000);
  const clock = open.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const midnight = (d: Date) => new Date(d).setHours(0, 0, 0, 0);
  const days = Math.round((midnight(due) - midnight(open)) / 86_400_000);
  if (days === 0) return `opens ${clock}, the same day`;
  if (days === 1) return `opens ${clock} the day before`;
  return `opens ${clock}, ${days} days before`;
}
