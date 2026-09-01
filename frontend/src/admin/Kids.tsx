import { useState } from 'react';
import {
  useChildren,
  useCheckinToken,
  useCreateChild,
  useDeactivateChild,
  useRotateCheckinToken,
  useUpdateChild,
} from './api';
import type { Child } from '../api/types';
import { Button, Card, Spinner } from '../shared/ui';

export function Kids() {
  const kids = useChildren();
  const create = useCreateChild();
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ username: '', display_name: '', email: '' });
  const [error, setError] = useState<string | null>(null);

  if (kids.isLoading) return <Spinner />;

  async function add() {
    setError(null);
    try {
      await create.mutateAsync(form);
      setForm({ username: '', display_name: '', email: '' });
      setAdding(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="flex max-w-2xl flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold">Kids</h1>
        <Button className="min-h-0 px-3 py-1 text-sm" onClick={() => setAdding((v) => !v)}>
          {adding ? 'Cancel' : 'Add kid'}
        </Button>
      </div>

      {adding && (
        <Card className="flex flex-col gap-2">
          <input
            className="inp"
            placeholder="username"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
          />
          <input
            className="inp"
            placeholder="display name"
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
          />
          <input
            className="inp"
            type="email"
            inputMode="email"
            placeholder="google address"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
          <p className="text-xs text-slate-500">
            Add this same address to the Cloudflare Access policy too — listing it here alone gets
            them turned away at the edge, before the app ever sees them.
          </p>
          {error && <p className="text-sm text-rose-400">{error}</p>}
          <Button
            className="min-h-0 self-start px-3 py-2 text-sm"
            onClick={add}
            disabled={create.isPending}
          >
            Create
          </Button>
        </Card>
      )}

      {(kids.data ?? []).map((k) => (
        <KidRow key={k.id} kid={k} />
      ))}
    </div>
  );
}

function KidRow({ kid }: { kid: Child }) {
  const update = useUpdateChild();
  const deactivate = useDeactivateChild();
  const rotate = useRotateCheckinToken();
  const token = useCheckinToken(kid.id);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(kid.display_name);
  const [error, setError] = useState<string | null>(null);

  function run(p: Promise<unknown>) {
    setError(null);
    p.catch((e) => setError((e as Error).message));
  }

  return (
    <Card className={kid.is_active ? '' : 'opacity-60'}>
      <button
        type="button"
        className="flex w-full items-center justify-between text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="font-semibold">
          {kid.display_name}{' '}
          <span className="text-xs text-slate-500">{kid.email ?? `@${kid.username}`}</span>
        </span>
        <span className={`text-xs ${kid.is_active ? 'text-emerald-400' : 'text-slate-500'}`}>
          {kid.is_active ? 'active' : 'inactive'}
        </span>
      </button>

      {open && (
        <div className="mt-3 flex flex-col gap-3 border-t border-slate-800 pt-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-slate-400">Display name</span>
            <div className="flex gap-2">
              <input className="inp" value={name} onChange={(e) => setName(e.target.value)} />
              <Button
                className="min-h-0 px-3 py-2 text-sm"
                variant="ghost"
                disabled={name === kid.display_name || update.isPending}
                onClick={() =>
                  run(update.mutateAsync({ id: kid.id, body: { display_name: name } }))
                }
              >
                Rename
              </Button>
            </div>
          </label>

          <div className="flex flex-wrap gap-2">
            {kid.is_active ? (
              <Button
                className="min-h-0 px-3 py-2 text-sm"
                variant="danger"
                disabled={deactivate.isPending}
                onClick={() => run(deactivate.mutateAsync(kid.id))}
              >
                Deactivate
              </Button>
            ) : (
              <Button
                className="min-h-0 px-3 py-2 text-sm"
                variant="ghost"
                disabled={update.isPending}
                onClick={() => run(update.mutateAsync({ id: kid.id, body: { is_active: true } }))}
              >
                Reactivate
              </Button>
            )}
            <Button
              className="min-h-0 px-3 py-2 text-sm"
              variant="ghost"
              disabled={update.isPending}
              onClick={() => {
                const next = window.prompt(
                  `Google address for ${kid.display_name}`,
                  kid.email ?? '',
                );
                if (next) run(update.mutateAsync({ id: kid.id, body: { email: next } }));
              }}
            >
              Change sign-in address
            </Button>
          </div>

          <div>
            <p className="text-slate-400">Check-in webhook</p>
            {token.data && (
              <code className="mt-1 block break-all rounded bg-slate-800 p-2 text-xs">
                {token.data.webhook_url}
              </code>
            )}
            <Button
              className="mt-2 min-h-0 px-3 py-2 text-xs"
              variant="ghost"
              disabled={rotate.isPending}
              onClick={() => run(rotate.mutateAsync(kid.id))}
            >
              Rotate token
            </Button>
          </div>

          {error && <p className="text-sm text-rose-400">{error}</p>}
        </div>
      )}
    </Card>
  );
}
