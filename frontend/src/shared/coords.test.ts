import { describe, expect, it } from 'vitest';
import { haversineM, parseCoords } from './coords';

describe('parseCoords', () => {
  it('reads the shapes a parent actually pastes', () => {
    expect(parseCoords('https://www.google.com/maps/@37.7749,-122.4194,17z')).toEqual({
      lat: 37.7749,
      lon: -122.4194,
    });
    expect(parseCoords('https://maps.apple.com/?ll=37.7749,-122.4194&q=School')).toEqual({
      lat: 37.7749,
      lon: -122.4194,
    });
    expect(parseCoords('https://maps.google.com/?q=37.7749, -122.4194')).toEqual({
      lat: 37.7749,
      lon: -122.4194,
    });
    expect(parseCoords('https://www.google.com/maps/place/X/data=!3d37.7749!4d-122.4194')).toEqual({
      lat: 37.7749,
      lon: -122.4194,
    });
    expect(parseCoords(' 37.7749 , -122.4194 ')).toEqual({ lat: 37.7749, lon: -122.4194 });
  });

  it('rejects junk and out-of-range pairs', () => {
    expect(parseCoords('the school on the corner')).toBeNull();
    expect(parseCoords('')).toBeNull();
    expect(parseCoords('195.0, -122.4')).toBeNull();
  });
});

describe('haversineM', () => {
  it('matches the backend rule it mirrors', () => {
    // ~111.2 km per degree of latitude.
    const d = haversineM({ lat: 0, lon: 0 }, { lat: 1, lon: 0 });
    expect(d).toBeGreaterThan(110_000);
    expect(d).toBeLessThan(112_000);
    expect(haversineM({ lat: 37.7, lon: -122.4 }, { lat: 37.7, lon: -122.4 })).toBe(0);
  });
});
