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

/** Largest gallery pick we forward untouched; the API caps an upload at 12MB. */
export const MAX_PASSTHROUGH_BYTES = 6 * 1024 * 1024;

/**
 * Prepare a gallery pick for upload, keeping its EXIF when we safely can.
 *
 * The metadata anti-cheat checks only run on gallery uploads, and they need real EXIF to
 * say anything — but `createImageBitmap` + canvas strips it. So a JPEG small enough to
 * send as-is goes through untouched; the server downscales and strips on ingest anyway.
 * Anything else (HEIC from an iPhone, PNG, an oversized original) is decoded here: the
 * backend's Pillow has no HEIF plugin, so the browser has to do that conversion.
 */
export async function prepareGalleryUpload(file: File): Promise<Blob> {
  if (file.type === 'image/jpeg' && file.size <= MAX_PASSTHROUGH_BYTES) return file;
  return await fileToDownscaledJpeg(file);
}
