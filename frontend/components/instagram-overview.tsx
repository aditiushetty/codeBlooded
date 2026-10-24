"use client";

import { ArrowClockwise, ArrowSquareOut, CaretDown, ChatCircle, Eye, Heart, InstagramLogo, Info, PaperPlaneTilt, BookmarkSimple, Users } from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { api, useResource } from "@/lib/api";
import { timeAgo } from "./ui";

type Comment = {
  id: string;
  author: string | null;
  body: string;
  category: string | null;
  translation: string | null;
  language: string;
  occurred_at: string;
  reply: string | null;
};
type Post = {
  id: string;
  caption: string;
  permalink: string | null;
  timestamp: string | null;
  picture: string | null;
  media_type: string | null;
  likes: number;
  comments: number;
  reach?: number;
  saved?: number;
  shares?: number;
  views?: number;
  engagement_rate: number | null;
  campaign?: string | null;
  campaign_id?: string | null;
  post_code?: string | null;
  read: Comment[];
  held_back: number;
};
type Overview = {
  connected: boolean;
  at?: string;
  days?: number;
  profile?: { username: string; name: string | null; followers_count: number | null; follows_count: number | null; media_count: number | null; profile_picture_url: string | null };
  totals?: Partial<Record<"reach" | "views" | "accounts_engaged" | "total_interactions" | "likes" | "comments" | "shares" | "saves" | "profile_views" | "website_clicks", number>>;
  series?: { day: string; reach: number }[];
  posts?: Post[];
  held_back?: number;
};

const TOTALS: [keyof NonNullable<Overview["totals"]>, string][] = [
  ["reach", "Accounts reached"],
  ["views", "Views"],
  ["total_interactions", "Interactions"],
  ["likes", "Likes"],
  ["comments", "Comments"],
  ["shares", "Shares"],
  ["saves", "Saves"],
  ["profile_views", "Profile visits"],
];
const KIND: Record<string, { label: string; tone: string }> = {
  praise: { label: "Praise", tone: "bg-pen-soft text-pen-ink" },
  complaint: { label: "Complaint", tone: "bg-kumkum-soft text-kumkum" },
  question: { label: "Question", tone: "bg-marker-soft text-ink" },
  suggestion: { label: "Suggestion", tone: "bg-sunken text-ink-2" },
  mention: { label: "Mention", tone: "bg-sunken text-ink-2" },
};
// Below this many accounts reached, an engagement rate says nothing (2 reached and 7 likes and comments reads as 350%).
export const MIN_REACH = 20;
const n = (v: number | null | undefined) => (v == null ? "–" : v.toLocaleString("en-IN"));

