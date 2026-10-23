# Counterpart: project memory

The running context for this project: what we are building, what we decided and why, and where setup stands.
**Update this file whenever a decision is made or a step is finished** (newest entries at the top of each log).
Architecture and code rules live in `CLAUDE.md`; this file is the "why" and the "where are we".

Last updated: 2026-10-23 (multi-agent step 1)

---

## 1. What we are building

**Counterpart: an AI marketing team for a small business, run by the owner from behind the counter.**

The owner says a half-formed idea ("15% off filter coffee for students, weekday evenings") in English, Kannada or
Hindi. A team of AI agents turns it into a complete, consistent campaign: the offer written down and locked, posts
for each audience, language and channel, links and QR codes to share, and results counted when customers redeem
their code at the counter. The owner approves anything customers will see.

- **Deployed previous version:** https://counterpart-three.vercel.app (frontend on Vercel; backend on Render).
- **Demo business:** Kaapi Kone, a Jayanagar (Bengaluru) café, synthetic data, reachable through "Try the demo".
- **Origin:** HR26 hackathon, problem HR26-AI-02 (Marketing Campaigns).

## 2. The problem statement (as given)

Small businesses know what they want to say but lack time, resources and expertise to turn it into an effective
campaign. One campaign must carry the same message to different audiences, in different languages, across
different channels, while staying recognisable and consistent. Requirements change as the owner reacts to what is
being created, and **what customers are told to expect must never be wrong**.

What the solution must do (our checklist):
1. Go from a half-formed idea to a campaign the owner is proud to put their name on, with very little effort.
2. Keep message, offer and brand consistent across audiences, languages and channels.
3. Ensure nothing customers are told to expect is wrong.
4. Absorb changing requirements without losing what was already approved.
5. Let the owner see what exists, what changed and what is pending.
6. Feel local and authentic, not generic or translated.
7. Keep the owner in control.
8. Fit realistic time and cost for a small business.

## 3. Decisions (newest first)

| Date | Decision | Why |
|---|---|---|
| 2026-10-23 | **Split order:** Orchestrator + Writer + Checker first (done); next Offer, Language (Sarvam), Analyst, Brief, Customer listener. | Writer/Checker separation is the core safety story. |
| 2026-10-23 | **Focus: a multi-agent system.** Split the single planner + tools into specialist agents (Brief, Offer, Language, Writer, Checker, Change, Analyst, Customer listener) coordinated by an Orchestrator. See `PITCH.md` §5. | This is the core of the pitch; each agent has one job, its own tools and model, and they check each other. |
| 2026-10-23 | **Languages through Sarvam AI** (speech to text, translation, back-translation for checking). | Indian-language specialist; LLM Kannada was unreliable (invented words, wrong meanings). |
| 2026-10-23 | **Drop Agnes** (images and fallback LLM). | No key; not needed. AI pictures are off; posts use the business's real photos. |
| 2026-10-23 | **Drop religious/festival and local-sentiment features from the pitch** (`domain/culture.py`: festival greetings, customs). Code still exists; remove or hide it later. | Out of scope for the new direction. |
| 2026-10-23 | **Text models: Groq + Cerebras (free, no card) now; Gemini later** when AI Studio works again. Writer and Checker must stay on different models. | Gemini AI Studio was down; Groq/Cerebras need no card. |
| 2026-10-09 | Gemini as default text provider, router with failover across providers. | Free tier, structured output. |
| 2026-10-09 | "Counter book" design system (ink black, pen blue, highlighter yellow). | Old green look read as generic AI. |
| 2026-10-08 | Locked offer facts + `{{fact_key}}` slots; the model never types offer values. | Stops invented prices/dates (seen live). |

## 4. Setup status (local, this machine)

Folder: `~/Downloads/counterpart-main` (a downloaded copy, **not a git repo**). Full steps: `docs/SETUP.md`.

