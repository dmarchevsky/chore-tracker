import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSectionState } from './collapsed';

const KEY = 'test.sections';
const DEFAULTS = { open: true, shut: false };

const mount = () => renderHook(() => useSectionState(KEY, DEFAULTS));

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe('useSectionState', () => {
  it('follows the declared default until someone toggles', () => {
    const { result } = mount();
    expect(result.current.isOpen('open')).toBe(true);
    expect(result.current.isOpen('shut')).toBe(false);
  });

  it('treats a section nobody declared as open', () => {
    // A section added to the screen but not to its defaults map shows its rows rather than
    // vanishing — the failure mode of a typo should be visible, not silent.
    expect(mount().result.current.isOpen('brand-new')).toBe(true);
  });

  it('toggles from whichever default applies', () => {
    const { result } = mount();
    act(() => result.current.toggle('shut'));
    expect(result.current.isOpen('shut')).toBe(true);
    act(() => result.current.toggle('open'));
    expect(result.current.isOpen('open')).toBe(false);
  });

  it('remembers a choice across a fresh mount', () => {
    // What "survives a reload and a re-login" comes down to: sign-out never clears storage.
    const first = mount();
    act(() => first.result.current.toggle('open'));
    expect(mount().result.current.isOpen('open')).toBe(false);
  });

  it('stores only what was actually toggled, so defaults stay changeable', () => {
    const { result } = mount();
    act(() => result.current.toggle('open'));
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({ open: false });
  });

  it('ignores stored junk', () => {
    localStorage.setItem(KEY, '["not", "an", "object"]');
    expect(mount().result.current.isOpen('open')).toBe(true);
    localStorage.setItem(KEY, '{"open": "yes please"}');
    expect(mount().result.current.isOpen('open')).toBe(true);
  });

  it('keeps working when storage is unavailable', () => {
    // A private window, or a browser set to block site data. The preference is lost on
    // reload, but the screen must still open and still toggle.
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });
    const { result } = mount();
    expect(result.current.isOpen('open')).toBe(true);
    act(() => result.current.toggle('open'));
    expect(result.current.isOpen('open')).toBe(false);
  });
});
