# Frontend: how the code works

The frontend is a Next.js 15 app (App Router, React 19, Tailwind CSS v4) in `frontend/`. It has three audiences:

- **Owners**, who sign in and run campaigns.
- **Customers**, who scan a QR code or open a link from a post, with no login.
- **Counter staff**, who check and redeem coupon codes on their phone with a PIN.

The browser never talks to the Python backend directly. Every call goes to this Next.js server first, which adds the owner's login token and forwards it.

## Folder map

```
frontend/
  middleware.ts          sends owner pages without a session to /login
  app/
    layout.tsx           root layout: fonts, globals.css
    globals.css          design tokens and shared CSS classes
    (app)/               owner pages, wrapped in BusinessProvider
      page.tsx           Today
      campaigns/         list + [id] detail
      results/ customers/ photos/ brand/ channels/ counter/ agents/
    onboarding/          set up a new business
    login/ signup/       sign-in pages (both use AuthForm)
    r/[code]/            customer landing page for a post code
    c/[code]/            customer's personal coupon page
    k/[code]/ k/desk/[slug]/   staff counter pages
    api/[...path]/       proxy to the backend
    api/session/[action] sign in, sign up, sign out: sets cookies
  components/            UI pieces (see below)
  lib/                   data, session, theme and helper code
```

## Login and the proxy

1. `AuthForm` posts to `/api/session/login` (or `signup`). That route calls the backend, then stores the access token in an httpOnly cookie `cp_at` and the refresh token in `cp_rt`. Browser JavaScript can never read them.
2. `middleware.ts` checks for `cp_rt` on owner pages. No cookie means a redirect to `/login?next=...`. Customer pages (`/r`, `/c`), staff pages (`/k`) and `/api` are left open.
3. `app/api/[...path]/route.ts` forwards every `/api/...` request to `BACKEND_URL/api/...`. For owner routes it adds `Authorization: Bearer <cp_at>`. If the backend answers 401, it refreshes once with `cp_rt`, retries, and sets the new cookies. Public routes (`/api/public/...`) get no token, but WhatsApp's `x-hub-signature-256` header is passed through.

`lib/session.ts` holds the cookie names, `BACKEND` URL and `refreshSession`.

## Talking to the API (`lib/api.ts`)

- `api<T>(path, { json })`: a typed `fetch` wrapper. Throws `ApiError(status, detail)` with the backend's message.
- `useResource<T>(path)`: a hook that loads data and reloads it whenever a relevant ledger event arrives.
- `useLedgerEvents(fn)` and `setLiveBusiness(slug)`: one shared `EventSource` on `/businesses/{slug}/events`. When an agent does something, the backend writes a ledger event, the stream delivers it, and every page using `useResource` refreshes. That is why the UI updates live without polling.

All response shapes are typed in `lib/types.ts`.

## The selected business (`lib/business.tsx`)

`BusinessProvider` wraps every owner page (see `app/(app)/layout.tsx`):

- loads `/me` (the user, their businesses and enabled features),
- picks the business to show (remembered in localStorage),
- points the live feed at it (`setLiveBusiness`),
- applies the business's theme colour (`lib/theme.ts`) and watermark setting (`PostStyle`),
- sends people with no business to `/onboarding`.

Pages read it with `useWorkspace()` or `useBusiness()`.

## Owner pages (`app/(app)/`)

| Page | What it is for |
| --- | --- |
| `page.tsx` (Today) | what needs the owner now (inbox), the composer to start a campaign, and the campaign ledger |
| `campaigns/page.tsx` | table of all campaigns with live, opened, claimed, redeemed, conversion and filters |
| `campaigns/[id]/page.tsx` | one campaign: journey track, next step, performance, festival notes, offer, posts, share, A/B tests |
| `results/page.tsx` | results across campaigns |
| `customers/page.tsx` | reviews and Instagram comments, "Needs a reply", reply drafts, Google review link |
| `photos/page.tsx` | the business's photo library: upload, import from website or Google |
| `brand/page.tsx` | brand voice, palette, theme, watermark |
| `channels/page.tsx` | connect WhatsApp and Instagram |
| `counter/page.tsx` | owner's own redeem desk and staff PIN |
| `agents/page.tsx` | the AI team: who does what, recent work |

