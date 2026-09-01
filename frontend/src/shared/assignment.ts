import type { Chore } from '../api/types';

/** Is this chore assigned to `userId`?
 *
 * GET /chores serves every household definition to every kid on purpose — they can read the
 * rules (spec §15 Q8). Anything that shows a chore's *live state* has to narrow that back to
 * the viewer, or one kid sees another's business (spec §15 Q1, own data only).
 *
 * `anyone` is a genuinely unassigned pool, so it belongs to nobody in particular.
 */
export function isAssignedTo(c: Chore, userId: string | null | undefined): boolean {
  if (!userId) return false;
  if (c.assignment_mode === 'fixed') return c.fixed_assignee_id === userId;
  if (c.assignment_mode === 'rotating' || c.assignment_mode === 'all')
    return c.assignee_ids.includes(userId);
  return false;
}
