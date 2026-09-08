import type { Child } from '../api/types';

type Props = {
  kids: Child[];
  /** Selected child id; `''` is the "Everyone" pill when `allowAll`. */
  value: string;
  onChange: (id: string) => void;
  /** Prepend an "Everyone" pill bound to `''` — for a filter rather than a view scope. */
  allowAll?: boolean;
  /** Names the group for assistive tech. */
  label?: string;
};

/**
 * "Whose data am I looking at" as a row of pills instead of a `<select>`.
 *
 * The household has a handful of kids, so a dropdown hides one tap behind two; the pills
 * match the status filter beside them on History. Maps over the real list — no fixed count.
 */
export function KidTabs({ kids, value, onChange, allowAll = false, label = 'Kid' }: Props) {
  const opts: { id: string; display_name: string }[] = [
    ...(allowAll ? [{ id: '', display_name: 'Everyone' }] : []),
    ...kids.map((k) => ({ id: k.id, display_name: k.display_name })),
  ];

  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {opts.map((k) => (
        <button
          key={k.id || 'all'}
          type="button"
          aria-pressed={value === k.id}
          onClick={() => onChange(k.id)}
          className={`rounded-full border px-3 py-1 text-sm ${
            value === k.id ? 'border-sky-600 text-sky-300' : 'border-slate-700 text-slate-500'
          }`}
        >
          {k.display_name}
        </button>
      ))}
    </div>
  );
}
