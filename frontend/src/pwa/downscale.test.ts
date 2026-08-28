import { describe, expect, it } from 'vitest';
import { fittedSize, MAX_LONG_EDGE } from './downscale';

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
