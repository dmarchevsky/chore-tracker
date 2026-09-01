import { Field } from '../../../shared/ui';
import { isTiered, LLM_MODES } from '../choreFields';
import { TierField } from '../TierField';
import type { OutcomeTier } from '../../../api/types';
import type { ChoreFormApi } from '../useChoreForm';

export function WorthSection({ f }: { f: ChoreFormApi }) {
  const form = f.form;

  const tiered = isTiered(form);

  return (
    <>
      <TierField
        value={(form.outcome_tiers as OutcomeTier[] | null) ?? null}
        onChange={(v) => f.set('outcome_tiers', v)}
      />

      {!tiered && (
        <Field label="Reward / penalty ($)">
          <div className="flex gap-2">
            <input
              className="inp"
              type="number"
              value={Number(form.reward_cents) / 100}
              onChange={(e) =>
                f.set('reward_cents', Math.round(parseFloat(e.target.value || '0') * 100))
              }
            />
            <input
              className="inp"
              type="number"
              value={Number(form.penalty_cents) / 100}
              onChange={(e) =>
                f.set('penalty_cents', Math.round(parseFloat(e.target.value || '0') * 100))
              }
            />
          </div>
        </Field>
      )}

      {!tiered && LLM_MODES.has(String(form.verification_mode)) && (
        <Field label="Auto pass / fail confidence">
          <div className="flex gap-2">
            <input
              className="inp"
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={Number(form.auto_pass_threshold)}
              onChange={(e) => f.set('auto_pass_threshold', parseFloat(e.target.value || '0'))}
            />
            <input
              className="inp"
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={Number(form.auto_fail_threshold)}
              onChange={(e) => f.set('auto_fail_threshold', parseFloat(e.target.value || '0'))}
            />
          </div>
        </Field>
      )}
    </>
  );
}
