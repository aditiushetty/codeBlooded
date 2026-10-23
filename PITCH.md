# Counterpart: first presentation

> **A marketing team of AI agents for every small business.**
> The owner says the idea in their own words. Specialist agents turn it into a full campaign in English, ಕನ್ನಡ and
> हिन्दी, check each other's work, and never tell a customer anything the owner didn't approve.

Previous version, live: **https://counterpart-three.vercel.app** ("Try the demo business": Kaapi Kone, a Bengaluru café)

---

## 1. The problem

A café owner in Bengaluru knows exactly what she wants people to hear: a weekend offer, in her own tone, in the
languages her customers speak. But she is behind the counter all day. She has no designer, no marketing team and no
time to write a brief. Her ideas change as she sees what takes shape.

- **One message, many versions.** A single campaign needs posts for students and families, in three languages, on
  Instagram, WhatsApp and a counter poster, and they must all stay consistent.
- **Requirements keep changing.** "Make it Sunday only" shouldn't mean redoing everything, or losing what was
  already approved.
- **One thing can never go wrong: what customers are told to expect.** A post that promises "free coffee all day"
  when the offer was 15% off from 4 to 7 pm costs the owner money and trust.
- **Generic AI makes it worse.** It invents prices and dates, sounds like an ad agency, and its Kannada is often
  wrong.

## 2. The solution

Counterpart works like a small marketing team, not a chatbot. Each AI agent has one job, its own tools and its own
model. **The agent that writes a post is never the one that checks it**, and nothing reaches customers without the
owner's approval.

Every campaign goes through the same five steps, and the owner always sees which step it's on and what's waiting:

| Step | What the owner does | What the agents do |
|---|---|---|
| **1. Brief** | Types or **speaks** the idea in any of the three languages | Brief agent turns it into a goal, audience, channels and languages |
| **2. Offer** | Reads it back and **locks** it | Offer agent writes the offer as structured facts and checks the margin; Language agent writes each language and back-translates it for checking |
| **3. Posts** | **Approves** (or edits) | Writer agent drafts posts per audience × language × channel; Checker agent and the rule guard verify every word against the locked offer |
| **4. Share** | Taps share | Each post gets its own link, QR code, WhatsApp message and caption |
| **5. Results** | Staff type the customer's code at the counter | Analyst agent counts opened → claimed → redeemed per post, runs A/B tests, and suggests what to do next |

## 3. How it answers the brief

| The brief asks for | How Counterpart does it |
|---|---|
| Half-formed idea → campaign, with little effort | Speak or type one line. Agents plan, write and check; the owner only reads and approves. |
| Consistent across audiences, languages and channels | Every post is built from the **same locked offer facts** and the same brand voice. The offer box on each post is system-rendered from the locked wording, so it's identical everywhere. |
| Nothing customers expect is wrong | The writer **can't type** a price, date or time: it writes `{{discount}}` and the system fills in the approved wording. A rule guard blocks any invented number or banned claim, and an independent Checker agent verifies the meaning. |
| Absorb changes without losing approvals | Changing the offer locks a **new version**. Only the posts that used a changed fact are marked stale and rewritten; everything else stays approved. |
| Owner knows what exists, what changed, what's pending | The five-step tracker on each campaign, a "needs you" list on the Today page, and an append-only **work log** of every action by owner, agent and customer. |
| Local and authentic, not translated | Posts are **written natively** per language, not translated word for word. The owner's own brand voice, real photos of the business, and robotic phrases ("elevate", "indulge") blocked by rule. |
| Owner in control | Anything customers will see, and any offer change, becomes an approval in the owner's inbox. |
| Realistic time and cost | About 2 minutes of the owner's time per campaign. Runs on free AI tiers and free hosting. |

## 4. Demo flow (about 4 minutes)

1. **Try the demo business:** Kaapi Kone, a Jayanagar café.
2. **Today page:** the yellow "needs you" list. **Speak** a brief: *"15% off filter coffee and dosa, weekdays 4 to 7, for
   students."*
3. **Campaign page:** watch the agents work live (the **AI team** page shows which agent and model did each step).
4. **Offer:** the offer in three languages, each with its back-translation in English. Margin check. **Lock.**
5. **Posts:** real photos, the "matches the locked offer" seal. Edit a post and type "Elevate your evening, 30% off!!"
   to show it gets **blocked** (invented number, robotic phrase).
6. **Change of mind:** "Make it Sunday only." The offer re-locks as version 2; only the posts that mention the days
   are rewritten, and the rest stay approved.
7. **Share:** WhatsApp message, caption, QR code. Scan the QR with a phone and claim a code.
8. **Counter:** type the code → redeemed. **Results** update: opened → claimed → redeemed, best post, A/B result.

