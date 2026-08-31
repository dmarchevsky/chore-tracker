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
const close = () => {};

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
    render(
      <Capture chore={chore} promptToken={null} onSubmit={noop} onClose={close} busy={false} />,
    );

    expect(screen.getByText(/blocking the camera on http:\/\/localhost/i)).toBeInTheDocument();
    expect(screen.getByText(/unsafely-treat-insecure-origin-as-secure/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Take photo')).not.toBeInTheDocument();
  });

  it('shows a live viewfinder when a camera stream is available', async () => {
    const stream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    setMediaDevices({ getUserMedia });
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);

    render(
      <Capture chore={chore} promptToken={null} onSubmit={noop} onClose={close} busy={false} />,
    );

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

    render(
      <Capture chore={chore} promptToken={null} onSubmit={noop} onClose={close} busy={false} />,
    );
    fireEvent.click(await screen.findByLabelText('Take photo'));

    await waitFor(() => expect(grabFrame).toHaveBeenCalled());
    expect(toDownscaledJpeg).toHaveBeenCalledWith(expect.objectContaining({ width: 640 }));
  });

  it('surfaces the failure name when getUserMedia rejects', async () => {
    const getUserMedia = vi.fn().mockRejectedValue({ name: 'NotReadableError' });
    setMediaDevices({ getUserMedia });

    render(
      <Capture chore={chore} promptToken={null} onSubmit={noop} onClose={close} busy={false} />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/Couldn't start the camera \(NotReadableError\)/i),
      ).toBeInTheDocument(),
    );
  });

  it('keeps the shutter and Send in one footer, with the note out of the way', async () => {
    const stream = {
      getTracks: () => [{ stop: vi.fn() }],
      getVideoTracks: () => [{ stop: vi.fn() }],
    } as unknown as MediaStream;
    setMediaDevices({ getUserMedia: vi.fn().mockResolvedValue(stream) });
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    vi.stubGlobal('URL', { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} });
    vi.stubGlobal(
      'ImageCapture',
      class {
        grabFrame = vi.fn().mockResolvedValue({ width: 640, height: 480, close: vi.fn() });
      },
    );
    // afterEach's restoreAllMocks resets the module mock's implementation.
    vi.mocked(toDownscaledJpeg).mockResolvedValue(new Blob(['jpeg'], { type: 'image/jpeg' }));
    const onSubmit = vi.fn().mockResolvedValue(undefined);

    render(
      <Capture chore={chore} promptToken={null} onSubmit={onSubmit} onClose={close} busy={false} />,
    );

    // The note used to be a permanent textarea between the shutter and Submit.
    expect(screen.queryByPlaceholderText(/add a note/i)).not.toBeInTheDocument();
    // Nothing to send until a slot is filled, so the shutter is alone at first.
    expect(screen.queryByRole('button', { name: /send/i })).not.toBeInTheDocument();

    const shutter = await screen.findByLabelText('Take photo');
    fireEvent.click(shutter);

    const send = await screen.findByRole('button', { name: 'Send' });
    // Both are in the footer — a kid never scrolls from one to the other.
    expect(send.closest('footer')).toBe(shutter.closest('footer'));

    fireEvent.click(send);
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toHaveLength(1);
    expect(onSubmit.mock.calls[0][2]).toBe('camera');
  });

  it('is a fixed full-height sheet that cannot scroll, and closes on ✕', async () => {
    const onClose = vi.fn();
    setMediaDevices({ getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) });
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);

    const { container } = render(
      <Capture chore={chore} promptToken="47" onSubmit={noop} onClose={onClose} busy={false} />,
    );

    // 100dvh, not 100vh: `vh` counts the retracted mobile URL bar.
    expect(container.firstElementChild?.className).toContain('h-[100dvh]');
    expect(container.firstElementChild?.className).toContain('fixed inset-0');
    expect(container.firstElementChild?.className).toContain('overflow-hidden');
    expect(document.body.style.overflow).toBe('hidden');

    expect(screen.getByText('47')).toBeInTheDocument(); // token pill, not a banner
    fireEvent.click(screen.getByLabelText('Close camera'));
    expect(onClose).toHaveBeenCalled();
  });
});
