import { useState } from 'react';
import {
  useAdminOccurrence,
  useAdminSubmissions,
  useAdminVerifications,
  useDecision,
  useOccurrenceDisputes,
  useResolveDispute,
} from './api';
import type { AdminSubmission, AdminVerification } from './api';
import { Button, Card, Spinner } from '../shared/ui';
import { StatusBadge } from '../shared/StatusBadge';
import { flagLabel, statusLabel, verdictLabel } from '../shared/status';
import { money } from '../shared/format';
import type { Occurrence } from '../api/types';

/** Why this occurrence is sitting in the queue, in one sentence a parent can act on. */
function holdReason(
  o: Occurrence,
  sub: AdminSubmission | undefined,
  v: AdminVerification | undefined,
) {
  if (o.verification_error) return `The vision model couldn’t be reached — ${o.verification_error}`;
  if (sub?.flags?.length) return `Held for a look: ${sub.flags.map(flagLabel).join(' · ')}`;
  if (o.status === 'submitted') return 'Waiting on the AI check.';
  if (o.status === 'verified_fail') return 'The AI called this a miss — your call overrides it.';
  if (o.status === 'needs_review' && v?.verdict === 'needs_review')
    return v.confidence != null
      ? `The AI wasn’t confident enough to call it (${Math.round(v.confidence * 100)}%).`
      : 'The AI wasn’t confident enough to call it.';
  return null;
}

/** The stored LLM reasoning is a `#1:no(0.91)` digest, prefixed with the raw flag names
 *  when any fired. The flags are already spelled out above, so drop that prefix. */
function digest(reasoning: string | null): string {
  return (reasoning ?? '').replace(/^flags: [^;]*;\s*/, '');
}

function VerificationCard({ v, latest }: { v: AdminVerification; latest: boolean }) {
  const who = v.kind === 'manual' ? 'A parent' : 'The AI';
  return (
    <Card className={latest ? '' : 'opacity-70'}>
      <p className="text-sm font-semibold">
        {who} says: {verdictLabel(v.verdict)}
        {v.confidence != null && ` · ${Math.round(v.confidence * 100)}% confident`}
      </p>
      <p className="text-xs text-slate-500">{new Date(v.created_at).toLocaleString()}</p>

      {v.checks?.length ? (
        <ul className="mt-2 flex flex-col gap-1">
          {v.checks.map((c) => (
            <li key={c.id} className="text-sm text-slate-300">
              <span
                className={
                  c.answer === 'yes'
                    ? 'text-emerald-400'
                    : c.answer === 'no'
                      ? 'text-rose-400'
                      : 'text-amber-400'
                }
              >
                {c.answer}
              </span>{' '}
              — {c.evidence}
            </li>
          ))}
        </ul>
      ) : (
        v.kind === 'manual' &&
        v.reasoning && <p className="mt-1 text-sm text-slate-300">“{v.reasoning}”</p>
      )}

      {v.image_quality_issue && v.image_quality_issue !== 'none' && (
        <p className="mt-1 text-xs text-amber-400">image issue: {v.image_quality_issue}</p>
      )}
      {v.kind !== 'manual' && digest(v.reasoning) && (
        <p className="mt-2 text-xs text-slate-500">{digest(v.reasoning)}</p>
      )}
      {latest && v.kind !== 'manual' && (
        <a
          className="mt-1 inline-block text-xs text-sky-400 underline"
          href={`/api/v1/verifications/${v.id}`}
          target="_blank"
          rel="noreferrer"
        >
          raw model I/O
        </a>
      )}
    </Card>
  );
}

function DisputeCard({ id }: { id: string }) {
  const resolve = useResolveDispute();
  const [note, setNote] = useState('');
  const [noteError, setNoteError] = useState(false);

  return (
    <Card className="border-rose-800">
      <textarea
        className="w-full rounded-xl bg-slate-800 p-3 text-sm"
        placeholder="Reply — your kid will see this"
        value={note}
        onChange={(e) => {
          setNote(e.target.value);
          setNoteError(false);
        }}
      />
      {noteError && <p className="mt-1 text-sm text-rose-400">Write a reply first.</p>}
      <Button
        className="mt-2 min-h-0 px-3 py-2 text-sm"
        variant="ghost"
        disabled={resolve.isPending}
        onClick={() => {
          if (!note.trim()) return setNoteError(true);
          resolve.mutate({ id, note });
        }}
      >
        Reply &amp; close
      </Button>
      {resolve.isError && <p className="mt-2 text-sm text-rose-400">Couldn’t send that reply.</p>}
    </Card>
  );
}

