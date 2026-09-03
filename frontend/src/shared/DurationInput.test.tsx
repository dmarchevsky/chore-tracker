import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DurationInput } from './DurationInput';

afterEach(cleanup);

function setup(value = 12 * 3600, max = 14 * 24 * 3600) {
  const onChange = vi.fn();
  render(<DurationInput value={value} onChange={onChange} max={max} id="d" />);
  return { onChange, box: screen.getByRole('textbox') as HTMLInputElement };
}

describe('DurationInput', () => {
  it.each([
    [12 * 3600, '12h'],
    [9000, '2h30m'],
    [900, '15m'],
  ])('shows %d seconds as the shortest exact spelling', (secs, text) => {
    expect(setup(secs).box.value).toBe(text);
  });

  it('reads hours and minutes together', () => {
    const { onChange, box } = setup();
    fireEvent.change(box, { target: { value: '2h30m' } });
    expect(onChange).toHaveBeenCalledWith(9000);
  });

  it('reads a bare number as hours, which is what the field used to take', () => {
    const { onChange, box } = setup();
    fireEvent.change(box, { target: { value: '3' } });
    expect(onChange).toHaveBeenCalledWith(3 * 3600);
  });

  it('keeps a half-typed value on screen without writing it to the form', () => {
    // "2h3" is the keystroke between "2h" and "2h30m"; writing 2h at that moment would
    // silently change what the parent is in the middle of typing.
    const { onChange, box } = setup();
    fireEvent.change(box, { target: { value: 'later' } });

    expect(box.value).toBe('later');
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/Try 2h30m/)).toBeInTheDocument();
  });

  it('catches a value past the backend bound here rather than as a 422', () => {
    const { onChange, box } = setup();
    fireEvent.change(box, { target: { value: '400h' } });

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/longer than the 336h limit/)).toBeInTheDocument();
  });

  it('re-seeds when the value changes from outside, e.g. loading a chore to edit', () => {
    const onChange = vi.fn();
    const { rerender } = render(<DurationInput value={900} onChange={onChange} max={86400} />);
    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('15m');

    rerender(<DurationInput value={5400} onChange={onChange} max={86400} />);
    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('1h30m');
  });
});
