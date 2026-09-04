import { useEffect, useRef, type ReactNode } from 'react';
import { PHONE, useMediaQuery } from './useMediaQuery';
import { useBodyScrollLock } from './useBodyScrollLock';

type Props = {
  open: boolean;
  onClose: () => void;
  /** Names the dialog for assistive tech, e.g. "Review". */
  label: string;
  children: ReactNode;
};

/**
 * The right-hand pane of a list/detail screen, as-is from `md` up.
 *
 * On a phone the grid is one column, so that pane renders below the whole list — far past the
 * fold, which reads as the tap having done nothing. There it becomes a sheet over the list
 * instead, closed by its own button, Escape, or the back button.
 */
export function DetailSheet({ open, onClose, label, children }: Props) {
  const phone = useMediaQuery(PHONE);
  const sheet = phone && open;
  const panel = useRef<HTMLDivElement>(null);
  // The detail panes close themselves after a decision, so `onClose` is called from outside
  // this component too; hold it in a ref to keep the listeners below subscribed just once.
  const close = useRef(onClose);
  close.current = onClose;

  useBodyScrollLock(sheet);

  useEffect(() => {
    if (!sheet) return;
    panel.current?.focus();
    // Our own entry on the same URL: the router sees no navigation, and the back button
    // dismisses the sheet rather than leaving the screen.
    window.history.pushState({ chorekeeperSheet: true }, '', window.location.href);
    const onPop = () => close.current();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close.current();
    window.addEventListener('popstate', onPop);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('popstate', onPop);
      window.removeEventListener('keydown', onKey);
      // Closed by anything but the back button — drop the entry we pushed, unless a real
      // navigation has already stacked something on top of it.
      if (window.history.state?.chorekeeperSheet) window.history.back();
    };
  }, [sheet]);

  if (!sheet) return <>{children}</>;

  return (
    <div
      ref={panel}
      role="dialog"
      aria-modal="true"
      aria-label={label}
      tabIndex={-1}
      className="fixed inset-0 z-40 overflow-y-auto bg-slate-950 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
    >
      <button
        className="sticky top-0 z-10 -mx-4 mb-2 flex w-[calc(100%+2rem)] items-center gap-2 bg-slate-950 px-4 py-2 text-left text-sm font-medium text-slate-300"
        onClick={() => close.current()}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M15 5l-7 7 7 7"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        Back
      </button>
      {children}
    </div>
  );
}
