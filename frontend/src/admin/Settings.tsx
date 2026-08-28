import { useEffect, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import {
  useLlmModels,
  useSettings,
  useTotpConfirm,
  useTotpEnroll,
  useTotpReset,
  useUpdateSettings,
} from './api';
import type { SettingsPatch } from './api';
import { useAuth } from '../auth/AuthContext';
import { Button, Card, Spinner } from '../shared/ui';

export function Settings() {
  const settings = useSettings();
  const save = useUpdateSettings();

  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [pass, setPass] = useState(0.85);
  const [fail, setFail] = useState(0.35);
  const [timeout, setTimeoutS] = useState(120);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    const d = settings.data;
    if (!d) return;
    setBaseUrl(d.llm.base_url);
    setModel(d.llm.model);
    setPass(d.verification.auto_pass_threshold);
    setFail(d.verification.auto_fail_threshold);
    setTimeoutS(d.llm.timeout_s);
  }, [settings.data]);

  const models = useLlmModels(baseUrl, apiKey);

  if (settings.isLoading) return <Spinner />;
  const src = settings.data?.source ?? {};

  async function submit() {
    setMsg(null);
    const body: SettingsPatch = {
      llm_base_url: baseUrl || null,
      llm_model: model || null,
      llm_timeout_s: timeout,
      auto_pass_threshold: pass,
      auto_fail_threshold: fail,
    };
    if (apiKey) body.llm_api_key = apiKey;
    try {
      await save.mutateAsync(body);
      setApiKey('');
      setMsg('Saved.');
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-lg font-bold">Settings</h1>

      <Card className="flex flex-col gap-3">
        <h2 className="font-bold">Vision model &amp; connection</h2>

        <Field label={`Base URL (${src.llm_base_url ?? 'env'})`}>
          <input className="inp" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </Field>

        <Field label={`API key (${settings.data?.llm.api_key_set ? 'set' : 'none'})`}>
          <input
            className="inp"
            type="password"
            placeholder="leave blank to keep current"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </Field>

        <div className="flex items-end gap-2">
          <Field label={`Model (${src.llm_model ?? 'env'})`}>
            {models.data?.models?.length ? (
              <select className="inp" value={model} onChange={(e) => setModel(e.target.value)}>
                {!models.data.models.includes(model) && model && (
                  <option value={model}>{model}</option>
                )}
                {models.data.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            ) : (
              <input className="inp" value={model} onChange={(e) => setModel(e.target.value)} />
            )}
          </Field>
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="ghost"
            disabled={!baseUrl || models.isFetching}
            onClick={() => models.refetch()}
          >
            Fetch models
          </Button>
        </div>
        {models.isFetched && (
          <p className={`text-xs ${models.data?.reachable ? 'text-emerald-400' : 'text-rose-400'}`}>
            {models.data?.reachable
              ? `reachable — ${models.data.models.length} model(s)`
              : `unreachable${models.data?.error ? `: ${models.data.error}` : ''}`}
          </p>
        )}
      </Card>

      <Card className="flex flex-col gap-3">
        <h2 className="font-bold">Verification tuning</h2>
        <div className="flex gap-2">
          <Field label={`Auto-pass ≥ (${src.auto_pass_threshold ?? 'env'})`}>
            <input
              className="inp"
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={pass}
              onChange={(e) => setPass(parseFloat(e.target.value || '0'))}
            />
          </Field>
          <Field label={`Auto-fail ≤ (${src.auto_fail_threshold ?? 'env'})`}>
            <input
              className="inp"
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={fail}
              onChange={(e) => setFail(parseFloat(e.target.value || '0'))}
            />
          </Field>
          <Field label={`Timeout s (${src.llm_timeout_s ?? 'env'})`}>
            <input
              className="inp"
              type="number"
              value={timeout}
              onChange={(e) => setTimeoutS(parseInt(e.target.value || '0', 10))}
            />
          </Field>
        </div>
      </Card>

      <TwoFactor />

      <div className="flex items-center gap-3">
        <Button className="min-h-0 px-4 py-2 text-sm" onClick={submit} disabled={save.isPending}>
          Save
        </Button>
        {msg && (
          <span className={`text-sm ${msg === 'Saved.' ? 'text-emerald-400' : 'text-rose-400'}`}>
            {msg}
          </span>
        )}
      </div>
    </div>
  );
}

function TwoFactor() {
  const { me, refresh } = useAuth();
  const enroll = useTotpEnroll();
  const confirm = useTotpConfirm();
  const reset = useTotpReset();
  const [uri, setUri] = useState<string | null>(null);
  const [secret, setSecret] = useState('');
  const [code, setCode] = useState('');
  const [msg, setMsg] = useState<string | null>(null);

  async function begin() {
    setMsg(null);
    try {
      const r = await enroll.mutateAsync();
      setUri(r.provisioning_uri);
      setSecret(r.secret);
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  async function finish() {
    setMsg(null);
    try {
      await confirm.mutateAsync(code.trim());
      await refresh();
      setUri(null);
      setCode('');
      setMsg('Two-factor is on.');
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  async function doReset() {
    setMsg(null);
    const pw = window.prompt('Confirm your password to reset the authenticator');
    if (!pw) return;
    try {
      await reset.mutateAsync(pw);
      await refresh();
      setMsg('Authenticator cleared — set up a new one below.');
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  return (
    <Card className="flex flex-col gap-3">
      <h2 className="font-bold">Two-factor (Google Authenticator)</h2>

      {me?.totp_enrolled && !uri && (
        <div className="flex items-center gap-3">
          <span className="text-sm text-emerald-400">Enabled for {me.username}.</span>
          <Button
            className="min-h-0 px-3 py-2 text-sm"
            variant="ghost"
            onClick={doReset}
            disabled={reset.isPending}
          >
            Move to a new phone / reset
          </Button>
        </div>
      )}

      {!me?.totp_enrolled && !uri && (
        <Button
          className="min-h-0 self-start px-3 py-2 text-sm"
          onClick={begin}
          disabled={enroll.isPending}
        >
          Set up Google Authenticator
        </Button>
      )}

      {uri && (
        <div className="flex flex-col gap-2 text-sm">
          <p className="text-slate-400">
            In Google Authenticator: <b>+</b> → <b>Scan a QR code</b>.
          </p>
          <div className="w-fit rounded-lg bg-white p-2">
            <QRCodeSVG value={uri} size={160} />
          </div>
          <p className="break-all text-xs text-slate-500">
            or enter this key manually: <code>{secret}</code>
          </p>
          <div className="flex gap-2">
            <input
              className="inp"
              inputMode="numeric"
              placeholder="6-digit code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
            <Button
              className="min-h-0 px-3 py-2 text-sm"
              onClick={finish}
              disabled={code.trim().length < 6 || confirm.isPending}
            >
              Confirm
            </Button>
          </div>
        </div>
      )}

      {msg && (
        <span
          className={`text-sm ${msg.includes('on.') || msg.includes('cleared') ? 'text-emerald-400' : 'text-rose-400'}`}
        >
          {msg}
        </span>
      )}
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-slate-400">{label}</span>
      {children}
    </label>
  );
}
