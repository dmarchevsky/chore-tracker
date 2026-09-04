import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DetailSheet } from './DetailSheet';

/** jsdom has no matchMedia; every test says how wide the device is. */
function device(phone: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: phone, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('DetailSheet', () => {
  it('stays an ordinary pane from md up', () => {
    device(false);
    render(
      <DetailSheet open onClose={vi.fn()} label="Review">
        <p>the detail</p>
      </DetailSheet>,
    );

    expect(screen.getByText('the detail')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.body.style.overflow).toBe('');
  });

  it('covers the list on a phone, and freezes what is behind it', () => {
    device(true);
    const { unmount } = render(
      <DetailSheet open onClose={vi.fn()} label="Review">
        <p>the detail</p>
      </DetailSheet>,
    );

    const dialog = screen.getByRole('dialog', { name: 'Review' });
    expect(dialog).toContainElement(screen.getByText('the detail'));
    expect(document.body.style.overflow).toBe('hidden');

    unmount();
    expect(document.body.style.overflow).toBe('');
  });

  it('does not take over the screen while nothing is selected', () => {
    device(true);
    render(
      <DetailSheet open={false} onClose={vi.fn()} label="Review">
        <p>Select something to review.</p>
      </DetailSheet>,
    );

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByText('Select something to review.')).toBeInTheDocument();
  });

  it('closes on Back, on Escape, and on the back button', () => {
    device(true);
    const onClose = vi.fn();
    const sheet = (
      <DetailSheet open onClose={onClose} label="Review">
        <p>the detail</p>
      </DetailSheet>
    );

    const { unmount } = render(sheet);
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();

    render(sheet);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);
    cleanup();

    render(sheet);
    fireEvent.popState(window);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it('leaves the history stack as it found it', () => {
    device(true);
    const push = vi.spyOn(window.history, 'pushState');
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});

    const { unmount } = render(
      <DetailSheet open onClose={vi.fn()} label="Review">
        <p>the detail</p>
      </DetailSheet>,
    );
    expect(push).toHaveBeenCalledWith({ chorekeeperSheet: true }, '', window.location.href);

    // Closing without the back button has to pop the entry the sheet pushed.
    unmount();
    expect(back).toHaveBeenCalledTimes(1);
  });
});
