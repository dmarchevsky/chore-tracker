import { describe, expect, it } from 'vitest';
import { groupNote, groupStatement, netOfRange } from './statement';
import type { LedgerEntry } from '../api/types';

function entry(e: Partial<LedgerEntry> & { id: string }): LedgerEntry {
  return {
    kind: 'earning',
    amount_cents: 0,
    reason: '',
    created_at: '2026-09-09T00:00:00Z',
    occurrence_id: null,
    reversed_by_entry_id: null,
    reverses_entry_id: null,
    chore_id: null,
    chore_title: null,
    occurrence_due_at: null,
    ...e,
  };
}

// The exact shape the parent reported: the model failed the photo, the parent overrode it.
// Three rows, two of them positive, and read line by line it looks like a double payment.
const AUTO_FAIL_THEN_APPROVED = [
  entry({
    id: 'p',
    kind: 'penalty',
    amount_cents: -500,
    reason: 'auto-verified fail',
    occurrence_id: 'o9',
    chore_title: 'Kitchen',
    occurrence_due_at: '2026-09-09T15:00:00Z',
    reversed_by_entry_id: 'r',
    created_at: '2026-09-09T08:00:00Z',
  }),
  entry({
    id: 'e',
    kind: 'earning',
    amount_cents: 500,
    reason: 'Ok',
    occurrence_id: 'o9',
    chore_title: 'Kitchen',
    created_at: '2026-09-09T09:00:00Z',
  }),
  entry({
    id: 'r',
    kind: 'adjustment',
    amount_cents: 500,
    reason: 'approved: Ok',
    occurrence_id: 'o9',
    chore_title: 'Kitchen',
    reverses_entry_id: 'p',
    created_at: '2026-09-09T09:00:00Z',
  }),
];

// A miss the scheduler charged for, then the parent excused. Two rows, net zero.
const MISSED_THEN_EXCUSED = [
  entry({
    id: 'p2',
    kind: 'penalty',
    amount_cents: -500,
    reason: 'chore missed',
    occurrence_id: 'o7',
    chore_title: 'Kitchen',
    reversed_by_entry_id: 'r2',
    created_at: '2026-09-07T08:00:00Z',
  }),
  entry({
    id: 'r2',
    kind: 'adjustment',
    amount_cents: 500,
    reason: 'excused: we were away',
    occurrence_id: 'o7',
    chore_title: 'Kitchen',
    reverses_entry_id: 'p2',
    created_at: '2026-09-08T08:00:00Z',
  }),
];

describe('groupStatement', () => {
  it('folds a chore the parent approved over the model into one Earned line', () => {
    const [g] = groupStatement(AUTO_FAIL_THEN_APPROVED);

    expect(g.outcome).toBe('earned');
    // The whole point: paid once, not twice.
    expect(g.net_cents).toBe(500);
    expect(g.entries).toHaveLength(3);
    expect(g.chore_title).toBe('Kitchen');
    expect(g.live_penalty).toBeNull();
  });

  it('puts each reversal directly after the entry it undoes', () => {
    // They share a timestamp — written in one transaction — so time can't order them, and
    // a reversal floating above its charge reads as an unexplained credit.
    const [g] = groupStatement(AUTO_FAIL_THEN_APPROVED);
    expect(g.entries.map((e) => e.id)).toEqual(['p', 'r', 'e']);
  });

  it('folds an excused miss into one net-zero line', () => {
    const [g] = groupStatement(MISSED_THEN_EXCUSED);

    expect(g.outcome).toBe('excused');
    expect(g.net_cents).toBe(0);
    expect(g.entries).toHaveLength(2);
    // Nothing left to excuse — the charge no longer stands.
    expect(g.live_penalty).toBeNull();
  });

  it('still calls a chore excused when the date filter kept only half the story', () => {
    // Charged inside the window, excused outside it (or the reverse). Net is not zero, but
    // the charge is undone either way, and calling it Missed would be a lie.
    const [charge, reversal] = MISSED_THEN_EXCUSED;
    expect(groupStatement([charge])[0].outcome).toBe('excused');
    expect(groupStatement([reversal])[0].outcome).toBe('excused');
  });

  it('offers a standing miss up to be excused', () => {
    const g = groupStatement([
      entry({
        id: 'p3',
        kind: 'penalty',
        amount_cents: -500,
        reason: 'chore missed',
        occurrence_id: 'o6',
        chore_title: 'Tidy your bedroom',
      }),
    ])[0];

    expect(g.outcome).toBe('missed');
    expect(g.live_penalty?.id).toBe('p3');
  });

  it('leaves entries with no occurrence standing alone', () => {
    const groups = groupStatement([
      entry({ id: 'pay', kind: 'payout', amount_cents: -2000, reason: 'payout via Cash' }),
      entry({
        id: 'man',
        kind: 'penalty',
        amount_cents: -200,
        reason: 'Bike left out: in the driveway',
        chore_id: 'c4',
        chore_title: 'Bike left out',
      }),
    ]);

    // A payout is already one line meaning one thing; a hand-applied penalty (spec §4.8)
    // has no occurrence to fold into.
    expect(groups).toHaveLength(2);
    expect(groups.map((g) => g.outcome).sort()).toEqual(['payout', 'penalty']);
    expect(groups.every((g) => g.entries.length === 1)).toBe(true);
    expect(groups.find((g) => g.outcome === 'penalty')?.live_penalty?.id).toBe('man');
  });

  it('sorts newest group first', () => {
    const groups = groupStatement([...MISSED_THEN_EXCUSED, ...AUTO_FAIL_THEN_APPROVED]);
    expect(groups.map((g) => g.occurrence_id)).toEqual(['o9', 'o7']);
  });

  it('reads an entry with no reversal marker as still standing', () => {
    // The field is non-null in every real payload, but treating a missing one as reversed
    // would quietly hide a charge the kid actually paid.
    const g = groupStatement([
      { ...entry({ id: 'x', kind: 'penalty', amount_cents: -100, occurrence_id: 'o1' }) },
    ])[0];
    expect(g.outcome).toBe('missed');
  });
});

describe('groupNote', () => {
  it('quotes the decision that stands, not the one it replaced', () => {
    expect(groupNote(groupStatement(AUTO_FAIL_THEN_APPROVED)[0])).toBe('Ok');
  });

  it('falls back to the reversal when everything was undone', () => {
    expect(groupNote(groupStatement(MISSED_THEN_EXCUSED)[0])).toBe('excused: we were away');
  });
});

describe('netOfRange', () => {
  it('sums exactly what is on screen, reversals included', () => {
    expect(netOfRange([...MISSED_THEN_EXCUSED, ...AUTO_FAIL_THEN_APPROVED])).toBe(500);
  });
});