export function ReviewDetail({ id, onDone }: { id: string; onDone: () => void }) {
  const occ = useAdminOccurrence(id);
  const subs = useAdminSubmissions(id);
  const vers = useAdminVerifications(id);
  const decide = useDecision();
  const disputes = useOccurrenceDisputes(id);
  const [reason, setReason] = useState('');
  const [reasonError, setReasonError] = useState(false);
  const [override, setOverride] = useState('');

  if (occ.isLoading) return <Spinner />;
  if (!occ.data) return <p className="text-rose-400">Not found.</p>;
  const o = occ.data;
  const verifications = vers.data ?? [];
  const latestVer = verifications[0];
  const latestSub = subs.data?.[0];
  const why = holdReason(o, latestSub, latestVer);
  const locked = o.settlement_locked_at != null;
  const decided = ['approved', 'rejected', 'excused'].includes(o.status);

  function act(action: 'approve' | 'reject' | 'excuse' | 'redo') {
    if (!reason.trim()) {
      setReasonError(true);
      return;
    }
    const amount = override.trim() ? Math.round(parseFloat(override) * 100) : null;
    decide.mutate(
      { id, body: { action, reason, amount_override_cents: amount } },
      { onSuccess: onDone },
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-bold">
          <StatusBadge status={o.status} /> · {money(o.reward_cents)}
        </h2>
        <p className="text-sm text-slate-400">
          due {new Date(o.due_at).toLocaleString()} · window{' '}
          {new Date(o.window_open_at).toLocaleString()}
        </p>
        {why && <p className="mt-1 text-sm text-amber-400">{why}</p>}
        {locked && (
          <p className="text-sm text-amber-400">settlement locked — decisions are frozen</p>
        )}
      </div>

      {(subs.data ?? []).map((s) => (
        <Card key={s.id}>
          <p className="text-xs text-slate-400">
            {new Date(s.created_at).toLocaleString()} ·{' '}
            {s.source === 'gallery'
              ? 'from the gallery'
              : s.source === 'camera'
                ? 'in-app camera'
                : s.source}
          </p>
          {s.note && <p className="mt-1 text-sm">“{s.note}”</p>}
          {s.flags.length > 0 && (
            <p className="mt-1 text-sm text-amber-400">{s.flags.map(flagLabel).join(' · ')}</p>
          )}
          {s.geo_distance_m != null && (
            <p className="mt-1 text-sm">
              {Math.round(s.geo_distance_m)} m from the fence ·{' '}
              {s.geo_within ? 'inside' : 'outside'}
            </p>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {s.media.map((m) => (
              <a key={m.id} href={m.url ?? '#'} target="_blank" rel="noreferrer">
                <img
                  src={m.url ?? ''}
                  alt={m.prompt_label ?? `photo ${m.idx}`}
                  className="h-40 w-40 rounded-lg object-cover"
                />
                <span className="text-xs text-slate-400">{m.prompt_label}</span>
              </a>
            ))}
          </div>
        </Card>
      ))}
      {(subs.data ?? []).length === 0 && <p className="text-sm text-slate-500">No submissions.</p>}

      {(disputes.data ?? []).map((d) => (
        <div key={d.id} className="flex flex-col gap-2">
          <Card className="border-rose-800">
            <p className="text-sm font-semibold text-rose-400">
              {d.status === 'open' ? 'Your kid says this isn’t right' : 'Answered'}
            </p>
            <p className="mt-1 text-sm">“{d.message}”</p>
            <p className="text-xs text-slate-500">
              {new Date(d.created_at).toLocaleString()}
              {d.status_at_filing && ` · filed when it was ${statusLabel(d.status_at_filing)}`}
            </p>
            {d.resolution_note && (
              <p className="mt-2 text-sm text-slate-300">You replied: “{d.resolution_note}”</p>
            )}
          </Card>
          {d.status === 'open' && <DisputeCard id={d.id} />}
        </div>
      ))}

      {verifications.map((v, i) => (
        <VerificationCard key={v.id} v={v} latest={i === 0} />
      ))}

      <Card>
        <textarea
          className="w-full rounded-xl bg-slate-800 p-3 text-sm"
          placeholder="Reason — your kid will see this"
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
            setReasonError(false);
          }}
        />
        {reasonError && <p className="mt-1 text-sm text-rose-400">Add a reason first.</p>}
        {decided && !locked && (
          <p className="mt-2 text-xs text-slate-500">
            Already {statusLabel(o.status).toLowerCase()}. Deciding again reverses the old ledger
            entry and writes a new one — nothing is edited in place.
          </p>
        )}
        <input
          className="mt-2 w-full rounded-xl bg-slate-800 p-2 text-sm"
          placeholder="Adjust amount ($, optional)"
          value={override}
          onChange={(e) => setOverride(e.target.value)}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            disabled={locked}
            onClick={() => act('approve')}
          >
            Approve
          </Button>
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="danger"
            disabled={locked}
            onClick={() => act('reject')}
          >
            Reject
          </Button>
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="ghost"
            disabled={locked}
            onClick={() => act('excuse')}
          >
            Excuse
          </Button>
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="ghost"
            disabled={locked}
            onClick={() => act('redo')}
          >
            Request redo
          </Button>
        </div>
        {decide.isError && (
          <p className="mt-2 text-sm text-rose-400">Couldn’t save that decision.</p>
        )}
      </Card>
    </div>
  );
}
