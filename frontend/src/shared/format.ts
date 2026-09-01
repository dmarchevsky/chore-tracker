export function money(cents: number): string {
  const sign = cents < 0 ? '-' : '';
  return `${sign}$${(Math.abs(cents) / 100).toFixed(2)}`;
}

export function dueLabel(iso: string, now = new Date()): string {
  const ms = new Date(iso).getTime() - now.getTime();
  const mins = Math.round(ms / 60000);
  if (mins < -60) return 'overdue';
  if (mins < 0) return `${-mins} min late`;
  if (mins < 60) return `due in ${mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `due in ${hrs} h`;
  return `due ${new Date(iso).toLocaleDateString()}`;
}

/** A tier's outcome as the parent wrote it: signed money, or the sentence. */
export function tierOutcome(t: { amount_cents: number | null; text: string | null }): string {
  if (t.text) return t.text;
  const cents = t.amount_cents ?? 0;
  return `${cents < 0 ? '-' : '+'}${money(Math.abs(cents))}`;
}