---

## 5. The agent team (multi-agent architecture)

```
                         Owner (voice or text, EN / ಕನ್ನಡ / हिन्दी)
                                         │
                                         ▼
                     ┌──────────────── ORCHESTRATOR ────────────────┐
                     │ reads the situation, picks the next agent,   │
                     │ enforces budgets, turns customer-facing      │
                     │ actions into owner approvals                 │
                     └──┬──────┬───────┬───────┬───────┬───────┬───┘
                        │      │       │       │       │       │
                    Brief   Offer  Language  Writer  Checker  Analyst ── Customer
                    agent   agent   agent    agent    agent    agent     listener
                        │      │       │       │       │       │           │
                        └──────┴───────┴── shared state ───────┴───────────┘
                         Postgres: locked facts, posts, approvals, ledger
```

| Agent | One job | Tools it can use | Model |
|---|---|---|---|
| **Orchestrator** | Reads the campaign situation, decides which agent works next, stops when it needs the owner | `get_situation`, hand-off to any agent, `recommend` | Groq (fast reasoning) |
| **Brief agent** | Turns the owner's words (or voice) into goal, audience, channels, languages | Sarvam speech-to-text, `set_campaign_plan` | Groq |
| **Offer agent** | Writes the offer as structured facts; checks margin and break-even against menu costs | `draft_offer_facts`, `evaluate_offer`, `revise_offer_facts`, `lock_facts` (owner approves) | Groq |
| **Language agent** | Native Kannada/Hindi wording of the offer; independent back-translation for checking | Sarvam translate, script checker | **Sarvam AI** |
| **Writer agent** | Headlines and short posts per audience × language × channel, in the owner's voice, with slots for offer values | `generate_copy` | Groq |
| **Checker agent** | Verifies every promise in every post against the locked facts; never the writer's model | Rule guard L1/L2, `validate_assets` (L3) | **Cerebras** (different model from the writer) |
| **Analyst agent** | Reads results, runs A/B tests, records what worked for next time | `experiment_status`, `create_experiment`, `decide_experiment`, `record_learning` | Groq |
| **Customer listener** | Reads reviews and Instagram comments; finds complaints, questions and themes; drafts replies | `get_customer_themes`, review import, reply drafts | Groq / Cerebras |

**How the agents work together**
- **One shared source of truth.** Agents never pass offer details to each other in chat. They read and write the
  database (locked facts, posts, approvals), so no agent can "remember" a price wrongly.
- **Checks and balances.** Writer and Checker run on different model providers. The Language agent's
  back-translation is done by Sarvam, independently of the model that wrote the text.
- **Policy gate.** Every tool has an effect class (read, internal, customer-facing, fact). Customer-facing and fact
  actions become owner approvals automatically; the agent can't skip this.
- **Repair loop.** If the guard blocks a post, the Writer gets the exact reasons and one rewrite.
- **Event-driven.** When the owner approves or changes something, the Orchestrator resumes on its own.

**Where we are:** the **Orchestrator, Writer and Checker are running as separate agents.** Each has its own
prompt, model and tool set; the Orchestrator hands work over with `ask_writer` and `ask_checker`, and an agent that
reaches for another's tool is refused. The Offer, Language, Analyst, Brief and Customer listener agents are next;
until then the Orchestrator does their jobs with the same tools.

## 6. Workflow in detail

```
Owner brief ──► Brief agent ──► campaign plan (goal, audience × channel × language)
                                      │
                                      ▼
                 Offer agent ──► offer facts draft ──► Language agent (native wording + back-translation)
                                      │
                         Owner reads it back and LOCKS (version 1)
                                      │
                                      ▼
                 Writer agent ──► posts with {{slots}} ──► Rule guard (L1/L2) ──► Checker agent (L3)
                                      │            ▲ blocked: exact reasons, one rewrite
                                      ▼
                         Owner approves ──► live: link + QR + code per post
                                      │
              Customer scans ──► claims a personal code ──► redeemed at the counter
                                      │
                                      ▼
                 Analyst agent ──► funnel, A/B result, learning ──► used by the next campaign

Owner changes the offer ──► new locked version ──► only the affected posts go stale ──► Writer rewrites those
```

## 7. Why it can't tell customers something wrong

1. **Locked facts.** The offer is stored as structured, versioned facts. The database itself refuses edits to a
   locked version.
2. **Slots, not values.** The Writer never types a number, date or price. It writes `{{discount_pct}}`; the system
   inserts the owner's exact wording.
