"use client";

import { ArrowSquareOut, ArrowsClockwise, ArrowUUpLeft, ChartLineUp, InstagramLogo, Lightbulb, PaperPlaneTilt, Sparkle, WhatsappLogo } from "@phosphor-icons/react";
import clsx from "clsx";
import { type ReactNode, useState } from "react";
import { api, useResource } from "@/lib/api";
import { useBusiness } from "@/lib/business";
import type { Analytics, Asset, FunnelGroup } from "@/lib/types";
import { CostLine } from "./effort-cost";
import { CountUp } from "./motion";
import { Button, CHANNEL_LABEL, LANG_LABEL, segmentLabel, Skeleton, stagger } from "./ui";
import { MIN_REACH } from "./instagram-overview";

const pct = (x: number | null | undefined, d = 0) => (x == null ? "–" : x === 0 ? "0%" : `${(x * 100).toFixed(x < 0.1 ? 1 : d)}%`);

/** Opened → claimed → came in. Every rate shows the two counts it divides, and only divides a stage by the stage
 *  those people came from: WhatsApp/Instagram claims never opened the link, and visits with the post's own code
 *  (typed from a caption or poster) never claimed, so they are shown as extras, not folded into a rate. */
function Funnel({ t }: { t: Analytics["totals"] }) {
  const elsewhere = t.claims - t.link_claims;
  const stages = [
    { n: t.posts, label: "Posts live", rate: null as ReactNode },
    { n: t.scans, label: "Opened the link", rate: null },
    {
      n: t.claims,
      label: "Claimed a code",
      rate: (
        <>
          {t.scans > 0 && (
            <>
              <span className="font-semibold text-ink">{pct(t.claim_rate)}</span> of people who opened ({t.link_claims} of {t.scans})
            </>
          )}
          {elsewhere > 0 && <span className="block">+{elsewhere} asked on WhatsApp or Instagram</span>}
        </>
      ),
    },
    {
      n: t.redeems,
      label: "Came in",
      rate: (
        <>
          {t.claims > 0 && (
            <>
              <span className="font-semibold text-ink">{pct(t.redeem_rate)}</span> of codes used ({t.used_claims} of {t.claims})
            </>
          )}
          {t.post_code > 0 && <span className="block">{t.used_claims > 0 ? "+" : ""}{t.post_code} with the post&apos;s own code</span>}
        </>
      ),
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-lg)] bg-ink ring-1 ring-ink md:grid-cols-5">
      {stages.map((s, i) => (
        <div key={s.label} className={clsx("rise-in relative p-4 md:p-5", i === 3 ? "bg-marker" : "bg-surface")} style={stagger(i)}>
          <p className="text-[14px] font-semibold text-ink-2">{s.label}</p>
          <p className="sign tabular mt-2 text-[44px]">
            <CountUp value={s.n} />
          </p>
          {s.rate && <p className="mt-1 text-[13px] text-ink-2">{s.rate}</p>}
        </div>
      ))}
      <div className="rise-in col-span-2 bg-ink p-4 text-white md:col-span-1 md:p-5" style={stagger(4)}>
        <p className="text-[14px] font-semibold text-white/70">Conversion</p>
        <p className="sign tabular mt-2 text-[44px] text-marker">{pct(t.conversion, 1)}</p>
        <p className="mt-1 text-[13px] text-white/70">
          {t.scans ? `${t.from_link} of ${t.scans} who opened the link came in with its code` : "Shows once people open the link"}
        </p>
      </div>
      {t.bills > 0 && (
        <p className="col-span-2 bg-surface px-4 py-3 text-[14px] text-ink-2 md:col-span-5 md:px-5">
          <span className="font-semibold text-ink">₹{t.sales.toLocaleString("en-IN")}</span> in sales from {t.bills} redeemed bill{t.bills === 1 ? "" : "s"}
          {t.average_bill != null && <>, about ₹{t.average_bill.toLocaleString("en-IN")} each</>}. Staff type the bill when they redeem, or match your payment statement on the Results page.
        </p>
      )}
      {t.returns > 0 && (
        <p className="col-span-2 bg-surface px-4 py-3 text-[14px] text-ink-2 md:col-span-5 md:px-5">
          <span className="font-semibold text-ink">{t.returns}</span> came back for a second visit with a come-back code
          {t.return_rate != null && <> ({pct(t.return_rate)} of those who redeemed)</>}.
        </p>
      )}
    </div>
  );
}

