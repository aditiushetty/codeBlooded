# Counterpart: project memory

The running context for this project: what we are building, what we decided and why, and where setup stands.
**Update this file whenever a decision is made or a step is finished** (newest entries at the top of each log).
Architecture and code rules live in `CLAUDE.md`; this file is the "why" and the "where are we".
The ordered roadmap with checkboxes is `TODO.md` (root); tick items there when they are finished.

Last updated: 2026-10-23 (TODO #7 redone as the Scout)

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
| 2026-10-23 | **TODO #7 = "whatever is happening around" (owner's wording), not just hiding festivals.** Scout agent + moments from real sources only: weather (Open-Meteo), calendar, business events, owner-added events (IPL match, fest). No invented fixtures. | Owner's correction; first build only hid festivals. |
| 2026-10-23 | **Festivals behind `FESTIVALS` (default off).** Replaces "festival cards stay visible": set `FESTIVALS=true` in backend/.env to show them again for a review. | TODO #7; out of the pitch. |
| 2026-10-23 | **Offer wording: Offer/Change agents write English, the Language agent writes kn/hi** (Sarvam first, its own words where checks fail). The checker compares against the English only (no raw values). | Sarvam is fluent but not trusted; one agent owns languages. |
| 2026-10-23 | **Offer change = rewrite only posts whose own text uses the changed detail; refill the rest.** | The offer box is system-rendered; rewriting every post wasted model calls and approvals. |
| 2026-10-23 | **Keep the original "counter book" UI.** A dark "AI team control room" redesign was built and then reverted to the pushed version at the owner's request. | Owner preferred the UI already pushed to git. |
| 2026-10-23 | **Festival cards stay visible in the app** (Today, campaign page, Customers) for the review demo, though festivals are out of the pitch. | Owner's call; no UI change. |
| 2026-10-23 | **Split order:** Orchestrator + Writer + Checker first (done), Offer (done); next Change, Language (Sarvam), Analyst, Brief, Customer listener. | Writer/Checker separation is the core safety story. |
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
| `DEMO_PASSWORD` | Done |
| `GROQ_API_KEY` | Done (backup) |
| `CEREBRAS_API_KEY` | Optional |
| `SARVAM_API_KEY` | Done (2026-10-23, tested; free plan 100 credits, spend carefully) |
| `GEMINI_API_KEY` | Done (main text models; ~20 requests/day per model on free tier) |
| `AGNES_API_KEY` | Not used any more |
| Google Maps, Meta (WhatsApp/Instagram) | Optional, later |

Without Gemini: photo captioning ("vision" role) is off. Without Agnes: no AI pictures (real photos only).

## 5. Work log (newest first)

- **2026-10-23** **TODO #7 redone: Scout agent.** First pass only hid festivals; the owner's TODO note asked for
  context ("IPL going on or some event: find a business opportunity and offers"). Built moments (weather via
  Open-Meteo, weekend, salary week, business + owner-added events), `GET/POST/DELETE /businesses/{slug}/moments`,
  `POST /businesses/{slug}/opportunities` (Scout, one reasoning call, `scout.ideas` in the ledger), Today page
  section. 84 tests pass. Note: the owner's editor had overwritten TODO.md ticks for #3-#5; restored.

- **2026-10-23** **TODO #3, #4, #5, #7 in one go** (82 tests pass, typecheck clean; migrations `20261023000100_translation_cache.sql`
  applied). Team is now Orchestrator + Offer, Change, Language, Writer, Checker. Live run on Kaapi Kone ("20% off
  masala dosa, Mon-Fri, 3 to 6 pm, till 6 Nov"): Offer agent drafted English -> Orchestrator's lock refused by the
  rules (missing kn/hi) -> Language agent: Sarvam wrote "evening 3 to 6" for 3 pm, checker caught it, agent fixed
  to "afternoon 3 to evening 6" -> number rule refused dates the English lacked -> Offer agent fixed the English ->
  wording passed -> lock request waiting in the inbox. Seen live: the Language agent once reported "ready" when its
  tool said not ready; the lock gate refused it (tool now returns `next_step`). The checker flagged "start date not
  specified" from the raw dates: fixed by sending it only the English. Change agent tested in unit tests only (a live
  run needs locked offer + posts = many model calls). Editing backend files restarts uvicorn and kills a running
  agent run (seen once).

