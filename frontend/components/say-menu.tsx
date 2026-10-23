"use client";

import { Microphone, Stop } from "@phosphor-icons/react";
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
