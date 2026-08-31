import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../api/client';
import { useChore, useDispute, useDisputes, useOccurrence } from '../api/hooks';
import { Button, Card, Spinner } from '../shared/ui';
import { money } from '../shared/format';
import { Capture } from './Capture';
import { LocationCheckin } from './LocationCheckin';
import { enqueue } from '../pwa/offlineQueue';

interface KidVerdict {
  verdict: string;
  child_message: string | null;
  image_quality_issue: string | null;
  kind: string;
  created_by: string;
  created_at: string;
}

const ACTIONABLE = new Set(['open', 'needs_review', 'verified_fail']);
const CANNED: Record<string, string> = {
  verified_pass: 'Nice work — that one passed! ✅',
  approved: 'A parent approved this. ✅',
  submitted: 'Sent! A parent will check it soon.',
  needs_review: 'Sent to a parent to double-check.',
  rejected: 'Not quite — have a look and try again.',
  verified_fail: 'Not quite — have a look at the note and try again.',
  missed: 'This one was missed.',
  excused: 'A parent excused this one.',
};

export function ChoreView() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const occ = useOccurrence(id);
  const chore = useChore(occ.data?.chore_id);
  const verdicts = useQuery({
    enabled: !!id,
    queryKey: ['verdicts', id],
    queryFn: () => api.get<KidVerdict[]>(`/occurrences/${id}/verifications`),
    retry: false,
  });
  const sent = useQuery({
    enabled: !!id && !!occ.data && occ.data.status !== 'pending' && occ.data.status !== 'open',
    queryKey: ['submissions', id],
    queryFn: () =>
      api.get<{ id: string; media: { idx: number; url: string | null }[] }[]>(
        `/occurrences/${id}/submissions`,
      ),
    retry: false,
  });
  const disputes = useDisputes(id);
  const dispute = useDispute(id);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [showDispute, setShowDispute] = useState(false);
  const [disputeMsg, setDisputeMsg] = useState('');

  if (occ.isLoading || chore.isLoading) return <Spinner />;
  if (occ.error || !occ.data || !chore.data)
    return <p className="text-rose-400">Couldn’t load this chore.</p>;

  const o = occ.data;
  const c = chore.data;
  const latest = verdicts.data?.[0];
  const actionable = ACTIONABLE.has(o.status);
  const filed = disputes.data ?? [];
  const openDispute = filed.find((d) => d.status === 'open');
  const message = latest?.child_message || CANNED[o.status] || o.status;
  // A parent's own words, not the model's — say so, so the kid knows who to talk to.
  const fromParent = latest?.kind === 'manual' && !!latest.child_message;

  async function afterSubmit() {
    await qc.invalidateQueries({ queryKey: ['occurrence', id] });
    await qc.invalidateQueries({ queryKey: ['occurrences'] });
    await verdicts.refetch();
  }

  async function submitPhotos(files: Blob[], note: string, source: 'camera' | 'gallery') {
    setBusy(true);
    setFlash(null);
    const fd = new FormData();
    fd.set('note', note);
    fd.set('source', source);
    files.forEach((f, i) => fd.append('files', f, `photo-${i}.jpg`));
    try {
      await api.post(`/occurrences/${id}/submissions`, fd);
      setFlash('Sent! ✅');
      await afterSubmit();
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        setFlash(e.message);
      } else {
        await enqueue({ occurrenceId: id, note, source, files, geo: null });
        setFlash('Saved — it will send when you’re back online.');
      }
    } finally {
      setBusy(false);
      // Close either way: the outcome — sent, queued offline, or refused — is a flash
      // message on the chore screen, and the sheet would cover it.
      setCapturing(false);
    }
  }

  async function submitCheckin(geo: { lat: number; lon: number; accuracy: number }) {
    setBusy(true);
    setFlash(null);
    const fd = new FormData();
    fd.set('source', 'camera');
    fd.set('geo', JSON.stringify(geo));
    try {
      await api.post(`/occurrences/${id}/submissions`, fd);
      setFlash('Checked in! ✅');
      await afterSubmit();
    } catch (e) {
      setFlash(e instanceof ApiError ? e.message : 'Could not check in — try again.');
    } finally {
      setBusy(false);
    }
  }

  const isLocation = c.proof_type === 'location' || c.proof_type === 'photo+location';
  const isAck = c.proof_type === 'acknowledgement' || c.proof_type === 'none';
  const sentPhotos = sent.data?.[0]?.media ?? [];

  return (
    <div className="flex flex-col gap-4 pt-2">
      <button className="self-start text-sm text-slate-400" onClick={() => nav(-1)}>
        ← Back
      </button>
      <div>
        <h1 className="text-2xl font-bold">{c.title}</h1>
        <p className="text-slate-400">
          {money(o.reward_cents)} · due {new Date(o.due_at).toLocaleString()}
        </p>
        {c.description && <p className="mt-2 text-sm text-slate-300">{c.description}</p>}
      </div>

      <Card className={actionable ? 'border-sky-700' : ''}>
        {fromParent && <p className="text-xs font-semibold text-slate-400">From a parent</p>}
        <p className="text-base">{message}</p>
        {!actionable && o.status !== 'pending' && (
          <p className="mt-2 text-xs text-slate-500">A parent always has the final say.</p>
        )}
        {flash && <p className="mt-2 text-sm text-emerald-400">{flash}</p>}
      </Card>

      {sentPhotos.length > 0 && (
        <div>
          <p className="text-sm font-semibold text-slate-400">What you sent</p>
          <div className="mt-2 flex gap-2 overflow-x-auto">
            {sentPhotos.map((m) => (
              <img
                key={m.idx}
                src={m.url ?? ''}
                alt={`photo ${m.idx + 1}`}
                className="h-24 w-24 shrink-0 rounded-lg object-cover"
              />
            ))}
          </div>
        </div>
      )}

      {actionable &&
        (isAck ? (
          <Button disabled={busy} onClick={() => submitPhotos([], '', 'camera')}>
            Mark it done
          </Button>
        ) : isLocation ? (
          <LocationCheckin onSubmit={submitCheckin} busy={busy} />
        ) : (
          <Button disabled={busy} onClick={() => setCapturing(true)}>
            {Math.max(c.photo_count, c.photo_prompts.length) > 1
              ? 'Take the photos'
              : 'Take a photo'}
          </Button>
        ))}

      {capturing && (
        <Capture
          chore={c}
          promptToken={o.prompt_token}
          onSubmit={submitPhotos}
          onClose={() => setCapturing(false)}
          busy={busy}
        />
      )}

      {filed.map((d) => (
        <Card key={d.id}>
          <p className="text-sm font-semibold text-slate-300">You said: “{d.message}”</p>
          {d.status === 'open' ? (
            <p className="mt-1 text-sm text-amber-400">Waiting for a parent to look. ⏳</p>
          ) : (
            <p className="mt-1 text-sm text-emerald-400">A parent replied: “{d.resolution_note}”</p>
          )}
        </Card>
      ))}

      {!openDispute && !actionable && o.status !== 'verified_pass' && o.status !== 'approved' && (
        <button
          className="self-start text-sm text-slate-400 underline"
          onClick={() => setShowDispute((s) => !s)}
        >
          This isn’t right
        </button>
      )}
      {showDispute && (
        <Card>
          <textarea
            className="w-full rounded-xl bg-slate-800 p-3 text-sm"
            placeholder="Tell a parent what happened…"
            value={disputeMsg}
            onChange={(e) => setDisputeMsg(e.target.value)}
          />
          <Button
            className="mt-2 w-full"
            variant="ghost"
            disabled={!disputeMsg.trim() || dispute.isPending}
            onClick={() =>
              dispute.mutate(disputeMsg, {
                onSuccess: () => {
                  setShowDispute(false);
                  setDisputeMsg('');
                  setFlash('Sent to a parent.');
                },
              })
            }
          >
            Send to a parent
          </Button>
        </Card>
      )}
    </div>
  );
}
