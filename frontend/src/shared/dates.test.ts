import { describe, expect, it } from 'vitest';
import { daysAgo, endOfDay, startOfDay } from './dates';

describe('date range helpers', () => {
  it('renders a day offset in the shape a date input wants', () => {
    expect(daysAgo(30)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(new Date(daysAgo(0)).getTime()).toBeGreaterThan(new Date(daysAgo(30)).getTime());
  });

  it('stretches a `to` bound to the end of the day', () => {
    // `created_at <= to` against midnight would drop the whole day the parent asked for.
    const from = startOfDay('2026-09-09') as string;
    const to = endOfDay('2026-09-09') as string;
    expect(new Date(to).getTime() - new Date(from).getTime()).toBe(86_400_000 - 1);
  });

  it('treats an empty or unparseable value as no bound', () => {
    expect(startOfDay('')).toBeUndefined();
    expect(endOfDay('')).toBeUndefined();
    expect(endOfDay('not-a-date')).toBeUndefined();
  });
});
