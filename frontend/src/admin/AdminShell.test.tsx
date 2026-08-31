import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AdminShell } from './AdminShell';

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ me: { display_name: 'Parent' }, logout: vi.fn() }),
}));

function renderShell() {
  render(
    <MemoryRouter initialEntries={['/admin']}>
      <Routes>
        <Route path="/admin" element={<AdminShell />}>
          <Route index element={<p>inbox page</p>} />
          <Route path="money" element={<p>money page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  return document.getElementById('admin-nav')!;
}

const isOpen = (nav: HTMLElement) => !nav.className.includes('-translate-x-full');

afterEach(cleanup);

describe('AdminShell', () => {
  it('keeps the tabs in a side menu that starts closed on a phone', () => {
    const nav = renderShell();

    // The links used to sit in a single non-wrapping header row, twice the width
    // of a 360px screen.
    expect(screen.getByRole('link', { name: 'Inbox' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument();
    expect(isOpen(nav)).toBe(false);
    expect(screen.getByLabelText('Menu')).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens on the hamburger and closes again on navigation', () => {
    const nav = renderShell();

    fireEvent.click(screen.getByLabelText('Menu'));
    expect(isOpen(nav)).toBe(true);
    expect(screen.getByLabelText('Menu')).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(screen.getByRole('link', { name: 'Money' }));
    expect(screen.getByText('money page')).toBeInTheDocument();
    expect(isOpen(nav)).toBe(false);
  });

  it('closes on the backdrop and on Escape', () => {
    const nav = renderShell();

    fireEvent.click(screen.getByLabelText('Menu'));
    fireEvent.click(screen.getByLabelText('Close menu'));
    expect(isOpen(nav)).toBe(false);

    fireEvent.click(screen.getByLabelText('Menu'));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(isOpen(nav)).toBe(false);
  });

  it('releases the body scroll lock when it closes', () => {
    renderShell();

    fireEvent.click(screen.getByLabelText('Menu'));
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(document.body.style.overflow).not.toBe('hidden');
  });
});
