import { describe, expect, it, vi } from 'vitest';
import {
  fittedSize,
  MAX_LONG_EDGE,
  MAX_PASSTHROUGH_BYTES,
  prepareGalleryUpload,
} from './downscale';

describe('fittedSize', () => {
  it('leaves small images untouched', () => {
    expect(fittedSize(800, 600)).toEqual({ w: 800, h: 600 });
  });

  it('scales the long edge down to 1568 and keeps the aspect ratio', () => {
    const { w, h } = fittedSize(4000, 3000);
    expect(Math.max(w, h)).toBe(MAX_LONG_EDGE);
    expect(w).toBe(MAX_LONG_EDGE);
    expect(h).toBe(Math.round((3000 * MAX_LONG_EDGE) / 4000));
  });

  it('handles portrait orientation', () => {
    const { w, h } = fittedSize(3024, 4032);
    expect(h).toBe(MAX_LONG_EDGE);
    expect(w).toBe(Math.round((3024 * MAX_LONG_EDGE) / 4032));
  });
});

describe('prepareGalleryUpload', () => {
  const file = (type: string, size: number) => new File([new Uint8Array(size)], 'pic', { type });

  it('forwards a modest JPEG untouched so its EXIF survives', async () => {
    const f = file('image/jpeg', 1024);
    expect(await prepareGalleryUpload(f)).toBe(f);
  });

  it('decodes anything the backend cannot read, or that is too big to forward', async () => {
    // The decode path needs a real 2d canvas, which jsdom does not provide — reaching
    // that error is the assertion that we did not take the passthrough branch.
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn().mockResolvedValue({ width: 4, height: 4, close() {} }),
    );

    await expect(prepareGalleryUpload(file('image/heic', 1024))).rejects.toThrow(/canvas/i);
    await expect(
      prepareGalleryUpload(file('image/jpeg', MAX_PASSTHROUGH_BYTES + 1)),
    ).rejects.toThrow(/canvas/i);

    vi.unstubAllGlobals();
  });
});
