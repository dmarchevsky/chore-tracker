import { useState } from 'react';
import { useAdminOccurrence, useAdminSubmissions, useAdminVerifications, useDecision } from './api';
import { Button, Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';

export function ReviewDetail({ id, onDone }: { id: string; onDone: () => void }) {
  const occ = useAdminOccurrence(id);
  const subs = useAdminSubmissions(id);
  const vers = useAdminVerifications(id);
  const decide = useDecision();
  const [reason, setReason] = useState('');
  const [override, setOverride] = useState('');

  if (occ.isLoading) return <Spinner />;
  if (!occ.data) return <p className="text-rose-400">Not found.</p>;
  const o = occ.data;
  const latestVer = vers.data?.[0];

  function act(action: 'approve' | 'reject' | 'excuse' | 'redo') {
    if (!reason.trim()) {
      setReason('(reason required)');
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
          {o.status} · {money(o.reward_cents)}
        </h2>
        <p className="text-sm text-slate-400">
          due {new Date(o.due_at).toLocaleString()} · window{' '}
          {new Date(o.window_open_at).toLocaleString()}
          {o.prompt_token && ` · token ${o.prompt_token}`}
        </p>
        {o.settlement_locked_at && (
          <p className="text-sm text-amber-400">settlement locked — decisions are frozen</p>
        )}
      </div>

      {(subs.data ?? []).map((s) => (
        <Card key={s.id}>
          <p className="text-xs text-slate-400">
            {new Date(s.created_at).toLocaleString()} · {s.source} · {s.kind}
          </p>
          {s.note && <p className="mt-1 text-sm">“{s.note}”</p>}
          {s.flags.length > 0 && (
            <p className="mt-1 text-sm text-amber-400">flags: {s.flags.join(', ')}</p>
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

      {latestVer && (
        <Card>
          <p className="text-sm font-semibold">
            model verdict: {latestVer.verdict}
            {latestVer.confidence != null && ` (conf ${latestVer.confidence.toFixed(2)})`}
          </p>
          {latestVer.reasoning && (
            <p className="mt-1 text-sm text-slate-300">{latestVer.reasoning}</p>
          )}
          {latestVer.checks?.map((c) => (
            <p key={c.id} className="text-xs text-slate-400">
              #{c.id} {c.answer} ({c.confidence.toFixed(2)}) — {c.evidence}
            </p>
          ))}
          {latestVer.image_quality_issue && (
            <p className="text-xs text-amber-400">image issue: {latestVer.image_quality_issue}</p>
          )}
          <a
            className="mt-1 inline-block text-xs text-sky-400 underline"
            href={`/api/v1/verifications/${latestVer.id}`}
            target="_blank"
            rel="noreferrer"
          >
            raw model I/O
          </a>
        </Card>
      )}

      <Card>
        <textarea
          className="w-full rounded-xl bg-slate-800 p-3 text-sm"
          placeholder="Reason (required, kept on the record)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <input
          className="mt-2 w-full rounded-xl bg-slate-800 p-2 text-sm"
          placeholder="Adjust amount ($, optional)"
          value={override}
          onChange={(e) => setOverride(e.target.value)}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <Button className="min-h-0 px-3 py-2 text-sm" onClick={() => act('approve')}>
            Approve
          </Button>
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="danger"
            onClick={() => act('reject')}
          >
            Reject
          </Button>
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="ghost"
            onClick={() => act('excuse')}
          >
            Excuse
          </Button>
          <Button className="min-h-0 px-3 py-2 text-sm" variant="ghost" onClick={() => act('redo')}>
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
