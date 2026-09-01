import { Field } from '../../../shared/ui';
import { GeofenceField } from '../../GeofenceField';
import { DEFAULT_FENCE, type Geofence } from '../../../shared/coords';
import { FENCED, PHOTO_PROOFS } from '../choreFields';
import type { ChoreFormApi } from '../useChoreForm';

export function ProofSection({ f }: { f: ChoreFormApi }) {
  const form = f.form;

  return (
    <>
      <Field label="Proof / verification">
        <div className="flex gap-2">
          <select
            className="inp"
            disabled={f.editing}
            value={String(form.proof_type)}
            onChange={(e) => f.setProofType(e.target.value)}
          >
            <option>photo</option>
            <option value="photo+location">photo+location</option>
            <option>location</option>
            <option>acknowledgement</option>
            <option>none</option>
          </select>
          <select
            className="inp"
            value={String(form.verification_mode)}
            onChange={(e) => f.set('verification_mode', e.target.value)}
          >
            <option>manual</option>
            {PHOTO_PROOFS.has(String(form.proof_type)) && (
              <>
                <option>llm_assist</option>
                <option>llm_auto</option>
              </>
            )}
            <option>auto_accept</option>
          </select>
        </div>
      </Field>

      {PHOTO_PROOFS.has(String(form.proof_type)) && (
        <div className="flex flex-col gap-2 rounded-xl border border-slate-800 p-3">
          <span className="text-sm font-semibold text-slate-300">What the kid sends</span>

          <Field label="How many photos">
            <input
              className="inp"
              type="number"
              min="1"
              max="6"
              value={Number(form.photo_count) || 1}
              onChange={(e) => f.setPhotoCount(Number(e.target.value))}
            />
          </Field>

          {Array.from({ length: Number(form.photo_count) || 1 }, (_, i) => (
            <Field key={i} label={`Photo ${i + 1} — what should it show?`}>
              <input
                className="inp"
                placeholder={i === 0 ? 'sink close-up' : 'wide kitchen'}
                value={((form.photo_prompts as string[]) ?? [])[i] ?? ''}
                onChange={(e) => f.setLabel(i, e.target.value)}
              />
            </Field>
          ))}
          <p className="text-xs text-slate-500">
            Labels name each shot for the kid and travel with the photo to the AI and the review
            pane. Two angles — a close-up and a wide shot — make staging a photo much harder. Leave
            them blank for unlabelled photos.
          </p>

          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={Boolean(form.allow_gallery_upload)}
              onChange={(e) => f.set('allow_gallery_upload', e.target.checked)}
            />
            Allow picking an existing photo
          </label>
          <p className="text-xs text-slate-500">
            Off means the in-app camera only. Anything picked from the gallery is flagged and always
            comes to you for review.
          </p>
        </div>
      )}

      {FENCED.has(String(form.proof_type)) && (
        <GeofenceField
          value={(form.geofence as Geofence | null) ?? DEFAULT_FENCE}
          onChange={(g) => f.set('geofence', g)}
        />
      )}
    </>
  );
}
