import { useEffect, useState } from 'react';
import { formatDuration, parseDuration } from './schedule';

/** A duration box that takes `2h30m`, `90m`, `12h`, or a bare number of hours.
 *
 * The text is held locally rather than derived from `value` on every render, because
 * "2h3" has to survive the keystroke between "2h" and "2h30m" — and because a value the
 * parser rejects must not reach the form at all. `value` only re-seeds the box when it
 * changes from the outside: loading a chore for edit, or switching chore_kind.
 */
export function DurationInput({
  value,
  onChange,
  max,
  id,
}: {
  value: number;
  onChange: (seconds: number) => void;
  /** Upper bound in seconds — the backend's, so a 422 is caught here instead (spec §4.1). */
  max: number;
  id?: string;
}) {
  const [text, setText] = useState(() => formatDuration(value));
  const [seeded, setSeeded] = useState(value);

  useEffect(() => {
    if (value !== seeded) {
      setText(formatDuration(value));
      setSeeded(value);
    }
  }, [value, seeded]);

  const parsed = parseDuration(text);
  const bad = text.trim() !== '' && (parsed === null || parsed > max);

  return (
    <>
      <input
        id={id}
        className="inp"
        type="text"
        inputMode="text"
        placeholder="2h30m"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          const secs = parseDuration(e.target.value);
          if (secs !== null && secs <= max) {
            setSeeded(secs);
            onChange(secs);
          }
        }}
      />
      {bad && (
        <p className="mt-1 text-xs text-rose-400">
          {parsed === null
            ? 'Try 2h30m, 90m or 12h.'
            : `That is longer than the ${formatDuration(max)} limit.`}
        </p>
      )}
    </>
  );
}
