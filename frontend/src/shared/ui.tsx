import type { ButtonHTMLAttributes, ReactNode } from 'react';

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-slate-400" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-slate-200" />
      {label}
    </div>
  );
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'danger';
};

export function Button({ variant = 'primary', className = '', ...rest }: BtnProps) {
  const base =
    'inline-flex min-h-[48px] items-center justify-center gap-2 rounded-xl px-5 text-base font-semibold transition disabled:opacity-40';
  const styles = {
    primary: 'bg-sky-500 text-white active:bg-sky-600',
    ghost: 'bg-slate-800 text-slate-100 active:bg-slate-700',
    danger: 'bg-rose-600 text-white active:bg-rose-700',
  }[variant];
  return <button className={`${base} ${styles} ${className}`} {...rest} />;
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl border border-slate-800 bg-slate-900 p-4 ${className}`}>
      {children}
    </div>
  );
}

/** Label + control wrapper. The <span> is the accessible name for the control inside, which
 *  is what makes getByLabelText work across the admin forms. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-slate-400">{label}</span>
      {children}
    </label>
  );
}

/** A collapsible group of rows.
 *
 * `title` arrives fully composed — "Missed (3)", "Standing (1 in force)" — because the
 * inbox's headings say different things and a rigid count prop would flatten them. It is
 * its own <span> so a test can still match the heading text exactly, with the chevron
 * hidden from the accessible name.
 */
export function Section({
  title,
  open,
  onToggle,
  tone = 'text-slate-400',
  children,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  /** Standing and Missed colour their headings; everything else is muted. */
  tone?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className={`mt-3 flex items-center gap-1.5 text-left text-sm font-semibold ${tone}`}
      >
        <span
          aria-hidden="true"
          className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`}
        >
          ›
        </span>
        <span>{title}</span>
      </button>
      {open && children}
    </div>
  );
}
