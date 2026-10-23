"use client";

import { CalendarBlank, CloudRain, Compass, Plus, Sun, Ticket, X } from "@phosphor-icons/react";
import { useState } from "react";
import { api, useResource } from "@/lib/api";
import type { Idea, Moment } from "@/lib/types";
import { Button, Skeleton, stagger } from "./ui";

function iconOf(m: Moment) {
  if (m.kind === "weather") return m.key.startsWith("rain") ? CloudRain : Sun;
  return m.kind === "event" ? Ticket : CalendarBlank;
}

const field =
  "h-9 rounded-[var(--radius-sm)] bg-surface px-2.5 text-[14px] shadow-[inset_0_0_0_1.5px_var(--color-line-strong)] outline-none focus:shadow-[inset_0_0_0_1.5px_var(--color-ink)]";

/** What is happening around the business, and the Scout agent's campaign ideas for it. */
export function AroundYou({ slug, onStart }: { slug: string; onStart: (brief: string) => Promise<void> }) {
  const { data, reload } = useResource<{ moments: Moment[] }>(`/businesses/${slug}/moments`, (e) => e.type === "moment.added");
  const [ideas, setIdeas] = useState<Idea[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ name: "", starts_on: new Date().toISOString().slice(0, 10), note: "" });

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const scout = () => run("scout", async () => setIdeas((await api<{ ideas: Idea[] }>(`/businesses/${slug}/opportunities`, { method: "POST" })).ideas));
  const add = () =>
    run("add", async () => {
      await api(`/businesses/${slug}/moments`, { method: "POST", json: { name: draft.name.trim(), starts_on: draft.starts_on, note: draft.note.trim() || null } });
      setDraft((d) => ({ ...d, name: "", note: "" }));
      setAdding(false);
      await reload();
    });
  const remove = (m: Moment) =>
    run(m.key, async () => {
      await api(`/businesses/${slug}/moments/${m.key}`, { method: "DELETE" });
      await reload();
    });

  return (
    <div className="grid grid-cols-1 gap-10 lg:grid-cols-12">
      <div className="lg:col-span-5">
        {!data ? (
          <Skeleton className="h-48" />
        ) : (
          <ul className="divide-y divide-ink/15 border-y border-ink">
            {data.moments.length === 0 && <li className="py-4 text-[14px] text-muted">Nothing on the radar for the next two weeks. Add something you know is coming.</li>}
            {data.moments.map((m) => {
              const Icon = iconOf(m);
              return (
                <li key={m.key} className="flex items-start gap-3 py-3">
                  <Icon size={20} weight="bold" className="mt-0.5 shrink-0 text-pen" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="text-[16px] font-semibold leading-snug">{m.title}</p>
                    <p className="text-[13px] text-ink-2">
                      {m.when}
                      {m.detail ? `, ${m.detail}` : ""}
                    </p>
                    <p className="font-receipt text-[12px] text-muted">{m.source}</p>
                  </div>
                  {m.removable && (
                    <button type="button" onClick={() => remove(m)} disabled={busy !== null} className="press p-1 text-muted hover:text-ink" aria-label={`Remove ${m.title}`}>
                      <X size={14} weight="bold" />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {adding ? (
          <form
            className="mt-3 flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (draft.name.trim().length >= 3) add();
            }}
          >
            <input className={`${field} min-w-0 flex-1 basis-56`} placeholder="IPL: RCB vs CSK, college fest…" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} aria-label="What is happening" autoFocus />
            <input className={field} type="date" value={draft.starts_on} onChange={(e) => setDraft({ ...draft, starts_on: e.target.value })} aria-label="When" />
            <input className={`${field} min-w-0 flex-1 basis-40`} placeholder="time or detail (optional)" value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} aria-label="Detail" />
            <Button variant="primary" size="sm" type="submit" disabled={busy !== null || draft.name.trim().length < 3}>
              {busy === "add" ? "Adding…" : "Add"}
            </Button>
            <Button variant="ghost" size="sm" type="button" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </form>
        ) : (
          <button type="button" onClick={() => setAdding(true)} className="press mt-3 inline-flex items-center gap-1.5 text-[14px] font-semibold text-pen underline decoration-pen/30 underline-offset-4">
            <Plus size={13} weight="bold" aria-hidden /> Add something happening nearby
          </button>
        )}
      </div>

      <div className="lg:col-span-7">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="marker" onClick={scout} disabled={busy !== null || !data?.moments.length} trailing={<Compass size={15} weight="bold" />}>
            {busy === "scout" ? "The Scout is looking…" : ideas ? "Look again" : "Find campaign ideas"}
          </Button>
          <p className="text-[13px] text-muted">The Scout matches these moments with your menu and what customers say.</p>
        </div>
        {error && <p className="mt-3 text-[14px] text-kumkum">{error}</p>}
        {ideas && ideas.length === 0 && <p className="mt-4 text-[14px] text-muted">No idea fits these moments well enough. Add an event, or try again later.</p>}
        {ideas && ideas.length > 0 && (
          <ol className="mt-5 space-y-4">
            {ideas.map((i, n) => (
              <li key={i.title} className="rise-in border-l-2 border-pen pl-4" style={stagger(n)}>
                <p className="font-receipt text-[12px] uppercase tracking-wide text-pen">
                  {i.moment.title} · {i.audience}
                </p>
                <p className="mt-1 text-[19px] font-bold leading-snug [font-stretch:90%]">{i.title}</p>
                <p className="mt-1 text-[15px] text-ink-2">“{i.brief}”</p>
                <p className="mt-1 text-[14px] text-muted">{i.why}</p>
                <Button className="mt-3" variant="primary" size="sm" disabled={busy !== null} onClick={() => run(`start-${n}`, () => onStart(i.brief))}>
                  {busy === `start-${n}` ? "Starting…" : "Start this campaign"}
                </Button>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
