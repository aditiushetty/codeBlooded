"use client";

import { ChatCircleText, CheckCircle, PaperPlaneTilt, Trash, UserPlus, Warning, WhatsappLogo } from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { api, useResource } from "@/lib/api";
import { Button, LANG_LABEL, timeAgo } from "./ui";

type Contact = {
  id: string;
  name: string | null;
  phone: string;
  language: "en" | "kn" | "hi" | null;
  source: "owner_import" | "code_page";
  opted_out_at: string | null;
  visits: number;
  last_visit: string | null;
  codes: number;
  reviews: number;
};
type Contacts = { contacts: Contact[]; segments: string[]; links_public: boolean };
type Invite = {
  code: string;
  customer_id: string;
  name: string | null;
  phone: string;
  language: string;
  status: "ready" | "sent" | "came_in" | "reviewed";
  opted_out: boolean;
  message: { kind: "invite" | "review"; text: string; link: string } | null;
};
type Invites = { invites: Invite[]; counts: Record<Invite["status"], number>; links_public: boolean };

const SEGMENTS: [string, string][] = [
  ["all", "Everyone"],
  ["visited", "Came in before"],
  ["regulars", "Regulars (2+ visits)"],
  ["lapsed", "Not seen in 30 days"],
  ["new", "Never came in yet"],
];
const STATUS: Record<Invite["status"], string> = { ready: "Code ready", sent: "Sent", came_in: "Came in", reviewed: "Reviewed" };

const pretty = (p: string) => (p.startsWith("91") && p.length === 12 ? `+91 ${p.slice(2, 7)} ${p.slice(7)}` : `+${p}`);

function LinksWarning() {
  return (
    <p className="mt-3 flex items-start gap-2 rounded-[var(--radius-sm)] bg-turmeric-soft px-3 py-2 text-[13px] text-turmeric">
      <Warning size={15} className="mt-0.5 shrink-0" aria-hidden />
      Links in these messages point to this computer (localhost), so customers can&apos;t open them. The code itself still works at the counter. Deploy, or set PUBLIC_BASE_URL to your public address.
    </p>
  );
}

