import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ChecklistField, type ChecklistItem } from './ChecklistField';

afterEach(cleanup);

const ITEM: ChecklistItem = { id: 1, text: 'Are there dirty dishes in the basin?', required: true };

function show(items: ChecklistItem[] = [ITEM]) {
  const onChange = vi.fn();
  render(<ChecklistField value={items} onChange={onChange} />);
  return onChange;
}

describe('ChecklistField', () => {
  it('lets a check say which answer means done', () => {
    // So the parent can ask the direct question instead of inverting it into "is the
    // basin clear of dishes?", which makes the model prove an absence.
    const onChange = show();
    fireEvent.change(screen.getByLabelText(/passes when the answer is/i), {
      target: { value: 'no' },
    });
    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ expect: 'no' })]);
  });

  it('defaults to yes, so an existing check is untouched', () => {
    show();
    expect(screen.getByLabelText(/passes when the answer is/i)).toHaveValue('yes');
  });

  it('collects the things that must not count against the check', () => {
    // The real failure: "a sponge, dish brush, or drain strainer is fine" written at the
    // end of the question was dropped, and the chore failed citing those very items.
    const onChange = show();
    fireEvent.change(screen.getByLabelText(/ignores/i), {
      target: { value: 'sponge, dish brush , drain strainer' },
    });
    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ ignore: ['sponge', 'dish brush', 'drain strainer'] }),
    ]);
  });

  it('round-trips an ignore list back into the box', () => {
    show([{ ...ITEM, ignore: ['sponge', 'dish brush'] }]);
    expect(screen.getByLabelText(/ignores/i)).toHaveValue('sponge, dish brush');
  });
});
