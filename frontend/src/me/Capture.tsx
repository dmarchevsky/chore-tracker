import { useEffect, useRef, useState } from 'react';
import type { Chore } from '../api/types';
import { Button, Card } from '../shared/ui';
import { fileToDownscaledJpeg, toDownscaledJpeg } from '../pwa/downscale';

type Perm = 'starting' | 'live' | 'denied' | 'error' | 'gallery';

interface Props {
  chore: Chore;
  promptToken: string | null;
  onSubmit: (files: Blob[], note: string, source: 'camera' | 'gallery') => Promise<void>;
  busy: boolean;
}

export function Capture({ chore, promptToken, onSubmit, busy }: Props) {
  const slots = chore.photo_prompts.length
    ? chore.photo_prompts
    : Array.from({ length: Math.max(chore.photo_count, 1) }, (_, i) => `Photo ${i + 1}`);

  const [perm, setPerm] = useState<Perm>('starting');
  const [shots, setShots] = useState<(Blob | null)[]>(() => slots.map(() => null));
  const [note, setNote] = useState('');
  const [active, setActive] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    let cancelled = false;
    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
      .then((s) => {
        if (cancelled) return s.getTracks().forEach((t) => t.stop());
        streamRef.current = s;
        if (videoRef.current) videoRef.current.srcObject = s;
        setPerm('live');
      })
      .catch((e) => setPerm(e?.name === 'NotAllowedError' ? 'denied' : 'error'));
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function shoot() {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    const c = document.createElement('canvas');
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext('2d')!.drawImage(v, 0, 0);
    const blob = await toDownscaledJpeg(Object.assign(c, { width: c.width, height: c.height }));
    setShots((prev) => prev.map((b, i) => (i === active ? blob : b)));
    setActive((a) => Math.min(a + 1, slots.length - 1));
  }

  async function pickFromGallery(file: File) {
    const blob = await fileToDownscaledJpeg(file);
    setShots((prev) => prev.map((b, i) => (i === active ? blob : b)));
    setPerm('gallery');
  }

  const allFilled = shots.every(Boolean);

  if (perm === 'denied' || perm === 'error') {
    return (
      <Card>
        <p className="font-semibold">Camera is off</p>
        <p className="mt-1 text-sm text-slate-400">
          {perm === 'denied'
            ? 'Allow camera access in your browser settings, then reload this page.'
            : "Couldn't start the camera on this device."}
        </p>
        {chore.allow_gallery_upload && (
          <label className="mt-3 inline-block cursor-pointer rounded-xl bg-slate-800 px-4 py-3 text-sm font-semibold">
            Pick a photo instead
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && pickFromGallery(e.target.files[0])}
            />
          </label>
        )}
        <Button className="mt-3 w-full" variant="ghost" onClick={() => location.reload()}>
          Reload
        </Button>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {promptToken && (
        <div className="rounded-xl bg-amber-500/20 p-3 text-center">
          <p className="text-sm text-amber-200">Hold up today’s number in the photo</p>
          <p className="text-4xl font-black tracking-widest">{promptToken}</p>
        </div>
      )}

      <div className="overflow-hidden rounded-2xl bg-black">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="aspect-[3/4] w-full object-cover"
        />
      </div>

      <p className="text-center text-sm text-slate-300">
        {slots[active]} — {active + 1} of {slots.length}
      </p>

      <div className="flex justify-center">
        <button
          aria-label="Take photo"
          onClick={shoot}
          disabled={perm !== 'live'}
          className="h-16 w-16 rounded-full border-4 border-white bg-white/20 active:scale-95"
        />
      </div>

      <div className="flex gap-2">
        {slots.map((label, i) => (
          <button
            key={label}
            onClick={() => setActive(i)}
            className={`flex-1 rounded-lg border p-1 text-xs ${
              i === active ? 'border-sky-500' : 'border-slate-700'
            }`}
          >
            {shots[i] ? (
              <img
                src={URL.createObjectURL(shots[i]!)}
                alt={label}
                className="h-16 w-full rounded object-cover"
              />
            ) : (
              <span className="flex h-16 items-center justify-center text-slate-500">{label}</span>
            )}
          </button>
        ))}
      </div>

      <textarea
        className="rounded-xl bg-slate-800 p-3 text-sm"
        placeholder="Add a note (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />

      <Button
        disabled={!allFilled || busy}
        onClick={() =>
          onSubmit(shots.filter(Boolean) as Blob[], note, perm === 'gallery' ? 'gallery' : 'camera')
        }
      >
        {busy ? 'Sending…' : 'Submit'}
      </Button>
    </div>
  );
}
