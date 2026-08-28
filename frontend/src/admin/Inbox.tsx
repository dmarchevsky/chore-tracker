import { useState } from 'react';
import { useInbox, useDecision } from './api';
import { useAdminChores } from './api';
import { ReviewDetail } from './ReviewDetail';
import { Button, Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';

export function Inbox() {
  const inbox = useInbox();
  const chores = useAdminChores();
  const decide = useDecision();
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());

  if (inbox.isLoading || chores.isLoading) return <Spinner />;
  const byId = new Map((chores.data ?? []).map((c) => [c.id, c]));
  const rows = inbox.data ?? [];

  function toggle(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function bulkApprove() {
    for (const id of checked) {
      await decide.mutateAsync({ id, body: { action: 'approve', reason: 'bulk approve' } });
    }
    setChecked(new Set());
  }

  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,360px)_1fr]">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold">Review inbox</h1>
          {checked.size > 0 && (
            <Button className="min-h-0 px-3 py-1 text-sm" onClick={bulkApprove}>
              Approve {checked.size}
            </Button>
          )}
        </div>
        {rows.length === 0 && <p className="text-slate-500">Nothing waiting. 🎉</p>}
        {rows.map((o) => (
          <Card
            key={o.id}
            className={`cursor-pointer ${selected === o.id ? 'border-sky-600' : ''}`}
          >
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-1"
                checked={checked.has(o.id)}
                onChange={() => toggle(o.id)}
                onClick={(e) => e.stopPropagation()}
              />
              <button className="flex-1 text-left" onClick={() => setSelected(o.id)}>
                <p className="font-semibold">{byId.get(o.chore_id)?.title ?? 'Chore'}</p>
                <p className="text-xs text-slate-400">
                  {o.status} · due {new Date(o.due_at).toLocaleString()} · {money(o.reward_cents)}
                </p>
                {o.verification_error && (
                  <p className="text-xs text-amber-400">model error — {o.verification_error}</p>
                )}
              </button>
            </div>
          </Card>
        ))}
      </div>
      <div>
        {selected ? (
          <ReviewDetail id={selected} onDone={() => setSelected(null)} />
        ) : (
          <p className="text-slate-500">Select an item to review.</p>
        )}
      </div>
    </div>
  );
}
