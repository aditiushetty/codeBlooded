import { HandTap, Receipt } from "@phosphor-icons/react";
import type { AiCost, Effort } from "@/lib/types";

const rupees = (n: number) =>
  n >= 100 ? `₹${Math.round(n).toLocaleString("en-IN")}` : n >= 1 ? `₹${n.toFixed(1)}` : n > 0 ? `${Math.max(1, Math.round(n * 100))} paise` : "₹0";
const mins = (m: number) => (m < 1 ? "under a minute" : m < 90 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} hours`);

/** "₹3 of AI, ₹4,200 at the counter": the campaign's model calls against the bills that came with its codes. */
export function CostLine({ ai }: { ai: AiCost }) {
  if (!ai.calls) return null;
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 text-[15px] text-ink-2">
      <Receipt size={16} weight="bold" className="translate-y-0.5 text-pen" aria-hidden />
      <span>
        <b className="text-ink">{rupees(ai.rupees)}</b> of AI ({ai.calls} model calls)
        {ai.sales > 0 ? (
          <>
            , <b className="text-ink">{rupees(ai.sales)}</b> at the counter
            {ai.sales_per_ai_rupee ? <>: about {rupees(ai.sales_per_ai_rupee)} of sales for every rupee of AI</> : null}.
          </>
        ) : ai.redeems ? (
          <>, {ai.redeems} redeemed so far. Type bills at the counter or match your statement to see sales.</>
        ) : (
          "."
        )}
      </span>
      <span className="text-[12px] text-muted">
        AI cost estimated from {(ai.input_tokens + ai.output_tokens).toLocaleString("en-IN")} tokens at ${ai.price.in_usd_per_m.toFixed(2)}/${ai.price.out_usd_per_m.toFixed(2)} per million (paid list price); on free tiers it is ₹0.
      </span>
    </p>
  );
}

/** How much of the owner's attention the campaign took, from the brief to the first live post. */
export function EffortLine({ e }: { e: Effort }) {
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 text-[15px] text-ink-2">
      <HandTap size={16} weight="bold" className="translate-y-0.5 text-pen" aria-hidden />
      <span>
        {e.live ? "From your brief to live posts: " : "Your part so far: "}
        <b className="text-ink">
          {e.taps} tap{e.taps === 1 ? "" : "s"}
        </b>
        , {mins(e.minutes)}
        {e.minutes >= 1 && (
          <span className="text-muted">
            {" "}
            (the team worked {mins(e.team_minutes)}
            {e.waiting_minutes >= 1 ? `, waited for you ${mins(e.waiting_minutes)}` : ""})
          </span>
        )}
        .
      </span>
    </p>
  );
}
