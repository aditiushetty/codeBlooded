"use client";

import { ArrowSquareOut, Check, DownloadSimple, FilmStrip, GoogleLogo, Pause, Play, WarningCircle, WhatsappLogo } from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useBusiness } from "@/lib/business";
import type { Asset, GooglePost, Reel, WaTemplate } from "@/lib/types";
import { Button } from "./ui";

const STATUS: Record<WaTemplate["status"], { label: string; tone: string }> = {
  draft: { label: "Draft", tone: "text-ink-2" },
  pending: { label: "Waiting for Meta", tone: "text-turmeric" },
  approved: { label: "Approved by Meta", tone: "text-pen" },
  rejected: { label: "Rejected by Meta", tone: "text-kumkum" },
  paused: { label: "Paused by Meta", tone: "text-turmeric" },
  disabled: { label: "Disabled by Meta", tone: "text-kumkum" },
};

function Problems({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="mt-2 space-y-1 text-[13px] text-turmeric">
      {items.map((p) => (
        <li key={p} className="flex gap-1.5">
          <WarningCircle size={14} className="mt-0.5 shrink-0" aria-hidden /> {p}
        </li>
      ))}
    </ul>
  );
}

function useAction<T>() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<T>) => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run };
}

/** A WhatsApp template for this post: what may go to customers who wrote more than 24 hours ago. Meta approves it. */
export function TemplatePanel({ asset }: { asset: Asset }) {
  const { slug } = useBusiness();
  const [t, setT] = useState<WaTemplate | null>(null);
  const [canSubmit, setCanSubmit] = useState<boolean | null>(null);
  const { busy, error, run } = useAction<WaTemplate | null>();

  useEffect(() => {
    run(async () => {
      const draft = await api<WaTemplate>(`/assets/${asset.id}/whatsapp/template`, { method: "POST" });
      const list = await api<{ templates: WaTemplate[]; can_submit: boolean }>(`/businesses/${slug}/whatsapp-templates`).catch(() => null);
      setCanSubmit(list?.can_submit ?? null);
      setT(draft);
      return draft;
    });
  }, [asset.id, slug, run]);

  if (!t) return <p className="text-[14px] text-muted">{error ?? "Drafting the template…"}</p>;
  const st = STATUS[t.status];
  return (
    <div>
      <p className="flex flex-wrap items-center gap-2 text-[13px]">
        <span className={clsx("font-semibold", st.tone)}>{st.label}</span>
        <span className="font-mono text-muted">{t.name}</span>
        {t.reason && <span className="text-kumkum">{t.reason}</span>}
      </p>
      <pre className="mt-2 whitespace-pre-wrap rounded-[var(--radius-sm)] bg-sunken p-3 font-sans text-[14px] leading-snug" lang={t.language}>
        {t.body.replace("{{1}}", "[the customer's link]")}
        {t.footer && <span className="mt-2 block text-[12px] text-muted">{t.footer}</span>}
      </pre>
      <Problems items={t.problems} />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {(t.status === "draft" || t.status === "rejected") && (
          <Button
            size="sm"
            variant="primary"
            disabled={busy || t.problems.length > 0 || canSubmit === false}
            onClick={() => run(async () => {
              const out = await api<WaTemplate>(`/whatsapp-templates/${t.id}/submit`, { method: "POST" });
              setT(out);
              return out;
            })}
          >
            {busy ? "Sending…" : "Send to Meta for approval"}
          </Button>
        )}
        {canSubmit === false && (
          <p className="text-[13px] text-muted">
            Connect WhatsApp with your Business Account id on the <Link href="/channels" className="underline underline-offset-4">Channels page</Link> to submit.
          </p>
        )}
        {t.status === "approved" && <p className="text-[13px] text-pen">Sending this post now reaches people who wrote more than a day ago too (Meta charges per message).</p>}
      </div>
      {error && <p className="mt-2 text-[13px] text-kumkum">{error}</p>}
    </div>
  );
}

const gdate = (d?: { year: number; month: number; day: number }) =>
  d ? new Date(d.year, d.month - 1, d.day).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "not set";

