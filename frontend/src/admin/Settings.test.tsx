import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../auth/AuthContext';
import { Settings } from './Settings';

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

const SETTINGS = {
  llm: {
    base_url: 'http://box:9000/v1',
    model: '',
    api_key_set: false,
    timeout_s: 120,
    max_retries: 1,
  },
  verification: { auto_pass_threshold: 0.85, auto_fail_threshold: 0.35 },
  source: { llm_base_url: 'db', llm_model: 'env' },
};

const ME = {
  id: 'a1',
  username: 'parent',
  display_name: 'Parent',
  email: 'parent@example.com',
  role: 'admin',
  csrf_token: 'x',
};

function setup() {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method !== 'GET')
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });

    if (url.includes('/admin/break-glass-password'))
      return Promise.resolve(new Response(null, { status: 204 }));
    if (url.includes('/admin/import')) {
      const body = JSON.parse(String(init?.body)) as { dry_run?: boolean };
      return Promise.resolve(
        json({
          counts: { users: 2, chores: 3, chore_occurrences: 40, ledger_entries: 12 },
          warnings: [],
          dry_run: !!body.dry_run,
          csrf_token: body.dry_run ? null : 'fresh',
        }),
      );
    }
    if (url.includes('/admin/profile'))
      return Promise.resolve(json({ email: 'moved@example.com', signed_out: true }));
    if (url.includes('/auth/me')) return Promise.resolve(json(ME));
    if (method === 'PATCH') return Promise.resolve(json(SETTINGS));
    if (url.includes('/admin/llm/models'))
      return Promise.resolve(json({ reachable: true, models: ['gemma3', 'qwen3-vl'] }));
    if (url.includes('/admin/settings')) return Promise.resolve(json(SETTINGS));
    return Promise.resolve(json({}));
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter>
          <Settings />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('admin Settings', () => {
  it('fetches models into the dropdown and saves', async () => {
    const calls = setup();
    await waitFor(() => expect(screen.getByDisplayValue('http://box:9000/v1')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /fetch models/i }));
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'qwen3-vl' })).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.method === 'PATCH')!;
    expect(patch.url).toContain('/admin/settings');
    expect((patch.body as Record<string, unknown>).llm_base_url).toBe('http://box:9000/v1');
  });

  it('names the Google account in use and sets the break-glass password', async () => {
    const calls = setup();
    expect(await screen.findByText(/parent@example.com/)).toBeInTheDocument();

    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('a-much-longer-passphrase');
    fireEvent.click(screen.getByRole('button', { name: /change break-glass password/i }));

    await waitFor(() =>
      expect(calls.some((c) => c.url.includes('/admin/break-glass-password'))).toBe(true),
    );
    const post = calls.find((c) => c.url.includes('/admin/break-glass-password'))!;
    expect(post.body).toEqual({ new_password: 'a-much-longer-passphrase' });
    prompt.mockRestore();
  });

  it('points the export link at the chosen sections', async () => {
    setup();
    const href = () => screen.getByRole('link', { name: /export/i }).getAttribute('href');
    await waitFor(() => expect(href()).toBe('/api/v1/admin/export?history=true&money=true'));

    fireEvent.click(screen.getByLabelText(/include money transactions/i));
    expect(href()).toBe('/api/v1/admin/export?history=true&money=false');

    fireEvent.click(screen.getByLabelText(/include chore history/i));
    expect(href()).toBe('/api/v1/admin/export?history=false&money=false');
  });

  it('previews a backup file, confirms, then restores and reloads', async () => {
    const calls = setup();
    const reload = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, reload },
    });
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('REPLACE');

    const bundle = { version: 1, tables: { households: [] } };
    const file = new File([JSON.stringify(bundle)], 'backup.json', { type: 'application/json' });
    fireEvent.change(await screen.findByLabelText('Backup file'), { target: { files: [file] } });

    const imports = () => calls.filter((c) => c.url.includes('/admin/import'));
    await waitFor(() => expect(imports()).toHaveLength(2));
    const [dry, real] = imports();
    expect((dry.body as Record<string, unknown>).dry_run).toBe(true);
    expect((real.body as Record<string, unknown>).bundle).toEqual(bundle);
    // The parent is told what they are about to erase, in their own terms.
    expect(String(prompt.mock.calls[0][0])).toContain('12 money entries');
    await waitFor(() => expect(reload).toHaveBeenCalled());
    prompt.mockRestore();
  });

  it('lets a parent re-point their own Google address', async () => {
    // The only way to fix a wrong ADMIN_EMAIL without a shell on the host: no other
    // endpoint can touch an admin's address.
    const calls = setup();
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('moved@example.com');
    await screen.findByRole('button', { name: /change my google address/i });

    fireEvent.click(screen.getByRole('button', { name: /change my google address/i }));

    await waitFor(() =>
      expect(calls.filter((c) => c.url.includes('/admin/profile'))).toHaveLength(1),
    );
    const [call] = calls.filter((c) => c.url.includes('/admin/profile'));
    expect(call.method).toBe('PATCH');
    expect(call.body).toEqual({ email: 'moved@example.com' });
    // The parent is warned before they commit to it, because it signs them out.
    expect(String(prompt.mock.calls[0][0])).toContain('signs you out');
    prompt.mockRestore();
  });
});
