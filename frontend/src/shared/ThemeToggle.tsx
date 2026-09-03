import { useTheme, type Theme } from './theme';

const OPTIONS: { value: Theme; label: string; glyph: string }[] = [
  { value: 'light', label: 'Day', glyph: '☀' },
  { value: 'dark', label: 'Night', glyph: '☾' },
  { value: 'auto', label: 'Match my device', glyph: 'A' },
];

/** Day / night / follow-the-device, in every shell header so it is one tap from anywhere. */
export function ThemeToggle({ className = '' }: { className?: string }) {
  const [theme, choose] = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className={`flex items-center gap-0.5 rounded-lg border border-slate-800 p-0.5 ${className}`}
    >
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={theme === o.value}
          aria-label={o.label}
          title={o.label}
          onClick={() => choose(o.value)}
          className={`h-7 w-7 rounded text-xs ${
            theme === o.value ? 'bg-slate-800 text-sky-400' : 'text-slate-500'
          }`}
        >
          <span aria-hidden>{o.glyph}</span>
        </button>
      ))}
    </div>
  );
}
