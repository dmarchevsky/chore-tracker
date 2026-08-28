import { useEffect, useState } from 'react';
import { useLlmModels, useSettings, useUpdateSettings } from './api';
import type { SettingsPatch } from './api';
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-slate-400">{label}</span>
      {children}
    </label>
  );
}
