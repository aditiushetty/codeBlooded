"use client";

import {
  ArrowRight,
  ArrowsClockwise,
  Brain,
  ChartLineUp,
  Compass,
  Ear,
  PenNib,
  ShieldCheck,
  ShieldWarning,
  Tag,
  Translate,
  Target,
  UserCircle,
} from "@phosphor-icons/react";
import clsx from "clsx";
import { useMemo, useState } from "react";
import { useResource } from "@/lib/api";
import type { LedgerEvent } from "@/lib/types";
import { Skeleton, timeAgo } from "./ui";

/** Who speaks in the feed: the agents, the rules (fact guard and policy gate) and the owner. */
const WHO = {
  orchestrator: { name: "Orchestrator", Icon: Brain },
  brief: { name: "Brief agent", Icon: Target },
  offer: { name: "Offer agent", Icon: Tag },
  change: { name: "Change agent", Icon: ArrowsClockwise },
  language: { name: "Language agent", Icon: Translate },
  writer: { name: "Writer", Icon: PenNib },
  checker: { name: "Checker", Icon: ShieldCheck },
  analyst: { name: "Analyst", Icon: ChartLineUp },
  listener: { name: "Customer listener", Icon: Ear },
  scout: { name: "Scout", Icon: Compass },
  rules: { name: "Rules", Icon: ShieldWarning },
  you: { name: "You", Icon: UserCircle },
} as const;
type Who = keyof typeof WHO;
type Tone = "work" | "reject" | "ask" | "done";

interface Turn {
  id: number;
  at: string;
  who: Who;
  to?: Who;
  text: string;
  tone: Tone;
  detail?: string[];
}

const LABEL: Record<string, string> = {
  draft_offer_facts: "draft the offer",
  revise_offer_facts: "change the offer",
  lock_facts: "lock the offer",
  generate_copy: "write posts",
  validate_assets: "check posts",
  publish_assets: "publish",
  translate_offer: "write the offer in every language",
  preview_change: "preview the change",
  set_campaign_plan: "save the plan",
  propose_next_move: "suggest the next move",
  draft_replies: "draft replies",
  raise_issue: "raise an issue",
  suggest_campaign: "suggest a campaign",
  decide_experiment: "decide the A/B test",
  record_learning: "remember what worked",
};
const LANG: Record<string, string> = { en: "English", kn: "Kannada", hi: "Hindi" };
const asWho = (k: unknown): Who => (typeof k === "string" && k in WHO ? (k as Who) : "orchestrator");
const n = (k: number, one: string, many = `${one}s`) => `${k} ${k === 1 ? one : many}`;
type R = Record<string, any>; // tool results are free-form JSON from the backend

