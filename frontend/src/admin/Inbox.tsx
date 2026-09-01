import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useInbox, useDecision } from './api';
import { useAdminChores, useChildren, useOpenDisputes } from './api';
import { ReviewDetail } from './ReviewDetail';
import { Button, Card, Spinner } from '../shared/ui';
import { StatusBadge } from '../shared/StatusBadge';
import { occurrenceWorth } from '../shared/outcome';

export function Inbox() {
  const inbox = useInbox();
  const chores = useAdminChores();
  const kids = useChildren();
  const openDisputes = useOpenDisputes();
  const decide = useDecision();
  const nav = useNavigate();
  // Push notifications deep-link straight at an item (/admin/review/:id).
  const { id: routeId } = useParams();
  const [picked, setPicked] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const selected = picked ?? routeId ?? null;

  function select(id: string) {
    setPicked(id);
    if (routeId && routeId !== id) nav('/admin');
  }

  function clearSelection() {
    setPicked(null);
    if (routeId) nav('/admin');
  }

  if (inbox.isLoading || chores.isLoading) return <Spinner />;
  const byId = new Map((chores.data ?? []).map((c) => [c.id, c]));
  const kidById = new Map((kids.data ?? []).map((k) => [k.id, k]));
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
      await decide.mutateAsync({
        id,
        body: { action: 'approve', reason: 'Approved by a parent.' },
      });
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
        {(openDisputes.data ?? []).length > 0 && (
          <div className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold text-rose-400">
              Kids say something is wrong ({openDisputes.data!.length})
            </h2>
            {openDisputes.data!.map((d) => (
              <Card key={d.id} className="cursor-pointer border-rose-800">
                <button className="w-full text-left" onClick={() => select(d.occurrence_id)}>
                  <p className="font-semibold">{d.chore_title ?? 'Chore'}</p>
                  <p className="text-sm text-slate-300">“{d.message}”</p>
                  <p className="text-xs text-slate-400">
                    {d.author_name ?? 'A kid'} · {new Date(d.created_at).toLocaleString()}
                  </p>
                </button>
              </Card>
            ))}
          </div>
        )}
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
              <button className="flex-1 text-left" onClick={() => select(o.id)}>
                <div className="flex items-baseline justify-between gap-2">
                  <p className="font-semibold">{byId.get(o.chore_id)?.title ?? 'Chore'}</p>
                  <StatusBadge status={o.status} className="shrink-0 text-xs" />
                </div>
                <p className="text-xs text-slate-400">
                  {o.assignee_id
                    ? (kidById.get(o.assignee_id)?.display_name ?? 'Unassigned')
                    : 'Unassigned'}{' '}
                  · due {new Date(o.due_at).toLocaleString()}
                  {occurrenceWorth(o) && ` · ${occurrenceWorth(o)}`}
                </p>
                {o.verification_error && (
                  <p className="text-xs text-amber-400">
                    the vision model couldn’t be reached — {o.verification_error}
                  </p>
                )}
              </button>
            </div>
          </Card>
        ))}
      </div>
      <div>
        {selected ? (
          <ReviewDetail id={selected} onDone={clearSelection} />
        ) : (
          <p className="text-slate-500">Select an item to review.</p>
        )}
      </div>
    </div>
  );
}