/** Customers page: the business's own WhatsApp list. Pasted by the owner with consent, or added by customers on their code page. */
export function CustomerList({ slug }: { slug: string }) {
  const { data, reload } = useResource<Contacts>(`/businesses/${slug}/contacts`, (e) => e.type.startsWith("customers."));
  const [text, setText] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const r = await api<{ added: number; updated: number; skipped: string[] }>(`/businesses/${slug}/contacts`, { method: "POST", json: { text, consent } });
      setNote(
        `Added ${r.added}${r.updated ? `, ${r.updated} already on the list` : ""}.` +
          (r.skipped.length ? ` No usable number on: ${r.skipped.slice(0, 3).join(" · ")}${r.skipped.length > 3 ? "…" : ""}` : ""),
      );
      setText("");
      setConsent(false);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const rows = data?.contacts ?? [];
  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
      <div className="lg:col-span-5">
        <label htmlFor="contacts-paste" className="text-[14px] font-semibold">
          Add customers
        </label>
        <p className="mt-1 text-[13px] text-muted">One per line: a name and a mobile number. Add kannada or hindi to write to them in that language.</p>
        <textarea
          id="contacts-paste"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          placeholder={"Asha, 98450 12345\nRavi 99001 23456 kannada"}
          className="mt-2 w-full rounded-[var(--radius-sm)] bg-surface p-3 font-mono text-[13px] ring-1 ring-line focus:outline-none focus:ring-2 focus:ring-pen"
        />
        <label className="mt-2 flex items-start gap-2 text-[13px] text-ink-2">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 accent-[var(--color-ink)]" />
          These customers agreed to get offers from us on WhatsApp.
        </label>
        <Button className="mt-3" variant="primary" size="sm" disabled={busy || !text.trim() || !consent} onClick={add}>
          <UserPlus size={15} aria-hidden /> {busy ? "Adding…" : "Add to the list"}
        </Button>
        {note && <p className="mt-2 text-[13px] text-pen">{note}</p>}
        {error && <p className="mt-2 text-[13px] text-kumkum">{error}</p>}
        <p className="mt-4 text-[13px] text-muted">Customers can also add themselves on their code page, after they get a code.</p>
      </div>

      <div className="lg:col-span-7">
        <p className="text-[14px] font-semibold">
          {rows.length} on your WhatsApp list
          {rows.some((c) => c.opted_out_at) && <span className="font-normal text-muted"> · {rows.filter((c) => c.opted_out_at).length} said stop</span>}
        </p>
        {rows.length === 0 ? (
          <p className="mt-2 text-[14px] text-muted">Nobody yet. Add the regulars who already message you.</p>
        ) : (
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {rows.map((c) => (
              <li key={c.id} className={clsx("flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-[14px]", c.opted_out_at && "opacity-55")}>
                <span className="min-w-0 flex-1">
                  <span className="font-semibold">{c.name ?? "No name"}</span> <span className="font-mono text-[12px] text-muted">{pretty(c.phone)}</span>
                  {c.language && c.language !== "en" && <span className="ml-2 text-[12px] text-muted">{LANG_LABEL[c.language]}</span>}
                  {c.source === "code_page" && <span className="ml-2 text-[12px] text-pen">added themselves</span>}
                </span>
                <span className="text-[13px] text-ink-2">
                  {c.visits ? `${c.visits} visit${c.visits > 1 ? "s" : ""}, last ${timeAgo(c.last_visit!)}` : "No visit yet"}
                  {c.reviews ? ` · ${c.reviews} review${c.reviews > 1 ? "s" : ""}` : ""}
                </span>
                <button
                  className="press text-[13px] font-semibold text-ink-2 hover:text-ink"
                  onClick={async () => {
                    await api(`/contacts/${c.id}`, { method: "PATCH", json: { opted_out: !c.opted_out_at } });
                    reload();
                  }}
                >
                  {c.opted_out_at ? "Said start" : "Said stop"}
                </button>
                <button
                  aria-label={`Remove ${c.name ?? pretty(c.phone)}`}
                  className="press text-muted hover:text-kumkum"
                  onClick={async () => {
                    if (!confirm(`Remove ${c.name ?? pretty(c.phone)} from the list?`)) return;
                    await api(`/contacts/${c.id}`, { method: "DELETE" });
                    reload();
                  }}
                >
                  <Trash size={15} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Campaign Share step: a personal code for each customer on the list, sent from the owner's own WhatsApp, then a review link once they came in. */
export function SendToCustomers({ campaignId, slug }: { campaignId: string; slug: string }) {
  const list = useResource<Contacts>(`/businesses/${slug}/contacts`, (e) => e.type.startsWith("customers."));
  const { data, reload } = useResource<Invites>(`/campaigns/${campaignId}/invites`);
  const [segment, setSegment] = useState("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reachable = (list.data?.contacts ?? []).filter((c) => !c.opted_out_at).length;

  async function make() {
    setBusy(true);
    setError(null);
    try {
      await api(`/campaigns/${campaignId}/invites`, { method: "POST", json: { segment } });
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function open(i: Invite) {
    if (!i.message) return;
    window.open(i.message.link, "_blank", "noopener");
    await api(`/claims/${i.code}/sent`, { method: "POST", json: { kind: i.message.kind } });
    reload();
  }

  const rows = data?.invites ?? [];
  return (
    <div className="mt-8 rounded-[var(--radius-lg)] bg-surface p-5 ring-1 ring-line">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-[19px] font-semibold">
            <WhatsappLogo size={20} aria-hidden /> Send to your customers
          </h3>
          <p className="mt-1 max-w-xl text-[13px] text-muted">
            Each customer gets their own code, sent from your WhatsApp: press Send, WhatsApp opens with the message ready, you press send. Once they use it at the counter, ask how it was the same way.
          </p>
        </div>
        {data && rows.length > 0 && (
          <p className="text-[13px] text-ink-2">
            {data.counts.sent + data.counts.came_in + data.counts.reviewed} sent · {data.counts.came_in + data.counts.reviewed} came in · {data.counts.reviewed} reviewed
          </p>
        )}
      </div>

      {list.data && reachable === 0 ? (
        <p className="mt-4 text-[14px]">
          Your WhatsApp list is empty.{" "}
          <Link href="/customers#list-h" className="font-semibold text-pen hover:underline">
            Add customers
          </Link>{" "}
          first.
        </p>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <label htmlFor="segment" className="text-[13px] font-semibold">
            Who
          </label>
          <select id="segment" value={segment} onChange={(e) => setSegment(e.target.value)} className="h-8 rounded-[var(--radius-sm)] bg-paper px-2 text-[13px] ring-1 ring-line">
            {SEGMENTS.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
          <Button size="sm" variant="primary" disabled={busy} onClick={make}>
            {busy ? "Making codes…" : "Make their codes"}
          </Button>
          <span className="text-[13px] text-muted">{reachable} on the list. Customers who already have a code keep it.</span>
        </div>
      )}
      {error && <p className="mt-2 text-[13px] text-kumkum">{error}</p>}
      {data && !data.links_public && rows.length > 0 && <LinksWarning />}

      {rows.length > 0 && (
        <ul className="mt-4 divide-y divide-line border-y border-line">
          {rows.map((i) => (
            <li key={i.code} className="flex flex-wrap items-center gap-x-4 gap-y-1.5 py-2.5 text-[14px]">
              <span className="min-w-0 flex-1">
                <span className="font-semibold">{i.name ?? pretty(i.phone)}</span>
                <span className="ml-2 font-mono text-[12px] text-muted">{i.code}</span>
              </span>
              <span
                className={clsx(
                  "inline-flex items-center gap-1 text-[13px] font-semibold",
                  i.status === "reviewed" ? "text-pen" : i.status === "came_in" ? "text-ink" : "text-muted",
                )}
              >
                {(i.status === "came_in" || i.status === "reviewed") && <CheckCircle size={14} weight="fill" aria-hidden />}
                {i.opted_out ? "Said stop" : STATUS[i.status]}
              </span>
              {i.message && (
                <Button size="sm" variant={i.message.kind === "review" ? "marker" : i.status === "sent" ? "ghost" : "secondary"} onClick={() => open(i)} title={i.message.text}>
                  {i.message.kind === "review" ? (
                    <>
                      <ChatCircleText size={14} aria-hidden /> Ask for a review
                    </>
                  ) : (
                    <>
                      <PaperPlaneTilt size={14} aria-hidden /> {i.status === "sent" ? "Send again" : "Send"}
                    </>
                  )}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Customer's own code page: "send me the next offers on WhatsApp". */
export function OptIn({ code, lang }: { code: string; lang: string }) {
  const [phone, setPhone] = useState("");
  const [agree, setAgree] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const t = (m: Record<string, string>) => m[lang] ?? m.en;
  if (done)
    return (
      <p className="flex items-center gap-2 text-[14px] text-pen">
        <CheckCircle size={16} weight="fill" aria-hidden /> {t({ en: "Done. Next offers come on WhatsApp.", kn: "ಆಯಿತು. ಮುಂದಿನ ಆಫರ್‌ಗಳು WhatsApp ನಲ್ಲಿ ಬರುತ್ತವೆ.", hi: "हो गया। अगले ऑफ़र WhatsApp पर आएँगे।" })}
      </p>
    );
  return (
    <form
      className="text-left"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await api(`/public/claims/${code}/opt-in`, { method: "POST", json: { phone, agree } });
          setDone(true);
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }}
    >
      <label htmlFor="optin-phone" className="text-[14px] font-semibold">
        {t({ en: "Get the next offers on WhatsApp", kn: "ಮುಂದಿನ ಆಫರ್‌ಗಳನ್ನು WhatsApp ನಲ್ಲಿ ಪಡೆಯಿರಿ", hi: "अगले ऑफ़र WhatsApp पर पाएँ" })}
      </label>
      <div className="mt-2 flex gap-2">
        <input
          id="optin-phone"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="98450 12345"
          className="h-10 min-w-0 flex-1 rounded-[var(--radius-sm)] bg-surface px-3 text-[15px] ring-1 ring-line focus:outline-none focus:ring-2 focus:ring-pen"
        />
        <Button type="submit" variant="primary" disabled={!agree || phone.replace(/\D/g, "").length < 10}>
          {t({ en: "Add me", kn: "ಸೇರಿಸಿ", hi: "जोड़ें" })}
        </Button>
      </div>
      <label className="mt-2 flex items-start gap-2 text-[13px] text-ink-2">
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-0.5 accent-[var(--color-ink)]" />
        {t({ en: "Yes, send me offers on WhatsApp. I can reply STOP any time.", kn: "ಹೌದು, WhatsApp ನಲ್ಲಿ ಆಫರ್‌ಗಳನ್ನು ಕಳುಹಿಸಿ. ಯಾವಾಗ ಬೇಕಾದರೂ STOP ಎಂದು ಕಳುಹಿಸಬಹುದು.", hi: "हाँ, मुझे WhatsApp पर ऑफ़र भेजें। कभी भी STOP भेजकर बंद कर सकते हैं।" })}
      </label>
      {error && <p className="mt-1 text-[13px] text-kumkum">{error}</p>}
    </form>
  );
}
