"use client";

import { ArrowRight, CaretDown, Check, Copy, CursorClick, DeviceMobile, DownloadSimple, InstagramLogo, Link as LinkIcon, QrCode, Storefront, Trophy, WhatsappLogo } from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { useEffect, useState } from "react";
import { BillImport } from "@/components/bill-import";
import { Hours } from "@/components/campaign-analytics";
import { CostLine } from "@/components/effort-cost";
import { InstagramOverview } from "@/components/instagram-overview";
import { CountUp } from "@/components/motion";
import { Shell } from "@/components/shell";
import { CHANNEL_LABEL, Empty, LANG_LABEL, PageHeader, segmentLabel, Skeleton, stagger } from "@/components/ui";
import { useResource } from "@/lib/api";
import { useBusiness } from "@/lib/business";
import type { ResultRow, Results } from "@/lib/types";

const CHANNEL_ICON = { instagram_post: InstagramLogo, instagram_story: DeviceMobile, poster: Storefront, whatsapp: WhatsappLogo } as const;
const pct = (x: number | null) => (x === null ? "–" : `${(x * 100).toFixed(x < 0.1 ? 1 : 0)}%`);

const HOW = [
  { icon: LinkIcon, title: "A link for every post", text: "Each post gets its own short link and QR code when you approve it." },
  { icon: CursorClick, title: "Customers open and claim", text: "Opening counts as a visit. Tapping “Get my code” counts as a claim." },
  { icon: QrCode, title: "Staff redeem at the counter", text: "Typing the code on the Counter screen counts the sale for that exact post." },
];

function CopyLink({ link }: { link: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard?.writeText(link);
        setDone(true);
        setTimeout(() => setDone(false), 1600);
      }}
      className="press inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-sunken px-3 py-1.5 text-[13px] font-medium text-ink hover:bg-line"
      aria-label={`Copy link ${link}`}
    >
      {done ? <Check size={13} weight="bold" className="text-pen" aria-hidden /> : <Copy size={13} aria-hidden />}
      {done ? "Copied" : "Copy link"}
    </button>
  );
}

function PostRow({ r, best, i }: { r: ResultRow; best: boolean; i: number }) {
  const Icon = CHANNEL_ICON[r.channel];
  return (
    <li className="rise-in flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-line py-4 md:flex-nowrap" style={stagger(Math.min(i, 8))}>
      <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-sunken text-ink">
        <Icon size={19} aria-hidden />
      </span>
      <div className="min-w-0 flex-1 basis-48">
        <p className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          {CHANNEL_LABEL[r.channel]} <span className="font-normal text-muted">in {LANG_LABEL[r.language]}</span>
          {best && (
            <span className="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-pen-soft px-2 py-0.5 text-[12px] font-medium text-pen-ink">
              <Trophy size={11} weight="fill" aria-hidden /> Best so far
            </span>
          )}
        </p>
        <p className="truncate text-[13px] text-muted">
          For {segmentLabel(r.segment).toLowerCase()}
          {r.variant && `, variant ${r.variant}`} <span className="font-receipt text-ink-2">· {r.code}</span>
        </p>
      </div>
      <dl className="flex gap-5 text-right">
        {[
          ["Opened", r.scans],
          ["Claimed", r.claims],
          ["Redeemed", r.redeemed],
        ].map(([l, n]) => (
          <div key={l as string}>
            <dd className="text-[17px] font-semibold leading-none tabular-nums">{n}</dd>
            <dt className="mt-1 text-[12px] text-muted">{l}</dt>
          </div>
        ))}
        <div>
          <dd className={clsx("text-[17px] font-semibold leading-none tabular-nums", r.conversion ? "text-pen" : "text-muted")}>{pct(r.conversion)}</dd>
          <dt className="mt-1 text-[12px] text-muted">Converted</dt>
        </div>
      </dl>
      <div className="flex gap-1.5">
        <CopyLink link={r.link} />
        <a href={`/api/public/qr/${r.code}.png`} download={`qr-${r.code}.png`} className="press inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-sunken px-3 py-1.5 text-[13px] font-medium text-ink hover:bg-line">
          <DownloadSimple size={13} aria-hidden /> QR
        </a>
      </div>
    </li>
  );
}

