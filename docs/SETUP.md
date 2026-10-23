# Setup: database, accounts and API keys

**Never paste keys, tokens or passwords into a chat (Claude included).** Every secret below is saved with a script
that asks for it hidden, checks it against the service, and only then writes it to `backend/.env`.

All commands run from `backend/`:

```bash
cd backend
export PATH=~/.local/opt/node/bin:~/.local/bin:$PATH
```

## What you need

| Setting | Needed? | Where it comes from | How to save it |
|---|---|---|---|
| `DATABASE_URL` | **Required** | Supabase > Connect > Session pooler | `scripts.set_db_password` |
| `SUPABASE_URL` | **Required** | Supabase > Project Settings > Data API | edit `backend/.env` (not secret) |
| `SUPABASE_PUBLISHABLE_KEY` | **Required** | Supabase > Project Settings > API Keys | `scripts.set_secret` |
| `SUPABASE_SERVICE_ROLE_KEY` | **Required** | Supabase > Project Settings > API Keys > Secret keys | `scripts.set_secret` |
| `GEMINI_API_KEY` | **Required** (or Groq/Cerebras) | aistudio.google.com/apikey | `scripts.set_secret` |
| `AGNES_API_KEY` | Recommended | apihub.agnes-ai.com | `scripts.set_secret` |
| `DEMO_PASSWORD` | For "Try the demo" | you choose | `scripts.set_secret` |
| `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `GEMINI_API_KEY_2` | Optional backups | console.groq.com, cloud.cerebras.ai | `scripts.set_secret` |
| `SARVAM_API_KEY` | Optional (Kannada/Hindi) | dashboard.sarvam.ai | `scripts.set_secret` |
| `GOOGLE_MAPS_API_KEY` | Optional (Maps photos) | console.cloud.google.com | `scripts.set_secret` |
| `META_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | Optional (WhatsApp/Instagram) | developers.facebook.com | `scripts.set_secret`, then [CHANNELS.md](CHANNELS.md) |
| `OWNER_API_TOKEN` | Recommended when deployed | generated | `scripts.set_secret` |

## 0. Create the env files

```bash
cp .env.example .env
cp ../frontend/.env.example ../frontend/.env.local
uv sync
```

The frontend file needs no changes for local development (`BACKEND_URL=http://localhost:8000`).

---

## 1. Supabase project (database, accounts, storage)

1. Go to https://supabase.com/dashboard and sign in (GitHub sign-in is fine).
2. Click **New project**. Pick your organisation, give it a name, and pick the region closest to you (Mumbai: `ap-south-1`).
3. Next to **Database password**, click **Generate a password** and **Copy** it. Keep it somewhere safe (a password manager); you need it in step 2.
4. Click **Create new project** and wait about 2 minutes for it to finish.

### 1a. Project URL (not secret)

1. **Project Settings** (gear icon, bottom left) > **Data API**.
2. Copy **Project URL** (`https://<letters>.supabase.co`).
3. In `backend/.env`, set `SUPABASE_URL=https://<letters>.supabase.co`, with no slash at the end and no quotes.

### 1b. Publishable and secret keys

1. **Project Settings** > **API Keys**.
2. If you only see `anon` / `service_role` keys, click **Create new API keys** (or the "API Keys" tab, not "Legacy API Keys").
3. Run this and paste the **Publishable key** (`sb_publishable_...`):
   ```bash
   uv run python -m scripts.set_secret SUPABASE_PUBLISHABLE_KEY
   ```
4. Under **Secret keys**, click the eye icon, copy the key (`sb_secret_...`), and run:
   ```bash
   uv run python -m scripts.set_secret SUPABASE_SERVICE_ROLE_KEY
   ```
   (The legacy `service_role` JWT `eyJ...` also works.)

### 1c. Turn off email confirmation (local dev)

So owners can sign up and use the app straight away: **Authentication** > **Sign In / Providers** > **Email**, then turn off **Confirm email** and **Save**. (With the secret key set, the app already creates confirmed accounts. This switch is a backup.)

---

## 2. Database connection (`DATABASE_URL`)

1. In the Supabase project, click **Connect** (top bar).
2. Choose the **Session pooler** connection string (port **5432**, works over IPv4), **not** "Direct connection" (IPv6 only) and not the transaction pooler (6543).
   It looks like `postgresql://postgres.<project-ref>:[YOUR-PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres`.
3. Copy it as it is, `[YOUR-PASSWORD]` included, and run:
   ```bash
   uv run python -m scripts.set_db_password
   ```
4. Paste the connection string when asked, then paste the database password from step 1.3 (hidden).
5. You should see **Connected to Supabase. Saved to backend/.env.**

Forgot the password? **Project Settings** > **Database** > **Reset database password**, then run the script again. Special characters are fine because the script URL-encodes them.

Then create the tables and load the demo café:

```bash
uv run python -m scripts.migrate
uv run python -m scripts.seed
```

