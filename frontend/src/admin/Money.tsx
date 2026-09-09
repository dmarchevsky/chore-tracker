import { useEffect, useMemo, useState } from 'react';
import {
  useChildBalance,
  useChildLedger,
  useChildren,
  useDecision,
  usePayout,
  useReversePenalty,
} from './api';
import { ledgerQs } from '../api/hooks';
import { Button, Card, Spinner } from '../shared/ui';
import { KidTabs } from '../shared/KidTabs';
import { RangeTabs } from '../shared/RangeTabs';
import { DEFAULT_RANGE_DAYS, toRange, type RangeDays } from '../shared/dates';
import { money } from '../shared/format';
import { groupNote, groupStatement, netOfRange, type StatementGroup } from '../shared/statement';
import { entryLabel, isManualPenalty, OUTCOME_LABEL, TONE_CLASS } from '../shared/status';
import type { LedgerEntry } from '../api/types';

export function Money() {
  const kids = useChildren();
  const [childId, setChildId] = useState('');
  useEffect(() => {
    if (!childId && kids.data?.length) setChildId(kids.data[0].id);
  }, [kids.data, childId]);

  if (kids.isLoading) return <Spinner />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-bold">Money</h1>
        <KidTabs kids={kids.data ?? []} value={childId} onChange={setChildId} />
      </div>
      {childId && <ChildPanel childId={childId} />}
    </div>
  );
}

function ChildPanel({ childId }: { childId: string }) {
  // A year of chores is a lot of statement, and almost none of it is what the parent came
  // to look at. Default to a month; the pills reach further when something needs chasing.
  const [days, setDays] = useState<RangeDays>(DEFAULT_RANGE_DAYS);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const range = useMemo(() => toRange(days, from, to), [days, from, to]);

  const balance = useChildBalance(childId);
  const ledger = useChildLedger(childId, range);
  const payout = usePayout();
  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState('Cash');
  const [note, setNote] = useState('');

  const entries = useMemo(() => ledger.data ?? [], [ledger.data]);
  const groups = useMemo(() => groupStatement(entries), [entries]);
  const rangeNet = netOfRange(entries);

  return (
    <div className="grid gap-4">
      <Card>
        <p className="text-sm text-slate-400">Balance</p>
        <p
          className={`text-3xl font-bold ${
            (balance.data?.balance_cents ?? 0) < 0 ? 'text-rose-400' : ''
          }`}
        >
          {money(balance.data?.balance_cents ?? 0)}
        </p>
        {/* The balance is all-time and the statement is not, so say so — otherwise the two
            numbers on this card look like they disagree. */}
        <p className="text-xs text-slate-500">all time · {signed(rangeNet)} in the range shown</p>
        <a
          className="mt-1 inline-block text-xs text-sky-400 underline"
          href={`/api/v1/children/${childId}/ledger.csv${ledgerQs(range)}`}
        >
          export CSV
        </a>
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-sm font-semibold">Record a payout</p>
          <input
            className="inp"
            placeholder="Amount ($)"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          <div className="flex gap-2">
            <select
              className="inp"
              aria-label="Method"
              value={method}
              onChange={(e) => setMethod(e.target.value)}
            >
              <option value="Cash">Cash</option>
              <option value="GreenLight">GreenLight</option>
            </select>
            <input
              className="inp"
              placeholder="note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            disabled={!parseFloat(amount) || payout.isPending}
            onClick={() =>
              payout.mutate(
                {
                  child_id: childId,
                  amount_cents: Math.round(parseFloat(amount) * 100),
                  method,
                  note,
                },
                { onSuccess: () => setAmount('') },
              )
            }
          >
            Record payout
          </Button>
        </div>
      </Card>

      <div>
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <p className="text-sm font-semibold">Statement</p>
          <RangeTabs
            days={days}
            from={from}
            to={to}
            onChange={(next) => {
              setDays(next.days);
              setFrom(next.from);
              setTo(next.to);
            }}
          />
        </div>
        {ledger.isLoading ? (
          <Spinner />
        ) : groups.length === 0 ? (
          <p className="text-slate-500">No money moved in this range.</p>
        ) : (
          groups.map((g) => <StatementGroupRow key={g.key} group={g} />)
        )}
      </div>
    </div>
  );
}

const signed = (cents: number) => `${cents > 0 ? '+' : ''}${money(cents)}`;

