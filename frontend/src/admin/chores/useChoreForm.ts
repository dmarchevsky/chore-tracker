// All chore-form state and its cross-field normalisers. Deliberately one
// Record<string, unknown> rather than per-section state: setProofType and body() have to
// see the whole definition to keep it consistent, and splitting the state would break them.

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { Chore } from '../../api/types';
import { useDeactivateChore, useUpdateChore } from '../api';
import {
  BLANK,
  EDITABLE,
  FENCED,
  isTiered,
  LLM_MODES,
  PHOTO_PROOFS,
  type PreviewItem,
} from './choreFields';

export type FormState = { mode: 'create' } | { mode: 'edit'; chore: Chore };

export type ChoreFormApi = ReturnType<typeof useChoreForm>;

export function useChoreForm(state: FormState, onDone: () => void) {
  const qc = useQueryClient();
  const update = useUpdateChore();
  const deactivate = useDeactivateChore();
  const chore = state.mode === 'edit' ? state.chore : null;
  const editing = chore !== null;

  const [form, setForm] = useState<Record<string, unknown>>(
    chore ? { ...(chore as unknown as Record<string, unknown>) } : { ...BLANK },
  );
  const [preview, setPreview] = useState<PreviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function set(k: string, v: unknown) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  /** photo_prompts is either empty or exactly photo_count long — the backend rejects
   *  anything else, and the kid's capture screen builds its slots from the labels. */
  function setPhotoCount(n: number) {
    const count = Math.min(Math.max(n || 1, 1), 6);
    setForm((f) => {
      const labels = (f.photo_prompts as string[]) ?? [];
      const next = labels.length
        ? Array.from({ length: count }, (_, i) => labels[i] ?? '')
        : labels;
      return { ...f, photo_count: count, photo_prompts: next };
    });
  }

  function setLabel(idx: number, text: string) {
    setForm((f) => {
      const count = Number(f.photo_count) || 1;
      const labels = Array.from(
        { length: count },
        (_, i) => ((f.photo_prompts as string[]) ?? [])[i] ?? '',
      );
      labels[idx] = text;
      // All blank means "no labels" — send [] rather than a row of empty strings.
      return { ...f, photo_prompts: labels.some((x) => x.trim()) ? labels : [] };
    });
  }

  /** An LLM mode needs an image to look at, so it can't survive a switch to a proof type
   *  that sends none — the select would otherwise show a value it no longer offers. */
  function setProofType(proof: string) {
    setForm((f) => {
      const next: Record<string, unknown> = { ...f, proof_type: proof };
      if (!PHOTO_PROOFS.has(proof) && LLM_MODES.has(String(next.verification_mode)))
        next.verification_mode = 'manual';
      return next;
    });
  }

  /** A standing chore's schedule/proof/money fields are meaningless and the backend rejects
   *  them, so switching kind resets them to what the standing branch expects. */
  function setChoreKind(kind: string) {
    setForm((f) =>
      kind === 'standing'
        ? {
            ...f,
            chore_kind: kind,
            cadence: 'standing',
            due_time: '00:00:00',
            proof_type: 'none',
            verification_mode: 'manual',
            geofence: null,
            end_date: null,
            reward_cents: 0,
            penalty_cents: 0,
            assignment_mode: f.assignment_mode === 'all' ? 'all' : 'fixed',
          }
        : { ...f, chore_kind: kind, cadence: 'daily', due_time: '08:00:00', proof_type: 'photo' },
    );
  }

  function setAssignmentMode(mode: string) {
    setForm((f) => {
      const next: Record<string, unknown> = { ...f, assignment_mode: mode };
      if (mode === 'rotating') {
        if (!next.rotation_period) next.rotation_period = 'weekly';
        if (!next.rotation_anchor_date)
          next.rotation_anchor_date = new Date().toISOString().slice(0, 10);
      }
      return next;
    });
  }

  async function doPreview() {
    setError(null);
    try {
      setPreview(await api.post<PreviewItem[]>('/chores/preview?count=8', form));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  // Only send the assignee fields that matter for the chosen mode.
  function assignmentBody(src: Record<string, unknown>): Record<string, unknown> {
    const mode = src.assignment_mode;
    const out = { ...src };
    out.fixed_assignee_id = mode === 'fixed' ? src.fixed_assignee_id || null : null;
    if (mode !== 'rotating' && mode !== 'all') out.assignee_ids = [];
    if (mode !== 'rotating') {
      out.rotation_period = null;
      out.rotation_anchor_date = null;
    }
    return out;
  }

  /** proof_type is immutable, so it is not in the PATCH allowlist — take it from the
   *  form. A chore that doesn't check location must not carry a stale fence. */
  function body(src: Record<string, unknown>): Record<string, unknown> {
    const out = assignmentBody(src);
    if (!FENCED.has(String(form.proof_type))) out.geofence = null;
    if (!PHOTO_PROOFS.has(String(form.proof_type))) {
      out.photo_prompts = [];
      out.allow_gallery_upload = false;
      // Nothing reads a rule or a checklist without a photo to look at, and the form hides
      // both — so don't carry stale text over from a proof_type the parent switched away
      // from. Same for the mode: only manual / auto_accept are reachable here.
      out.verification_rule = null;
      out.verification_checklist = null;
      if (LLM_MODES.has(String(out.verification_mode))) out.verification_mode = 'manual';
    }
    if (isTiered(form)) {
      // A tier is chosen by a person, and its money is the tier's — the backend rejects
      // an LLM mode, a rule/checklist, or a non-zero reward on a tiered chore.
      out.verification_mode = 'manual';
      out.verification_rule = null;
      out.verification_checklist = null;
      out.reward_cents = 0;
      out.penalty_cents = 0;
      out.late_multiplier = 1;
    }
    return out;
  }

  async function save() {
    setError(null);
    try {
      if (editing) {
        const patch: Record<string, unknown> = {};
        for (const k of EDITABLE) patch[k] = form[k];
        await update.mutateAsync({ id: chore!.id, body: body(patch) });
      } else {
        await api.post('/chores', body(form));
        await qc.invalidateQueries({ queryKey: ['chores', 'all'] });
      }
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove() {
    setError(null);
    try {
      await deactivate.mutateAsync(chore!.id);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function reactivate() {
    set('active', true);
    void update
      .mutateAsync({ id: chore!.id, body: { active: true } })
      .then(onDone)
      .catch((e) => setError((e as Error).message));
  }

  return {
    chore,
    editing,
    form,
    set,
    setPhotoCount,
    setLabel,
    setProofType,
    setChoreKind,
    setAssignmentMode,
    preview,
    error,
    setError,
    doPreview,
    save,
    remove,
    reactivate,
    update,
    deactivate,
    onDone,
  };
}
