"use client";

import { ShieldCheck } from "@phosphor-icons/react";
import { useResource } from "@/lib/api";
import { Skeleton } from "./ui";

interface Report {
  ran_at: number;
  live: boolean;
  model: string | null;
  caught: number;
  bad_total: number;
  false_alarms: number;
  good_total: number;
  by_layer: Record<string, number>;
  by_category: Record<string, { total: number; caught: number }>;
  no_verdict?: number[];
  missed: { id: number; category: string; language: string; headline: string; why_bad: string }[];
  wrongly_blocked: { id: number; headline: string; reason: string }[];
  note: string | null;
}

const human = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** The Checker test: 50 posts that must never go out (wrong price, invented date, broken Kannada, a promise the
 *  offer never made) and 10 good ones, run through the same checks as every real post. */
export function CheckerTest({ slug }: { slug: string }) {
  const { data } = useResource<Report>(`/businesses/${slug}/checker-test`);
  if (!data) return <Skeleton className="h-40" />;
  return (
    <div className="grid gap-6 md:grid-cols-[auto_minmax(0,1fr)]">
      <div className="rounded-[var(--radius-lg)] bg-ink p-6 text-white">
        <p className="flex items-center gap-1.5 text-[13px] text-white/70">
          <ShieldCheck size={15} weight="bold" aria-hidden /> Known-bad posts caught
        </p>
        <p className="sign tabular mt-2 text-[72px] text-marker">
          {data.caught}
          <span className="text-[34px] text-white/60"> of {data.bad_total}</span>
        </p>
        <p className="mt-1 text-[14px] text-white/80">
          Good posts wrongly blocked: <b className="text-white">{data.false_alarms} of {data.good_total}</b>
        </p>
        <p className="mt-3 text-[12px] text-white/60">
          {new Date(data.ran_at * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
          {data.live ? ` · meaning check on ${data.model ?? "the verification models"}` : " · rules only"}
        </p>
      </div>
      <div className="min-w-0">
        <ul className="flex flex-wrap gap-2 text-[14px]">
          {Object.entries(data.by_layer).map(([k, v]) => (
            <li key={k} className="rounded-[var(--radius-sm)] bg-pen-soft px-2.5 py-1 text-pen">
              {human(k)}: <b>{v}</b>
            </li>
          ))}
        </ul>
        <table className="mt-3 w-full text-[14px]">
          <tbody>
            {Object.entries(data.by_category).map(([k, c]) => (
              <tr key={k} className="border-b border-line">
                <td className="py-1.5">{human(k)}</td>
                <td className={`py-1.5 text-right tabular-nums ${c.caught < c.total ? "font-semibold text-kumkum" : "text-ink-2"}`}>
                  {c.caught}/{c.total}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.missed.length > 0 && (
          <div className="mt-3 text-[14px]">
            <p className="font-semibold">Still gets through</p>
            {data.missed.map((m) => (
              <p key={m.id} className="text-ink-2" lang={m.language}>
                “{m.headline}”: {m.why_bad}
              </p>
            ))}
          </div>
        )}
        {data.note && <p className="mt-3 text-[13px] text-muted">{data.note}</p>}
      </div>
    </div>
  );
}