function ReachBars({ series }: { series: { day: string; reach: number }[] }) {
  const top = Math.max(1, ...series.map((s) => s.reach));
  return (
    <figure className="mt-5">
      <div className="flex h-16 items-end gap-[3px]" role="img" aria-label={`Accounts reached per day, last ${series.length} days, highest ${top}`}>
        {series.map((s) => (
          <span
            key={s.day}
            title={`${new Date(s.day).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}: ${s.reach} reached`}
            className={clsx("flex-1 rounded-t-[2px]", s.reach ? "bg-pen" : "bg-line")}
            style={{ height: `${Math.max(4, (s.reach / top) * 100)}%` }}
          />
        ))}
      </div>
      <figcaption className="mt-1.5 flex justify-between text-[12px] text-muted">
        <span>{series[0] && new Date(series[0].day).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
        <span>Accounts reached per day</span>
        <span>Today</span>
      </figcaption>
    </figure>
  );
}

function PostRow({ p }: { p: Post }) {
  const [open, setOpen] = useState(false);
  const stats: [typeof Heart, number | undefined, string][] = [
    [Heart, p.likes, "likes"],
    [ChatCircle, p.comments, "comments"],
    [Eye, p.reach, "reached"],
    [BookmarkSimple, p.saved, "saves"],
    [PaperPlaneTilt, p.shares, "shares"],
  ];
  return (
    <li className="py-4">
      <div className="flex gap-4">
        {p.picture ? (
          <img src={p.picture} alt="" className="h-20 w-16 shrink-0 rounded-[var(--radius-sm)] object-cover ring-1 ring-line" />
        ) : (
          <span className="flex h-20 w-16 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-sunken text-muted">
            <InstagramLogo size={18} aria-hidden />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-[14px] text-ink">{p.caption || "No caption"}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-muted">
            {p.timestamp && <span>{timeAgo(p.timestamp)}</span>}
            {p.campaign && p.campaign_id && (
              <Link href={`/campaigns/${p.campaign_id}`} className="font-semibold text-pen hover:underline">
                {p.campaign}
              </Link>
            )}
            {p.post_code && <span className="font-mono">{p.post_code}</span>}
            {p.permalink && (
              <a href={p.permalink} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-ink">
                Open <ArrowSquareOut size={11} aria-hidden />
              </a>
            )}
          </p>
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] tabular-nums">
            {stats.map(([Icon, v, label]) => (
              <span key={label} className="inline-flex items-center gap-1" title={label}>
                <Icon size={14} className="text-ink-2" aria-hidden /> <span className="font-semibold">{n(v)}</span>
                <span className="text-muted">{label}</span>
              </span>
            ))}
            {p.engagement_rate != null && (p.reach ?? 0) >= MIN_REACH && <span className="font-semibold text-pen">{(p.engagement_rate * 100).toFixed(1)}% engaged</span>}
          </p>
        </div>
      </div>
      {p.comments > 0 && p.read.length === 0 && p.held_back > 0 && (
        <p className="ml-20 mt-2 text-[13px] text-muted">
          {p.held_back} comment{p.held_back === 1 ? "" : "s"} held back by Instagram until the app is published.
        </p>
      )}
      {p.read.length > 0 && (
        <div className="ml-20 mt-2">
          <button onClick={() => setOpen(!open)} aria-expanded={open} className="press inline-flex items-center gap-1 text-[13px] font-semibold text-ink-2 hover:text-ink">
            <CaretDown size={12} className={clsx("transition-transform", open && "rotate-180")} aria-hidden />
            Read {p.read.length} comment{p.read.length === 1 ? "" : "s"}
            {p.held_back > 0 && <span className="font-normal text-muted"> · {p.held_back} held back by Instagram</span>}
          </button>
          {open && (
            <ul className="mt-2 space-y-2.5 border-l-2 border-line pl-3">
              {p.read.map((c) => (
                <li key={c.id} className="text-[14px]">
                  <span className="font-semibold">@{c.author ?? "someone"}</span>{" "}
                  {c.category && KIND[c.category] && <span className={clsx("ml-1 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[11px] font-semibold", KIND[c.category].tone)}>{KIND[c.category].label}</span>}
                  <span className="ml-2 text-[12px] text-muted">{timeAgo(c.occurred_at)}</span>
                  <p lang={c.language} className="text-ink">{c.body}</p>
                  {c.translation && <p className="text-[13px] italic text-ink-2">“{c.translation}”</p>}
                  {c.reply && <p className="mt-0.5 text-[13px] text-pen">You replied: {c.reply}</p>}
                </li>
              ))}
              {p.held_back > 0 && (
                <li className="text-[13px] text-muted">
                  {p.held_back} more comment{p.held_back === 1 ? "" : "s"} counted by Instagram but not shared with Counterpart yet.
                </li>
              )}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

/** Results page: the connected Instagram account. Meta's numbers (followers, reach, likes, saves, shares) plus the comments Counterpart has read. */
export function InstagramOverview({ slug }: { slug: string }) {
  const { data, error, reload } = useResource<Overview>(`/businesses/${slug}/instagram/overview`, (e) => e.type.startsWith("customers.instagram") || e.type === "instagram.published");
  const [busy, setBusy] = useState(false);

  if (error) return <p className="text-[14px] text-kumkum">{error}</p>;
  if (!data) return <div className="skeleton h-48 w-full" />;
  if (!data.connected)
    return (
      <p className="text-[14px] text-ink-2">
        <Link href="/channels" className="font-semibold text-pen hover:underline">
          Connect Instagram
        </Link>{" "}
        to see followers, reach, likes and comments for every post here.
      </p>
    );

  const p = data.profile!;
  const t = data.totals ?? {};
  return (
    <div>
      <div className="flex flex-wrap items-center gap-4">
        {p.profile_picture_url ? (
          <img src={p.profile_picture_url} alt="" className="h-12 w-12 rounded-full ring-1 ring-line" />
        ) : (
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-sunken">
            <InstagramLogo size={20} aria-hidden />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-[17px] font-semibold">@{p.username}</p>
          <p className="flex flex-wrap gap-x-3 text-[13px] text-ink-2">
            <span className="inline-flex items-center gap-1">
              <Users size={13} aria-hidden /> {n(p.followers_count)} {p.followers_count === 1 ? "follower" : "followers"}
            </span>
            <span>{n(p.media_count)} posts</span>
          </p>
        </div>
        <p className="text-[12px] text-muted">From Instagram {data.at ? timeAgo(data.at) : ""}</p>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api(`/businesses/${slug}/instagram/sync`, { method: "POST" });
              await api(`/businesses/${slug}/instagram/overview?refresh=true`);
              await reload();
            } finally {
              setBusy(false);
            }
          }}
          className="press inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 text-[13px] font-semibold text-pen hover:bg-pen-soft disabled:opacity-50"
        >
          <ArrowClockwise size={14} className={clsx(busy && "animate-spin")} aria-hidden /> {busy ? "Reading…" : "Refresh"}
        </button>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-lg)] bg-line ring-1 ring-line sm:grid-cols-4">
        {TOTALS.map(([k, label]) => (
          <div key={k} className="bg-surface px-4 py-3">
            <dt className="text-[12px] text-muted">{label}</dt>
            <dd className="sign mt-0.5 text-[26px] leading-none tabular-nums">{n(t[k])}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-1.5 text-[12px] text-muted">Last {data.days} days, as Instagram reports them. Instagram can take up to 48 hours to count.</p>

      {data.series && data.series.length > 0 && <ReachBars series={data.series} />}

      {(data.held_back ?? 0) > 0 && (
        <p className="mt-5 flex items-start gap-2 rounded-[var(--radius-sm)] bg-turmeric-soft px-3 py-2.5 text-[13px] text-turmeric">
          <Info size={15} className="mt-0.5 shrink-0" aria-hidden />
          Instagram counts {data.held_back} comment{data.held_back === 1 ? "" : "s"} it isn&apos;t sharing yet. Meta withholds comment text while the Counterpart app is unpublished; publishing the app in the Meta dashboard lets them through. Likes, reach and views
          above are complete.
        </p>
      )}

      {data.posts && data.posts.length > 0 && (
        <ul className="mt-6 divide-y divide-line border-y border-line">
          {data.posts.map((post) => (
            <PostRow key={post.id} p={post} />
          ))}
        </ul>
      )}
    </div>
  );
}
