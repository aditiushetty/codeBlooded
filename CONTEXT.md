# Counterpart: chat context

A summary of the Claude Code working session that ended on 2026-10-23, so a new session (or a teammate) can pick up from here. Lasting decisions live in `MEMORY.md`, the roadmap in `TODO.md`, the pitch in `PITCH.md`. This file is the story of the session and its loose ends.

No secrets are in this file. Keys are set only with `uv run python -m scripts.set_secret <NAME>` from `backend/` and live only in `backend/.env`.

---

## 1. Where things stand

| Area | State |
|---|---|
| UI | The original "counter book" UI (light paper, black ink, yellow highlighter), exactly as pushed in commit `cf104e6` "review-ready". |
| Agents | Orchestrator, Writer and Checker. Offer, Language (Sarvam) and Analyst agents are next. |
| Models | Gemini (default text), Groq and Cerebras (free backups), Sarvam (speech and translation). Images need Agnes. |
| Demo | `kaapi-kone` café with the old repo's demo data and simulated customers. It has 0 photos. |
| Git | Remote `origin/main`. Last commit `cf104e6`. Nothing from this session is committed. |

### Uncommitted changes

- `backend/app/agent/prompts.py`: Orchestrator prompt fix (see section 4).
- `MEMORY.md`: records the UI revert, the festival-cards decision and a work log entry.
- `CLAUDE.md`: one line pointing to `TODO.md`.
- New files: `TODO.md`, `docs/BACKEND.md`, `docs/FRONTEND.md`, `docs/UI_REDESIGN_PROMPT.md`, `.claude/launch.json`, and this `CONTEXT.md`.

---

## 2. What happened, in order

### Earlier in the session
- Set up `.env` and API keys.
- Chose the multi-agent direction: Sarvam for Indian languages, Groq and Cerebras as free backups now, Gemini as the default. Agnes and festivals stay out of the pitch.
- Wrote `MEMORY.md` and `PITCH.md`.
- Split the single agent into an Orchestrator, a Writer and a Checker. More agents were put on hold.
- Built the Nexathon PPT, prepared for the review, verified the APIs, wrote run instructions, and brainstormed names. The name lists were rejected.

### Selling the AI part
- The question: in a real business, which AI do we use?
- The answer: **we ship the agent team and the system around it** (locked facts, guard, approvals, ledger, attribution). The models are rented and swappable: Gemini, Sarvam, and Llama on Groq.

### Demo data
- Downloaded the demo data from the old repo (`https://github.com/Sathwik-1712/counterpart.git`). It turned out identical to ours.
- Showed the demo business, including simulated customers.
- **Decision:** the festival cards stay visible in the app for the review demo.

### New API key, test run
- The user changed the API key. It was tested and the backend reloaded.
- A demo campaign, "Weekend Morning Vada Combo", ran and exposed issues (section 5).

### Image generation
- **Why it fails:** only Agnes is wired for the image role (`ROLE_IMAGE=agnes`), and there was no working `AGNES_API_KEY`. Gemini image models return 429 on the free tier (no image quota).
- **Free options:** the Agnes free plan includes images (1K, 10 RPM). Alternatives would need new provider code: Cloudflare Workers AI (FLUX), or Gemini image with billing or the GCP $300 trial.
- The user chose to try Agnes and ran `set_secret`. It is not confirmed whether the key works.
- Note: `set_secret` must run from `backend/` (`cd backend` first), or it fails with "No module named 'scripts'".

### How to run
```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
```
```bash
cd frontend && npm run dev
```
Do not run `npm run build` while `npm run dev` is running; it corrupts `.next`.

### UI redesign, then revert
- The user wanted a richer UI. An "AI team control room" (dark, whole app) was built.
- The user then asked to bring back the old UI they had pushed to git.
- **Done:** `git restore frontend/ CLAUDE.md`. Deleted the new files `frontend/app/{r,c,k}/layout.tsx`, `frontend/components/team-room.tsx` and `frontend/lib/team.ts`, plus stale `.next/types/app/{r,c,k}/layout.ts`. Typecheck passes and the app loads with the original look.
- **Decision (in `MEMORY.md`):** keep the original counter book UI.
- `docs/UI_REDESIGN_PROMPT.md` holds a redesign prompt for a future session, if wanted.