function toolTurn(e: LedgerEvent): Omit<Turn, "id" | "at"> | null {
  const tool = e.type.slice(5);
  const p = e.payload as R;
  const who = asWho(p.agent);
  const res: R = p.result ?? {};
  const args: R = (typeof p.args === "object" && p.args) || {};
  const label = LABEL[tool] ?? tool.replace(/_/g, " ");
  if ((tool.startsWith("get_") && tool !== "get_results") || (tool.startsWith("ask_") && tool !== "ask_owner")) return null;
  if (res.queued_for_owner_approval)
    return { who, to: "you", tone: "ask", text: `Asked you to approve: ${args.summary ?? label}` };
  if (res.precondition_failed)
    return { who: "rules", to: who, tone: "reject", text: `Stopped the ${WHO[who].name} from trying to ${label}.`, detail: [res.precondition_failed] };
  if (res.error) return { who, tone: "reject", text: `Could not ${label}.`, detail: [String(res.error)] };

  switch (tool) {
    case "ask_owner":
      return { who, to: "you", tone: "ask", text: `Asked you: ${args.question}` };
    case "evaluate_offer":
      return { who, tone: "work", text: `Margin check: ${res.summary ?? res.verdict}` };
    case "draft_offer_facts":
    case "revise_offer_facts": {
      const gaps: R[] = res.gaps ?? [];
      const blocking = gaps.filter((g) => g.blocks);
      return {
        who,
        tone: "work",
        text: blocking.length
          ? `Wrote the offer down. Still missing: ${blocking.map((g) => g.issue.replace(/\.$/, "").toLowerCase()).join("; ")}.`
          : `Wrote the offer down; nothing left for a customer to guess${res.margin?.verdict ? `, margin ${res.margin.verdict.replace("_", " ")}` : ""}.`,
      };
    }
    case "translate_offer": {
      const rows: R[] = res.wording ?? [];
      const by = (f: string) => rows.filter((r) => r.from === f).length;
      const bad = rows.filter((r) => r.issue);
      return {
        who,
        tone: bad.length || res.missing?.length ? "reject" : "work",
        text: `${[...new Set(rows.map((r) => LANG[r.language] ?? r.language))].join(" and ")} wording: ${[
          by("sarvam") && `${by("sarvam")} translated by Sarvam`,
          by("agent") && `${by("agent")} written in its own words`,
          by("kept") && `${by("kept")} unchanged`,
        ]
          .filter(Boolean)
          .join(", ")}.${bad.length ? "" : " All match the English."}`,
        detail: bad.map((r) => `${LANG[r.language] ?? r.language} “${r.wording}”: ${r.issue}`),
      };
    }
    case "preview_change": {
      const posts: R = res.posts ?? {};
      const c = (k: string) => (posts[k] ?? []).length;
      return {
        who,
        tone: "work",
        text: `This changes ${(res.changed ?? []).join(", ") || "nothing"}: ${n(c("rewrite"), "post")} to rewrite, ${n(c("refill"), "post")} only get the new offer box, ${n(c("untouched"), "post")} untouched.`,
      };
    }
    case "generate_copy": {
      const assets: R[] = res.assets ?? [];
      const sentBack = assets.filter((a) => a.first_draft_blocked_by?.length);
      return {
        who,
        tone: "work",
        text: `Wrote ${n(assets.length, "post")}.${sentBack.length ? ` The rules sent ${n(sentBack.length, "first draft")} back, and it rewrote them.` : ""}`,
        detail: sentBack.map((a) => a.first_draft_blocked_by[0]),
      };
    }
    case "validate_assets": {
      const results: R[] = Object.values(res.results ?? {});
      const failed = results.filter((r) => !r.passed);
      return {
        who: "checker",
        tone: failed.length ? "reject" : "work",
        text: failed.length ? `Rejected ${failed.length} of ${n(results.length, "post")}.` : `Passed ${n(results.length, "post")}: every promise matches the offer.`,
        detail: failed.flatMap((r) => r.why ?? []),
      };
    }
    case "set_campaign_plan": {
      const cells: R[] = (args.plan as R)?.cells ?? [];
      const aud = [...new Set(cells.map((c) => c.segment))].join(", ");
      const kpi: R = (args.goal as R)?.kpi ?? {};
      return {
        who,
        tone: "work",
        text: `Planned ${n(cells.length, "post")} for ${aud || "the brief"}${kpi.target ? `; goal: ${kpi.target} ${String(kpi.metric ?? "").replace(/_/g, " ")}${kpi.window_days ? ` in ${kpi.window_days} days` : ""}` : ""}.`,
      };
    }
    case "get_results": {
      const t: R = res.totals ?? {};
      return { who, tone: "work", text: res.too_early ?? `Read the results: ${t.scans ?? 0} opened, ${t.claims ?? 0} claimed a code, ${t.redeems ?? 0} came in${t.returns ? `, ${t.returns} came back` : ""}.` };
    }
    case "propose_next_move":
    case "suggest_campaign":
    case "raise_issue":
      return { who, to: "you", tone: "ask", text: `${tool === "raise_issue" ? "Told you" : "Suggested"}: ${args.title}` };
    case "draft_replies":
      return { who, tone: "work", text: `Drafted ${n((res.drafts ?? []).filter((d: R) => d.draft).length, "reply", "replies")} for you to read and send.` };
    case "lock_facts":
      return null; // the owner's lock shows as its own event
    default:
      return { who, tone: "work", text: label.charAt(0).toUpperCase() + label.slice(1) + "." };
  }
}

