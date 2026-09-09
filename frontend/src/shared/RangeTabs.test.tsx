import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { RangeTabs } from './RangeTabs';
import { toRange } from './dates';

afterEach(cleanup);

describe('RangeTabs', () => {
  it('marks the preset in force, and reports the one pressed', () => {
    const onChange = vi.fn();
    render(<RangeTabs days={30} from="" to="" onChange={onChange} />);

    expect(screen.getByRole('button', { name: '30 days' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    expect(onChange).toHaveBeenCalledWith({ days: null, from: '', to: '' });
  });

  it('lets a typed date take over from the presets', () => {
    // A hand-picked window and a preset answer the same question; showing both as in force
    // would leave the parent unable to tell what they are looking at.
    render(<RangeTabs days={30} from="2026-09-01" to="" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: '30 days' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });
});

describe('toRange', () => {
  it('turns All into no bounds at all', () => {
    expect(toRange(null, '', '')).toEqual({});
  });

  it('bounds a preset at the bottom only, so today is always included', () => {
    const r = toRange(30, '', '');
    expect(r.from).toBeDefined();
    expect(r.to).toBeUndefined();
  });

  it('prefers typed dates over the preset', () => {
    const r = toRange(30, '2026-09-01', '2026-09-05');
    expect(r.from?.startsWith('2026-09-01')).toBe(true);
    // The `to` bound stretches to the end of the day, or `created_at <= to` would drop it.
    expect(new Date(r.to as string).getTime()).toBeGreaterThan(
      new Date('2026-09-05T00:00:00Z').getTime(),
    );
  });
});
