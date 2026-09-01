// What a chore or an occurrence is "worth", in one place.
//
// Every surface used to print money(reward_cents) unconditionally, which reads as "$0.00 —
// this is worth nothing" for a tiered chore (its money lives in its tiers) and for a
// standing chore (which moves no money at all). null means "say nothing here".
import type { Chore, Occurrence } from '../api/types';
import { money, tierOutcome } from './format';

/** Worth of a chore *definition* — the list rows and the kid's rules screen. */
export function choreWorth(c: Chore): string | null {
  if (c.chore_kind === 'standing') return null;
  if (c.outcome_tiers?.length) return 'depends on how it goes';
  if (!c.reward_cents && !c.penalty_cents) return null;
  return money(c.reward_cents);
}

/** Worth of a single occurrence — queue rows, review header, the kid's to-do rows. */
export function occurrenceWorth(o: Occurrence): string | null {
  if (o.outcome_tier) return tierOutcome(o.outcome_tier);
  if (o.outcome_tiers?.length) return 'depends on how it goes';
  if (!o.reward_cents && !o.penalty_cents) return null;
  return money(o.reward_cents);
}
