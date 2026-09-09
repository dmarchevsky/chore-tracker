import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useBalance, useLedger } from '../api/hooks';
import { Card, Spinner } from '../shared/ui';
import { RangeTabs } from '../shared/RangeTabs';
import { DEFAULT_RANGE_DAYS, toRange, type RangeDays } from '../shared/dates';
import { money } from '../shared/format';
import { groupNote, groupStatement, type StatementGroup } from '../shared/statement';
import { entryLabel, OUTCOME_LABEL, TONE_CLASS } from '../shared/status';
import type { LedgerEntry } from '../api/types';

const signed = (cents: number) => `${cents > 0 ? '+' : ''}${money(cents)}`;

export function Money() {
  const { me } = useAuth();
  const [days, setDays] = useState<RangeDays>(DEFAULT_RANGE_DAYS);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const range = useMemo(() => toRange(days, from, to), [days, from, to]);

  const balance = useBalance(me?.id ?? '');
  const ledger = useLedger(me?.id ?? '', range);
  const entries = useMemo(() => ledger.data ?? [], [ledger.data]);
  const groups = useMemo(() => groupStatement(entries), [entries]);

  if (!me || balance.isLoading) return <Spinner />;

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h1 className="text-xl font-bold">Money</h1>
      <Card>
        <p className="text-sm text-slate-400">Balance</p>
        <p
          className={`text-3xl font-bold ${
            (balance.data?.balance_cents ?? 0) < 0 ? 'text-rose-400' : ''
          }`}
        >
          {money(balance.data?.balance_cents ?? 0)}
        </p>
      </Card>
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
      <div className="flex flex-col gap-2">
        {ledger.isLoading ? (
          <Spinner />
        ) : groups.length === 0 ? (
          <p className="text-slate-500">No entries yet.</p>
        ) : (
          groups.map((g) => <LedgerGroup key={g.key} group={g} />)
        )}
      </div>
    </div>
  );
}

/** One chore's money, folded into a line.
 *
 * A chore the parent approved after the model failed it wrote three ledger rows — the
 * charge, the reversal cancelling it, and the reward (spec §9, append-only). Shown flat
 * that reads like being paid twice; shown as one line with the net, it reads like what
 * happened. The rows are still there under the tap.
 *
 * A charge names a chore, and the obvious next question is "which time, and what happened?"
 * — so when the group hangs off an occurrence the whole line opens that chore, the same
 * screen the Done tab links to, where the verdict and the Dispute button already live.
 * Payouts, adjustments and hand-applied penalties (spec §4.8) have no occurrence behind
 * them, so those stay plain text rather than a tap that leads nowhere.
 */
function LedgerGroup({ group: g }: { group: StatementGroup }) {
  const [open, setOpen] = useState(false);
  const outcome = OUTCOME_LABEL[g.outcome];
  const many = g.entries.length > 1;
  const note = groupNote(g);

  const body = (
    <div className="border-b border-slate-800 py-2 text-sm">
      <div className="flex justify-between gap-3">
        <div>
          <p>
            {g.chore_title || note || 'Adjustment'}
            <span className={`ml-2 text-xs ${TONE_CLASS[outcome.tone]}`}>{outcome.label}</span>
          </p>
          {note && g.chore_title && <p className="text-xs text-slate-400">{note}</p>}
          <p className="text-xs text-slate-500">
            {new Date(g.at).toLocaleDateString()}
            {g.occurrence_due_at && ` · due ${new Date(g.occurrence_due_at).toLocaleDateString()}`}
          </p>
        </div>
        <span className={`shrink-0 ${g.net_cents < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
          {signed(g.net_cents)}
        </span>
      </div>
    </div>
  );

  return (
    <div>
      {g.occurrence_id ? (
        <Link to={`/me/chores/${g.occurrence_id}`} className="block">
          {body}
        </Link>
      ) : (
        body
      )}
      {many && (
        <>
          <button
            type="button"
            className="text-xs text-sky-400 underline"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {open ? 'Hide the details' : 'How this adds up'}
          </button>
          {open && (
            <div className="mt-1 space-y-0.5 border-l border-slate-800 pl-3">
              {g.entries.map((e) => (
                <EntryLine key={e.id} entry={e} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** The kind leads, the reason follows: a reversal's reason is the parent's decision text
 *  ("approved: Ok"), which alone reads exactly like a second reward. */
function EntryLine({ entry: e }: { entry: LedgerEntry }) {
  return (
    <div className="flex justify-between gap-3 text-xs text-slate-400">
      <span>
        {entryLabel(e)}
        {e.reason && <span className="text-slate-500"> — {e.reason}</span>}
      </span>
      <span className={`shrink-0 ${e.amount_cents < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
        {signed(e.amount_cents)}
      </span>
    </div>
  );
}