| Item | Status |
|---|---|
| Backend Python packages (`uv sync`) | Done |
| Frontend packages (`npm ci`), typecheck passes | Done (2026-10-23) |
| Supabase project `soqcxhwrvlgawznnnora` (Mumbai), `SUPABASE_URL` | Done |
| `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | Done |
| `DATABASE_URL` (session pooler) | Done |
| Tables + demo data (`scripts.migrate`, `scripts.seed`) | Done (9 migrations, demo café seeded) |
| `DEMO_PASSWORD` | To do |
| `GROQ_API_KEY`, `CEREBRAS_API_KEY` | To do (main text models for now) |
| `SARVAM_API_KEY` | To do (languages) |
| `GEMINI_API_KEY` | Later (AI Studio was not working) |
| `AGNES_API_KEY` | Not used any more |
| Google Maps, Meta (WhatsApp/Instagram) | Optional, later |

Without Gemini: photo captioning ("vision" role) is off. Without Agnes: no AI pictures (real photos only).

## 5. Work log (newest first)

- **2026-10-23** **Review prep.** Checked: 71 backend tests, ruff, typecheck, production build all pass; Supabase
  has all 9 migrations, the demo café and one real business. Fixed `.gitignore` (a trailing `.env*` was also
  hiding both `.env.example` files from git). Removed an unused root `package.json`/`package-lock.json`/
  `node_modules`. README rewritten for reviewers (team, agent team, models, links); `render.yaml` and
  `docs/DEPLOY.md` list Groq/Cerebras/Sarvam keys. Dry-run of the first commit: 171 files, no secrets.
  Next: owner pushes to a new GitHub repo; add a Groq or Cerebras key so posts can be written live.
- **2026-10-23** **Nexathon 2026 deck:** `codeBlooded-Counterpart-Nexathon-2026.pptx` (root), built on the official
  Nexathon template (6 slides: title, existing vs proposed + use cases, overview, progress, tech stack, future).
  Team codeBlooded, RV Institute of Technology and Management (Karnataka), track Open Innovation. **Team member
  names still a placeholder on slide 1.** Agent splitting paused while the deck was made (Orchestrator/Writer/
  Checker done; next agent not chosen).
- **2026-10-23** **Multi-agent, step 1: Orchestrator, Writer, Checker.** New `backend/app/agent/team.py` defines
  each agent (job, model role, prompt, allowed tools). The Orchestrator (reasoning role) hands work over with
  `ask_writer` / `ask_checker`; each specialist runs the same loop (`runtime._loop`) on its own model chain with
  only its own tools, then reports back. Writer = `generate_copy`, `generate_visual` (generation role); Checker =
  `validate_assets` (verification role, never writes). The Orchestrator keeps offer facts, plan, experiments,
  publishing, learnings. Calling another agent's tool is refused with "hand it over with ask_x". Ledger shows
  "Asked the Writer: ...", "Writer: Generate copy", "Checker: ..."; model calls carry an `agent` tag. Specialist
  budget `AGENT_SPECIALIST_MAX_LLM_CALLS` (default 4). AI team page: Planner renamed Orchestrator.
  Tests: `tests/test_team.py` (4), suite 71 passed.
- **2026-10-23** Fixed env setup: rewrote `backend/.env.example` (required vs optional, no inline notes), blank
  values now count as unset (`env_ignore_empty`), `set_secret` handles Agnes/publishable/demo/owner-token and
  edits lines in place, `set_db_password` asks for the pooler string (accepts `[YOUR-PASSWORD]`), new
  `docs/SETUP.md`. Installed frontend packages. Wrote this file and `PITCH.md`.

## 6. Open questions

- Next agent to split out: Offer agent (draft/revise/lock facts, evaluate_offer) or Language agent (Sarvam)?
- Which Sarvam model handles Kannada/Hindi *writing* (not just translation), or does the Writer stay on
  Groq/Cerebras with Sarvam checking? Test both on 5 real briefs.
- Remove `culture.py` from the code, or just hide it in the UI?
- When is the first presentation (Nexathon 2026), and who presents which part? Team member names for slide 1.
- Is the Render backend for the deployed app still running, and on which Supabase project?

## 7. Glossary

- **Locked facts**: the owner-approved offer details (discount, items, days, times, conditions), versioned; can
  only change by locking a new version.
- **Slots**: `{{discount_pct}}` placeholders the writer uses instead of typing values.
- **Guard L1/L2/L3**: rule checks (numbers, broken script, banned claims, robotic phrases) and an independent AI
  meaning check.
- **Stale**: a post made from an older offer version; it must be regenerated before it can go live again.
- **Ledger / work log**: append-only record of every action by owner, agent and customer.
