import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Chore } from '../api/types';
import { Capture } from './Capture';

vi.mock('../pwa/downscale', () => ({
  toDownscaledJpeg: vi.fn().mockResolvedValue(new Blob(['jpeg'], { type: 'image/jpeg' })),
  prepareGalleryUpload: vi.fn().mockResolvedValue(new Blob(['jpeg'])),
}));
import { toDownscaledJpeg } from '../pwa/downscale';

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
  vi.unstubAllGlobals();
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

  it('captures the frame via ImageCapture (drawImage(<video>) is black on some Android)', async () => {
    const track = { stop: vi.fn() };
    const stream = {
      getTracks: () => [track],
      getVideoTracks: () => [track],
    } as unknown as MediaStream;
    setMediaDevices({ getUserMedia: vi.fn().mockResolvedValue(stream) });
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    vi.stubGlobal('URL', { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} });
    const grabFrame = vi.fn().mockResolvedValue({ width: 640, height: 480, close: vi.fn() });
    vi.stubGlobal(
      'ImageCapture',
      class {
        grabFrame = grabFrame;
      },
    );

    render(<Capture chore={chore} promptToken={null} onSubmit={noop} busy={false} />);
    fireEvent.click(await screen.findByLabelText('Take photo'));

    await waitFor(() => expect(grabFrame).toHaveBeenCalled());
    expect(toDownscaledJpeg).toHaveBeenCalledWith(expect.objectContaining({ width: 640 }));
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