const TABS = [
  { id: "posts", label: "By post" },
  { id: "instagram", label: "Instagram" },
  { id: "sales", label: "Match your sales" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export default function ResultsPage() {
  const business = useBusiness();
  const [tab, setTab] = useState<Tab>("posts");
  useEffect(() => {
    const h = window.location.hash.slice(1);
    if (TABS.some((x) => x.id === h)) setTab(h as Tab);
  }, []);
  const pick = (t: Tab) => {
    setTab(t);
    history.replaceState(null, "", `#${t}`);
  };
  const { data, reload } = useResource<Results>(`/businesses/${business.slug}/results`, (e) => e.type.startsWith("outcome.") || e.type === "assets.published" || e.type === "bills.imported");
  const groups = new Map<string, ResultRow[]>();
  for (const r of data?.posts ?? []) groups.set(r.campaign_id, [...(groups.get(r.campaign_id) ?? []), r]);
  const t = data?.totals;

  return (
    <Shell>
      <PageHeader title="Results" sub="Every post has its own link and code, so you can see which message actually brought people in." />

      {!data ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <section aria-label="Totals">
            {(t?.simulated ?? 0) > 0 && (
              <p className="stamp mb-4 text-turmeric">Includes {t!.simulated} simulated results (demo)</p>
            )}
            <div className="grid grid-cols-1 gap-px overflow-hidden rounded-[var(--radius-lg)] bg-ink ring-1 ring-ink sm:grid-cols-2 lg:grid-cols-4">
              {[
                { n: t?.scans ?? 0, label: "opened a post's link" },
                { n: t?.claims ?? 0, label: "claimed an offer code" },
                { n: t?.redeemed ?? 0, label: "redeemed at your counter", hero: true },
              ].map((x, i) => (
                <div key={x.label} className={clsx("rise-in p-6", x.hero ? "bg-marker" : "bg-surface")} style={stagger(i)}>
                  <p className="sign tabular text-[72px]">
                    <CountUp value={x.n} />
                  </p>
                  <p className="mt-1 text-[14px] text-ink-2">{x.label}</p>
                </div>
              ))}
              <div className="rise-in bg-ink p-6 text-white" style={stagger(3)}>
                <p className="sign tabular text-[72px] text-marker">
                  {t?.conversion == null ? "–" : <CountUp value={(t.conversion ?? 0) * 100} format={(n) => `${n.toFixed(1)}%`} />}
                </p>
                <p className="mt-1 text-[14px] text-white/70">{t?.conversion == null ? "conversion shows once people open links" : "of people who opened a link came in and redeemed"}</p>
              </div>
            </div>
            <dl className="mt-4 flex flex-wrap gap-x-10 gap-y-3 border-b border-line pb-4">
              <div>
                <dt className="text-[12px] text-muted">Sales with codes</dt>
                <dd className="text-[20px] font-semibold tabular-nums">₹{(t?.sales ?? 0).toLocaleString("en-IN")}</dd>
              </div>
              {t && t.came_back > 0 && (
                <div>
                  <dt className="text-[12px] text-muted">Came back a second time</dt>
                  <dd className="text-[20px] font-semibold tabular-nums">{t.came_back}</dd>
                </div>
              )}
              {data.effort && (
                <div title={`Across ${data.effort.campaigns} campaign${data.effort.campaigns === 1 ? "" : "s"}${data.effort.waiting_minutes >= 1 ? `, ${Math.round(data.effort.waiting_minutes)} minutes of it waiting for your answers` : ""}`}>
                  <dt className="text-[12px] text-muted">Your effort per campaign</dt>
                  <dd className="text-[20px] font-semibold tabular-nums">
                    {data.effort.taps} taps <span className="text-[14px] font-normal text-muted">· {Math.round(data.effort.minutes)} min</span>
                  </dd>
                </div>
              )}
            </dl>
            {data.ai && (
              <div className="mt-3">
                <CostLine ai={data.ai} />
              </div>
            )}
            {t && t.redeemed > t.scans && (
              <p className="mt-3 text-[13px] text-muted">Some codes were redeemed from printed posters or forwarded messages without opening the link, so redemptions can be higher than visits.</p>
            )}
          </section>

          <div className="mt-12 flex gap-1 border-b border-ink" role="tablist" aria-label="Results views">
            {TABS.map((x) => (
              <button
                key={x.id}
                role="tab"
                aria-selected={tab === x.id}
                onClick={() => pick(x.id)}
                className={clsx("press relative -mb-px px-4 py-2.5 text-[15px] font-semibold", tab === x.id ? "border-x border-t border-ink bg-paper text-ink" : "text-muted hover:text-ink")}
              >
                {x.label}
                {x.id === "posts" && (data.posts?.length ?? 0) > 0 && <span className="ml-1.5 text-[13px] font-normal text-muted">{data.posts.length}</span>}
              </button>
            ))}
          </div>

          <div className="pt-6" role="tabpanel">
            {tab === "posts" && (
              <section aria-label="By post">
                <p className="mb-4 text-[14px] text-ink-2">Each post&apos;s own link and code. Copy a link to share it anywhere, or download its QR code for print.</p>
              {groups.size === 0 ? (
                <Empty icon={<LinkIcon size={17} aria-hidden />}>Nothing is live yet. When you approve a post, its link and QR code appear here and start counting.</Empty>
              ) : (
                <div className="space-y-10">
                  <div className="max-w-[560px]">
                    <Hours hours={[]} overall={data.hours} />
                  </div>
                  {[...groups.entries()].map(([cid, rows]) => {
                    const best = rows.filter((r) => r.scans >= 5).sort((a, b) => (b.conversion ?? 0) - (a.conversion ?? 0))[0];
                    return (
                      <div key={cid}>
                        <Link href={`/campaigns/${cid}`} className="press mb-3 inline-flex items-center gap-1.5 rounded-full text-[17px] font-semibold tracking-tight hover:text-pen">
                          {rows[0].campaign} <ArrowRight size={15} aria-hidden />
                        </Link>
                        <ul className="border-t border-ink">
                          {rows.map((r, i) => (
                            <PostRow key={r.code} r={r} i={i} best={!!best && best.code === r.code && (best.conversion ?? 0) > 0} />
                          ))}
                        </ul>
                      </div>
                    );
                  })}
                </div>
              )}
              </section>
            )}
            {tab === "instagram" && (
              <section aria-label="Instagram">
                <p className="mb-4 text-[14px] text-ink-2">Followers, reach, likes, saves and shares from Instagram itself, with the comments on each post.</p>
                <InstagramOverview slug={business.slug} />
              </section>
            )}
            {tab === "sales" && (
              <section aria-label="Match your sales">
                <BillImport slug={business.slug} onSaved={reload} />
              </section>
            )}
          </div>

          <details className="group mt-14 border-t border-line pt-4">
            <summary className="press inline-flex cursor-pointer list-none items-center gap-2 text-[15px] font-semibold text-ink-2 hover:text-ink">
              <CaretDown size={14} weight="bold" className="transition-transform group-open:rotate-180" aria-hidden /> How are these counted?
            </summary>
            <ol className="mt-4 grid grid-cols-1 gap-px overflow-hidden rounded-[var(--radius-lg)] bg-line ring-1 ring-line md:grid-cols-3">
              {HOW.map(({ icon: Icon, title, text }, i) => (
                <li key={title} className="bg-surface p-5">
                  <span className="flex items-center justify-between">
                    <span className="font-mono text-[12px] font-semibold text-muted">{String(i + 1).padStart(2, "0")}</span>
                    <Icon size={20} weight="bold" className="text-pen" aria-hidden />
                  </span>
                  <p className="mt-2 text-[17px] font-bold [font-stretch:90%]">{title}</p>
                  <p className="mt-1 text-[14px] text-ink-2">{text}</p>
                </li>
              ))}
            </ol>
            <p className="mt-3 text-[13px] text-muted">
              Conversion counts only people who opened a post&apos;s link and then redeemed the code they got there. Codes typed straight from a caption or poster count as redeemed, not as conversion.
            </p>
          </details>
        </>
      )}
    </Shell>
  );
}
