// Every campaign moves through the same five steps. The UI always shows where a campaign is and what the owner
// does next, so the product reads as one flow instead of a set of tabs.
import type { CampaignDetail, CampaignSummary } from "./types";

export const STEPS = [
  { key: "brief", label: "Brief", who: "You" },
  { key: "offer", label: "Offer", who: "You lock it" },
  { key: "posts", label: "Posts", who: "You approve" },
  { key: "share", label: "Share", who: "You post" },
  { key: "results", label: "Results", who: "Counted" },
] as const;

export type StepKey = (typeof STEPS)[number]["key"];

/** Index of the step the campaign is on (0..4); 5 means finished. */
export function stepOfSummary(c: CampaignSummary): number {
  if (c.is_historical || c.status === "concluded" || c.status === "retired") return 5;
  if ((c.redemptions ?? 0) > 0) return 4;
  if ((c.live ?? 0) > 0) return 3;
  if (c.assets > 0 || c.facts === "locked") return 2;
  return 1;
}

/** Where a campaign stands from the list's point of view: what to say, and whether the owner is the one to act.
 *  "Counterpart is writing" only while an agent really is; a run that ended with nothing to show asks the owner
 *  to let it carry on instead of looking busy forever. */
export function summaryState(c: CampaignSummary): { step: number; text: string; you: boolean; stalled: boolean } {
  const step = stepOfSummary(c);
  const stalled = !c.working && (c.last_run === "agent.failed" || c.last_run === "agent.finished" || c.last_run === "agent.started");
  if (step === 1) {
    if (c.facts === "draft") return { step, text: "Check the offer and lock it", you: true, stalled: false };
    if (c.working) return { step, text: "Counterpart is writing the offer down", you: false, stalled: false };
    return { step, text: "Counterpart stopped before the offer was ready", you: true, stalled };
  }
  if (step === 2) {
    if ((c.ready ?? 0) > 0) return { step, text: `Approve the posts you like (${c.ready} ready)`, you: true, stalled: false };
    if (c.working) return { step, text: "Counterpart is writing the posts", you: false, stalled: false };
    return { step, text: "Counterpart stopped before the posts were ready", you: true, stalled };
  }
  return { step, text: nextAction(step), you: false, stalled: false };
}

export function stepOfDetail(d: CampaignDetail): number {
  if (d.campaign.is_historical || d.campaign.status === "concluded") return 5;
  const locked = d.facts.some((f) => f.status === "locked");
  if (!locked) return 1;
  const assets = d.assets.filter((a) => a.status !== "rejected");
  const live = assets.filter((a) => a.status === "live");
  if (!live.length) return 2;
  const redeemed = assets.reduce((n, a) => n + (a.outcomes?.redeem ?? 0), 0);
  return redeemed > 0 ? 4 : 3;
}

/** What the owner should do next on a campaign, in plain words. */
export function nextAction(step: number, d?: CampaignDetail): string {
  switch (step) {
    case 1:
      return d?.facts.some((f) => f.status === "draft") ? "Check the offer and lock it" : "Counterpart is writing the offer down";
    case 2: {
      const ready = d?.assets.filter((a) => a.status === "valid").length ?? 0;
      return d && !ready ? "Counterpart is writing the posts" : "Approve the posts you like";
    }
    case 3:
      return "Post them and put the QR code on your counter";
    case 4:
      return "Customers are redeeming";
    default:
      return "Finished";
  }
}
