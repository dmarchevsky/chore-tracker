import { useEffect, useState } from 'react';
import { useChildBalance, useChildLedger, useCheckinToken, useChildren, usePayout } from './api';
import { Button, Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';

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
        <h1 className="text-lg font-bold">Kids &amp; money</h1>
        <select
          className="inp max-w-xs"
          value={childId}
          onChange={(e) => setChildId(e.target.value)}
        >
          {(kids.data ?? []).map((k) => (
            <option key={k.id} value={k.id}>
              {k.display_name}
            </option>
          ))}
        </select>
      </div>
      {childId && <ChildPanel childId={childId} />}
    </div>
  );
}

function ChildPanel({ childId }: { childId: string }) {
  const balance = useChildBalance(childId);
  const ledger = useChildLedger(childId);
  const token = useCheckinToken(childId);
  const payout = usePayout();
  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState('cash');
  const [note, setNote] = useState('');

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <p className="text-sm text-slate-400">Balance</p>
        <p
          className={`text-3xl font-bold ${
            (balance.data?.balance_cents ?? 0) < 0 ? 'text-rose-400' : ''
          }`}
        >
          {money(balance.data?.balance_cents ?? 0)}
        </p>
        <a
          className="mt-1 inline-block text-xs text-sky-400 underline"
          href={`/api/v1/children/${childId}/ledger.csv`}
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
            <input className="inp" value={method} onChange={(e) => setMethod(e.target.value)} />
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

      <Card>
        <p className="text-sm font-semibold">Check-in webhook</p>
        {token.data && (
          <>
            <code className="mt-1 block break-all rounded bg-slate-800 p-2 text-xs">
              {token.data.webhook_url}
            </code>
            <p className={`mt-1 text-xs ${token.data.stale ? 'text-amber-400' : 'text-slate-400'}`}>
              {token.data.last_used_at
                ? `last seen ${new Date(token.data.last_used_at).toLocaleString()}`
                : 'never used'}
              {token.data.stale && ' — automation may be broken'}
            </p>
          </>
        )}
      </Card>

      <div className="md:col-span-2">
        <p className="mb-1 text-sm font-semibold">Statement</p>
        {(ledger.data ?? []).map((e) => (
          <div key={e.id} className="flex justify-between border-b border-slate-800 py-1 text-sm">
            <span>
              {new Date(e.created_at).toLocaleDateString()} · {e.reason || e.kind}
            </span>
            <span className={e.amount_cents < 0 ? 'text-rose-400' : 'text-emerald-400'}>
              {money(e.amount_cents)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
