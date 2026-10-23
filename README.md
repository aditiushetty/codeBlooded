# Counterpart

**A team of AI agents that runs marketing for small businesses.** Team codeBlooded · Nexathon 2026 · Open Innovation.

A café owner says what she wants customers to hear. Counterpart writes the offer down as locked facts, plans and writes campaign posts in English, Kannada and Hindi that cannot misstate the offer, gives each post a tracking code, measures what actually brings people in, and comes back with the next move. The models write; the system guarantees, measures and remembers.

- **Live demo:** https://counterpart-three.vercel.app ("Try the demo business": Kaapi Kone, a synthetic Bengaluru café)
- **Pitch:** [PITCH.md](PITCH.md) · **Slides:** [codeBlooded-Counterpart-Nexathon-2026.pptx](codeBlooded-Counterpart-Nexathon-2026.pptx)
- **Decisions and status:** [MEMORY.md](MEMORY.md) · **Architecture rules:** [CLAUDE.md](CLAUDE.md)

## The agent team

| Agent | Job | Model role |
|---|---|---|
| **Orchestrator** | Reads the campaign situation, drafts and locks the offer (with the owner), plans audiences and channels, hands work to specialists | reasoning |
| **Writer** | Writes each post natively per language, in the owner's brand voice, with `{{fact}}` slots instead of offer values | generation |
| **Checker** | A different model chain from the Writer: reads every post back and blocks anything that doesn't match the locked offer. Never edits | verification |

The Orchestrator hands work over with `ask_writer` and `ask_checker`; each specialist runs on its own model with only its own tools (`backend/app/agent/team.py`). Every tool call from every agent goes through the same policy gate, so nothing reaches customers without the owner's approval. More specialists (Offer, Language on Sarvam AI, Analyst, Brief, Customer listener) are planned; see [PITCH.md](PITCH.md).

## What makes it more than an LLM wrapper

| System feature | Where it lives |
|---|---|
| Offer facts are versioned and **immutable once locked** (enforced by a Postgres trigger) | `supabase/migrations/…_init.sql`, `backend/app/services.py` |
| Copy carries offer values only as `{{fact}}` slots; a 3-layer **Fact Guard** blocks anything else (numbers the model typed, in any script; missing facts; forbidden claims; LLM meaning check) | `backend/app/domain/facts.py`, `domain/audit.py` |
| Changing a fact marks **only the dependent pieces** stale; approved, unaffected pieces stay approved | `backend/app/domain/impact.py` |
| Agents pick their own tools; a **policy gate** turns anything customer-facing or fact-changing into an owner approval, and each agent may only use its own tools | `backend/app/agent/runtime.py`, `agent/team.py`, `agent/tools.py` |
| Deterministic **detectors** decide what needs attention (stale pieces, complaint spikes, upcoming events, decidable experiments) | `backend/app/agent/situation.py` |
| Per-piece **QR / counter codes**: real attribution of scans, claims and redemptions | `backend/app/api/public.py`, `/counter` screen |
| **Small-sample Bayesian experiments** (Beta-Binomial, Thompson sampling, expected-loss stopping, priors pooled from the café's own history) | `backend/app/domain/stats.py` |
| **Offer economics** from real menu costs (break-even before a discount is locked) | `backend/app/domain/economics.py` |
| **Model-agnostic** provider router: roles → provider chains, rate limiting, circuit breaker, record/replay with labelled saved outputs | `backend/app/providers/` |
| Append-only **ledger** of everything owner, agent and customers did | `ledger_events`, the receipt-roll log in the UI |

## Stack

- **Frontend**: Next.js 15 (App Router) + TypeScript + Tailwind CSS 4. Browser talks only to Next; a server-side proxy forwards to the API and adds the owner token.
- **Backend**: FastAPI (Python 3.12, uv), psycopg 3 async pool, plain SQL.
- **Database**: Supabase Postgres (any Postgres 15+ works). RLS on, no policies: the public Supabase keys can read nothing.
- **Files**: local disk in development, Supabase Storage when deployed (`STORAGE_BACKEND`).
- **Models**: Groq and Cerebras (free, no card) and Gemini, through a role-based router with automatic failover; any OpenAI-compatible model can be added. Writer and Checker always start on different models. Agnes is supported but optional.
- **Indian languages**: Sarvam AI (speech to text for voice briefs, independent translation for the Checker); the browser's speech API without a key.

## Run it

Database and API keys, step by step (Supabase, Groq, Cerebras, Gemini, Sarvam, optional extras): see [docs/SETUP.md](docs/SETUP.md).

Prerequisites: Node 20+ and [uv](https://docs.astral.sh/uv/). (On this machine both live in `~/.local`: `export PATH=~/.local/opt/node/bin:~/.local/bin:$PATH`.)

```bash
# 1. Backend
cd backend
cp .env.example .env              # then fill it with the scripts in docs/SETUP.md
uv sync
uv run python -m scripts.migrate  # creates the schema (add --reset to start over)
uv run python -m scripts.seed     # loads the synthetic demo café
uv run uvicorn app.main:app --reload --port 8000

# 2. Frontend (another terminal)
cd frontend
cp .env.example .env.local
npm install
npm run dev                       # http://localhost:3000
```

No Supabase yet? `uv run python -m scripts.dev_db` starts a local Postgres 16 (no Docker) and prints a `DATABASE_URL`.
No model key yet? `uv run python -m scripts.sample_campaign` builds a hand-written sample campaign through the real services so every screen has data.

### Supabase

1. Create a project. Click **Connect**, copy the **Session pooler** string (IPv4, port 5432) and run `uv run python -m scripts.set_db_password`, which asks for it and the password and writes `DATABASE_URL`.
2. `uv run python -m scripts.migrate && uv run python -m scripts.seed`. (`supabase db push` also works with the same migration files.)
3. When deploying, set `STORAGE_BACKEND=supabase`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the **backend** env. The bucket is created on startup.

All keys exist only in `backend/.env` (or the host's env settings). The frontend never receives them.

## Tests

```bash
cd backend && uv run pytest     # embedded Postgres 16 + scripted LLM; no network, no keys
cd backend && uv run ruff check .
cd frontend && npm run typecheck && npm run build
```

`tests/test_team.py` gives the Orchestrator, Writer and Checker separate scripted models and checks the hand-offs, the tool boundaries and the work log. The end-to-end test walks the whole loop: brief → agent drafts facts → lock is gated to the owner → owner approves → copy generated and guarded (a model-typed number is blocked) → meaning check → owner types “30% off” and is blocked → publish issues a code → customer scans and claims → counter redemption → experiment with history prior → “Sunday only” marks exactly the date-dependent pieces stale.

## Demo data

Everything in `data/seed/` is synthetic and labelled as such in the UI (“Imported history”, “Synthetic demo data”). Replayed model outputs are labelled “Saved output”. Live QR scans and counter redemptions are the only data presented as real.
