import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import type { Chore } from '../api/types';
import { Capture } from './Capture';

const chore = {
  photo_prompts: [],
  photo_count: 1,
  allow_gallery_upload: false,
} as unknown as Chore;
const noop = async () => {};

function setSecure(value: boolean) {
  Object.defineProperty(window, 'isSecureContext', { value, configurable: true });
}
function setMediaDevices(md: unknown) {
  Object.defineProperty(navigator, 'mediaDevices', { value: md, configurable: true });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  setSecure(false);
  setMediaDevices(undefined);
});

describe('Capture', () => {
  it('explains the https requirement on an insecure / unsupported origin', () => {
    setSecure(false);
    setMediaDevices(undefined);
    render(<Capture chore={chore} promptToken={null} onSubmit={noop} busy={false} />);

    expect(screen.getByText(/secure https address/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Take photo')).not.toBeInTheDocument();
  });

  it('shows a live viewfinder when a camera stream is available', async () => {
    setSecure(true);
    const stream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    setMediaDevices({ getUserMedia });
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);

    render(<Capture chore={chore} promptToken={null} onSubmit={noop} busy={false} />);

    await waitFor(() => expect(screen.getByLabelText('Take photo')).toBeEnabled());
    expect(getUserMedia).toHaveBeenCalled();
  });
});
