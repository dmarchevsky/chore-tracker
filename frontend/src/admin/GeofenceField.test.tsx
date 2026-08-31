import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { GeofenceField } from './GeofenceField';

// Leaflet needs a layout engine jsdom doesn't have; the map is a lazy chunk so the
// rest of the field is testable without it.
vi.mock('./FenceMap', () => ({ default: () => <div data-testid="map" /> }));

const fence = { lat: 37.7749, lon: -122.4194, radius_m: 120 };

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  Object.defineProperty(navigator, 'geolocation', { value: undefined, configurable: true });
});

function setGeolocation(pos: { latitude: number; longitude: number; accuracy: number } | null) {
  Object.defineProperty(navigator, 'geolocation', {
    configurable: true,
    value: {
      getCurrentPosition: (ok: PositionCallback, err: PositionErrorCallback) =>
        pos ? ok({ coords: pos } as GeolocationPosition) : err({} as GeolocationPositionError),
    },
  });
}

describe('GeofenceField', () => {
  it('fills the centre from the browser and reports the accuracy', async () => {
    setGeolocation({ latitude: 40.7128, longitude: -74.006, accuracy: 12 });
    const onChange = vi.fn();
    render(<GeofenceField value={fence} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: /use my current location/i }));

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(onChange.mock.calls[0][0]).toMatchObject({ lat: 40.7128, lon: -74.006, radius_m: 120 });
    expect(await screen.findByText(/±12 m/)).toBeInTheDocument();
  });

  it('says so instead of dying when the browser refuses', async () => {
    setGeolocation(null);
    render(<GeofenceField value={fence} onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /use my current location/i }));
    expect(await screen.findByText(/couldn’t get your location/i)).toBeInTheDocument();
  });

  it('accepts a pasted map link', () => {
    const onChange = vi.fn();
    render(<GeofenceField value={fence} onChange={onChange} />);

    fireEvent.change(screen.getByPlaceholderText(/paste a map link/i), {
      target: { value: 'https://www.google.com/maps/@51.5007,-0.1246,17z' },
    });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ lat: 51.5007, lon: -0.1246 }));
  });

  it('edits the radius from the slider', () => {
    const onChange = vi.fn();
    render(<GeofenceField value={fence} onChange={onChange} />);

    fireEvent.change(screen.getByRole('slider'), { target: { value: '300' } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ radius_m: 300 }));
  });
});
