# Counterpart: to-do list

Work in order; each section builds on the one before.
Mark an item done by changing `[ ]` to `[x]` and adding the date, e.g. `[x] ... (done 2026-10-24)`.
Decisions and context live in `MEMORY.md`; update it when an item here is finished.

Last updated: 2026-10-24

---

## 1. Must-haves for the pitch

- [x] **1. Sarvam key.** Add `SARVAM_API_KEY` with `uv run python -m scripts.set_secret SARVAM_API_KEY` and test speech to text + translation end to end. (done 2026-10-23)
- [x] **2. Offer agent.** Turns the owner's idea into draft facts and asks about anything unclear ("Does 15% apply to combos?"). The owner locks; the agent never does. (done 2026-10-23)
- [x] **3. Language agent (Sarvam).** Writes Kannada and Hindi natively (not translated from English) and back-translates for the Checker. Never trust Sarvam's translation blindly: in testing it turned "weekday evenings" into "Friday evening" in Kannada, so days and numbers must be compared against the locked facts. Free plan is 100 credits: cache translations. (done 2026-10-23)
- [x] **4. Change agent.** An offer edit creates a new facts version; only the posts it affects are redone, approved ones are kept. (done 2026-10-23)
- [x] **5. Live agent-team view.** Who is working, handoffs between agents, the Checker rejecting a Writer draft with its reason. (done 2026-10-23)
- [ ] **6. dont need thisReplay demo mode.** Recorded real runs (`providers/replay.py`), labelled in the UI, so free-tier limits can't break the demo.
- [x] **7. Hide festival features.** Put `domain/culture.py` (writer prompt, detector, festival cards) behind a flag, out of the pitch flow instead of this basically whatever is happening around suppose ipl is going on or some event there find a busniess oppurninty and ads or offers (done 2026-10-23: Scout agent + "Happening around you" on Today)

## 2. Proof for the judges

- [x] **8. Checker test.** A set of 50 known-bad drafts (wrong price, invented date, broken Kannada); report "caught X of 50". (done 2026-10-24)
- [x] **9. Owner effort metric.** Taps and minutes from idea to live posts. (done 2026-10-24)
- [x] **10. Cost against return in the UI.** "₹3 of AI, ₹4,200 at the counter" from `domain/economics.py`. (done 2026-10-24)

## 3. Next agents

- [x] **11. Analyst agent.** Reads funnel + A/B results and proposes the next move for owner approval. (done 2026-10-23)
- [x] **12. Customer listener agent.** Reviews and comments become detected issues, then draft replies, then a follow-up campaign suggestion. (done 2026-10-23)
- [x] **13. Brief agent.** Clarifies audience, goal and channels before the Offer agent starts. (done 2026-10-23)

## 4. Gaps against competitors

- [x] **14. Repeat-visit codes.** "Come back within 14 days" second-visit codes and a returning-customer rate per campaign. (done 2026-10-23)
- [x] **15. Google Business Profile.** Publish the offer as a GBP "Offer" post. (done 2026-10-23)
- [x] **16. Bill import.** CSV or UPI statement import that matches sales to redeemed codes. (done 2026-10-23)
- [x] **17. WhatsApp template drafts.** Meta-compliant template text with approval status tracking. (done 2026-10-23)
- [x] **18. Voice onboarding.** The owner speaks the menu in Kannada; Sarvam turns it into structured items. (done 2026-10-23)
- [x] **19. Photo-slideshow reels.** The business's own photos plus a Sarvam voice-over (no AI imagery). (done 2026-10-23)

## 5. Next up

- [ ] **20. Connect WhatsApp and Instagram for real.** (in progress 2026-10-24: Meta app 1283719630565611 made; WhatsApp test number retry 2026-10-25; Instagram via Business Suite) Meta app, tokens, webhook on a public address (`scripts.go_live`, docs/CHANNELS.md), then test the claim flow, sending a post, template approval and Instagram publishing against Meta instead of the fakes.

## Not now

Ad buying (Meta/Google spend), a full design editor, AI-generated images, more channels.
They dilute the core story: the system makes sure the offer is true and that it brought someone to the counter.

---

## Done log

Newest first. Copy a finished item here with its date and a one-line note on what changed.