---

## 3. Decisions made this session

- We sell the system and the agent team. LLMs are rented components.
- Festival cards stay visible for the review demo. Removing `culture.py` is an open question for later.
- The original counter book UI stays. The dark control room was tried and reverted.
- The agent split continues after the UI: the Offer agent first, then Language (Sarvam), then Analyst.

---

## 4. Code change kept: Orchestrator prompt

In `backend/app/agent/prompts.py`, `ORCHESTRATOR_SYSTEM` now says the Orchestrator:
- hands off only after the owner has locked the facts (`situation.offer_facts.status` is `"locked"`);
- asks for the lock and stops while the facts are a draft;
- then saves the plan once and calls `ask_writer` once for all its posts;
- calls `ask_writer` with the `asset_ids` of stale (offer changed) or blocked posts.

---

## 5. Open issues

1. **Live-update streams can freeze the backend.** Every page opens a ledger SSE stream (`/api/businesses/{slug}/events`). Leaked streams piled up to 61 connections to `:8000` and held database connections, so `/api/me` hung and the app stuck on loading. The fix used was `kill -9` on the stuck uvicorn worker (the `--reload` reloader starts a new one). This is a risk in a live demo with many refreshes or tabs. **Not fixed yet.** The last question to the user was whether to fix this or start the agents.
2. **Wrong test campaign.** "Weekend Morning Vada Combo" (id starts `ee70c51e`) has 50% off masala vada (wrong offer) and is missing the 7 to 10 am window. A misplaced click dismissed the Orchestrator's menu-item question, so the agent guessed. Nothing in it is approved or live. Not yet corrected or deleted.
3. **Time window dropped from locked facts.** The Orchestrator's approval summary said 7 to 10 am, but the locked facts did not include it. This is a real bug. Not fixed.
4. **Unknown facts lock.** The facts were locked by a direct owner `POST /campaigns/{id}/facts/lock` 0.5 s after the request. Its source is unknown; the user was asked whether they clicked it.
5. **Images.** The Agnes key needs checking: reload the backend, confirm the image role lists `agnes`, and generate a test picture.
6. **No photos in the demo café**, so posts have no pictures until photos or AI images work.

---

## 6. Next steps

1. Answer: fix the SSE stream leak first, or start the agents.
2. Offer agent: turns the owner's idea into draft facts and asks about anything unclear. The owner locks; the agent never does.
3. Language agent on Sarvam: writes Kannada and Hindi natively and back-translates for the Checker.
4. Analyst agent.
5. Fix the dropped time window, and correct or delete the test campaign.
6. Commit the uncommitted changes when the user asks.

---

## 7. Useful notes for the next session

- **Uvicorn `--reload`:** touching a `.py` file restarts the worker, but shutdown can hang on open SSE streams. `kill -9` the worker and the reloader respawns it.
- **Stale `.next/types`:** after deleting pages, old files in `.next/types` can break `npm run typecheck`. Delete them.
- **Live smoke test script:** run with `PYTHONPATH=.` from `backend/` (otherwise "No module named 'app'"). Scripts that read the DB must call `open_pool(get_settings().database_url, ...)` first.
- **Model router status:** `build_router(get_settings()).status()["roles"]` shows each role's model chain.
- **Policy gate:** `lock_facts` from the agent becomes an inbox approval. A direct owner lock approves pending `lock_facts` inbox items with decision `{"via": "direct"}`.
- **Agents in the UI:** `backend/app/api/workspace.py` lists Orchestrator (reasoning), Writer (generation), Checker (verification), Photo reader (vision) and Picture maker (image).
- **Standing rules:** never paste keys into chat; tokens never reach browser JS; commit or push only when asked.
