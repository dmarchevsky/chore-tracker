import { useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useInbox, useDecision, useMissed, useUpcoming } from './api';
import { useAdminChores, useChildren, useOpenDisputes } from './api';
import { ReviewDetail } from './ReviewDetail';
import { StandingDetail } from './StandingDetail';
import { PenaltyDetail } from './PenaltyDetail';
import { Button, Card, Spinner } from '../shared/ui';
import { StatusBadge } from '../shared/StatusBadge';
import { standingEntry, TONE_CLASS } from '../shared/status';
import { occurrenceWorth } from '../shared/outcome';
import { firstPerKey } from '../shared/occurrences';
import { tierOutcome } from '../shared/format';
import type { Occurrence } from '../api/types';

/** The right pane serves two kinds of thing now, so the selection has to say which.
 *  /admin/review/:id always means an occurrence — keeping the route the only untagged input
 *  is what stops the push deep-link breaking. */
type Selection = { kind: 'occurrence' | 'standing' | 'penalty'; id: string };

/** A miss sits at `missed` until someone decides it, and most never are — so the raw list only
 *  grows. These three bounds keep the section to what a parent might still act on today. */
const MISS_WINDOW_DAYS = 7;
const MISS_ROWS = 5;

/** One row per chore per kid: a daily chore otherwise repeats down both lists. */
const occKey = (o: Occurrence) => `${o.chore_id}:${o.assignee_id ?? ''}`;

/** Local midnight `days` back — a cutoff that does not drift as the session goes on. */
function midnightDaysAgo(days: number): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - days);
  return d;
}

/** One occurrence in the left rail. `onSelect` omitted leaves the row inert: the "Coming up"
 *  list is a forward view, and a chore whose window has not opened has nothing to review. */
function OccCard({
  o,
  title,
  kid,
  subtitle,
  selected,
  onSelect,
  muted,
  children,
}: {
  o: Occurrence;
  title: string;
  kid: string;
  subtitle: string;
  selected?: boolean;
  onSelect?: () => void;
  muted?: boolean;
  /** The bulk-approve checkbox — only the review queue passes one. */
  children?: ReactNode;
}) {
  const body = (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-semibold">{title}</p>
        <StatusBadge status={o.status} className="shrink-0 text-xs" />
      </div>
      <p className="text-xs text-slate-400">
        {kid} · {subtitle}
        {occurrenceWorth(o) && ` · ${occurrenceWorth(o)}`}
      </p>
      {o.verification_error && (
        <p className="text-xs text-amber-400">
          the vision model couldn’t be reached — {o.verification_error}
        </p>
      )}
    </>
  );
  return (
    <Card
      className={`${muted ? 'opacity-60' : ''} ${onSelect ? 'cursor-pointer' : ''} ${
        selected ? 'border-sky-600' : ''
      }`}
    >
      <div className="flex items-start gap-3">
        {children}
        {onSelect ? (
          <button className="flex-1 text-left" onClick={onSelect}>
            {body}
          </button>
        ) : (
          <div className="flex-1">{body}</div>
        )}
      </div>
    </Card>
  );
}

