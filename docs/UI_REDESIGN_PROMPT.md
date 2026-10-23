# Prompt: redesign the Counterpart owner UI

Paste everything below the line into a new Claude Code session opened at the repo root.

---

You are redesigning the owner-facing UI of Counterpart (Next.js 15 App Router, Tailwind v4, `frontend/`). Read `CLAUDE.md` and `MEMORY.md` first. Do not touch backend code, API shapes, routes, or any invariant in `CLAUDE.md`. This is a visual and layout change only.

## Who this is for
A small-business owner in Bengaluru (café, salon, kirana) checking their marketing on a phone between customers, sometimes on a laptop at night. They are not technical. They want to know three things in under five seconds: what needs me, what is live, and is it working. The product's real strength is trust: locked offer facts, a checker that verifies every post, honest numbers. The UI should feel like a well-kept shop ledger, not a sci-fi dashboard.

## What is wrong now
The current "control room" theme (`frontend/app/globals.css`, dated 2026-10-23) reads as generic AI product styling. Remove all of it:
- Dark navy paper `#060a13` with indigo/violet radial glows and the faint grid (`body::before`).
- `.glass` (backdrop blur cards), `.night` (gradient lifted panels), `.btn-grad` (gradient buttons with glow), `.grad-text` (gradient page titles).
- `.orb-live`, `.ring-spin`, `.scanline`, `AgentOrb`, breathing/pulsing orbs, `flow-dot` animations, glowing indigo shadows (`--shadow-lift` glow ring).
- Purple/violet and mint as decoration. Every `bg-gradient-*` and `backdrop-blur` in `app/` and `components/`.
- Emoji-like sparkles, "AI magic" wording, robot/brain metaphors, "Your AI team is thinking..." theatre.
Run `grep -rnE 'glass|night|grad-text|btn-grad|orb-live|ring-spin|scanline|needs-panel|AgentOrb|backdrop-blur|bg-gradient|violet|mint' frontend/app frontend/components frontend/lib` before and after; after, only intentional uses may remain.

## Colour: use the project's own palette, nothing new
The project already has an honest, local palette in `.light-scope` (warm paper, ink, pen blue, marker yellow, turmeric, kumkum red). Make that the app-wide default and delete the dark set. Keep the token names so every page keeps its meaning:
- `paper #f3f2ed` page, `surface #ffffff` cards, `sunken #e8e7e0` wells, `line #dcdad1`, `line-strong #b9b6aa`
- `ink #16150f`, `ink-2 #44423a`, `muted #6b685d` (check muted reaches 4.5:1 on paper; darken if not)
- `pen #2340c4` = Counterpart's work and links only
- `marker #ffd43b` / `marker-soft #fff3c4` = needs the owner now, used sparingly (one or two places per screen)
- `turmeric #8a5200` = warnings/pending; `kumkum #c2361b` = problems and the live dot only
- `--color-brand` on posts stays as set by `lib/theme.ts`
Rules: one accent per component. No gradients on surfaces, buttons, or text. Shadows only as a 1px line or a soft drop (`--shadow-soft`, `--shadow-lift` from the light set). Borders do most of the separation work. Once the whole app is light, `.light-scope` wrappers on customer pages (`app/r|c|k/layout.tsx`) and `components/previews.tsx` can stay as harmless no-ops; do not remove them. Remove the "on bright fills" remapping hacks only where you have checked every use still reads correctly. Set `color-scheme: light`.

## Type
Keep Anek (covers Latin, Kannada, Devanagari) and Martian Mono for codes, money and the log. Use type, not colour, for hierarchy: page title 28 to 32px semibold, section heading 18 to 20px, body 15 to 16px, labels 13px. Min 12px anywhere. Numbers that matter (claimed, redeemed, ₹ sales) in the condensed `.sign` style with `tabular-nums`. Sentence case everywhere. No em/en dashes in UI copy.

