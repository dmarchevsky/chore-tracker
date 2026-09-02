import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useBalance, useLedger } from '../api/hooks';
import { Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';
import { entryLabel } from '../shared/status';
import type { LedgerEntry } from '../api/types';

export function Money() {
  const { me } = useAuth();
  const balance = useBalance(me?.id ?? '');
  const ledger = useLedger(me?.id ?? '');

  if (!me || balance.isLoading || ledger.isLoading) return <Spinner />;

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
      <div className="flex flex-col gap-2">
        {/* backend returns oldest-first; show newest at the top */}
        {[...(ledger.data ?? [])].reverse().map((e) => (
          <LedgerRow key={e.id} entry={e} />
        ))}
        {(ledger.data ?? []).length === 0 && <p className="text-slate-500">No entries yet.</p>}
      </div>
    </div>
  );
}

/** One line of the statement.
 *
 * A charge names a chore, and the obvious next question is "which time, and what happened?"
 * — so when the entry hangs off an occurrence the whole row opens that chore, the same
 * screen the Done tab links to, where the verdict and the Dispute button already live.
 * Payouts, adjustments and hand-applied penalties (spec §4.8) have no occurrence behind
 * them, so those stay plain text rather than a tap that leads nowhere.
 */
function LedgerRow({ entry: e }: { entry: LedgerEntry }) {
  const body = (
    <div className="flex justify-between border-b border-slate-800 py-2 text-sm">
      <div>
        <p>
          {e.reason || entryLabel(e)}
          {/* "Missed chore" alone doesn't say *which* one — name it, like the
              parent's statement does, so a charge is recognisable. */}
          {e.chore_title && <span className="text-slate-400"> — {e.chore_title}</span>}
        </p>
        <p className="text-xs text-slate-500">
          {new Date(e.created_at).toLocaleDateString()}
          {e.occurrence_due_at && ` · due ${new Date(e.occurrence_due_at).toLocaleDateString()}`}
        </p>
      </div>
      <span className={e.amount_cents < 0 ? 'text-rose-400' : 'text-emerald-400'}>
        {e.amount_cents > 0 ? '+' : ''}
        {money(e.amount_cents)}
      </span>
    </div>
  );
  if (!e.occurrence_id) return body;
  return (
    <Link to={`/me/chores/${e.occurrence_id}`} className="block">
      {body}
    </Link>
  );
}