function turnOf(e: LedgerEvent): Turn | null {
  const p = e.payload as R;
  const base = { id: e.id, at: e.created_at };
  const after = (s: string) => s.replace(/^[^:]+:\s*/, "");
  if (e.type.startsWith("tool.") && p.agent) {
    const t = toolTurn(e);
    return t && { ...base, ...t };
  }
  switch (e.type) {
    case "agent.started":
      return { ...base, who: asWho(p.agent), tone: "work", text: `Picked up: ${after(e.summary)}` };
    case "agent.handoff":
      return { ...base, who: "orchestrator", to: asWho(p.agent), tone: "work", text: (p.task as R)?.task ?? after(e.summary) };
    case "agent.reported":
      return { ...base, who: asWho(p.agent), to: "orchestrator", tone: "done", text: after(e.summary) };
    case "agent.finished":
      return { ...base, who: asWho(p.agent), to: "you", tone: "done", text: e.summary };
    case "scout.ideas":
      return { ...base, who: "scout", to: "you", tone: "done", text: after(e.summary) };
    case "bills.imported":
    case "campaign.return_codes":
    case "moment.added":
      return { ...base, who: "you", tone: "done", text: e.summary };
    case "agent.failed":
      return { ...base, who: "rules", tone: "reject", text: e.summary };
    case "facts.wording_checked":
      return { ...base, who: "checker", tone: p.status === "failed" ? "reject" : "work", text: e.summary };
    case "asset.revised":
      return p.passed === false ? { ...base, who: "rules", tone: "reject", text: e.summary } : null;
    case "facts.locked":
    case "approval.decided":
    case "owner.said":
      return e.actor === "owner" ? { ...base, who: "you", tone: "done", text: e.summary } : null;
    default:
      return null;
  }
}

/** The agents talking to each other, from the work ledger: hand-offs, reports, rejections and what needs you. */
export function TeamFeed({ slug, campaignId, limit = 14 }: { slug: string; campaignId?: string; limit?: number }) {
  const qs = new URLSearchParams({ limit: "150", ...(campaignId ? { campaign_id: campaignId } : {}) });
  const { data } = useResource<LedgerEvent[]>(`/businesses/${slug}/ledger?${qs}`);
  const [all, setAll] = useState(false);
  const turns = useMemo(() => (data ?? []).slice().reverse().map(turnOf).filter((t): t is Turn => t !== null), [data]);
  const working = useMemo(() => {
    const last = (data ?? []).find((e) => e.type.startsWith("agent."));
    return !!last && !["agent.finished", "agent.failed"].includes(last.type) && Date.now() - new Date(last.created_at).getTime() < 5 * 60_000;
  }, [data]);

  if (!data) return <Skeleton className="h-40" />;
  if (!turns.length) return <p className="text-[14px] text-muted">The team has not worked on this yet. Its hand-offs and checks will show here as they happen.</p>;
  const shown = all ? turns : turns.slice(-limit);

  return (
    <div>
      {working && (
        <p className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-pen">
          <span className="pulse-dot h-2 w-2 rounded-full bg-kumkum" aria-hidden /> Working now
        </p>
      )}
      {turns.length > shown.length && (
        <button type="button" onClick={() => setAll(true)} className="press mb-2 text-[13px] font-semibold text-pen underline decoration-pen/30 underline-offset-4">
          Show {n(turns.length - shown.length, "earlier step")}
        </button>
      )}
      <ol className="border-l border-ink/20" aria-live="polite">
        {shown.map((t) => {
          const { Icon, name } = WHO[t.who];
          return (
            <li
              key={t.id}
              className={clsx(
                "relative -ml-px border-l-2 py-2.5 pl-4",
                t.tone === "reject" ? "border-kumkum" : t.tone === "ask" ? "border-marker" : t.who === "you" ? "border-ink" : "border-transparent",
              )}
            >
              <p className="flex flex-wrap items-center gap-x-1.5 font-receipt text-[12px] uppercase tracking-wide">
                <Icon size={14} weight="bold" aria-hidden className={t.who === "rules" ? "text-kumkum" : t.who === "you" ? "text-ink" : "text-pen"} />
                <span className={t.who === "rules" ? "text-kumkum" : t.who === "you" ? "text-ink" : "text-pen"}>{name}</span>
                {t.to && (
                  <>
                    <ArrowRight size={11} weight="bold" aria-label="to" className="text-muted" />
                    <span className={t.to === "you" ? "text-ink" : "text-pen"}>{WHO[t.to].name}</span>
                  </>
                )}
                <span className="ml-auto normal-case tracking-normal text-muted">{timeAgo(t.at)}</span>
              </p>
              <p className={clsx("mt-1 text-[15px] leading-snug", t.tone === "reject" ? "text-kumkum" : "text-ink-2")}>
                {t.tone === "ask" ? <span className="hl">{t.text}</span> : t.text}
              </p>
              {t.detail?.length ? (
                <ul className="mt-1 space-y-0.5 text-[13px] text-ink-2">
                  {t.detail.slice(0, 4).map((d, i) => (
                    <li key={i} className="before:mr-1.5 before:text-kumkum before:content-['×']">
                      {d}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
