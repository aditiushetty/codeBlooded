# Backend: how the code works

The backend is a Python FastAPI app in `backend/app/`. It is one deployable service (a "modular monolith") talking to Postgres on Supabase. This file explains what each part does and how a request moves through it.

## The big idea

The business rules live in code, not in the AI prompts. The language models only write words. Everything that must be correct (prices, dates, who approved what, what counts as a sale) is handled by plain Python and the database:

- **Locked facts**: the offer (price, dates, conditions) is written down once, checked, and locked. Posts can only refer to it through slots like `{{price}}`. The system fills in the real values, never the model.
- **Guard**: every post is checked by deterministic rules (L1, L2) and then by a second model (L3) before it can go live.
- **Approvals**: anything a customer will see, and any change to the facts, waits for the owner in an inbox.
- **Ledger**: every action, by the owner, an agent, the system or a customer, is written to an append-only log.
- **Attribution**: each live post gets a code, so visits, claims and redemptions can be traced back to the post that caused them.

## Folder map

```
backend/
  app/
    main.py            app setup: DB pool, model router, routes, error handlers
    config.py          settings from backend/.env (pydantic-settings)
    db.py              Postgres connection pool (psycopg 3, async) and small helpers
    ledger.py          append-only event log + live fan-out to the browser
    auth.py            Supabase Auth over REST, current_user, membership checks
    services.py        every database business operation (used by API and agents)
    domain/            pure logic, no I/O
    agent/             the AI team: tools, agents, runtime loop, prompts
    providers/         model access: router, OpenAI-compatible clients, replay, rate limits
    api/               HTTP routes
    channels/          WhatsApp and Instagram (Meta Graph API)
    autofill.py        sign-up from one link (website or Google Maps)
    photos.py          business photos: import, captions, picking one per post
    reviews.py         customer reviews: import, visit reviews, Instagram comments
    sarvam.py          optional Sarvam AI speech-to-text and translation
    storage/           file storage (local folder or Supabase Storage)
  scripts/             migrate, seed, set secrets, go live, sample campaign
  tests/               pytest suite
supabase/migrations/   the only source of the database schema
```

## Startup (`main.py`)

On start the app:
1. opens the Postgres pool (`db.open_pool`),
2. builds the model router from settings (`providers.build_router`),
3. makes sure the storage bucket exists,
4. mounts five routers: `api` (owner), `accounts` (auth, onboarding, workspace), `public` (customers and staff), `channels_api` (WhatsApp/Instagram settings) and `webhook` (Meta callbacks).

Errors are mapped once: `NotFound` becomes 404, `Conflict` 409, `AuthError` 400.

## Database

Schema lives only in `supabase/migrations/*.sql`, applied by `scripts.migrate`. Row-level security is on. Main tables:

| Area | Tables |
| --- | --- |
| Accounts | `businesses`, `memberships`, `brand_dna` |
| Campaign work | `campaigns`, `offer_facts`, `assets`, `asset_revisions`, `experiments` |
| Tracking | `touchpoints` (post codes), `claims` (personal coupon codes), `outcome_events` (visit, claim, redeem) |
| Customers | `customer_interactions` (reviews, comments), `customer_insights` |
| Agent | `inbox_items` (owner approvals), `memories` (learnings), `ledger_events` |
| Counter | `counter_sessions` (staff phones) |
| Channels | `channel_accounts`, `wa_contacts`, `channel_messages`, `instagram_media` |
| Media | `business_photos` |

A database trigger makes locked `offer_facts` rows immutable. To change an offer you lock a new version.

`db.py` gives `connection()` (an async context manager), `fetch_one`, `fetch_all` and `jsonb`. The rule is: never call a model while a transaction is open. Read, close, call the model, then open a new connection and write.

## Auth (`auth.py`)

- Sign up, sign in and refresh go to Supabase Auth over REST.
- `current_user` reads the `Bearer` token, checks it with Supabase, and caches the answer for 60 seconds.
- `require_member` / `business_for` check the user belongs to the business in the URL. Unknown and forbidden both return 404, so nobody can probe which businesses exist.

Every owner route depends on these. Tests replace `current_user` (see `tests/conftest.py`).

## Services (`services.py`)

This is the single place for business operations. Both the HTTP routes and the agent tools call it, so a rule written here holds no matter who acts. Highlights:

- **Campaigns**: `create_campaign`, `update_campaign_plan`, `get_campaign`.
- **Offer facts**: `save_draft_facts` → `check_fact_wording` (script sanity plus a model back-translation) → `lock_facts`. Locking is refused if the wording check failed or is missing.
- **Posts**: `create_asset`, `add_revision` (each edit is a new revision with its guard result), `audit_assets` (the L3 check), `approvable` (is this post allowed to go live against the current facts version?), `approve_asset`, `publish`, `autopublish`.
- **Tracking**: `issue_touchpoint` (6-letter post code), `record_outcome`, `claim` (7-letter personal code, one per phone per campaign).
- **Counter**: `counter_check` and `counter_redeem` check a code against the locked rules (dates, hours, weekdays) and refuse used codes. Staff PIN and sessions: `set_counter_pin`, `open_counter_session` (scrypt hash, 5 tries then a 15 minute lock).
- **Experiments**: `experiment_status`.

## Domain logic (`domain/`)

Pure functions with no database or network, so they are easy to test.

- `facts.py`: the fact sheet model, slot rendering (`render` fills `{{fact_key}}` with locked wording in each language) and the guard, `deterministic_checks`:
  - **L1** `no_unapproved_numbers`: any digit outside a slot blocks the post. `well_formed_script` catches broken Kannada or Devanagari letter sequences.
  - **L2** `sounds_human` (blocks AI clichés, long dashes, double "!"), `known_facts_only`, `approved_wording`, `no_repeated_words`, `no_forbidden_claims`.
  - **channel** `fits_channel` (length limits per channel), **provenance** `sourced_segments`.
