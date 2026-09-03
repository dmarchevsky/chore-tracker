import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ThemeToggle } from './ThemeToggle';
import { THEME_KEY } from './theme';

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('ThemeToggle', () => {
  it('starts on the device setting', () => {
    render(<ThemeToggle />);
    expect(screen.getByRole('radio', { name: 'Match my device' })).toBeChecked();
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('switches the palette and remembers the choice on this device', () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole('radio', { name: 'Night' }));

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem(THEME_KEY)).toBe('dark');
    expect(screen.getByRole('radio', { name: 'Night' })).toBeChecked();
  });

  it('picks a stored choice back up on the next visit', () => {
    localStorage.setItem(THEME_KEY, 'light');
    render(<ThemeToggle />);

    expect(screen.getByRole('radio', { name: 'Day' })).toBeChecked();
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});
