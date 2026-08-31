import { TONE_CLASS, statusEntry } from './status';

export function StatusBadge({
  status,
  role = 'admin',
  className = '',
}: {
  status: string;
  role?: 'admin' | 'kid';
  className?: string;
}) {
  const entry = statusEntry(status, role);
  return (
    <span className={`font-semibold ${TONE_CLASS[entry.tone]} ${className}`}>{entry.label}</span>
  );
}