- **2026-10-24 #8-10 Proof for the judges.** Checker test (`data/eval/bad_drafts.json`, `app/checker_eval.py`, `scripts.checker_eval [--live]`, AI team page): 49 of 50 known-bad drafts caught (rules 39, meaning check 10), 0 of 10 good posts blocked; the one miss is "packed in two minutes". Two new rules came out of it: times of day and days named in a post must fit the offer (`language.time_mismatch`, `days_match`). Owner effort (`domain/effort.py`): taps and minutes from brief to first live post, split into team time and waiting for the owner (live demo campaign: 3 taps, 38 min, 34 of them waiting). AI cost against sales: model calls stored (`model_calls`, `app/usage.py`), ₹ estimated at a list price in settings, shown on the campaign and Results pages.
- **2026-10-23 #11-13 Brief agent, Analyst, Customer listener.** Brief agent plans audience/goal/channels/languages first (`set_campaign_plan` refused by `domain/brief.py` rules). Analyst (verification role) reads `results.campaign`, proposes moves; every number must exist in the results and "do more of X" / learnings need a >=90% likely difference (`domain/analyst.py`; added after a live run bet on 1 vs 0 redemptions). Customer listener raises issues (2+ real reviews with the theme), drafts replies (owner sends), suggests follow-up campaigns (approve = new campaign). Live: Analyst proposed reminding 11 claimers; listener raised the morning-queue issue and drafted 3 replies.
- **2026-10-23 #14-19 Competitor gaps.** Come-back codes (per-campaign days, counted as returns not new customers), CSV/UPI bill import matched by code-in-note or unambiguous time, WhatsApp template drafts checked against Meta rules + submit + webhook status, Google Business Profile offer posts (OAuth publish, or copy fields), spoken menu at sign-up (Sarvam; prices said in words flagged), photo reels (own photos only + Sarvam bulbul:v3 voice of checked words, recorded to MP4 in the browser; verified live, 17 s with audio). Migration `20261024000000_team_and_reach.sql` applied.
- **2026-10-23 #7 What is happening around you.** Moments from real sources only (`domain/moments.py`, `app/moments.py`): Open-Meteo forecast (rain this evening, hot afternoon; free, no key, cached 30 min), the calendar (weekend, salary week), the business's events and ones the owner adds in one line ("IPL: RCB vs CSK, Sunday, 7:30 pm"; no free fixture feed, so nothing is invented). The Scout agent turns them into up to 3 campaign ideas; ideas naming an unknown moment or a non-menu item are dropped. Today page: "Happening around you" with add/remove and "Start this campaign". Moments also reach the Orchestrator's snapshot. Live: rain 65-96% this week -> "Warm filter coffee and hot vada for evening rain".
- **2026-10-23 #5 Live agent-team view.** `components/team-feed.tsx` turns the ledger (live over SSE) into a conversation: hand-offs as arrows, each agent's work, rules/Checker rejections in red with reasons, questions and approvals in yellow. On the campaign page (beside "Tell Counterpart") and the AI team page.
- **2026-10-23 #4 Change agent.** `ask_change` -> Change agent (`preview_change`, `revise_offer_facts`, `ask_owner`). On a new lock, posts whose own text uses a changed detail are rewritten; posts that only show it in the offer box are refilled by the system and re-checked; the rest stay.
- **2026-10-23 #3 Language agent.** `ask_language` -> Language agent (`translate_offer`): Sarvam first, then a day-word rule (`domain/language.py`), numbers and a back-translation; the agent rewrites what fails. Lock refused while a language lacks wording. Sarvam calls cached. Live: fixed "evening 3 to 6" for 3 pm.
- **2026-10-23 (side effect of #7 v1)** Festival features are behind `FESTIVALS` (default off).
- **2026-10-23 #2 Offer agent.** New specialist (`team.OFFER`): drafts/revises facts from the real menu, gets a deterministic gap check (`domain/offer.py`) and margin with every draft, asks the owner up to 3 questions in the inbox (`ask_owner`, kind `question`), never locks. The agent's lock request is refused while blocking gaps remain. Live run on Kaapi Kone: "15% off for college students" became a complete offer after one question.
- **2026-10-23 #1 Sarvam key.** Key set and tested: Kannada/Hindi translation both ways, English and Kannada speech to text. Found a Kannada day-word mistranslation (see #3). TTS model is now `bulbul:v3`.
