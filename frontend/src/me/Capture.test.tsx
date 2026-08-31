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

function setMediaDevices(md: unknown) {
  Object.defineProperty(navigator, 'mediaDevices', { value: md, configurable: true });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  setMediaDevices(undefined);
});

describe('Capture', () => {
  it('explains how to unblock the camera when getUserMedia is missing', () => {
    setMediaDevices(undefined); // jsdom default — like plain http on a LAN IP
    render(<Capture chore={chore} promptToken={null} onSubmit={noop} busy={false} />);

    expect(screen.getByText(/blocking the camera on http:\/\/localhost/i)).toBeInTheDocument();
    expect(screen.getByText(/unsafely-treat-insecure-origin-as-secure/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Take photo')).not.toBeInTheDocument();
  });

  it('shows a live viewfinder when a camera stream is available', async () => {
    const stream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    setMediaDevices({ getUserMedia });
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);

    render(<Capture chore={chore} promptToken={null} onSubmit={noop} busy={false} />);

    await waitFor(() => expect(screen.getByLabelText('Take photo')).toBeEnabled());
    expect(getUserMedia).toHaveBeenCalled();
  });

  it('surfaces the failure name when getUserMedia rejects', async () => {
    const getUserMedia = vi.fn().mockRejectedValue({ name: 'NotReadableError' });
    setMediaDevices({ getUserMedia });

    render(<Capture chore={chore} promptToken={null} onSubmit={noop} busy={false} />);

    await waitFor(() =>
      expect(
        screen.getByText(/Couldn't start the camera \(NotReadableError\)/i),
      ).toBeInTheDocument(),
    );
  });
});
