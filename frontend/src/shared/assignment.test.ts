import { describe, expect, it } from 'vitest';
import { isAssignedTo, isVisibleTo } from './assignment';
import type { Chore } from '../api/types';

const c = (over: Partial<Chore>) =>
  ({ assignment_mode: 'fixed', fixed_assignee_id: null, assignee_ids: [], ...over }) as Chore;

describe('isAssignedTo', () => {
  it('matches the named kid on a fixed chore', () => {
    expect(isAssignedTo(c({ fixed_assignee_id: 'nika' }), 'nika')).toBe(true);
    expect(isAssignedTo(c({ fixed_assignee_id: 'nika' }), 'kira')).toBe(false);
  });

  it('matches any listed kid on rotating and all', () => {
    for (const mode of ['rotating', 'all'] as const) {
      const chore = c({ assignment_mode: mode, assignee_ids: ['nika', 'kira'] });
      expect(isAssignedTo(chore, 'kira')).toBe(true);
      expect(isAssignedTo(chore, 'mo')).toBe(false);
    }
  });

  it('belongs to nobody in particular when the pool is unassigned', () => {
    expect(isAssignedTo(c({ assignment_mode: 'anyone' }), 'nika')).toBe(false);
  });

  it('is false for a signed-out viewer rather than throwing', () => {
    expect(isAssignedTo(c({ fixed_assignee_id: 'nika' }), null)).toBe(false);
    expect(isAssignedTo(c({ fixed_assignee_id: 'nika' }), undefined)).toBe(false);
  });
});

describe('isVisibleTo', () => {
  it('covers the assignee plus the unassigned pool', () => {
    expect(isVisibleTo(c({ fixed_assignee_id: 'nika' }), 'nika')).toBe(true);
    expect(isVisibleTo(c({ assignment_mode: 'anyone' }), 'nika')).toBe(true);
  });

  it("hides a sibling's chore", () => {
    expect(isVisibleTo(c({ fixed_assignee_id: 'nika' }), 'kira')).toBe(false);
  });
});
