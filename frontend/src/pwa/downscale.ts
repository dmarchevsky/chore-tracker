// Client-side downscale before upload — a 6MB photo over home DSL upstream is a bad
// experience, and most VLMs downsample anyway (spec §7.1, §11).

export const MAX_LONG_EDGE = 1568;
export const JPEG_QUALITY = 0.82;

export function fittedSize(w: number, h: number, max = MAX_LONG_EDGE) {
  const long = Math.max(w, h);
  if (long <= max) return { w, h };
  const s = max / long;
  return { w: Math.round(w * s), h: Math.round(h * s) };
}

/** Draw a source bitmap/canvas/video frame onto a downscaled JPEG blob. */
export async function toDownscaledJpeg(
  source: CanvasImageSource & { width: number; height: number },
): Promise<Blob> {
  const { w, h } = fittedSize(source.width, source.height);
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('2d canvas unavailable');
  ctx.drawImage(source, 0, 0, w, h);
  return await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error('toBlob failed'))),
      'image/jpeg',
      JPEG_QUALITY,
    ),
  );
}

export async function fileToDownscaledJpeg(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  try {
    return await toDownscaledJpeg(bitmap);
  } finally {
    bitmap.close();
  }
}
