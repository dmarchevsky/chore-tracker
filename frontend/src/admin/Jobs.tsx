import { useJobsDashboard, useNotificationLog } from './api';
import { Card, Spinner } from '../shared/ui';

export function Jobs() {
  const d = useJobsDashboard();
  const pushes = useNotificationLog();
  if (d.isLoading) return <Spinner />;
  if (!d.data) return <p className="text-rose-400">Couldn’t load ops data.</p>;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-bold">Ops</h1>

      <Card>
        <p className="text-sm font-semibold">Scheduler</p>
        <p className={`text-sm ${d.data.scheduler.stale ? 'text-amber-400' : 'text-slate-400'}`}>
          {d.data.scheduler.last_tick_at
            ? `last tick ${new Date(d.data.scheduler.last_tick_at).toLocaleString()}`
            : 'has never ticked'}
          {d.data.scheduler.stale && ' — the worker looks stopped; chores are not being generated'}
        </p>
      </Card>

      <Card>
        <p className="text-sm font-semibold">Verification queue</p>
        <p className="text-sm text-slate-400">
          {Object.entries(d.data.queue)
            .map(([k, v]) => `${k}: ${v}`)
            .join(' · ') || 'empty'}
          {d.data.stuck_jobs > 0 && ` · ${d.data.stuck_jobs} stuck`}
        </p>
      </Card>

      {d.data.recent_failures.length > 0 && (
        <Card>
          <p className="text-sm font-semibold text-amber-400">Recent job failures</p>
          {d.data.recent_failures.map((f) => (
            <p key={f.id} className="text-xs text-slate-400">
              {f.occurrence_id} — {f.error}
            </p>
          ))}
        </Card>
      )}

      <Card>
        <p className="text-sm font-semibold">Recent notifications</p>
        {pushes.data?.length === 0 && <p className="text-sm text-slate-500">Nothing sent yet.</p>}
        {pushes.data?.map((n) => (
          <p key={n.created_at + n.kind} className="text-xs text-slate-400">
            <span className={n.status === 'sent' ? 'text-emerald-400' : 'text-amber-400'}>
              {n.status}
            </span>{' '}
            {new Date(n.created_at).toLocaleString()} — {n.kind}: {n.title}
            {n.error && <span className="text-rose-400"> — {n.error}</span>}
          </p>
        ))}
        {pushes.data?.some((n) => n.status === 'skipped') && (
          // The one status an operator can fix from here, and the one that looks like
          // silence rather than an error.
          <p className="mt-2 text-xs text-amber-400">
            `skipped` means the server has no VAPID keys — see docs/notifications.md.
          </p>
        )}
      </Card>

      <Card>
        <p className="text-sm font-semibold">Check-in automations</p>
        {d.data.checkins.length === 0 && <p className="text-sm text-slate-500">None set up.</p>}
        {d.data.checkins.map((c) => (
          <p key={c.child} className={`text-sm ${c.stale ? 'text-amber-400' : 'text-slate-400'}`}>
            {c.child}: {c.last_seen ? new Date(c.last_seen).toLocaleString() : 'never'}
            {c.stale && ' — check the automation'}
          </p>
        ))}
      </Card>
    </div>
  );
}