- `audit.py`: the L3 check. A second model back-translates the post and compares each promise to the locked facts. Kannada and Hindi go through Sarvam first when it is set up.
- `redeem.py`: the rules the counter applies to a code.
- `analytics.py`: funnel, daily and hourly series, breakdowns with a 90% likely range, and tips that only appear when the data is at least 90% sure.
- `stats.py`: Bayesian maths for experiments. `economics.py`: margin and break-even of a discount. `impact.py`: before/after effect.
- `culture.py`: hand-written festival knowledge (names in en/kn/hi, greetings, customs, dates).

## The AI team (`agent/`)

Three agents, each with its own model role and its own tools (`team.py`):

| Agent | Model role | Can use |
| --- | --- | --- |
| Orchestrator | reasoning | everything except the specialists' tools, plus `ask_writer` and `ask_checker` |
| Writer | generation | read tools, `generate_copy`, `generate_visual` |
| Checker | verification | `get_situation`, `validate_assets` |

The Writer and Checker run on different model chains, so a post is never checked by the model that wrote it.

**Tools** (`tools.py`) are registered with `@tool(name, description, ArgsModel, effect, preconditions)`. The effect says how risky a tool is: `read`, `internal`, `customer_facing` or `fact`. Examples: `get_situation`, `evaluate_offer`, `draft_offer_facts`, `lock_facts`, `set_campaign_plan`, `generate_copy`, `validate_assets`, `generate_visual`, `create_experiment`, `publish_assets`, `record_learning`, `recommend`.

**Runtime** (`runtime.py`):
1. `run` starts a run for a campaign, with a time limit, and refuses a second run on the same campaign.
2. `situation.snapshot` collects the current state plus findings from deterministic detectors (stale posts, complaint spikes, festivals coming up).
3. `_loop` is the tool-calling loop shared by every agent: send the system prompt and situation to the model, run each tool call it asks for, write each step to the ledger, feed the result back, repeat until it answers in prose or hits its budget.
4. `execute` is the policy gate for every tool call: validate arguments, check preconditions, and if the effect is `customer_facing` or `fact` and the owner has not approved, put it in `inbox_items` instead of running it.
5. `delegate` is a hand-off: the Orchestrator's `ask_writer` / `ask_checker` run a specialist's own loop and return its summary.
6. `decide_inbox` runs a queued tool when the owner approves, then resumes the agent in the background.

`generate_copy` does one repair round in the tool itself: if the guard blocks a post, the exact reasons go back to the model once.

## Models (`providers/`)

- `router.py` `ModelRouter`: you ask for a **role** (`reasoning`, `generation`, `verification`, `image`, `vision`), not a model. Each role has a chain of providers and the router fails over down the chain. A circuit breaker and a "rest" timer skip a provider that keeps failing or is rate limited.
- `__init__.py` `build_router`: builds the chains from settings. Gemini models first, then the same models on a second key, then Groq and Cerebras, then Agnes. Swapping a model is a config change.
- `openai_compat.py`: one client for every OpenAI-compatible API (Gemini, Groq, Cerebras, Agnes).
- `ratelimit.py`: requests-per-minute limiter per provider. `replay.py`: record model replies and replay them (offline demos and tests).

## Ledger and live updates (`ledger.py`)

`record()` inserts a row in `ledger_events` and pushes it to every subscriber queue. `GET /businesses/{slug}/events` streams those events to the browser as Server-Sent Events. That is how the UI updates live while agents work.

## HTTP routes (`api/`)

| File | Prefix | What it serves |
| --- | --- | --- |
| `workspace.py` | `/api` | sign up, log in, refresh, log out, demo login, `/me`, onboarding (`read-link`, `POST /businesses`), brand edits, photos, speech, review import, `/agents`, `/results` |
| `owner.py` | `/api` | business overview, customers, review replies, ledger and live events, campaigns, analytics, facts draft and lock, publish, autopublish, approve and reject posts, inbox decisions, counter PIN, start the agent, demo-only actions |
| `public.py` | `/api/public` | no login: QR landing visit, claim a code, claim status, visit review, QR images, staff counter session, check and redeem |
| `channels.py` | `/api` and `/api/public` | connect WhatsApp and Instagram, send or publish a post, link Instagram media, sync comments, Meta webhook |

## Outside services

- `channels/meta.py` is the only caller of the Meta Graph API. `whatsapp.py` handles the webhook (signed), replies with claim codes, opt-outs and broadcasts. `instagram.py` publishes, links media, pulls insights and comments.
- `sarvam.py`: speech to text and translation for Kannada and Hindi. Everything still works without a key.
- `photos.py`: imports photos from the website (with SSRF guards) or Google Places, captions them with the vision model, and picks one per post.
- `autofill.py`: reads a website or Google Maps link and keeps only names and prices found word for word in the page.
- `reviews.py`: imports reviews, stores visit reviews and Instagram comments, then labels them with a model. `verified()` drops anything not found in the source.

## Scripts and tests

- `scripts.migrate [--reset]`, `scripts.seed` (loads the Kaapi Kone demo from `data/seed/`), `scripts.set_secret` (hidden prompt), `scripts.go_live` (connects WhatsApp and Instagram in one run), `scripts.sample_campaign`.
- `tests/`: `test_domain.py` (guard and maths), `test_flow.py` (a full campaign end to end), `test_team.py` (agent permissions and hand-offs), `test_channels.py`, `test_accounts.py`, `test_router.py`. `fakes.py` gives a fake model router.

Run them:

```bash
cd backend && uv run pytest
```