function CopyField({ label, value }: { label: string; value: string }) {
  const [ok, setOk] = useState(false);
  return (
    <div className="flex items-start gap-3 py-2">
      <span className="w-28 shrink-0 text-[12px] font-semibold uppercase tracking-wide text-muted">{label}</span>
      <span className="min-w-0 flex-1 whitespace-pre-wrap text-[14px]">{value}</span>
      <button
        onClick={async () => {
          await navigator.clipboard?.writeText(value);
          setOk(true);
          setTimeout(() => setOk(false), 1400);
        }}
        className="press shrink-0 text-[12px] font-semibold text-pen underline underline-offset-4"
      >
        {ok ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** The post as an Offer on the business's Google listing (Search and Maps). */
export function GooglePanel({ asset }: { asset: Asset }) {
  const [g, setG] = useState<GooglePost | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const { busy, error, run } = useAction<unknown>();
  useEffect(() => {
    run(async () => setG(await api<GooglePost>(`/assets/${asset.id}/google-post`)));
  }, [asset.id, run]);
  if (!g) return <p className="text-[14px] text-muted">{error ?? "Preparing the Google offer…"}</p>;
  const p = g.post;
  const live = g.posted[0]?.search_url ?? done;
  return (
    <div>
      <div className="divide-y divide-line border-y border-line">
        <CopyField label="Title" value={p.event.title} />
        <CopyField label="Details" value={p.summary} />
        <CopyField
          label="Dates"
          value={p.event.schedule.startDate || p.event.schedule.endDate ? `${gdate(p.event.schedule.startDate)} to ${gdate(p.event.schedule.endDate)}` : "Not in the offer: Google asks for a start and end date"}
        />
        <CopyField label="Coupon code" value={p.offer.couponCode} />
        <CopyField label="Link" value={p.offer.redeemOnlineUrl} />
        <CopyField label="Terms" value={p.offer.termsConditions} />
      </div>
      <Problems items={g.problems} />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {live ? (
          <a href={live} target="_blank" rel="noreferrer" className="press inline-flex items-center gap-1.5 text-[14px] font-semibold text-pen">
            <Check size={14} weight="bold" aria-hidden /> On Google <ArrowSquareOut size={13} aria-hidden />
          </a>
        ) : g.connected ? (
          <Button
            size="sm"
            variant="primary"
            disabled={busy || !p.event.schedule.endDate}
            onClick={() => run(async () => {
              const out = await api<{ search_url: string | null }>(`/assets/${asset.id}/google-post`, { method: "POST" });
              setDone(out.search_url ?? "https://business.google.com/");
            })}
          >
            <GoogleLogo size={14} weight="bold" aria-hidden /> {busy ? "Posting…" : "Post the offer on Google"}
          </Button>
        ) : (
          <>
            <a href="https://business.google.com/" target="_blank" rel="noreferrer" className="press inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] bg-ink px-3 text-[13px] font-semibold text-white">
              <GoogleLogo size={14} weight="bold" aria-hidden /> Open Google Business Profile <ArrowSquareOut size={12} aria-hidden />
            </a>
            <p className="text-[13px] text-muted">
              Add update, then Offer, and paste the fields above.{" "}
              {g.configured && (
                <>
                  Or <Link href="/channels" className="underline underline-offset-4">connect Google</Link> to post it from here.
                </>
              )}
            </p>
          </>
        )}
      </div>
      {error && <p className="mt-2 text-[13px] text-kumkum">{error}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ photo reels

const W = 720;
const H = 1280;

function wrap(ctx: CanvasRenderingContext2D, text: string, max: number): string[] {
  const words = text.split(/\s+/);
  const lines: string[] = [];
  let line = "";
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (ctx.measureText(next).width > max && line) {
      lines.push(line);
      line = w;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

/** Black or white, whichever reads better on a CSS colour (hex or rgb()). */
function inkOn(color: string): string {
  const hex = color.match(/^#([0-9a-f]{6})$/i)?.[1];
  const rgb = hex ? [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)) : (color.match(/\d+/g) ?? ["255", "255", "255"]).slice(0, 3).map(Number);
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4 ? "#111" : "#fff";
}

/** One frame at time t (seconds) of a reel lasting `total` seconds. */
function draw(ctx: CanvasRenderingContext2D, imgs: HTMLImageElement[], reel: Reel, t: number, total: number, font: string, brand: string) {
  const per = total / imgs.length;
  const i = Math.min(imgs.length - 1, Math.floor(t / per));
  const local = (t - i * per) / per;
  const img = imgs[i];
  ctx.fillStyle = "#111";
  ctx.fillRect(0, 0, W, H);
  if (img?.naturalWidth) {
    // slow zoom and drift (Ken Burns), alternating direction per photo
    const zoom = 1.06 + 0.1 * local;
    const scale = Math.max(W / img.naturalWidth, H / img.naturalHeight) * zoom;
    const dw = img.naturalWidth * scale;
    const dh = img.naturalHeight * scale;
    const dir = i % 2 ? -1 : 1;
    const x = (W - dw) / 2 + dir * (local - 0.5) * (dw - W) * 0.6;
    const y = (H - dh) / 2;
    // dip to black between photos: fade in (except the first) and out (except the last) over a third of a second
    ctx.globalAlpha = Math.min(1, i === 0 ? 1 : local * per * 3, i === imgs.length - 1 ? 1 : (1 - local) * per * 3);
    ctx.drawImage(img, x, y, dw, dh);
    ctx.globalAlpha = 1;
  }
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, "rgba(0,0,0,0.55)");
  g.addColorStop(0.3, "rgba(0,0,0,0)");
  g.addColorStop(0.55, "rgba(0,0,0,0)");
  g.addColorStop(1, "rgba(0,0,0,0.8)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = "#fff";
  ctx.textBaseline = "top";
  ctx.font = `700 60px ${font}`;
  wrap(ctx, reel.headline ?? "", W - 96).slice(0, 3).forEach((l, n) => ctx.fillText(l, 48, 80 + n * 72));

  // the offer box: the locked wording, shown from a third of the way in
  if (t > total * 0.3) {
    const lines = reel.offer.slice(0, 4);
    ctx.font = `600 40px ${font}`;
    const boxH = 48 + lines.length * 54 + 70;
    const top = H - boxH - 70;
    ctx.fillStyle = brand;
    ctx.fillRect(40, top, W - 80, boxH);
    ctx.fillStyle = inkOn(brand);
    lines.forEach((l, n) => ctx.fillText(l, 72, top + 30 + n * 54));
    ctx.font = `600 30px ${font}`;
    ctx.fillText(`${reel.cta ?? ""}${reel.code ? `  ·  ${reel.code}` : ""}`, 72, top + 36 + lines.length * 54);
  }
  const credit = reel.photos[i]?.attribution;
  if (credit) {
    ctx.font = `400 20px ${font}`;
    ctx.fillStyle = "rgba(255,255,255,0.8)";
    ctx.fillText(`Photo: ${credit}`.slice(0, 60), 48, H - 40);
  }
}

/** Turns a post into a short vertical video: the business's own photos, the post's words and the locked offer,
 *  with a Sarvam voice-over reading only those words. Drawn and recorded in the browser. */
export function ReelPanel({ asset }: { asset: Asset }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [reel, setReel] = useState<Reel | null>(null);
  const [imgs, setImgs] = useState<HTMLImageElement[]>([]);
  const [playing, setPlaying] = useState(false);
  const [video, setVideo] = useState<{ url: string; ext: string } | null>(null);
  const { busy, error, run } = useAction<unknown>();
  const stop = useRef<() => void>(() => {});

  useEffect(() => {
    run(async () => {
      const r = await api<Reel>(`/assets/${asset.id}/reel`, { method: "POST" });
      const loaded = await Promise.all(
        r.photos.map(
          (p) =>
            new Promise<HTMLImageElement>((ok) => {
              const im = new Image();
              im.crossOrigin = "anonymous";
              im.onload = () => ok(im);
              im.onerror = () => ok(im);
              im.src = p.url;
            }),
        ),
      );
      setImgs(loaded.filter((im) => im.naturalWidth));
      setReel(r);
    });
    return () => stop.current();
  }, [asset.id, run]);

  const style = () => {
    const css = getComputedStyle(document.body);
    return { font: css.fontFamily || "sans-serif", brand: css.getPropertyValue("--color-brand").trim() || "#f5d90a" };
  };

  useEffect(() => {
    if (!reel || !imgs.length || !canvas.current) return;
    const { font, brand } = style();
    draw(canvas.current.getContext("2d")!, imgs, reel, 0.1, 10, font, brand);
  }, [reel, imgs]);

  /** Plays the reel on the canvas; when `record` is set, also records it with its voice into a video file. */
  async function play(record: boolean) {
    if (!reel || !canvas.current) return;
    const ctx = canvas.current.getContext("2d")!;
    const { font, brand } = style();
    const audio = reel.voice_url ? new Audio() : null;
    let total = Math.max(8, imgs.length * 2.5);
    let ac: AudioContext | null = null;
    const stream = record ? canvas.current.captureStream(30) : null;
    if (audio) {
      audio.crossOrigin = "anonymous";
      audio.src = reel.voice_url!;
      await new Promise((ok) => { audio.onloadedmetadata = ok; audio.onerror = ok; });
      if (Number.isFinite(audio.duration) && audio.duration > 0) total = audio.duration + 1.2;
      if (stream) {
        ac = new AudioContext();
        const src = ac.createMediaElementSource(audio);
        const dest = ac.createMediaStreamDestination();
        src.connect(dest);
        src.connect(ac.destination);
        dest.stream.getAudioTracks().forEach((tr) => stream.addTrack(tr));
      }
    }
    const types = ["video/mp4;codecs=avc1.42E01E,mp4a.40.2", "video/mp4", "video/webm;codecs=vp9,opus", "video/webm"];
    const mime = stream ? types.find((t) => MediaRecorder.isTypeSupported(t)) : undefined;
    const rec = stream ? new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 5_000_000 } : undefined) : null;
    const chunks: Blob[] = [];
    if (rec) rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    setPlaying(true);
    setVideo(null);
    rec?.start(250);
    audio?.play().catch(() => {});
    const start = performance.now();
    let raf = 0;
    const done = () => {
      cancelAnimationFrame(raf);
      audio?.pause();
      setPlaying(false);
      if (rec && rec.state !== "inactive") {
        rec.onstop = () => {
          const type = rec.mimeType || "video/webm";
          setVideo({ url: URL.createObjectURL(new Blob(chunks, { type })), ext: type.includes("mp4") ? "mp4" : "webm" });
          ac?.close();
        };
        rec.stop();
      }
    };
    stop.current = done;
    const tick = () => {
      const t = (performance.now() - start) / 1000;
      draw(ctx, imgs, reel, Math.min(t, total), total, font, brand);
      if (t >= total) done();
      else raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  }

  if (!reel) return <p className="text-[14px] text-muted">{error ?? "Picking your photos and recording the voice-over…"}</p>;
  return (
    <div className="grid gap-5 md:grid-cols-[200px_minmax(0,1fr)]">
      <canvas ref={canvas} width={W} height={H} className="w-[200px] rounded-[var(--radius-md)] bg-ink ring-1 ring-ink" aria-label="Reel preview" />
      <div className="min-w-0">
        <p className="text-[14px] text-ink-2">
          {reel.photos.length} of your own photo{reel.photos.length === 1 ? "" : "s"}, the post's words and the offer box.{" "}
          {reel.voice_url ? `Voice-over by Sarvam (${reel.voice}), reading only these words:` : reel.voice_note}
        </p>
        <p className="mt-2 border-l-2 border-pen pl-3 text-[14px] italic text-ink-2" lang={reel.language}>
          {reel.script}
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" disabled={busy || (playing && !video)} onClick={() => (playing ? stop.current() : play(false))}>
            {playing ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />} {playing ? "Stop" : "Play"}
          </Button>
          <Button size="sm" variant="primary" disabled={playing || typeof MediaRecorder === "undefined"} onClick={() => play(true)}>
            <FilmStrip size={14} aria-hidden /> Make the video
          </Button>
          {video && (
            <a href={video.url} download={`reel-${reel.code ?? asset.id}.${video.ext}`} className="press inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] bg-ink px-3 text-[13px] font-semibold text-white">
              <DownloadSimple size={14} aria-hidden /> Download {video.ext.toUpperCase()}
            </a>
          )}
        </div>
        {playing && <p className="mt-2 text-[13px] text-muted">Recording plays the reel once in real time.</p>}
        {video?.ext === "webm" && <p className="mt-2 text-[13px] text-muted">This browser records WebM. Instagram takes MP4: open this page in Chrome or Safari to get one.</p>}
      </div>
    </div>
  );
}

/** More ways to share one live post: a WhatsApp template, a Google offer, a reel. */
export function MoreWays({ asset }: { asset: Asset }) {
  const [open, setOpen] = useState<"template" | "google" | "reel" | null>(null);
  const tabs = [
    asset.channel === "whatsapp" && { key: "template" as const, label: "WhatsApp template", Icon: WhatsappLogo },
    { key: "google" as const, label: "Google offer", Icon: GoogleLogo },
    asset.channel !== "whatsapp" && { key: "reel" as const, label: "Reel with voice-over", Icon: FilmStrip },
  ].filter(Boolean) as { key: "template" | "google" | "reel"; label: string; Icon: typeof GoogleLogo }[];
  return (
    <div className="col-span-full">
      <div className="flex flex-wrap gap-1.5">
        {tabs.map(({ key, label, Icon }) => (
          <button
            key={key}
            onClick={() => setOpen(open === key ? null : key)}
            aria-expanded={open === key}
            className={clsx("press inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 text-[13px] font-semibold", open === key ? "bg-pen text-white" : "text-pen hover:bg-pen-soft")}
          >
            <Icon size={14} aria-hidden /> {label}
          </button>
        ))}
      </div>
      {open && (
        <div className="mt-3 rounded-[var(--radius-md)] bg-surface p-4 ring-1 ring-line">
          {open === "template" && <TemplatePanel asset={asset} />}
          {open === "google" && <GooglePanel asset={asset} />}
          {open === "reel" && <ReelPanel asset={asset} />}
        </div>
      )}
    </div>
  );
}
