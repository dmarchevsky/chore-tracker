import type { Chore } from '../api/types';

/** Is this chore assigned to `userId`?
 *
 * `anyone` is a genuinely unassigned pool, so it belongs to nobody in particular — which is
 * why this is about a chore's *live state* (is the rule in force for me right now), not
 * about whether the rule may be read. Use `isVisibleTo` for that (spec §15 Q1 vs. Q8).
 */
export function isAssignedTo(c: Chore, userId: string | null | undefined): boolean {
  if (!userId) return false;
  if (c.assignment_mode === 'fixed') return c.fixed_assignee_id === userId;
  if (c.assignment_mode === 'rotating' || c.assignment_mode === 'all')
    return c.assignee_ids.includes(userId);
  return false;
}

/** May `userId` read this chore's rule at all?
 *
 * Their own chores, plus the `anyone` pool — a kid is allowed to claim one, so hiding the
 * rule would hide something they can act on. GET /chores already scopes a kid's list this
 * way server-side; this keeps a cached or stale response honest too.
 */
export function isVisibleTo(c: Chore, userId: string | null | undefined): boolean {
  return isAssignedTo(c, userId) || c.assignment_mode === 'anyone';
}