/** One chore's worth of statement.
 *
 * A single decision can write three rows — a penalty, the reversal that cancels it, and the
 * earning that replaces it (spec §9, append-only) — and read line by line the last two are
 * indistinguishable credits. So the group leads with what actually happened and what it came
 * to, and keeps the rows themselves one tap away rather than deleting them from the view.
 *
 * Excusing is the ordinary decision path (spec §4.2): it writes a reversing entry rather
 * than removing the charge. A manually applied penalty (spec §4.8) has no occurrence to
 * excuse, so it gets its own undo — two affordances because they are genuinely different
 * acts: excusing forgives a missed chore and clears its state, undoing says the charge
 * itself shouldn't have happened.
 */
function StatementGroupRow({ group: g }: { group: StatementGroup }) {
  const decide = useDecision();
  const undo = useReversePenalty();
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState('');

  const charge = g.live_penalty;
  const excusable = !!charge?.occurrence_id;
  const undoable = !!charge && isManualPenalty(charge);
  const pending = decide.isPending || undo.isPending;
  const outcome = OUTCOME_LABEL[g.outcome];
  const many = g.entries.length > 1;
  const note = groupNote(g);
  // With one row there is nothing to expand into, so its reason belongs on the face of the
  // group — on a hand-applied penalty the note is the whole content of the charge (§4.8).
  const lone = !many ? g.entries[0] : null;

  const header = (
    <div className="flex items-baseline justify-between gap-3">
      <span>
        {many && <span className="mr-1 text-slate-500">{open ? '▾' : '▸'}</span>}
        {g.chore_title || note || 'Adjustment'}
        <span className="text-slate-400">
          {g.occurrence_due_at
            ? `, due ${new Date(g.occurrence_due_at).toLocaleDateString()}`
            : ` · ${new Date(g.at).toLocaleDateString()}`}
        </span>
        <span className={`ml-2 text-xs ${TONE_CLASS[outcome.tone]}`}>{outcome.label}</span>
        {lone?.reversed_by_entry_id && (
          <span className="ml-2 text-xs text-slate-500">(reversed)</span>
        )}
      </span>
      <span className={`shrink-0 ${g.net_cents < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
        {signed(g.net_cents)}
      </span>
    </div>
  );

  return (
    <div className="border-b border-slate-800 py-1 text-sm">
      {many ? (
        <button
          type="button"
          className="w-full text-left"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {header}
        </button>
      ) : (
        header
      )}

      {note && g.chore_title && <p className="text-xs text-slate-500">{note}</p>}

      {open && (
        <div className="mt-1 space-y-0.5 border-l border-slate-800 pl-3">
          {g.entries.map((e) => (
            <EntryLine key={e.id} entry={e} />
          ))}
        </div>
      )}

      {(excusable || undoable) && !asking && (
        <button className="text-xs text-sky-400 underline" onClick={() => setAsking(true)}>
          {excusable ? 'Excuse this' : 'Undo this'}
        </button>
      )}
      {asking && charge && (
        <div className="mt-1 flex gap-2">
          <input
            className="inp text-sm"
            placeholder="Why? Your kid reads this."
            value={reason}
            onChange={(ev) => setReason(ev.target.value)}
          />
          <Button
            className="min-h-0 shrink-0 px-3 py-2 text-sm"
            variant="ghost"
            disabled={!reason.trim() || pending}
            onClick={() =>
              excusable
                ? decide.mutate(
                    { id: charge.occurrence_id as string, body: { action: 'excuse', reason } },
                    { onSuccess: () => setAsking(false) },
                  )
                : undo.mutate({ id: charge.id, reason }, { onSuccess: () => setAsking(false) })
            }
          >
            {excusable ? 'Excuse' : 'Undo'}
          </Button>
        </div>
      )}
      {decide.isError && <p className="text-xs text-rose-400">Couldn’t excuse that one.</p>}
      {undo.isError && <p className="text-xs text-rose-400">Couldn’t undo that one.</p>}
    </div>
  );
}

/** One raw ledger row, inside an expanded group.
 *
 * The kind leads and the reason follows it, rather than the other way round: a reversal's
 * reason is the parent's own decision text ("approved: Ok"), which on its own reads exactly
 * like a reward for the chore.
 */
function EntryLine({ entry: e }: { entry: LedgerEntry }) {
  return (
    <div className="flex justify-between gap-3 text-xs text-slate-400">
      <span>
        {new Date(e.created_at).toLocaleDateString()} · {entryLabel(e)}
        {e.reason && <span className="text-slate-500"> — {e.reason}</span>}
        {e.reversed_by_entry_id && <span className="text-slate-500"> (reversed)</span>}
      </span>
      <span className={`shrink-0 ${e.amount_cents < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
        {signed(e.amount_cents)}
      </span>
    </div>
  );
}
