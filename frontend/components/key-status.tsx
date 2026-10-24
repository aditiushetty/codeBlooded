"use client";

import { ArrowClockwise, ArrowSquareOut, Key, X } from "@phosphor-icons/react";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { api, useResource } from "@/lib/api";
import { useWorkspace } from "@/lib/business";
import { timeAgo } from "./ui";

type State = "ok" | "used_up" | "rejected" | "error" | "unchecked" | "off";
type Item = { id: string; name: string; env?: string; job?: string; get_url?: string; ai?: boolean; set?: boolean; state: State; note: string | null; last_ok?: string | null; display?: string; expires_at?: string | null };
type Keys = { overall: "green" | "amber" | "red"; summary: string; keys: Item[]; channels: Item[]; how_to_set: string };

const DOT: Record<State, string> = {
  ok: "bg-leaf",
  used_up: "bg-turmeric",
  rejected: "bg-kumkum",
  error: "bg-kumkum",
  unchecked: "bg-line-strong",
  off: "bg-transparent ring-1 ring-inset ring-line-strong",
};
const SAYS: Record<State, string> = {
  ok: "Works",
  used_up: "Used up for now",
  rejected: "Refused: needs a new key",
  error: "Failing",
  unchecked: "Not used yet",
  off: "Not set",
};
const OVERALL = { green: "bg-leaf", amber: "bg-turmeric", red: "bg-kumkum" } as const;

function Row({ k }: { k: Item }) {
  const fix = k.state === "rejected" || k.state === "used_up" || (k.state === "off" && k.ai);
  return (
    <li className="flex gap-3 py-2.5">
      <span className={clsx("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", DOT[k.state])} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline justify-between gap-x-2">
          <span className="text-[14px] font-semibold">
            {k.name}
            {k.display && <span className="font-normal text-muted"> {k.display}</span>}
          </span>
          <span className={clsx("text-[13px]", k.state === "ok" ? "text-ink-2" : k.state === "off" || k.state === "unchecked" ? "text-muted" : "font-semibold text-kumkum")}>{SAYS[k.state]}</span>
        </p>
        {k.job && <p className="text-[13px] text-muted">{k.job}</p>}
        {k.note && <p className="mt-0.5 text-[13px] text-ink-2">{k.note}</p>}
        {k.state === "ok" && k.last_ok && <p className="text-[12px] text-muted">Last answered {timeAgo(k.last_ok)}</p>}
        {fix && k.get_url && (
          <a href={k.get_url} target="_blank" rel="noreferrer" className="mt-0.5 inline-flex items-center gap-1 text-[13px] font-semibold text-pen hover:underline">
            Get a key <ArrowSquareOut size={11} aria-hidden />
            {k.env && <span className="ml-1 font-mono text-[11px] font-normal text-muted">{k.env}</span>}
          </a>
        )}
      </div>
    </li>
  );
}

/** A dot in the header: green when every key works, amber when one ran out or there is no backup, red when no AI
 *  model can answer. Opens the list of keys, what each one is for, and what to do about it. */
export function KeyStatus() {
  const { business } = useWorkspace();
  const path = `/businesses/${business.slug}/keys`;
  const { data, reload } = useResource<Keys>(path, (e) => e.type === "agent.failed" || e.type === "agent.finished");
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setInterval(reload, 120_000);
    return () => clearInterval(t);
  }, [reload]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);

  if (!data) return null;
  const ai = data.keys.filter((k) => k.ai);
  const other = data.keys.filter((k) => !k.ai);
  const label = data.overall === "green" ? "All keys work" : data.overall === "red" ? "AI keys not working" : "A key needs attention";

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={label}
        className={clsx("press inline-flex h-9 items-center gap-2 rounded-[var(--radius-sm)] px-2.5 text-[14px] font-semibold", open ? "bg-ink text-white" : "text-ink-2 hover:bg-ink/[0.06] hover:text-ink")}
      >
        <span className="relative inline-flex">
          <Key size={16} weight="bold" aria-hidden />
          <span className={clsx("absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full ring-2 ring-paper", OVERALL[data.overall], data.overall === "red" && "pulse-dot")} aria-hidden />
        </span>
        <span className="hidden md:inline lg:hidden xl:inline">Keys</span>
        <span className="sr-only">{label}</span>
      </button>
      {open && (
        <div role="dialog" aria-label="API keys" className="pop absolute right-0 top-12 z-50 w-[min(400px,calc(100vw-24px))] rounded-[var(--radius-lg)] bg-surface shadow-[var(--shadow-float)] ring-1 ring-ink/15">
          <div className="flex items-start gap-3 border-b border-line px-4 py-3">
            <span className={clsx("mt-1.5 h-3 w-3 shrink-0 rounded-full", OVERALL[data.overall])} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-[16px] font-bold">{label}</p>
              <p className="text-[13px] text-ink-2">{data.summary}</p>
            </div>
            <button onClick={() => setOpen(false)} className="press rounded-[var(--radius-sm)] p-1.5 text-ink-2 hover:bg-sunken" aria-label="Close">
              <X size={16} aria-hidden />
            </button>
          </div>
          <div className="max-h-[60vh] overflow-y-auto px-4 pb-2">
            <p className="mt-3 font-mono text-[11px] font-semibold uppercase tracking-wide text-muted">AI models</p>
            <ul className="divide-y divide-line">{ai.map((k) => <Row key={k.id} k={k} />)}</ul>
            {data.channels.length > 0 && (
              <>
                <p className="mt-3 font-mono text-[11px] font-semibold uppercase tracking-wide text-muted">Your accounts</p>
                <ul className="divide-y divide-line">{data.channels.map((k) => <Row key={k.id} k={k} />)}</ul>
              </>
            )}
            <p className="mt-3 font-mono text-[11px] font-semibold uppercase tracking-wide text-muted">Other services</p>
            <ul className="divide-y divide-line">{other.map((k) => <Row key={k.id} k={k} />)}</ul>
          </div>
          <div className="border-t border-line px-4 py-3">
            <button
              disabled={checking}
              onClick={async () => {
                setChecking(true);
                try {
                  await api(`${path}?check=true`);
                  await reload();
                } finally {
                  setChecking(false);
                }
              }}
              className="press inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] bg-ink px-3 text-[13px] font-semibold text-white disabled:opacity-60"
            >
              <ArrowClockwise size={13} className={clsx(checking && "animate-spin")} aria-hidden /> {checking ? "Checking…" : "Check now"}
            </button>
            <p className="mt-2 text-[12px] text-muted">
              Checking asks each provider if the key is valid; it uses no quota. Keys are never typed here. To add or replace one, run in the backend folder:{" "}
              <code className="font-mono text-[11px] text-ink-2">{data.how_to_set}</code>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