No internet or no Supabase? `uv run python -m scripts.dev_db` starts a local Postgres and prints a `DATABASE_URL` to put in `.env` (sign-in still needs Supabase).

---

## 3. Gemini (main text model, free)

1. Open https://aistudio.google.com/apikey and sign in with a Google account.
2. Click **Create API key**. Pick a project or let it create one, then copy the key (`AIza...`).
3. Save it:
   ```bash
   uv run python -m scripts.set_secret GEMINI_API_KEY
   ```

The free tier gives about 20 requests a day **per model**, and the app spreads work over several models. For a live demo, turn on billing for that project (it costs cents) or add the backups in step 5.

---

## 4. Agnes (pictures + last-resort text)

1. Open https://apihub.agnes-ai.com and sign in with the hackathon account.
2. Go to **API keys**, then **Create key**, and copy it.
3. Save it:
   ```bash
   uv run python -m scripts.set_secret AGNES_API_KEY
   ```

Without Agnes, posts still use the business's real photos. Only the AI-picture fallback is off.

---

## 5. Free backups (optional, no card)

Each is tried in order once Gemini runs out. The script also finds and saves the best model the key can use.

| Key | Steps |
|---|---|
| `GEMINI_API_KEY_2` | Same as step 3, but in a **different Google account/project** (quota is per project). |
| `GROQ_API_KEY` | https://console.groq.com > sign in > **API Keys** > **Create API Key** (`gsk_...`). |
| `CEREBRAS_API_KEY` | https://cloud.cerebras.ai > sign in > **API Keys** > copy (`csk-...`). |

```bash
uv run python -m scripts.set_secret GROQ_API_KEY
uv run python -m scripts.set_secret CEREBRAS_API_KEY
uv run python -m scripts.set_secret GEMINI_API_KEY_2
```

---

## 6. Demo password

"Try the demo" signs in as `demo@counterpart.app`. Choose any password (8+ characters, no spaces). The account is created the first time someone clicks the button.

```bash
uv run python -m scripts.set_secret DEMO_PASSWORD
```

---

## 7. Optional features

### Sarvam AI (Kannada/Hindi voice briefs and an independent translation check)
1. https://dashboard.sarvam.ai > sign in > **API Keys** > copy the subscription key.
2. `uv run python -m scripts.set_secret SARVAM_API_KEY`

### Google Maps photos and "sign up from a Maps link"
1. https://console.cloud.google.com > create or pick a project.
2. **Billing**: link a billing account (Places needs one; the monthly free credit covers a demo).
3. **APIs & Services** > **Library** > search **Places API (New)** > **Enable**. The old "Places API" is not enough.
4. **APIs & Services** > **Credentials** > **Create credentials** > **API key**. Optional: **Restrict key** > API restrictions > Places API (New).
5. `uv run python -m scripts.set_secret GOOGLE_MAPS_API_KEY` (if it says "not used/disabled", wait a minute after enabling and retry).

### WhatsApp and Instagram
1. https://developers.facebook.com > **My Apps** > your app > **App settings** > **Basic** > **App secret** > **Show**.
2. `uv run python -m scripts.set_secret META_APP_SECRET`
3. `uv run python -m scripts.set_secret WHATSAPP_VERIFY_TOKEN` (any phrase you make up, 8+ characters).
4. Then follow [CHANNELS.md](CHANNELS.md) (`scripts.go_live` connects the number and account).

### Owner API token (lock the API to your frontend)
```bash
uv run python -m scripts.set_secret OWNER_API_TOKEN
```
Press Enter to generate one. It is written to both `backend/.env` and `frontend/.env.local`.

---

## 8. Run it

```bash
uv run uvicorn app.main:app --reload --port 8000
```
In a second terminal:
```bash
cd frontend && npm install && npm run dev
```
Open http://localhost:3000. Restart the backend after any change to `backend/.env`.

## Troubleshooting

| You see | Fix |
|---|---|
| `database_url Field required` | Step 2 not done (`DATABASE_URL` empty). |
| `wrong password` from `set_db_password` | Reset the password (step 2), wait 30 seconds, run again. |
| Connection timeout on port 5432 | You used "Direct connection"; use the **Session pooler** string. |
| Sign-in/sign-up fails with 401/404 | `SUPABASE_URL` or `SUPABASE_PUBLISHABLE_KEY` wrong; rerun step 1a/1b. |
| "The demo is not set up on this server" | Step 6. |
| "set SUPABASE_URL in backend/.env first" | Do step 1a before 1b. |
| Every model fails / 429 | Free Gemini quota used up: add step 5 backups or enable billing. |
| Frontend 401 on every page with `OWNER_API_TOKEN` set | `frontend/.env.local` must hold the same value; restart `npm run dev`. |

Deploying (Render + Vercel): [DEPLOY.md](DEPLOY.md). Copy the same values into the hosts' env settings.
