import { describe, expect, it } from 'vitest';
import { formatCadence, formatClock, onceDate, opensAt } from './schedule';

describe('formatCadence', () => {
  it.each([
    ['daily', 'Every day'],
    ['weekdays', 'Every weekday'],
    ['weekends', 'Every weekend'],
    ['weekly(on=[SAT])', 'Every Sat'],
    ['weekly(on=[MON,WED,FRI])', 'Every Mon, Wed and Fri'],
    ['monthly(day=1)', 'The 1st of each month'],
    ['monthly(day=2)', 'The 2nd of each month'],
    ['monthly(day=3)', 'The 3rd of each month'],
    ['monthly(day=11)', 'The 11th of each month'],
    ['monthly(day=15)', 'The 15th of each month'],
    ['monthly(day=21)', 'The 21st of each month'],
  ])('renders %s', (cadence, expected) => {
    expect(formatCadence(cadence)).toBe(expected);
  });

  it('warns that a late monthly day gets clamped, as the backend parser does', () => {
    expect(formatCadence('monthly(day=31)')).toBe(
      'The 31st of each month (or the last day, in a short month)',
    );
  });

  it('is case- and whitespace-insensitive, like the backend parser', () => {
    expect(formatCadence(' WEEKLY(on=[Mon, Wed]) ')).toBe('Every Mon and Wed');
  });

  it('renders a one-off as its local date', () => {
    expect(formatCadence('once(2026-09-14)')).toBe(
      `Just once, on ${new Date('2026-09-14T00:00').toLocaleDateString()}`,
    );
  });

  it('hands back anything it cannot parse rather than throwing', () => {
    // `custom_rule` is a valid column value the backend parser does not implement, and a
    // half-typed cadence reaches the form's preview on every keystroke.
    expect(formatCadence('custom_rule')).toBe('custom_rule');
    expect(formatCadence('weekly(on=[XYZ])')).toBe('weekly(on=[XYZ])');
    expect(formatCadence('monthly(day=0)')).toBe('monthly(day=0)');
  });
});

describe('onceDate', () => {
  it('pulls the date out of a one-off', () => {
    expect(onceDate('once(2026-09-14)')).toBe('2026-09-14');
  });

  it('is null for a recurring cadence', () => {
    expect(onceDate('daily')).toBeNull();
  });
});

describe('formatClock', () => {
  it('reads a stored wall clock without a timezone shift', () => {
    expect(formatClock('08:00:00')).toBe(
      new Date(2000, 0, 3, 8, 0).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
    );
  });

  it('hands back a value it cannot parse', () => {
    expect(formatClock('')).toBe('');
  });
});

describe('opensAt', () => {
  it('names the day the window opens on', () => {
    expect(opensAt('08:00:00', -2 * 3600)).toMatch(/the same day$/);
    expect(opensAt('08:00:00', -12 * 3600)).toMatch(/the day before$/);
    expect(opensAt('08:00:00', -3 * 24 * 3600)).toMatch(/3 days before$/);
  });
});
