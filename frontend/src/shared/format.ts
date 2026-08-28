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
