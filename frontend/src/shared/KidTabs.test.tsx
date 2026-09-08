import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { KidTabs } from './KidTabs';
import type { Child } from '../api/types';

const KIDS = [
  { id: 'k1', username: 'mo', display_name: 'Mo', email: null, role: 'child', is_active: true },
  { id: 'k2', username: 'lu', display_name: 'Lu', email: null, role: 'child', is_active: true },
] as Child[];

afterEach(cleanup);

describe('KidTabs', () => {
  it('renders one pill per kid and marks the selected one', () => {
    render(<KidTabs kids={KIDS} value="k2" onChange={vi.fn()} />);

    const pills = screen.getAllByRole('button');
    expect(pills.map((b) => b.textContent)).toEqual(['Mo', 'Lu']);
    expect(screen.getByRole('button', { name: 'Mo' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Lu' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('reports the picked kid id', () => {
    const onChange = vi.fn();
    render(<KidTabs kids={KIDS} value="k1" onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: 'Lu' }));
    expect(onChange).toHaveBeenCalledWith('k2');
  });

  it('adds an Everyone pill bound to the empty string when allowAll', () => {
    const onChange = vi.fn();
    render(<KidTabs kids={KIDS} value="" onChange={onChange} allowAll />);

    const everyone = screen.getByRole('button', { name: 'Everyone' });
    expect(everyone).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: 'Mo' }));
    expect(onChange).toHaveBeenLastCalledWith('k1');

    fireEvent.click(everyone);
    expect(onChange).toHaveBeenLastCalledWith('');
  });
});
