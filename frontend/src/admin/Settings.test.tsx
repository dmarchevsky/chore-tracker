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
  role: 'admin',
  csrf_token: 'x',
  totp_enrolled: false,
};

function setup() {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method !== 'GET')
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });

    if (url.includes('/auth/totp/enroll'))
      return Promise.resolve(
        json({
          secret: 'JBSWY3DPEHPK3PXP',
          provisioning_uri: 'otpauth://totp/ChoreKeeper:parent?secret=JBSWY3DPEHPK3PXP',
        }),
      );
    if (url.includes('/auth/totp/confirm'))
      return Promise.resolve(json({ ...ME, totp_enrolled: true }));
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

  it('runs the TOTP enrollment flow', async () => {
    const calls = setup();
    fireEvent.click(await screen.findByRole('button', { name: /set up google authenticator/i }));

    await waitFor(() => expect(calls.some((c) => c.url.includes('/auth/totp/enroll'))).toBe(true));
    expect(await screen.findByText(/JBSWY3DPEHPK3PXP/)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/6-digit code/i), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    await waitFor(() => expect(calls.some((c) => c.url.includes('/auth/totp/confirm'))).toBe(true));
  });
});