export function Inbox() {
  const inbox = useInbox();
  // A miss never enters the review queue, and nothing else on this screen looks ahead —
  // so the parent gets the same three-part picture the kid's Today screen gives.
  const missed = useMissed();
  const upcoming = useUpcoming();
  const chores = useAdminChores();
  const kids = useChildren();
  const openDisputes = useOpenDisputes();
  const decide = useDecision();
  const nav = useNavigate();
  // Push notifications deep-link straight at an item (/admin/review/:id).
  const { id: routeId } = useParams();
  const [picked, setPicked] = useState<Selection | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const selected: Selection | null =
    picked ?? (routeId ? { kind: 'occurrence', id: routeId } : null);

  function select(sel: Selection) {
    setPicked(sel);
    if (routeId && routeId !== sel.id) nav('/admin');
  }

  function clearSelection() {
    setPicked(null);
    if (routeId) nav('/admin');
  }

  if (inbox.isLoading || chores.isLoading || missed.isLoading || upcoming.isLoading)
    return <Spinner />;
  const byId = new Map((chores.data ?? []).map((c) => [c.id, c]));
  const kidById = new Map((kids.data ?? []).map((k) => [k.id, k]));
  const rows = inbox.data ?? [];
  const title = (o: Occurrence) => byId.get(o.chore_id)?.title ?? 'Chore';
  const kidName = (o: Occurrence) =>
    (o.assignee_id ? kidById.get(o.assignee_id)?.display_name : null) ?? 'Unassigned';
  // Newest first from the query, so: drop the stale ones, keep the newest miss per chore and
  // kid, then cap. Anything dropped is counted into the History link below the section.
  const allMissed = missed.data ?? [];
  const cutoff = midnightDaysAgo(MISS_WINDOW_DAYS);
  const recentMissed = allMissed.filter((o) => new Date(o.due_at) >= cutoff);
  const sameKey = new Map<string, number>();
  recentMissed.forEach((o) => sameKey.set(occKey(o), (sameKey.get(occKey(o)) ?? 0) + 1));
  const misses = recentMissed.filter(firstPerKey(occKey)).slice(0, MISS_ROWS);
  // The query asks for 200, so a pathological backlog under-counts — the link goes to the
  // full list either way.
  const hiddenMisses = allMissed.length - misses.length;
  // A daily chore materialises a row per day across the horizon, per kid; the parent only
  // needs to know whose turn is next on each chore.
  const soon = (upcoming.data ?? []).filter(firstPerKey(occKey));
  // include_inactive=true on the underlying query, and set_state does not check active — so a
  // retired grounding would otherwise offer a live flip button.
  const standing = (chores.data ?? [])
    .filter((c) => c.chore_kind === 'standing' && c.active)
    .sort(
      (a, b) =>
        Number(b.standing_on) - Number(a.standing_on) ||
        (b.standing_since ?? '').localeCompare(a.standing_since ?? '') ||
        a.title.localeCompare(b.title),
    );
  const inForce = standing.filter((c) => c.standing_on).length;
  // Deactivated rules are filtered out for the same reason standing ones are: the underlying
  // query passes include_inactive=true, and a rule that can't be charged (services/penalties.py
  // 409s) has no business offering a Charge button.
  const penalties = (chores.data ?? [])
    .filter((c) => c.chore_kind === 'penalty' && c.active)
    .sort((a, b) => a.title.localeCompare(b.title));

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
                <button
                  className="w-full text-left"
                  onClick={() => select({ kind: 'occurrence', id: d.occurrence_id })}
                >
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
        {standing.length > 0 && (
          <div className="flex flex-col gap-2">
            <h2 className={`text-sm font-semibold ${inForce ? 'text-rose-400' : 'text-slate-400'}`}>
              Standing{inForce > 0 && ` (${inForce} in force)`}
            </h2>
            {standing.map((c) => {
              const state = standingEntry(c.standing_on);
              const tier = (c.outcome_tiers ?? []).find((t) => t.id === c.standing_tier_id);
              return (
                <Card
                  key={c.id}
                  className={`cursor-pointer ${c.standing_on ? 'border-rose-800' : ''} ${
                    selected?.kind === 'standing' && selected.id === c.id ? 'border-sky-600' : ''
                  }`}
                >
                  <button
                    className="w-full text-left"
                    onClick={() => select({ kind: 'standing', id: c.id })}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="font-semibold">{c.title}</p>
                      <span className={`shrink-0 text-xs font-semibold ${TONE_CLASS[state.tone]}`}>
                        {state.label}
                      </span>
                    </div>
                    {c.standing_on && tier && <p className="text-sm text-rose-300">{tier.text}</p>}
                    <p className="text-xs text-slate-400">
                      {c.assignment_mode === 'fixed'
                        ? (kidById.get(c.fixed_assignee_id ?? '')?.display_name ?? 'Unassigned')
                        : 'Everyone'}
                      {c.standing_on && c.standing_since
                        ? ` · since ${new Date(c.standing_since).toLocaleDateString()}`
                        : ' · off'}
                    </p>
                  </button>
                </Card>
              );
            })}
          </div>
        )}
        {penalties.length > 0 && (
          <div className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold text-slate-400">Penalties</h2>
            {penalties.map((c) => (
              <Card
                key={c.id}
                className={
                  selected?.kind === 'penalty' && selected.id === c.id ? 'border-sky-600' : ''
                }
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold">{c.title}</p>
                    <p className="text-xs text-slate-400">
                      {c.assignment_mode === 'fixed'
                        ? (kidById.get(c.fixed_assignee_id ?? '')?.display_name ?? 'Unassigned')
                        : 'Everyone'}
                    </p>
                    <p className="text-xs text-slate-500">
                      {(c.outcome_tiers ?? [])
                        .map((t) => `${t.condition} ${tierOutcome(t)}`)
                        .join(' · ')}
                    </p>
                  </div>
                  <Button
                    className="min-h-0 shrink-0 px-3 py-1 text-sm"
                    variant="danger"
                    onClick={() => select({ kind: 'penalty', id: c.id })}
                  >
                    Charge
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}
        {rows.length === 0 && <p className="text-slate-500">Nothing waiting. 🎉</p>}
        {rows.map((o) => (
          <OccCard
            key={o.id}
            o={o}
            title={title(o)}
            kid={kidName(o)}
            subtitle={`due ${new Date(o.due_at).toLocaleString()}`}
            selected={selected?.kind === 'occurrence' && selected.id === o.id}
            onSelect={() => select({ kind: 'occurrence', id: o.id })}
          >
            <input
              type="checkbox"
              className="mt-1"
              checked={checked.has(o.id)}
              onChange={() => toggle(o.id)}
              onClick={(e) => e.stopPropagation()}
            />
          </OccCard>
        ))}

        {misses.length > 0 && (
          <div className="flex flex-col gap-2">
            {/* A miss is settled money the parent can still excuse (spec §4.2), and it never
                reaches the review queue — this is the only place it surfaces unprompted. */}
            <h2 className="mt-4 text-sm font-semibold text-rose-400">Missed ({misses.length})</h2>
            {misses.map((o) => {
              const also = (sameKey.get(occKey(o)) ?? 1) - 1;
              return (
                <OccCard
                  key={o.id}
                  o={o}
                  title={title(o)}
                  kid={kidName(o)}
                  subtitle={`was due ${new Date(o.due_at).toLocaleString()}${
                    also > 0 ? ` · ${also} more like this` : ''
                  }`}
                  selected={selected?.kind === 'occurrence' && selected.id === o.id}
                  onSelect={() => select({ kind: 'occurrence', id: o.id })}
                />
              );
            })}
            {hiddenMisses > 0 && (
              <Link to="/admin/history?status=missed" className="text-xs text-slate-400 underline">
                {hiddenMisses} more in History
              </Link>
            )}
          </div>
        )}

        {soon.length > 0 && (
          <div className="flex flex-col gap-2">
            <h2 className="mt-4 text-sm font-semibold text-slate-400">Coming up</h2>
            {soon.map((o) => (
              <OccCard
                key={o.id}
                o={o}
                title={title(o)}
                kid={kidName(o)}
                subtitle={`opens ${new Date(o.window_open_at).toLocaleString()} · due ${new Date(
                  o.due_at,
                ).toLocaleString()}`}
                muted
              />
            ))}
          </div>
        )}
      </div>
      <div>
        {selected?.kind === 'standing' ? (
          <StandingDetail id={selected.id} onDone={clearSelection} />
        ) : selected?.kind === 'penalty' ? (
          <PenaltyDetail id={selected.id} onDone={clearSelection} />
        ) : selected ? (
          <ReviewDetail id={selected.id} onDone={clearSelection} />
        ) : (
          <p className="text-slate-500">Select something to review.</p>
        )}
      </div>
    </div>
  );
}