- **2026-10-23** **Offer agent (TODO #2).** Orchestrator --ask_offer--> Offer agent (reasoning role, tools:
  get_situation, get_menu, evaluate_offer, draft/revise_offer_facts, ask_owner). Drafting moved off the Orchestrator;
  it keeps lock_facts (owner-gated). Rules in code: `domain/offer.py` gaps (no benefit, no end date, item not on menu,
  past/invalid dates, unreadable hours; "whole bill or items?" is advisory) + automatic margin on every draft; the
  agent's lock request is refused while blocking gaps remain (the owner can still lock directly). Questions:
  migration `20261023000000_owner_questions.sql` (inbox kind `question`, applied to Supabase), max 3 open, deduped;
  answer = decision note (required), resumes the team. revise_offer_facts now edits the unlocked draft and can add a
  fact. Specialist budget 4 -> 6 calls. UI: question card with answer chips in the inbox; Offer agent on the AI
  team page. Live check: brief "15% off for college students" -> draft (Filter coffee, 16:00-20:00, college ID,
  margin healthy) -> one question (end date) -> answer -> wording check caught "coffee" vs "filter coffee" in kn/hi,
  agent fixed it -> Orchestrator asked to lock. 75 tests pass.

- **2026-10-23** **Sarvam live (TODO #1).** Key set; end-to-end check passed: en→kn/hi translation and back
  (mayura:v1), English and Kannada speech to text (saaras:v4, Kannada "ಹದಿನೈದು ಶೇಕಡಾ" heard as "15%").
  **Found:** mayura turned "weekday evenings" into "week evening, Friday evening" in Kannada; the back-translation
  ("weekends, Friday evenings") exposed it. So machine translation is not trusted either: the Language agent must
  pass the Checker's back-translation + day/number comparison. Sarvam TTS `bulbul:v2` is deprecated, use `bulbul:v3`.
  Free plan is 100 credits; the whole check used well under 1.

- **2026-10-23** **Control room UI built, then reverted.** A dark redesign (sidebar, live AI team panel, glass cards) was
  made and checked, then all frontend files were restored from git (`git restore frontend/ CLAUDE.md`) because the
  owner wanted the old UI back. Kept: the Orchestrator prompt fix in `backend/app/agent/prompts.py`.
- **2026-10-23** **Live check with real keys (Gemini + Groq).** All three roles answer and call tools; Groq alone
  works as backup. Full run on the demo café through the running app: Orchestrator checked margin, drafted
  facts (Kannada/Hindi wording verified), asked for the lock; after the owner lock the Writer wrote 3 posts (guard
  blocked "ultimate" and a typed "4, 7", repaired), the Checker passed 3/3, publish queued for the owner, A/B test
  created. Campaign "Student Study Break Offer" is in the demo café, publish approval pending. Fixed: Orchestrator
  handed off before the lock (prompt now says hand off only once locked). A `next build` run during `next dev`
  corrupted `frontend/.next`; cleared and restarted dev. Added `.claude/launch.json` (frontend, backend).
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
- Remove `culture.py` from the code later? (Kept visible in the UI for the review demo.)
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

## 2026-10-23: remaining agents and competitor gaps (TODO 11-19)
- Team is now 12: Brief agent (plan first), Analyst (verification role; numbers must be in results, comparisons need analytics.SURE), Customer listener (issues/reply drafts/follow-up briefs; never sends). Owner can run Analyst/listener directly (`runtime.run_specialist`).
- Come-back codes (`claims.kind='return'`, `campaigns.return_days`), bill import (`domain/bills.py`), WhatsApp templates (`wa_templates`, `domain/wa_template.py`, needs `waba_id`), Google Business Profile (`channels/google_business.py`, needs GOOGLE_OAUTH_CLIENT_ID/SECRET; untested against real Google), spoken menu (`/onboarding/menu-speech`), reels (`/assets/{id}/reel`, `components/reach-tools.tsx`).
- Not verified live: Google publish, WhatsApp template submit (no Meta/Google creds in demo). Brief agent verified live 2026-10-24 ("Rainy evenings..." campaign: Brief -> Offer -> question to owner, waiting).
- Nothing committed yet.

## 2026-10-24: proof for the judges (TODO 8-10)
- Checker test: 49/50 known-bad caught (rules 39 + meaning check 10 on gemini-3.1-flash-lite), 0/10 good blocked. Report in data/eval/checker_report.json; rerun with `uv run python -m scripts.checker_eval --live` (6 model calls + cached Sarvam). Skipped posts are retried once and reported as no_verdict, not false alarms.
- New guard rules from it: times of day and day names in a post must fit the offer's hours/days (L2 times_match, days_match).
- Owner effort from the ledger (domain/effort.py); AI cost from stored model_calls at AI_PRICE_*_USD_PER_M (default Gemini Flash-Lite list $0.10/$0.40, USD_INR 84; an estimate, labelled so). Only calls made after 2026-10-24 are stored.
- Next (user, 2026-10-24): connect WhatsApp and Instagram for real (TODO 20). Nothing committed yet.
## 2026-10-24: connecting WhatsApp and Instagram (TODO 20, in progress)
- Business to connect first: Nexathon (`nexathon-26cc`, 6 approved/live posts). One WhatsApp number serves one business (webhook routes by phone_number_id); each business needs its own professional Instagram account. Others later via the Channels page or `scripts.go_live --reset`.
- cloudflared 2026.10.3 installed at ~/.local/bin (official Cloudflare release).
- Meta side (built-in browser pane): the user's first Facebook account was refused at developer phone verification (number shared with another Meta account); switched to a second account, registered as developer. App wizard filled (name Counterpart, WhatsApp use case) but stopped at Business: new accounts must wait ~1 hour before creating a business portfolio. Instagram use case was not offered in the wizard; add it after the app exists.
- The user does sign-ins, account/portfolio creation, codes and secrets; Claude drives the rest.
- Progress later on 2026-10-24: business portfolio "Counterpartdemo" (unverified, id 1104810049104981) and Meta app "Counterpart" (app id 1283719630565611, WhatsApp + Instagram use cases; Instagram side "Counterpart-IG" id 1155743350218695) created. Instagram permissions added: business_basic, content_publish, manage_comments, manage_insights, manage_messages.
- Blocked: WhatsApp "Claim test number" fails 3 times ("An error occurred while creating the test account"), likely the brand-new developer account. Instagram tester invite refused ("Form can't be saved") for insta_marketing_agent_nexathon and Nexathon_Marketing_agent1 (both "Profile isn't available" on instagram.com); Instagram login in the browser pane fails (security check). Options: retry tomorrow, use an older Facebook/Instagram account, or do the Instagram steps in the user's own Chrome.
- Instagram tester invite also refused for marketing_markii (a real account the user is signed in to in Chrome), and the WhatsApp test number failed a 3rd time: the blocker is the brand-new developer account / portfolio (same "too new" limits as the portfolio wait), not the Instagram accounts. Next: retry after ~24 h, or redo the app on an older Facebook account. Claude in Chrome is connected (user's Chrome, Instagram signed in as marketing_markii there).
- Real errors (read from Meta's network responses, 2026-10-24): WhatsApp claim test number -> "WhatsApp test numbers are currently unavailable. Try again later." (code 2655005, Meta-side); Instagram tester add -> typeahead finds marketing_markii (IG id 17841462612648945) but /async/instagram/roles/add/ returns success:false with no reason. Fallbacks: WhatsApp Step 2 with an own phone number that is not on WhatsApp; Instagram via Business Suite (add the IG account to the Counterpartdemo portfolio, which needs Facebook + Instagram signed in in the same browser).
- Decision (user, 2026-10-24): retry the WhatsApp test number on 2026-10-25 (Meta still "test numbers currently unavailable" at the last try). Fallback if it still fails: own spare number via Step 2. Instagram: Business Suite route once Facebook (Tester Dev) is signed in in Chrome.
- 2026-10-24 Instagram unblocked: the tester invite failed only because the account was personal. In Chrome (Claude in Chrome), marketing_markii was switched to a professional Business account (category Marketing Agency, no public contact info), added to the Counterpartdemo portfolio, invited as Instagram tester (accepted), and an IGAA token generated. scripts.go_live needs WhatsApp values, so Instagram alone is connected from the app's Channels page (PUT /businesses/{slug}/channels/instagram) with the owner pasting the token.
- 2026-10-24 Instagram LIVE for Nexathon: connected @marketing_markii (IG id 17841462612648945, token to 2026-12-22) on the Channels page; published the English "Student Coffee Combo" post through Counterpart -> https://www.instagram.com/p/De2pVesCF5h/ (caption carries code E3HNDG); insights sync reads it back (all 0 so far). Fixed: connecting the same WhatsApp number / Instagram account to a second business now returns a clear 409 instead of a 500 (`_not_taken` in api/channels.py, test added; 107 tests pass). Comment-to-review sync not yet tested live.
- 2026-10-24 also published the English "Weekday Special 10% Off" post -> https://www.instagram.com/p/De2puWtiH7j/ (code VPMP9T); hourly insights sync tracks both posts. Hindi Weekday Special post not published.
- 2026-10-24 Instagram follow-ups done: (1) "can't see Instagram reviews" had two causes: comments were read at most hourly (now every 3 min + "Check now" on Customers), and Meta's development mode counts comments from non-tester accounts but lists none (now reported to the owner as `comments_hidden`). To see real customers' comments: add each commenter as an Instagram tester, or take the app live after Meta review. (2) Personal codes from Instagram: a comment with CODE/coupon/offer/the post code gets a one-time claim (via 'instagram') in a private reply; captions now invite it. (3) `app/watch.py` background pass every CHANNEL_WATCH_SECONDS=180. Migration 20261024000200 applied. 109 tests pass.
- Decision 2026-10-24: Meta development mode only covers accounts with a role on the app (Instagram testers; 5 WhatsApp numbers). Reaching every customer needs Business Verification + App Review + Live mode (TODO 22), not doable before the demo. Demo plan: testers (team/judges) for the live comment->code moment; everyone else gets personal codes through the post link/QR ("Get my code"), which needs no Meta approval. TODO 21-24 added.
- 2026-10-24 (TODO 21-24): invited nishan_uhh, sathwik_shetty172, jeethannn as Instagram Testers on app 1283719630565611 (all Pending until each accepts on instagram.com). Instagram API CANNOT edit captions (live answer: "The parameter comment_enabled is required"), so old posts get the "Comment CODE" line as the business's own comment (`instagram_media.code_line` caption|comment, migration 20261025000000, applied). Running it live on the 3 old Nexathon posts was blocked by the auto-mode permission check (public content), so the owner presses the button on each post card. Built Instagram DM codes over `/api/public/instagram/webhook` (signed by INSTAGRAM_APP_SECRET or META_APP_SECRET; verify token shared with WhatsApp; `subscribe` on connect), and the Meta data deletion/deauthorize callback `/api/public/meta/data-deletion` + status page. Public /privacy, /terms, /data-deletion pages (contact from NEXT_PUBLIC_CONTACT_EMAIL; the owner's email is deliberately not hard-coded). Go-live checklist: docs/GO_LIVE.md. 111 tests pass.

- 2026-10-24 TODO 21 live test: nishan_uhh and sathwik_shetty172 accepted the tester invite; they commented CODE but no private reply arrived (backend had been stopped; restarted; not diagnosed further, the user moved to WhatsApp first).
- 2026-10-24 WhatsApp retry: 'Claim test number' still fails. Meta's Developer assistant says portfolio 1104810049104981 has a 'hard lock' that blocks WhatsApp; Account Quality shows no issues (most likely the new, unverified portfolio). The dashboard also states an UNPUBLISHED app receives only dashboard test webhooks, no real messages, so the live WhatsApp claim flow needs the app published too. The user won't use a personal number. Options: wait or start Business Verification, a new SIM, or a wa.me button plus a labelled simulation.
- 2026-10-24 Decision: reach existing customers WITHOUT the WhatsApp API (portfolio locked, user won't use a personal number): owner-sent wa.me messages from their own WhatsApp, a personal code per customer per campaign, a review link after redemption (TODO 25). Consent is required (owner tick or customer tick on the code page); no unofficial WhatsApp automation (ban risk). Messages link to PUBLIC_BASE_URL/c/<code>, so they only open for customers once deployed (the UI warns on localhost). Note: I overwrote the existing backend/tests/test_reach.py by mistake and restored it from git; the new tests are in tests/test_customer_list.py.
- 2026-10-24 Instagram: after nishan_uhh and sathwik_shetty172 accepted, the Customers page still says Instagram holds back 8 comments. Not diagnosed (the user parked Instagram).
- 2026-10-24 Instagram comments root cause: /{media}/comments returns data [] with non-empty paging cursors even for accepted testers. Meta withholds comment text while the app is unpublished (the WhatsApp Step 2 page says unpublished apps get no production data, admins and testers included). Account and post insights and like_count/comments_count DO work. Unlock = publish the Counterpart app (needs the privacy/terms/data-deletion URLs public, so deploy first). Built the Results page Instagram overview (TODO 26).
- 2026-10-24 Campaign numbers checked live on Nexathon. Live = approved posts out; Opened = link/QR opens (outcome 'scan', once per phone); Claimed = "Get my code" ('click'); Redeemed = used at the counter ('redeem'), INCLUDING a post's 6-letter code typed at the counter with no link open. Fixes: (1) Conversion was redeemed/opened and showed 200% because both Nexathon redemptions were typed post codes; it now counts only redemptions of codes got from the link (`from_link`: a claim with via 'web', or simulated meta.from_link), in results, campaigns list and campaign analytics. (2) Codes the owner makes for their customer list (via 'invite') no longer count as "claimed". Test open and claim (KPQRYYY) were removed afterwards.

- 2026-10-24 UX/bug pass after the user said "idea good, UX crowded, analytics/results buggy, app looks empty, need an API key indicator". Found live: (1) an owner's answer given while an agent run was still going was silently dropped (`_run` returned "busy"), which left Rainy Day Warmup Combo stuck while Today said "Counterpart is writing the offer down"; fixed with a per-campaign queue (`runtime._queued`) and a "Carry on" button wherever a run ended with nothing ready. (2) Instagram overview took 8 s on every expired cache; now parallel reads + stale-while-refresh. (3) Campaign Instagram table showed 300% engagement at reach 2; now "too few yet" under 20 reached. Key indicator: header "Keys" dot (green/amber/red), states from real calls, "Check now" lists models only (no quota). Live state on Nexathon: Gemini, Groq, Agnes work; Gemini key 2, Cerebras, Google Maps, Meta app secret not set; Sarvam unused since restart. Rainy Day still needs the owner to press "Carry on" (left for the user: it runs the agent).
- 2026-10-24 User: don't continue Rainy Day Warmup Combo (leave it). Scout gave the gym business (gigantics-gym-5561, sells "Monthly membership") café ideas ("warm beverages and comfort food"). Causes: the Scout prompt's only example was "filter coffee and onion pakoda", the list was called "menu", moment hints were food-flavoured ("somewhere warm", "cold drinks"), and no rule checked the brief text. Fixed: trade-neutral hints, prompt names the business type and its exact offerings, `domain/moments.off_trade` drops ideas naming food/drink the business does not sell (generic words like drink/combo allowed only for food kinds), items keep only real offerings (falls back to an offering named word for word in the brief). Live: gym now gets "Rainy Evening Workout", "Weekend Fitness Kickstart", "Payday Investment in Health" (all Monthly membership); Nexathon café still gets coffee/pastry ideas.
- 2026-10-24 User reported: Instagram posting stopped, Maps link sign-up only fills the name, best-time chart missing, UI slow; asked whether to deploy first. Found: Nexathon's last two campaigns were planned with counter posters only (Brief agent picked poster), and autopublish only marks posts live, never posts to Instagram (that needed a click). Decided: a connected Instagram makes an Instagram post mandatory in the plan (rule in `domain/brief.py`), and the campaign page auto-posts live Instagram posts when autopublish is on (browser draws the picture, as before; no server rendering because Pillow lacks Kannada shaping). Maps: GOOGLE_MAPS_API_KEY is not set, so photos from Google are impossible without it (never scrape Google); OpenStreetMap Nominatim is the no-key fallback; menu photo reader added. Speed: Supabase (ap-south-1) round trip ~40 ms per query is the floor; routes went from 0.25-1 s to 0.16-0.6 s; the bigger cost is `next dev` compiling each page on first open (~3 s), so demo with `npm run fast`. psycopg pipeline mode hangs through the Supabase pooler: don't use it. Answer on deploying: posting works without deploying (pictures go through Supabase Storage), but every customer link/QR uses PUBLIC_BASE_URL=http://localhost:3000, and comment/DM webhooks need a fixed public address, so deploy before real customers.
- 2026-10-24 User could not add a card to Google Cloud, so no Google Maps key: decided to skip it. Sign-up relies on OpenStreetMap for details and on "Take a photo of your menu", now also on the first sign-up screen (reads the photo, then opens the review page). Live check on a printed gym rate card: 4 priced items read correctly, the unpriced one skipped.
- 2026-10-24 User thought dynamic QR/code generation was pending before deploy. Checked: every QR (/api/public/qr/{code}.png) and link is built from PUBLIC_BASE_URL on each request, personal codes per customer on demand, Instagram pictures carry no URL (only posters have a QR). So nothing to build: set PUBLIC_BASE_URL to the deployed address and all links/QRs switch, old campaigns included. Added /me features.public_links and a warning on the campaign Share section while links point at localhost. Posters printed before deploy must be reprinted.
