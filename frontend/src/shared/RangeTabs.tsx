import type { RangeDays } from './dates';

const PRESETS: { days: RangeDays; label: string }[] = [
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: null, label: 'All' },
];

/**
 * "How far back am I looking" as pills, with two date inputs for anything they don't cover.
 *
 * Matches the KidTabs pills it sits beside rather than introducing a third filter idiom;
 * typing a date takes over from the pills, because a hand-picked window and a preset are
 * answers to the same question and only one of them can be in force.
 */
export function RangeTabs({
  days,
  from,
  to,
  onChange,
  label = 'Date range',
}: {
  days: RangeDays;
  from: string;
  to: string;
  onChange: (next: { days: RangeDays; from: string; to: string }) => void;
  label?: string;
}) {
  const custom = !!(from || to);

  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1">
      {PRESETS.map((p) => (
        <button
          key={p.label}
          type="button"
          aria-pressed={!custom && days === p.days}
          onClick={() => onChange({ days: p.days, from: '', to: '' })}
          className={`rounded-full border px-3 py-1 text-sm ${
            !custom && days === p.days
              ? 'border-sky-600 text-sky-300'
              : 'border-slate-700 text-slate-500'
          }`}
        >
          {p.label}
        </button>
      ))}
      <input
        type="date"
        aria-label="From"
        className="rounded-lg bg-slate-800 p-2 text-sm"
        value={from}
        onChange={(e) => onChange({ days, from: e.target.value, to })}
      />
      <input
        type="date"
        aria-label="To"
        className="rounded-lg bg-slate-800 p-2 text-sm"
        value={to}
        onChange={(e) => onChange({ days, from, to: e.target.value })}
      />
    </div>
  );
}
