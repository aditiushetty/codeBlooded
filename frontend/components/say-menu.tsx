"use client";

import { Camera, Microphone, Stop } from "@phosphor-icons/react";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const MAX_SECONDS = 28; // Sarvam's quick transcription takes clips under 30 seconds
const LANGS = [
  { code: "kn", label: "ಕನ್ನಡ", speech: "kn-IN" },
  { code: "hi", label: "हिन्दी", speech: "hi-IN" },
  { code: "en", label: "English", speech: "en-IN" },
] as const;

export interface HeardItem {
  name: string;
  price: number;
  said: string | null;
  check: boolean; // the price was not written as digits in what was heard: the owner should look at it
}

type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
};

const blobToDataUrl = (b: Blob) =>
  new Promise<string>((ok, no) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => no(r.error);
    r.readAsDataURL(b);
  });

/** "Say your menu": the owner reads items and prices aloud in Kannada, Hindi or English; Sarvam (or the browser)
 *  hears it and the items fill the form. Nothing is saved until the owner finishes sign-up. */
export function SayMenu({ onItems }: { onItems: (items: HeardItem[]) => void }) {
  const [lang, setLang] = useState<(typeof LANGS)[number]>(LANGS[0]);
  const [sarvam, setSarvam] = useState<boolean | null>(null);
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const rec = useRef<Recognition | null>(null);
  const heard = useRef("");

  useEffect(() => {
    api<{ features?: { sarvam?: boolean } }>("/me")
      .then((m) => setSarvam(!!m.features?.sarvam && "MediaRecorder" in window && !!navigator.mediaDevices?.getUserMedia))
      .catch(() => setSarvam(false));
  }, []);
  useEffect(() => {
    if (!listening || !sarvam) return;
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [listening, sarvam]);
  useEffect(() => {
    if (sarvam && listening && seconds >= MAX_SECONDS) recorder.current?.stop();
  }, [seconds, sarvam, listening]);

  async function send(json: Record<string, unknown>) {
    setBusy(true);
    try {
      const out = await api<{ items: HeardItem[]; said: string }>("/onboarding/menu-speech", { method: "POST", json: { ...json, language: lang.code } });
      if (!out.items.length) setNote(`Heard “${out.said.slice(0, 80)}”, but no item with a price. Say each item and its price.`);
      else {
        onItems(out.items);
        const unsure = out.items.filter((i) => i.check);
        setNote(`Added ${out.items.length} item${out.items.length === 1 ? "" : "s"}.${unsure.length ? ` Check the price of ${unsure.map((i) => i.name).join(", ")}: it was said in words.` : ""}`);
      }
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    setNote(null);
    if (sarvam) {
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        setNote("Microphone access is blocked for this site.");
        return;
      }
      const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported(t));
      const r = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      const parts: Blob[] = [];
      r.ondataavailable = (e) => e.data.size && parts.push(e.data);
      r.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setListening(false);
        await send({ data_url: await blobToDataUrl(new Blob(parts, { type: r.mimeType || "audio/webm" })) });
      };
      recorder.current = r;
      setSeconds(0);
      r.start();
      setListening(true);
      return;
    }
    const Ctor = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    if (!Ctor) {
      setNote("This browser cannot listen. Type the items instead.");
      return;
    }
    const r = new Ctor() as Recognition;
    r.lang = lang.speech;
    r.interimResults = false;
    r.continuous = true;
    heard.current = "";
    r.onresult = (e) => {
      heard.current = Array.from(e.results).map((x) => x[0].transcript).join(" ");
    };
    r.onerror = (e) => setNote(e.error === "not-allowed" ? "Microphone access is blocked for this site." : `Listening stopped (${e.error}).`);
    r.onend = () => {
      setListening(false);
      if (heard.current.trim()) send({ text: heard.current });
    };
    rec.current = r;
    r.start();
    setListening(true);
  }

  function stop() {
    if (sarvam) recorder.current?.stop();
    else rec.current?.stop();
  }

  return (
    <div className="mb-6 rounded-[var(--radius-md)] bg-pen-soft p-4 ring-1 ring-pen/30">
      <p className="text-[15px] font-semibold">Say your menu instead</p>
      <p className="mt-0.5 text-[14px] text-ink-2">Read out each item and its price, like “masala dosa sixty rupees, filter coffee twenty five”. Up to half a minute at a time.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {LANGS.map((l) => (
          <button
            key={l.code}
            type="button"
            onClick={() => setLang(l)}
            disabled={listening}
            className={clsx("press rounded-[var(--radius-sm)] px-3 py-1.5 text-[14px]", lang.code === l.code ? "bg-pen text-white" : "bg-surface text-ink-2 ring-1 ring-line-strong")}
            lang={l.code}
          >
            {l.label}
          </button>
        ))}
        <button
          type="button"
          onClick={listening ? stop : start}
          disabled={busy || sarvam === null}
          className={clsx("press ml-auto inline-flex h-10 items-center gap-2 rounded-full px-4 text-[14px] font-semibold", listening ? "bg-kumkum text-white" : "bg-ink text-white")}
        >
          {listening ? <Stop size={15} weight="fill" aria-hidden /> : <Microphone size={15} weight="fill" aria-hidden />}
          {busy ? "Reading the items…" : listening ? `Stop${sarvam ? ` (${MAX_SECONDS - seconds}s)` : ""}` : "Start speaking"}
        </button>
      </div>
      {note && <p className="mt-2 text-[14px] text-ink-2">{note}</p>}
    </div>
  );
}

/** Shrink a phone photo before it is sent; menus stay readable at this size. */
async function photoDataUrl(file: File, max = 1800): Promise<string> {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const canvas = Object.assign(document.createElement("canvas"), { width: Math.round(bmp.width * scale), height: Math.round(bmp.height * scale) });
  canvas.getContext("2d")!.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.88);
}

/** "Photo of your menu": the printed menu or rate card is read by the vision model; every price is marked for the
 *  owner to check, because a photo cannot be checked against text. */
export function MenuPhoto({ onItems }: { onItems: (items: HeardItem[]) => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function read(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setNote(null);
    let added = 0;
    try {
      for (const f of Array.from(files).slice(0, 4)) {
        const out = await api<{ items: HeardItem[] }>("/onboarding/menu-photo", { method: "POST", json: { data_url: await photoDataUrl(f) } });
        onItems(out.items);
        added += out.items.length;
      }
      setNote(added ? `Read ${added} item${added === 1 ? "" : "s"} from the photo. Check each price below before you save.` : "No item with a clear price was found. Try a sharper, straight-on photo.");
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-6 rounded-[var(--radius-md)] bg-surface p-4 ring-1 ring-line-strong">
      <p className="text-[15px] font-semibold">Or take a photo of your menu</p>
      <p className="mt-0.5 text-[14px] text-ink-2">A printed menu, price list or rate card. Up to 4 photos; Counterpart reads the items and prices.</p>
      <label className={clsx("press mt-3 inline-flex h-10 cursor-pointer items-center gap-2 rounded-full bg-ink px-4 text-[14px] font-semibold text-white", busy && "pointer-events-none opacity-60")}>
        <Camera size={15} weight="fill" aria-hidden />
        {busy ? "Reading the menu…" : "Choose photos"}
        <input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" multiple className="sr-only" disabled={busy} onChange={(e) => read(e.target.files)} />
      </label>
      {note && <p className="mt-2 text-[14px] text-ink-2">{note}</p>}
    </div>
  );
}