/** A round number at or above n, for chart scales (1, 2, 5, 10, 20, 50 ...). */
function niceMax(n: number) {
  if (n <= 5) return 5;
  const p = 10 ** Math.floor(Math.log10(n));
  return [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((m) => m * p).find((m) => m >= n)!;
}

/** Opens and redemptions per day, side by side on one labelled scale. A redemption is counted on the day it
 *  happened, which is often a day after the person opened the link. */
function Trend({ daily }: { daily: Analytics["daily"] }) {
  const top = niceMax(Math.max(1, ...daily.map((d) => Math.max(d.scans, d.redeems))));
  const total = daily.reduce((n, d) => n + d.scans + d.redeems, 0);
  const best = [...daily].sort((a, b) => b.redeems - a.redeems)[0];
  const day = (iso: string, opts: Intl.DateTimeFormatOptions) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", opts);
  const h = (n: number) => `${(n / top) * 100}%`;
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-[16px] font-bold">Day by day</p>
        <p className="flex items-center gap-3 text-[13px] text-ink-2">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px] bg-pen-soft ring-1 ring-inset ring-pen/40" aria-hidden /> opened
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px] bg-pen" aria-hidden /> redeemed
          </span>
        </p>
      </div>
      <p className="text-[14px] text-ink-2">
        {total && best?.redeems ? `Most redemptions: ${day(best.date, { weekday: "long", day: "numeric", month: "short" })}, ${best.redeems}.` : "Fills in as people open the links."}
      </p>
      <div className="mt-4 flex gap-2">
        <div className="relative h-48 w-7 shrink-0 text-right text-[11px] tabular-nums text-muted" aria-hidden>
          {[top, top / 2, 0].map((v, i) => (
            <span key={i} className="absolute right-0 -translate-y-1/2" style={{ top: `${(1 - v / top) * 100}%` }}>
              {v}
            </span>
          ))}
        </div>
        <div className="min-w-0 flex-1">
          <div className="relative h-48" role="img" aria-label={daily.map((d) => `${d.date}: ${d.scans} opened, ${d.redeems} redeemed`).join("; ")}>
            {[0, 0.5, 1].map((f) => (
              <span key={f} className={clsx("absolute inset-x-0 border-t", f === 0 ? "border-ink" : "border-dashed border-line")} style={{ bottom: `${f * 100}%` }} aria-hidden />
            ))}
            <div className="absolute inset-0 flex items-end gap-[6%] px-1">
              {daily.map((d, i) => (
                <div key={d.date} className="flex h-full min-w-0 max-w-16 flex-1 items-end justify-center gap-[3px]" title={`${day(d.date, { weekday: "short", day: "numeric", month: "short" })}: ${d.scans} opened, ${d.claims} claimed, ${d.redeems} redeemed`}>
                  {(["scans", "redeems"] as const).map((k) => (
                    <div key={k} className="relative flex h-full w-1/2 flex-col items-center justify-end">
                      {d[k] > 0 && <span className={clsx("mb-0.5 text-[11px] font-semibold tabular-nums", k === "scans" ? "text-ink-2" : "text-pen")}>{d[k]}</span>}
                      <div
                        className={clsx("w-full origin-bottom rounded-t-[2px]", k === "scans" ? "bg-pen-soft ring-1 ring-inset ring-pen/30" : "bg-pen")}
                        style={{ height: h(d[k]), minHeight: d[k] ? 2 : 0, animation: `grow-y 600ms ${i * 40}ms both` }}
                      />
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
          <div className="mt-1.5 flex gap-[6%] px-1">
            {daily.map((d) => (
              <span key={d.date} className="min-w-0 max-w-16 flex-1 truncate text-center text-[12px] leading-tight text-muted">
                {day(d.date, { weekday: "short" }).slice(0, 2)}
                <br />
                <span className="tabular-nums">{day(d.date, { day: "numeric", month: "short" })}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** When customers were active (link opens, claims, visits at the counter, Instagram comments), by hour of day.
 *  All 24 hours always show; with nothing for this campaign yet, the whole business's last 60 days stand in. */
export function Hours({ hours, overall }: { hours: Analytics["hours"]; overall?: Analytics["hours_overall"] }) {
  const own = hours.some((h) => h.active > 0);
  const shown: { hour: number; active: number; detail?: string }[] = own
    ? hours.map((h) => ({
        hour: h.hour,
        active: h.active,
        detail: [h.scans && `${h.scans} opened`, h.claims && `${h.claims} claimed`, h.redeems && `${h.redeems} came in`, h.comments && `${h.comments} commented`].filter(Boolean).join(", "),
      }))
    : overall ?? Array.from({ length: 24 }, (_, hour) => ({ hour, active: 0 }));
  const max = Math.max(1, ...shown.map((h) => h.active));
  const total = shown.reduce((n, h) => n + h.active, 0);
  const peak = [...shown].sort((a, b) => b.active - a.active)[0];
  const at = (h: number) => `${h % 12 || 12} ${h < 12 ? "am" : "pm"}`;
  return (
    <div>
      <p className="text-[16px] font-bold">Best time to post</p>
      <p className="text-[14px] text-ink-2">
        {!total
          ? "Fills in as customers open links, claim codes, come in or comment."
          : `${own ? "" : "Across all your campaigns: "}customers were most active around ${at(peak.hour)} (${peak.active} of ${total}). ${total < 10 ? "Still early; a few more days make this surer." : "Share about an hour before."}`}
      </p>
      <div className="relative mt-4">
        <div className="flex h-32 items-end gap-[2px] border-b border-ink" role="img" aria-label={shown.map((h) => `${at(h.hour)}: ${h.active}`).join("; ")}>
          {shown.map((h) => (
            <div
              key={h.hour}
              title={`${at(h.hour)}: ${h.active ? h.detail || `${h.active} active` : "nothing yet"}`}
              className={clsx("min-w-0 flex-1 rounded-t-[2px]", h.active && h.hour === peak.hour ? "bg-pen" : h.active ? "bg-pen-soft ring-1 ring-inset ring-pen/30" : "bg-line/60")}
              style={{ height: h.active ? `${(h.active / max) * 100}%` : 3 }}
            />
          ))}
        </div>
        <div className="relative mt-1 h-4 text-[11px] text-muted" aria-hidden>
          {[0, 6, 12, 18].map((h) => (
            <span key={h} className="absolute -translate-x-1/2" style={{ left: `${((h + 0.5) / 24) * 100}%` }}>
              {h === 0 ? "12 am" : h === 12 ? "noon" : at(h)}
            </span>
          ))}
        </div>
      </div>
      <p className="mt-2 text-[12px] text-muted">Counts link opens, claimed codes, visits at the counter and Instagram comments, in Indian time.</p>
    </div>
  );
}

const LABEL: Record<string, (k: string) => string> = {
  channel: (k) => CHANNEL_LABEL[k] ?? k,
  language: (k) => LANG_LABEL[k] ?? k,
  segment: (k) => segmentLabel(k),
};

/** Conversion per group, all groups on one scale from 0% (labelled below, so 26% is never drawn as most of a bar
 *  unless the axis says so). The light band is where the real rate likely is (90%), so a
 *  group with few opens shows a wide band instead of looking certain. */
function Breakdown({ title, dim, rows }: { title: string; dim: "channel" | "language" | "segment"; rows: FunnelGroup[] }) {
  const top = Math.min(1, Math.max(0.2, ...rows.map((r) => Math.max(r.conversion ?? 0, r.likely?.[1] ?? 0))));
  const scale = Math.ceil(top * 10) / 10; // nearest 10% above the highest value, so small rates stay readable
  const w = (x: number) => `${Math.min(100, (x / scale) * 100)}%`;
  return (
    <div>
      <p className="mb-2 text-[16px] font-bold">{title}</p>
      <ul className="divide-y divide-line border-y border-line">
        {rows.map((r) => (
          <li key={r.key} className="py-2.5">
            <div className="flex items-baseline justify-between gap-2 text-[14px]">
              <span className="truncate font-semibold">{LABEL[dim](r.key)}</span>
              <span className="shrink-0 tabular-nums text-ink-2">
                {r.from_link} of {r.scans} · <span className="font-semibold text-ink">{pct(r.conversion)}</span>
              </span>
            </div>
            <div className="relative mt-1.5 h-2 rounded-full bg-sunken">
              {r.likely && <div className="absolute inset-y-0 rounded-full bg-pen/25" style={{ left: w(r.likely[0]), width: `calc(${w(r.likely[1])} - ${w(r.likely[0])})` }} />}
              <div className="grow-x absolute inset-y-0 left-0 rounded-full bg-pen" style={{ width: w(r.conversion ?? 0) }} />
            </div>
            {r.likely && (
              <p className="mt-1 text-[12px] text-muted">
                likely {pct(r.likely[0])} to {pct(r.likely[1])}
              </p>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-1.5 flex justify-between text-[11px] tabular-nums text-muted" aria-hidden>
        <span>0%</span>
        <span>{Math.round(scale * 100)}%</span>
      </p>
    </div>
  );
}

function Tips({ tips, campaignId }: { tips: Analytics["tips"]; campaignId: string }) {
  const [sent, setSent] = useState<Record<string, boolean>>({});
  if (!tips.length) return null;
  return (
    <div>
      <p className="flex items-center gap-2 text-[18px] font-bold">
        <Lightbulb size={20} weight="fill" className="text-pen" aria-hidden /> How to do better
      </p>
      <ul className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        {tips.map((t, i) => (
          <li key={t.kind + i} className={clsx("rise-in flex flex-col rounded-[var(--radius-md)] p-4 ring-1", t.priority <= 1 ? "bg-marker-soft ring-ink" : "bg-surface ring-line")} style={stagger(i)}>
            <p className="text-[16px] font-bold leading-snug">{t.title}</p>
            <p className="mt-1 flex-1 text-[14px] text-ink-2">{t.detail}</p>
            {t.ask && (
              <div className="mt-3">
                {sent[t.kind] ? (
                  <p className="text-[14px] font-semibold text-pen">Sent to Counterpart. Watch the banner at the top.</p>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    trailing={<PaperPlaneTilt size={13} weight="bold" />}
                    onClick={async () => {
                      await api(`/campaigns/${campaignId}/agent`, { method: "POST", json: { message: t.ask } });
                      setSent({ ...sent, [t.kind]: true });
                    }}
                  >
                    Ask Counterpart to do it
                  </Button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Numbers from the channels themselves: Instagram's reach and engagement, WhatsApp's delivery and reads. */
function ChannelNumbers({ data, labels }: { data: Analytics; labels: Record<string, string> }) {
  const business = useBusiness();
  const [syncing, setSyncing] = useState(false);
  const ch = data.channels;
  if (!ch) return null;
  const ig = Object.entries(ch.instagram);
  const wa = Object.entries(ch.whatsapp);
  if (!ig.length && !wa.length) {
    if (!ch.instagram_connected && !ch.whatsapp_connected)
      return (
        <p className="text-[14px] text-ink-2">
          Connect WhatsApp and Instagram on the <a href="/channels" className="font-semibold underline underline-offset-4">Channels</a> page to see reach, engagement, deliveries and reads here.
        </p>
      );
    return <p className="text-[14px] text-ink-2">Post to Instagram or send on WhatsApp from the posts above; their numbers appear here.</p>;
  }
  const n = (x?: number) => (x == null ? "–" : x.toLocaleString("en-IN"));
  return (
    <div className={clsx("grid grid-cols-1 gap-10", ig.length > 0 && wa.length > 0 && "lg:grid-cols-2")}>
      {ig.length > 0 && (
        <div>
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-2 text-[16px] font-bold">
              <InstagramLogo size={18} aria-hidden /> Instagram
            </p>
            <Button
              size="sm"
              variant="ghost"
              disabled={syncing}
              onClick={async () => {
                setSyncing(true);
                try {
                  await api(`/businesses/${business.slug}/instagram/sync`, { method: "POST" });
                } finally {
                  setSyncing(false);
                }
              }}
            >
              <ArrowsClockwise size={14} aria-hidden /> {syncing ? "Reading…" : "Refresh"}
            </Button>
          </div>
          <p className="text-[13px] text-muted">Engagement rate = (likes + comments + saves + shares) ÷ people reached. Instagram's numbers can lag up to 48 hours.</p>
          <table className="mt-2 w-full border-t border-ink text-[14px]">
            <thead>
              <tr className="border-b border-ink text-right text-[12px] text-muted">
                <th className="w-[38%] py-1.5 text-left font-semibold">Post</th>
                <th className="py-1.5 font-semibold">Reached</th>
                <th className="hidden py-1.5 font-semibold sm:table-cell">Likes</th>
                <th className="hidden py-1.5 font-semibold sm:table-cell">Comments</th>
                <th className="hidden py-1.5 font-semibold sm:table-cell">Saves</th>
                <th className="hidden py-1.5 font-semibold sm:table-cell">Shares</th>
                <th className="py-1.5 font-semibold">Engagement</th>
              </tr>
            </thead>
            <tbody>
              {ig.map(([id, m]) => (
                <tr key={id} className="border-b border-line text-right tabular-nums">
                  <td className="max-w-0 truncate py-2 pr-2 text-left">
                    <a href={m.permalink ?? "#"} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 font-semibold hover:text-pen">
                      <span className="truncate">{labels[id] || "Post"}</span> <ArrowSquareOut size={12} className="shrink-0" aria-hidden />
                    </a>
                  </td>
                  <td className="py-2">{n(m.reach)}</td>
                  <td className="hidden py-2 sm:table-cell">{n(m.likes)}</td>
                  <td className="hidden py-2 sm:table-cell">{n(m.comments)}</td>
                  <td className="hidden py-2 sm:table-cell">{n(m.saved)}</td>
                  <td className="hidden py-2 sm:table-cell">{n(m.shares)}</td>
                  <td className="py-2 font-semibold text-pen">
                    {!m.metrics_at ? "waiting" : (m.reach ?? 0) < MIN_REACH ? <span className="font-normal text-muted" title={`Shown once ${MIN_REACH} accounts are reached; with fewer, one like swings it wildly`}>too few yet</span> : pct(m.engagement_rate, 1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {wa.length > 0 && (
        <div>
          <p className="flex items-center gap-2 text-[16px] font-bold">
            <WhatsappLogo size={18} aria-hidden /> WhatsApp
          </p>
          <p className="text-[13px] text-muted">From WhatsApp's own receipts. Clicked = opened the link in that message. Claimed and redeemed count codes asked for on WhatsApp.</p>
          <ul className="mt-2 space-y-4">
            {wa.map(([id, w]) => {
              const steps = [
                ["Sent", w.sent],
                ["Delivered", w.delivered],
                ["Read", w.read],
                ["Clicked", w.clicked],
                ["Claimed", w.claimed_on_whatsapp ?? 0],
                ["Redeemed", w.redeemed_from_whatsapp ?? 0],
              ] as const;
              const top = Math.max(1, ...steps.map((x) => x[1]));
              return (
                <li key={id}>
                  <p className="truncate text-[14px] font-semibold">{labels[id] || "Post"}</p>
                  <div className="mt-1.5 grid grid-cols-6 gap-1">
                    {steps.map(([label, v]) => (
                      <div key={label} className="text-center">
                        <div className="flex h-16 items-end rounded-[2px] bg-sunken">
                          <div className="w-full rounded-[2px] bg-pen" style={{ height: `${(v / top) * 100}%`, minHeight: v ? 2 : 0 }} />
                        </div>
                        <p className="mt-1 text-[14px] font-semibold tabular-nums">{v}</p>
                        <p className="text-[11px] text-muted">{label}</p>
                      </div>
                    ))}
                  </div>
                  {w.failed > 0 && <p className="mt-1 text-[12px] text-kumkum">{w.failed} could not be delivered.</p>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Everything about how this campaign is doing and what to change, in one place. */
/** The owner asks the Analyst to read the numbers; its suggestion lands in what needs the owner. */
function AskAnalyst({ campaignId }: { campaignId: string }) {
  const [state, setState] = useState<"idle" | "busy" | "asked" | string>("idle");
  return (
    <div className="flex flex-wrap items-center gap-3 border-y border-line py-3">
      <ChartLineUp size={20} weight="bold" className="text-pen" aria-hidden />
      <p className="min-w-0 flex-1 text-[15px] text-ink-2">
        {state === "asked" ? (
          <span className="text-pen">The Analyst is reading the results. Its suggestion will appear under what needs you, with the numbers behind it.</span>
        ) : state !== "idle" && state !== "busy" ? (
          <span className="text-kumkum">{state}</span>
        ) : (
          "The Analyst reads these numbers and the A/B tests, and suggests the next move for you to say yes or no to."
        )}
      </p>
      <Button
        size="sm"
        variant="primary"
        disabled={state === "busy" || state === "asked"}
        onClick={async () => {
          setState("busy");
          try {
            await api(`/campaigns/${campaignId}/analyst`, { method: "POST" });
            setState("asked");
          } catch (e) {
            setState(e instanceof Error ? e.message : String(e));
          }
        }}
      >
        {state === "busy" ? "Asking…" : "Ask the Analyst"}
      </Button>
    </div>
  );
}

/** Come-back codes: a customer whose code is used gets one more for the same offer, for a few days. */
function ComeBack({ campaignId, repeat, onChange }: { campaignId: string; repeat: NonNullable<Analytics["repeat"]>; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  async function set(days: number | null) {
    setBusy(true);
    try {
      await api(`/campaigns/${campaignId}/return-codes`, { method: "PUT", json: { days } });
      onChange();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
      <div>
        <p className="flex items-center gap-2 text-[16px] font-bold">
          <ArrowUUpLeft size={18} weight="bold" className="text-pen" aria-hidden /> Come-back codes
        </p>
        <p className="mt-1 max-w-[62ch] text-[14px] text-ink-2">
          {repeat.days
            ? `Each customer whose code is used gets a second code for the same offer, valid from the next day for ${repeat.days} days. It counts as a return visit, not a new customer.`
            : "Give each customer whose code is used one more code for the same offer, to bring them back. Off for this campaign."}
        </p>
        {repeat.issued > 0 && (
          <p className="mt-2 text-[14px]">
            <span className="font-semibold">{repeat.came_back}</span> of {repeat.issued} came back
            {repeat.rate != null && <> ({pct(repeat.rate)})</>}
            {repeat.waiting > 0 && <span className="text-muted">; {repeat.waiting} codes still open</span>}
          </p>
        )}
      </div>
      <label className="flex items-center gap-2 text-[14px] font-semibold">
        <span>Valid for</span>
        <select
          value={repeat.days ?? ""}
          disabled={busy}
          onChange={(e) => set(e.target.value ? Number(e.target.value) : null)}
          className="h-9 rounded-[var(--radius-sm)] bg-surface px-2 shadow-[inset_0_0_0_1.5px_var(--color-line-strong)]"
        >
          <option value="">Off</option>
          {[7, 14, 30].map((d) => (
            <option key={d} value={d}>
              {d} days
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

export function CampaignAnalytics({ campaignId, assets }: { campaignId: string; assets: Asset[] }) {
  const business = useBusiness();
  const { data, reload } = useResource<Analytics>(`/campaigns/${campaignId}/analytics`, (e) => e.campaign_id === campaignId && (e.type.startsWith("outcome.") || e.type === "assets.published" || e.type === "campaign.return_codes"));
  const [busy, setBusy] = useState(false);
  if (!data) return <Skeleton className="h-72" />;
  const image = Object.fromEntries(assets.map((a) => [a.id, a.image_url]));
  const t = data.totals;

  return (
    <div className="space-y-10">
      {(data.simulated > 0 || business.is_demo) && (
        <div className="flex flex-wrap items-center gap-3 text-[14px]">
          {data.simulated > 0 && (
            <span className="stamp text-turmeric">
              <Sparkle size={12} weight="fill" aria-hidden /> includes {data.simulated} simulated results
            </span>
          )}
          {business.is_demo && (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api(`/campaigns/${campaignId}/simulate`, { method: "POST" });
                  await reload();
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Simulating…" : data.simulated > 0 ? "Simulate again (replaces the simulated results)" : "Simulate customers for this campaign (demo)"}
            </Button>
          )}
        </div>
      )}

      <Funnel t={t} />
      {data.ai && <CostLine ai={data.ai} />}
      {t.posts > 0 && <AskAnalyst campaignId={campaignId} />}
      <Tips tips={data.tips} campaignId={campaignId} />
      {data.repeat && <ComeBack campaignId={campaignId} repeat={data.repeat} onChange={reload} />}

      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Trend daily={data.daily.slice(-10)} />
        <Hours hours={data.hours} overall={data.hours_overall} />
      </div>

      {t.scans > 0 && (
        <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
          <Breakdown title="By channel" dim="channel" rows={data.by.channel} />
          <Breakdown title="By language" dim="language" rows={data.by.language} />
          <Breakdown title="By audience" dim="segment" rows={data.by.segment} />
        </div>
      )}

      <ChannelNumbers data={data} labels={Object.fromEntries(data.posts.map((p) => [p.asset_id, p.headline || p.code]))} />

      {data.posts.length > 0 && (
        <div>
          <p className="mb-2 text-[16px] font-bold">Every post, best first</p>
          <div className="overflow-x-auto">
            <table className="w-full border-t border-ink text-[14px]">
              <thead>
                <tr className="border-b border-ink text-left text-[13px] text-muted">
                  <th className="py-2 font-semibold">Post</th>
                  <th className="hidden py-2 text-right font-semibold sm:table-cell">Opened</th>
                  <th className="hidden py-2 text-right font-semibold sm:table-cell">Claimed</th>
                  <th className="hidden py-2 text-right font-semibold sm:table-cell">Redeemed</th>
                  <th className="py-2 text-right font-semibold">Conversion</th>
                </tr>
              </thead>
              <tbody>
                {data.posts.map((p, i) => (
                  <tr key={p.code} className="border-b border-line">
                    <td className="py-2.5 pr-3">
                      <span className="flex min-w-0 items-center gap-3">
                        <span className="w-5 shrink-0 font-mono text-[12px] text-muted">{i + 1}</span>
                        {image[p.asset_id] ? <img src={image[p.asset_id]!} alt="" className="h-10 w-10 shrink-0 rounded-[3px] object-cover" /> : <span className="h-10 w-10 shrink-0 rounded-[3px] bg-sunken" />}
                        <span className="min-w-0">
                          <span className="block font-semibold leading-snug" lang={p.language}>
                            {p.headline || p.code}
                          </span>
                          <span className="block text-[13px] text-muted">
                            {CHANNEL_LABEL[p.channel]} · {LANG_LABEL[p.language]}
                            {p.variant ? ` · version ${p.variant}` : ""}
                            {data.ratings?.[p.asset_id] && (
                              <span className="font-semibold text-ink"> · ★ {data.ratings[p.asset_id].average} from {data.ratings[p.asset_id].n} visit{data.ratings[p.asset_id].n === 1 ? "" : "s"}</span>
                            )}
                          </span>
                          <span className="mt-0.5 block text-[13px] tabular-nums text-ink-2 sm:hidden">
                            {p.scans} opened · {p.claims} claimed · <span className="font-semibold text-ink">{p.redeems} redeemed</span>
                          </span>
                        </span>
                      </span>
                    </td>
                    <td className="hidden py-2.5 text-right tabular-nums sm:table-cell">{p.scans}</td>
                    <td className="hidden py-2.5 text-right tabular-nums sm:table-cell">{p.claims}</td>
                    <td className="hidden py-2.5 text-right font-semibold tabular-nums sm:table-cell">{p.redeems}</td>
                    <td className={clsx("py-2.5 text-right font-semibold tabular-nums", i === 0 && p.redeems > 0 && "text-pen")}>{pct(p.conversion)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