3. **Three-layer guard on every post.**
   - **L1 (rules):** any digit the model typed itself, and broken Kannada/Devanagari letters.
   - **L2 (rules):** missing facts, banned claims ("free", "unlimited", "DM us"), brand-banned words, and
     machine-sounding phrases.
   - **L3 (Checker agent):** an independent model compares the meaning of each post, with Sarvam's back-translation,
     against the locked facts.
4. **Approval required.** A post must pass against the *current* offer version before the owner can approve it.

## 8. Tech stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | **Next.js 15** (App Router), **React 19**, **Tailwind CSS 4**, Phosphor icons | Fast, server-rendered owner app; tokens never reach the browser |
| Backend | **Python 3.12**, **FastAPI**, Pydantic, psycopg 3 | Modular monolith: one rules layer (`services.py`) shared by the API and every agent |
| Agents | Our own agent runtime: tool registry with effect classes, policy gate, budgets, timeouts | Full control over approvals and safety; no framework lock-in |
| Text models | **Groq** and **Cerebras** (free, no card, OpenAI-compatible); **Gemini** when available | Role-based router with automatic failover; the model is a swappable part |
| Indian languages | **Sarvam AI**: speech-to-text for voice briefs, translation and back-translation | Built for Indian languages; independent from the writing model |
| Database | **Supabase Postgres** (Mumbai): row-level security, immutability trigger on locked facts | Managed, free tier, India region |
| Auth and files | **Supabase Auth** (httpOnly cookies via the Next server), **Supabase Storage** | Secure sessions, photo storage |
| Statistics | NumPy, Bayesian A/B tests | Works with the small numbers a single shop gets |
| Channels | WhatsApp Cloud API, Instagram API (optional); QR codes, share links | Reach customers where they already are |
| Hosting | **Vercel** (frontend), **Render** (backend Docker), Supabase | Free or hobby tiers |
| Quality | pytest (backend tests incl. an end-to-end campaign loop), ruff, TypeScript | |

## 9. What we measure

| Stage | Metric | How |
|---|---|---|
| Interest | Links opened | QR scans and link taps, once per phone |
| Intent | Codes claimed | "Get my code" on the post's landing page |
| Sales | Redeemed at the counter | Staff type the code; optional bill amount gives ₹ sales |
| Efficiency | Conversion | Redeemed ÷ opened, per post, language, audience and channel |
| Learning | Chance each version is better | Bayesian A/B test; tips shown only at ≥ 90% confidence |
| Quality | Guard pass rate, rewrites, owner edits | Work log |
| Cost | Model calls and tokens per campaign | Router log, shown on the AI team page |

## 10. Cost for a small business

| Item | Cost |
|---|---|
| AI models | ₹0 on Groq, Cerebras and Gemini free tiers, with failover. Paid tiers cost fractions of a rupee per campaign. |
| Sarvam AI | Free starter credits; low per-call cost after |
| Database, auth, storage | Supabase free tier |
| Hosting | Vercel and Render free/hobby tiers |
| Owner's time | About 2 minutes per campaign: speak, lock, approve |

## 11. Built vs next

| Built and running | Next |
|---|---|
| Owner accounts, onboarding from a website or Maps link | Sarvam as the Language agent end to end |
| Locked versioned facts, slots, 3-layer guard, approvals | Voice briefs in Kannada and Hindi via Sarvam |
| Orchestrator, Writer and Checker as separate agents with hand-offs, each on its own model | Offer, Language (Sarvam), Analyst, Brief and Customer listener agents; hand-off view on the AI team page |
| Posts with real photos, share links, QR codes, counter redemption | Direct posting once Meta business verification is done |
| Funnel analytics, Bayesian A/B tests, learnings | Pilot with 3 to 5 real shops |
| Reviews and Instagram comments sorted by theme | Staff logins with redeem-only access |

## 12. Likely questions

- **"Isn't this just a ChatGPT wrapper?"** No. Remove the model and the locked facts, the guard, the approvals, the
  tracking codes and the ledger all still run. The models write sentences; the system decides what's allowed and
  measures what worked.
- **"What stops it inventing a price?"** It can't type one. Values come only from locked slots, and any digit the
  model types is blocked.
- **"Why several agents instead of one?"** Each has one job and a small set of tools, so it's more reliable, and
  they check each other: the writer is never its own checker.
- **"How is the Kannada correct?"** Sarvam, an Indian-language specialist, back-translates every line, a script
  checker catches broken letters, and the owner reads it back before locking.
- **"How do you know it worked?"** A per-post code redeemed at the counter, not likes.
- **"What if a model provider goes down?"** The router fails over to the next provider in milliseconds.

---

*Context and decisions: `MEMORY.md`. Architecture and code rules: `CLAUDE.md`. Setup: `docs/SETUP.md`.*