Every campaign follows five steps defined in `lib/journey.ts`: Brief, Offer, Posts, Share, Results. `stepOfSummary` and `stepOfDetail` work out which step a campaign is on, and `nextAction` gives the one-line "what to do next".

## Customer and staff pages

- `r/[code]`: the landing page a post's QR code opens. Records a visit, shows the offer, and has "Get my code".
- `c/[code]`: the customer's personal coupon. Polls its status (`lib/claim.ts`) and, once redeemed, shows `ReviewForm`.
- `k/[code]` and `k/desk/[slug]`: staff phone pages behind `StaffGate` (PIN), then `RedeemDesk` to check and redeem codes.

These pages always use the light style, since customers see them.

## Components (`components/`)

**Layout and basics**
- `shell.tsx`: app frame: left sidebar on large screens, top bar and bottom nav on phones, business switcher, work log drawer.
- `ui.tsx`: `Button`, `Card`, `Pill`, `StatusPill`, `Stamp`, `PageHeader`, `SectionHeading`, `Empty`, `Skeleton`, `Stat`, `timeAgo`.
- `motion.tsx`: `Reveal`, `CountUp`, `Spotlight`.
- `journey.tsx`: `JourneyTrack` (full stepper) and `JourneyMini` (small one for list rows).

**Campaign work**
- `composer.tsx`: write or speak a campaign brief (speech via Sarvam or the browser).
- `facts-card.tsx`: the offer facts, wording check and lock button. `receipt.tsx` draws the locked offer as a printed receipt.
- `asset-card.tsx`: one post with its guard results and approve/reject. `post-editor.tsx`: edit a post (opens in a portal).
- `previews.tsx`: what the post really looks like: `InstagramPost`, `Story`, `Poster`, `WhatsAppMessage`. PNG export happens in the browser with `html-to-image`.
- `photo-picker.tsx`, `instagram-picker.tsx`: choose a photo, or link an existing Instagram post.
- `share-panel.tsx`: per live post: link, WhatsApp message, caption, QR.
- `campaign-analytics.tsx`: funnel, charts, breakdowns and tips. `experiment-panel.tsx`: A/B test result.
- `festival-card.tsx`: festival notes. `agent-status.tsx`: is the agent working on this campaign.
- `inbox.tsx`: `InboxList` (approve or reject what the agent queued) and `FindingsList`.
- `campaign-card.tsx`: `CampaignRow` and `CampaignLedger` used on Today.

**Customers and counter**
- `review-desk.tsx` (summary, Google link, reply box), `review-import.tsx`, `review-form.tsx`.
- `redeem-desk.tsx`, `staff-gate.tsx`.
- `auth-form.tsx`: login and sign-up form.

## Styling

- Tailwind v4 with design tokens declared in `app/globals.css` under `@theme`: `paper`, `surface`, `sunken`, `ink`, `ink-2`, `muted`, `line`, `pen`, `marker`, `turmeric`, `kumkum`, `brand`. Each colour has one job: `ink` the owner's words and main actions, `pen` the agents' work and links, `marker` what needs the owner now, `kumkum` problems and the live dot.
- Shared classes in the same file: `.sign` (condensed numbers), `.stamp`, `.receipt-edge`, `.perforation`, `.hl` (highlighter), and short animations like `.rise-in` and `.skeleton`, all turned off under `prefers-reduced-motion`.
- Fonts: Anek (Latin, Kannada and Devanagari in one family) and Martian Mono for codes, money and the log.
- `lib/theme.ts` and `lib/colors.ts`: each business gets a theme from its brand palette, contrast-checked. It only sets `--color-brand`, which is used on posts.
- Icons: Phosphor (`@phosphor-icons/react`) only.

## Running it

```bash
cd frontend && npm run dev
```

```bash
cd frontend && npm run typecheck
```

```bash
cd frontend && npm run build
```

Set `BACKEND_URL` if the backend is not on `http://localhost:8000`.
