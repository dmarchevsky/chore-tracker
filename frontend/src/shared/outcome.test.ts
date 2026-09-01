import { describe, expect, it } from 'vitest';
import { choreWorth, occurrenceWorth } from './outcome';
import type { Chore, Occurrence } from '../api/types';

const TIERS = [
  {
    id: 1,
    condition: 'all A grades',
    outcome_kind: 'money' as const,
    amount_cents: 10000,
    text: null,
  },
  { id: 2, condition: 'one C', outcome_kind: 'money' as const, amount_cents: -5000, text: null },
];

const chore = (over: Partial<Chore> = {}) =>
  ({
    chore_kind: 'scheduled',
    outcome_tiers: null,
    reward_cents: 200,
    penalty_cents: 0,
    ...over,
  }) as Chore;

const occ = (over: Partial<Occurrence> = {}) =>
  ({
    outcome_tiers: null,
    outcome_tier: null,
    reward_cents: 200,
    penalty_cents: 0,
    ...over,
  }) as Occurrence;

describe('choreWorth', () => {
  it('prints the reward for an ordinary chore', () => {
    expect(choreWorth(chore())).toBe('$2.00');
  });

  it('says nothing for a standing chore — it moves no money', () => {
    expect(choreWorth(chore({ chore_kind: 'standing', reward_cents: 0 }))).toBeNull();
  });

  it('does not pretend a tiered chore is worth a fixed amount', () => {
    expect(choreWorth(chore({ outcome_tiers: TIERS, reward_cents: 0 }))).toBe(
      'depends on how it goes',
    );
  });

  it('says nothing rather than $0.00 for a chore with no money', () => {
    expect(choreWorth(chore({ reward_cents: 0, penalty_cents: 0 }))).toBeNull();
  });

  it('still speaks up for a penalty-only chore', () => {
    expect(choreWorth(chore({ reward_cents: 0, penalty_cents: 500 }))).toBe('$0.00');
  });
});

describe('occurrenceWorth', () => {
  it('prints the snapshot reward for an ordinary occurrence', () => {
    expect(occurrenceWorth(occ())).toBe('$2.00');
  });

  it('is undecided until a tier is picked', () => {
    expect(occurrenceWorth(occ({ outcome_tiers: TIERS, reward_cents: 0 }))).toBe(
      'depends on how it goes',
    );
  });

  it('shows the chosen tier, signed', () => {
    expect(occurrenceWorth(occ({ outcome_tiers: TIERS, outcome_tier: TIERS[1] }))).toBe('-$50.00');
    expect(occurrenceWorth(occ({ outcome_tiers: TIERS, outcome_tier: TIERS[0] }))).toBe('+$100.00');
  });

  it('shows a text outcome as the sentence it is', () => {
    const tier = {
      id: 1,
      condition: 'more than one missing assignment',
      outcome_kind: 'text' as const,
      amount_cents: null,
      text: 'grounded until it is fixed',
    };
    expect(occurrenceWorth(occ({ outcome_tiers: [tier], outcome_tier: tier }))).toBe(
      'grounded until it is fixed',
    );
  });
});