## Layout (most effective, not most impressive)
1. Shell (`components/shell.tsx`): on lg a slim left sidebar, white surface, a 1px right border, business name and switcher at top, nav as plain text rows with a Phosphor icon and a 3px pen-coloured left bar for the active item. Replace the live `TeamPanel` in the sidebar with a single quiet status line ("2 agents working" with a small kumkum dot when something is live), linking to the AI team page. Phones: compact top bar plus bottom nav of max 5 items, 44px touch targets.
2. Content width: max 1120px, 24px gutters (16px on phone). A consistent 8px spacing scale. Generous whitespace between sections instead of boxes inside boxes: never nest a card inside a card.
3. Today (`app/(app)/page.tsx`): top to bottom in priority order:
   - "Needs you" list: plain rows on `marker-soft` with one action button each. If empty, a one-line "Nothing needs you" in muted text, no illustration.
   - Composer: a plain textarea with a clear primary button, like writing in a notebook.
   - Campaigns ledger: a real table on lg (name, step, live, claimed, redeemed, next action), stacked rows on phones. `JourneyMini` as small text steps or 5 short segments, not glowing dots.
   - `components/team-room.tsx`: turn into a compact activity list (time, agent name, what it did), mono timestamps, no orbs or animation. Collapsed by default to the last 5 lines.
4. Campaign page (`app/(app)/campaigns/[id]/page.tsx`): `JourneyTrack` as a simple numbered stepper (Brief, Offer, Posts, Share, Results) with the current step in ink and done steps with a check. One "Next" line under it with one button. Sections #offer #posts #share #results separated by headings and a rule, not by heavy cards. Locked offer facts look like a printed receipt (keep `.receipt-edge`/`.perforation`/`.stamp`; they fit the ledger idea and are not AI-coded).
5. Campaigns and Results: tables first, charts second. Charts use pen for the main series and ink-2 for comparisons, no gradients or area glows, light gridlines, direct labels instead of legends where possible.
6. Agents page: a plain list of agents (name, role in one line, what they may do, last action). Agent identity by name and a small neutral initial badge, not a colour-coded orb per agent. Drop `HUE` colours in `lib/team.ts` or map them all to ink/pen.
7. Buttons: primary = solid ink on paper with white text, 8px radius; secondary = white with `line-strong` border; destructive = kumkum text. One primary per view region. Inputs: white, 1px border, pen focus ring.
8. Radius: 8px controls, 12px cards. No pill-shaped everything.

## Motion
Keep only motion that explains a state change: page fade (≤200ms), sheet up for the post editor, `stamp-in` on lock, `skeleton` while loading, a small spinner on a button that is working. Remove infinite animations except one live dot. Respect `prefers-reduced-motion` (already in globals.css; keep it).

## Copy
Plain, specific, owner's words. "3 posts ready to check", not "Your AI team has crafted magic". Name agents by job (Writer, Checker) not personas. Synthetic/simulated data must stay labelled.

## Process
1. Audit: list every page in `app/(app)`, `app/onboarding`, `app/login`, `app/signup` and every component in `components/` that uses the classes above. Write the list in your plan.
2. Change tokens and base styles in `globals.css` first, delete the dead classes, then fix pages one at a time, starting with `shell.tsx`, Today, campaign detail, campaigns list, then the rest.
3. After each page: `npm run typecheck`, then open it with the preview tool at 1280px and 375px and screenshot. Check contrast of muted text, marker-soft rows and button text.
4. Finish with `npm run build`, a final grep for removed classes, and before/after screenshots of Today, a campaign page and Results on desktop and phone.
5. Update the "Design system (frontend)" section of `CLAUDE.md` and add a dated line to `MEMORY.md` describing the new direction ("ledger", light, replaced "control room").

Constraints: Phosphor icons only. Set `lang` on customer copy. Do not change customer-facing pages (`app/r`, `app/c`, `app/k`) or the post previews except where a removed class breaks them. Do not commit; leave the diff for review.
