import { useMemo, useState } from 'react';
import { useAdminChores, useChildren, useHistory } from './api';
import type { HistoryQuery } from './api';
import { ReviewDetail } from './ReviewDetail';
import { Button, Card, Spinner } from '../shared/ui';
import { StatusBadge } from '../shared/StatusBadge';
import { ADMIN_STATUS } from '../shared/status';
import { money } from '../shared/format';

const DECIDED = [
  'approved',
  'rejected',
  'excused',
  'missed',
  'verified_pass',
  'verified_fail',
] as const;
const PAGE = 50;

function daysAgo(n: number): string {
  return new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);
}

export function History() {
  const kids = useChildren();
  const chores = useAdminChores();
  const [child, setChild] = useState('');
  const [chore, setChore] = useState('');
  const [statuses, setStatuses] = useState<string[]>([...DECIDED]);
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState('');
  const [pages, setPages] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);

  // One query per "load more" press; `pages` widens the window rather than paging away
  // from what the parent is already looking at.
  const query: HistoryQuery = useMemo(
    () => ({
      child: child || undefined,
      chore: chore || undefined,
      statuses,
      from: from ? new Date(from).toISOString() : undefined,
      to: to ? new Date(to).toISOString() : undefined,
      limit: PAGE * pages,
      offset: 0,
    }),
    [child, chore, statuses, from, to, pages],
  );
  const history = useHistory(query);

  const choreById = new Map((chores.data ?? []).map((c) => [c.id, c]));
  const kidById = new Map((kids.data ?? []).map((k) => [k.id, k]));
  const rows = history.data?.items ?? [];
  const total = history.data?.total ?? 0;

  function reset<T>(set: (v: T) => void) {
    return (v: T) => {
      set(v);
      setPages(1);
    };
  }

  function toggleStatus(s: string) {
    setPages(1);
    setStatuses((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  }

  const select = 'rounded-lg bg-slate-800 p-2 text-sm';

  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,420px)_1fr]">
      <div className="flex flex-col gap-3">
        <h1 className="text-lg font-bold">History</h1>

        <div className="flex flex-wrap gap-2">
          <select
            className={select}
            value={child}
            onChange={(e) => reset(setChild)(e.target.value)}
            aria-label="Kid"
          >
            <option value="">Everyone</option>
            {(kids.data ?? []).map((k) => (
              <option key={k.id} value={k.id}>
                {k.display_name}
              </option>
            ))}
          </select>
          <select
            className={select}
            value={chore}
            onChange={(e) => reset(setChore)(e.target.value)}
            aria-label="Chore"
          >
            <option value="">All chores</option>
            {(chores.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
          <input
            type="date"
            className={select}
            value={from}
            onChange={(e) => reset(setFrom)(e.target.value)}
            aria-label="From"
          />
          <input
            type="date"
            className={select}
            value={to}
            onChange={(e) => reset(setTo)(e.target.value)}
            aria-label="To"
          />
        </div>

        <div className="flex flex-wrap gap-1">
          {DECIDED.map((s) => (
            <button
              key={s}
              onClick={() => toggleStatus(s)}
              className={`rounded-full border px-3 py-1 text-xs ${
                statuses.includes(s)
                  ? 'border-sky-600 text-sky-300'
                  : 'border-slate-700 text-slate-500'
              }`}
            >
              {ADMIN_STATUS[s].label}
            </button>
          ))}
        </div>

        {history.isLoading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <p className="text-slate-500">Nothing matches those filters.</p>
        ) : (
          rows.map((o) => (
            <Card
              key={o.id}
              className={`cursor-pointer ${selected === o.id ? 'border-sky-600' : ''}`}
            >
              <button className="w-full text-left" onClick={() => setSelected(o.id)}>
                <div className="flex items-baseline justify-between gap-2">
                  <p className="font-semibold">{choreById.get(o.chore_id)?.title ?? 'Chore'}</p>
                  <StatusBadge status={o.status} className="shrink-0 text-xs" />
                </div>
                <p className="text-xs text-slate-400">
                  {o.assignee_id ? (kidById.get(o.assignee_id)?.display_name ?? '—') : 'Unassigned'}{' '}
                  · {new Date(o.due_at).toLocaleDateString()} · {money(o.reward_cents)}
                  {o.settlement_locked_at && ' · paid out'}
                </p>
              </button>
            </Card>
          ))
        )}

        {rows.length < total && (
          <Button
            className="min-h-0 py-2 text-sm"
            variant="ghost"
            onClick={() => setPages((p) => p + 1)}
          >
            Load more ({rows.length} of {total})
          </Button>
        )}
      </div>
      <div>
        {selected ? (
          <ReviewDetail id={selected} onDone={() => setSelected(null)} />
        ) : (
          <p className="text-slate-500">Pick an item to look at it again.</p>
        )}
      </div>
    </div>
  );
}
