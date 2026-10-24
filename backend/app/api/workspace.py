"""Accounts and workspace: sign-up and sign-in, the demo, onboarding a new business, its photo library,
and the read-outs that show the owner what the agents are doing and how campaigns convert."""

import base64
import binascii
import re
import secrets
from datetime import date
from typing import Any, Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from pydantic import BaseModel, Field

from app import auth, autofill, ledger, photos, reviews, sarvam, services, usage
from app import moments as moments_mod
from app import results as results_mod
from app.api.deps import get_router, require_owner
from app.auth import CurrentUser, business_for, require_member
from app.config import get_settings
from app.db import connection, fetch_all, fetch_one, jsonb
from app.domain import analytics, economics, effort
from app.domain.facts import AI_CLICHES, machine_voice
from app.storage import get_storage

accounts = APIRouter(prefix="/api", dependencies=[Depends(require_owner)])


# ------------------------------------------------------------------ sign-in


class Credentials(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    password: str = Field(min_length=8, max_length=128)


class RefreshBody(BaseModel):
    refresh_token: str


@accounts.post("/auth/signup")
async def signup(body: Credentials) -> dict[str, Any]:
    return await auth.sign_up(body.email, body.password)


@accounts.post("/auth/login")
async def login(body: Credentials) -> dict[str, Any]:
    return await auth.sign_in(body.email, body.password)


@accounts.post("/auth/refresh")
async def refresh(body: RefreshBody) -> dict[str, Any]:
    return await auth.refresh(body.refresh_token)


@accounts.post("/auth/logout")
async def logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    if authorization and authorization.lower().startswith("bearer "):
        await auth.sign_out(authorization[7:].strip())
    return {"ok": True}


@accounts.post("/auth/demo")
async def demo() -> dict[str, Any]:
    """'Try the demo': a shared account that can open the demo business only."""
    s = get_settings()
    if s.demo_password is None:
        raise services.Conflict("The demo is not set up on this server (DEMO_PASSWORD).")
    session = await auth.sign_in_or_create(s.demo_email, s.demo_password.get_secret_value())
    async with connection() as conn:
        await conn.execute(
            """insert into memberships (user_id, business_id, role)
               select %s, id, 'owner' from businesses where is_demo on conflict do nothing""",
            (session["user"]["id"],))
    return session


@accounts.get("/me")
async def me(user: CurrentUser) -> dict[str, Any]:
    async with connection() as conn:
        rows = await fetch_all(
            conn, """select b.id, b.slug, b.name, b.locality, b.city, b.languages, b.is_demo,
                            b.profile->>'kind' as kind, b.profile->'owner'->>'name' as owner_name, m.role,
                            d.dna->>'theme' as theme, coalesce(d.dna->'palette', '[]') as palette,
                            coalesce(d.dna->'palette_hex', '{}') as palette_hex,
                            coalesce(d.dna->'voice', '[]') as voice,
                            coalesce((d.dna->>'watermark')::boolean, true) as watermark
                     from memberships m join businesses b on b.id = m.business_id
                     left join brand_dna d on d.business_id = b.id and d.status = 'active'
                     where m.user_id = %s order by b.is_demo, b.created_at""", (user.id,))
    s = get_settings()
    return {"user": user.model_dump(), "businesses": rows,
            "features": {"google_photos": s.google_maps_api_key is not None, "sarvam": s.sarvam_api_key is not None,
                         # customer links and QR codes are built from this address on every request
                         "public_links": s.public_base_url.startswith("https://")}}


# ------------------------------------------------------------------ onboarding


class Offering(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price: float = Field(gt=0, le=1_000_000)
    unit_cost: float | None = Field(None, ge=0, description="What one costs the business; enables the margin check.")


class NewBusiness(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: str = Field(min_length=2, max_length=60, description="e.g. café, salon, bakery, clothing store")
    city: str = Field(min_length=2, max_length=60)
    locality: str = Field(min_length=2, max_length=80)
    languages: list[Literal["en", "kn", "hi"]] = Field(min_length=1)
    owner_name: str | None = Field(None, max_length=60)
    description: str | None = Field(None, max_length=800, description="What customers love, in the owner's words.")
    website: str | None = Field(None, max_length=300)
    find_on_google: bool = True
    offerings: list[Offering] = Field(min_length=1, max_length=60)
    whatsapp: str | None = Field(None, max_length=20, description="Number customers message to claim an offer.")


class Phrase(BaseModel):
    lang: Literal["en", "kn", "hi"]
    phrase: str


class BrandDraft(BaseModel):
    voice: list[str] = Field(description="3 to 5 plain adjectives for how the owner talks to regulars "
                                         "(e.g. 'chatty', 'no-nonsense'), never marketing words like 'vibrant'.")
    do: list[str] = Field(description="2 to 4 short, concrete writing rules, e.g. 'name the product or service, not the "
                                      "experience'.")
    avoid: list[str] = Field(description="2 to 4 things never to do.")
    signature_phrases: list[Phrase] = Field(description="One short sign-off line per language, natively written.")
    imagery: str = Field(description="One or two sentences describing what photos of this business should show.")
    palette: list[str] = Field(description="3 or 4 colours, as words.")
    banned_words: list[str] = Field(description="Hype words this business would never use.")
    emoji_policy: str


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "business"
    return f"{base}-{secrets.token_hex(2)}"


def _default_brand(b: NewBusiness) -> dict[str, Any]:
    return {"voice": ["warm", "friendly", "local", "straightforward"],
            "do": ["Talk like a regular customer would, not like an advertisement", "Mention what people actually love here"],
            "avoid": ["hype words such as amazing, epic, mind-blowing", "ALL CAPS"],
            "signature_phrases": {}, "imagery": f"Real, natural-light photos of {b.name}'s own products and space.",
            "palette": [], "banned_words": ["amazing", "epic", "mind-blowing", "ultimate"],
            "emoji_policy": "At most two", "languages_priority": b.languages, "examples": []}


async def _draft_brand(request: Request, b: NewBusiness) -> tuple[dict[str, Any], str]:
    router = get_router(request)
    items = ", ".join(o.name for o in b.offerings[:20])
    prompt = (f"A new {b.kind} called {b.name} in {b.locality}, {b.city} is setting up its marketing. "
              f"They sell: {items}. In the owner's words: {b.description or '(nothing more given)'}. "
              f"Languages: {', '.join(b.languages)} (en English, kn Kannada script, hi Hindi Devanagari). "
              "Draft a starting brand voice the owner can edit. Do not invent facts about the business. "
              "It must sound like the owner chatting with a regular at the counter, not like an ad agency or an AI: "
              "plain everyday words, short sentences, local flavour. Signature lines are things the owner would "
              "actually say out loud. Never use words such as: " + ", ".join(AI_CLICHES[:30]) + ".")
    try:
        draft, _ = await router.chat_json("reasoning", [{"role": "user", "content": prompt}], BrandDraft)
    except Exception:
        return _default_brand(b), "Starting voice (the model was unavailable; edit it any time)"
    dna = draft.model_dump()
    dna["signature_phrases"] = {}
    for p in draft.signature_phrases:
        if p.lang in b.languages:
            dna["signature_phrases"].setdefault(p.lang, []).append(p.phrase)
    dna["banned_words"] = sorted({w.strip().lower() for w in dna["banned_words"] if w.strip()})
    if robotic := machine_voice(" ".join([*dna["voice"], *dna["do"], dna["imagery"]])):
        dna["voice_note"] = f"Reworded automatically to avoid: {', '.join(robotic)}"
        dna["voice"] = [v for v in dna["voice"] if not machine_voice(v)] or _default_brand(b)["voice"]
        dna["do"] = [d for d in dna["do"] if not machine_voice(d)] or _default_brand(b)["do"]
    dna |= {"languages_priority": b.languages, "examples": []}
    return dna, "Drafted by Counterpart from onboarding; the owner can edit it"


class LinkBody(BaseModel):
    link: str = Field(min_length=4, max_length=500)


@accounts.post("/onboarding/read-link")
async def read_link(user: CurrentUser, body: LinkBody, request: Request) -> dict[str, Any]:
    """Pre-fill sign-up from the owner's website or Google Maps link. Nothing is saved until they confirm."""
    try:
        return await autofill.read_link(get_router(request), body.link)
    except photos.UnsafeURL as e:
        raise services.Conflict(str(e)) from e


@accounts.post("/businesses")
async def create_business(user: CurrentUser, body: NewBusiness, request: Request, bg: BackgroundTasks) -> dict[str, Any]:
    dna, rationale = await _draft_brand(request, body)  # model call before opening a transaction
    profile = {
        "kind": body.kind, "owner": {"name": body.owner_name} if body.owner_name else {},
        "description": body.description, "website": body.website,
        "menu": [o.model_dump() for o in body.offerings], "allowed_phrases": [],
        "whatsapp": services.whatsapp_number(body.whatsapp),
        "baseline_covers_per_window": 30,
        "channels": ["instagram_post", "instagram_story", "whatsapp", "poster"],
    }
    async with connection() as conn:
        b = await fetch_one(
            conn, """insert into businesses (slug, name, locality, city, languages, profile)
                     values (%s, %s, %s, %s, %s, %s) returning *""",
            (_slug(body.name), body.name.strip(), body.locality.strip(), body.city.strip(), body.languages,
             jsonb(profile)))
        assert b is not None
        await conn.execute("insert into memberships (user_id, business_id, role) values (%s, %s, 'owner')",
                           (user.id, b["id"]))
        await conn.execute(
            """insert into brand_dna (business_id, version, status, dna, rationale, created_by)
               values (%s, 1, 'active', %s, %s, 'agent')""", (b["id"], jsonb(dna), rationale))
        await ledger.record(conn, b["id"], "business.created", f"{b['name']} joined Counterpart", actor="owner")
    if body.website or body.find_on_google:
        bg.add_task(photos.import_all, get_router(request), b, website=body.website,
                    google=body.find_on_google and get_settings().google_maps_api_key is not None)
    return b


class BrandUpdate(BaseModel):
    dna: dict[str, Any]


@accounts.put("/businesses/{slug}/brand")
async def update_brand(user: CurrentUser, slug: str, body: BrandUpdate) -> dict[str, Any]:
    """The owner edits the voice: a new active version, the old one superseded."""
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        cur = await services.active_brand(conn, b["id"])
        version = (cur["version"] if cur else 0) + 1
        await conn.execute("update brand_dna set status = 'superseded' where business_id = %s and status = 'active'",
                           (b["id"],))
        row = await fetch_one(conn, """insert into brand_dna (business_id, version, status, dna, rationale, created_by)
                                       values (%s, %s, 'active', %s, 'Edited by the owner', 'owner') returning *""",
                              (b["id"], version, jsonb(body.dna)))
        await ledger.record(conn, b["id"], "brand.updated", f"Brand voice updated to version {version}", actor="owner")
    return row  # type: ignore[return-value]


# ------------------------------------------------------------------ photos


def _photo_out(p: dict[str, Any]) -> dict[str, Any]:
    return {**p, "url": get_storage().url(p["image_key"])}


@accounts.get("/businesses/{slug}/photos")
async def list_photos(user: CurrentUser, slug: str) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        rows = await fetch_all(conn, "select * from business_photos where business_id = %s order by status, created_at desc",
                               (b["id"],))
    s = get_settings()
    return {"photos": [_photo_out(p) for p in rows], "website": b["profile"].get("website"),
            "google_available": s.google_maps_api_key is not None}


class ImportBody(BaseModel):
    website: str | None = Field(None, max_length=300)
    google: bool = False


@accounts.post("/businesses/{slug}/photos/import")
async def import_photos(user: CurrentUser, slug: str, body: ImportBody, request: Request,
                        bg: BackgroundTasks) -> dict[str, str]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        if body.website and body.website != b["profile"].get("website"):
            await conn.execute("""update businesses set profile = jsonb_set(profile, '{website}', to_jsonb(%s::text))
                                  where id = %s""", (body.website, b["id"]))
    bg.add_task(photos.import_all, get_router(request), b, website=body.website,
                google=body.google and get_settings().google_maps_api_key is not None)
    return {"status": "accepted"}


class Upload(BaseModel):
    data_url: str = Field(max_length=12_000_000, description="data:image/...;base64,...")


@accounts.post("/businesses/{slug}/photos")
async def upload_photo(user: CurrentUser, slug: str, body: Upload, request: Request, bg: BackgroundTasks) -> dict[str, Any]:
    m = re.match(r"^data:image/[\w.+-]+;base64,(.+)$", body.data_url, re.S)
    if not m:
        raise services.Conflict("Upload a JPG, PNG or WebP photo.")
    try:
        data = base64.b64decode(m.group(1), validate=True)
    except (binascii.Error, ValueError) as e:
        raise services.Conflict("That file could not be read.") from e
    if len(data) > photos.MAX_BYTES:
        raise services.Conflict("That photo is larger than 8 MB.")
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        row = await photos.save_photo(conn, b, data, source="upload", attribution="Uploaded by the owner")
        if not row:
            raise services.Conflict("That photo is too small or not an image (at least 300 px on each side).")
        await ledger.record(conn, b["id"], "photos.uploaded", "You added a photo", actor="owner")
    bg.add_task(photos.describe_new, get_router(request), b)
    return _photo_out(row)


class Speech(BaseModel):
    data_url: str = Field(max_length=5_000_000, description="data:audio/...;base64,...")
    language: Literal["en", "kn", "hi"] | None = None


@accounts.post("/businesses/{slug}/speech")
async def speech(user: CurrentUser, slug: str, body: Speech) -> dict[str, Any]:
    """The owner's spoken brief, transcribed by Sarvam (Kannada, Hindi or English)."""
    async with connection() as conn:
        await business_for(conn, user, slug)
    if not sarvam.available():
        raise services.Conflict("Voice through Sarvam is not set up.")
    m = re.match(r"^data:(audio/[\w.+-]+)(?:;[^,]*)?;base64,(.+)$", body.data_url, re.S)
    if not m:
        raise services.Conflict("That recording could not be read.")
    try:
        audio = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as e:
        raise services.Conflict("That recording could not be read.") from e
    try:
        return await sarvam.transcribe(audio, m.group(1), body.language)
    except sarvam.SarvamError as e:
        raise services.Conflict(str(e)) from e


class SpokenMenu(BaseModel):
    data_url: str | None = Field(None, max_length=5_000_000, description="data:audio/...;base64,... (Sarvam)")
    text: str | None = Field(None, max_length=4000, description="Already transcribed by the browser")
    language: Literal["en", "kn", "hi"] | None = None


@accounts.post("/onboarding/menu-speech")
async def menu_speech(user: CurrentUser, body: SpokenMenu, request: Request) -> dict[str, Any]:
    """The owner says their menu and prices (Kannada, Hindi or English); the items fill the sign-up form. Nothing
    is saved until they confirm, and prices that were not clearly heard are marked for checking."""
    language = body.language
    if body.data_url:
        if not sarvam.available():
            raise services.Conflict("Voice through Sarvam is not set up; type the menu instead.")
        m = re.match(r"^data:(audio/[\w.+-]+)(?:;[^,]*)?;base64,(.+)$", body.data_url, re.S)
        try:
            audio = base64.b64decode(m.group(2), validate=True) if m else b""
        except (binascii.Error, ValueError):
            audio = b""
        if not m or not audio:
            raise services.Conflict("That recording could not be read.")
        try:
            heard = await sarvam.transcribe(audio, m.group(1), language)
        except sarvam.SarvamError as e:
            raise services.Conflict(str(e)) from e
        said, language = heard["transcript"], heard["language"] or language
    else:
        said = (body.text or "").strip()
    if not said:
        raise services.Conflict("Nothing was heard. Try again a little closer to the phone.")
    english = await sarvam.to_english(said, language or "") if language in ("kn", "hi") else said
    from app.providers.base import ProviderError

    try:
        items = await autofill.menu_from_speech(get_router(request), said, language or "en", english)
    except ProviderError as e:
        raise services.Conflict(f"Could not read the menu right now ({str(e)[:120]}). Try again soon.") from e
    return {"said": said, "language": language, "english": english, "items": items}


class MenuPhoto(BaseModel):
    data_url: str = Field(max_length=8_000_000, description="A photo of the printed menu, as an image data URL.")


@accounts.post("/onboarding/menu-photo")
async def menu_photo(user: CurrentUser, body: MenuPhoto, request: Request) -> dict[str, Any]:
    """Items and prices read from a photo of the menu. Nothing is saved; the owner checks every price."""
    if not re.match(r"^data:image/(jpeg|png|webp);base64,", body.data_url):
        raise services.Conflict("Send a JPEG, PNG or WebP photo of the menu.")
    router = get_router(request)
    if not router.available("vision"):
        raise services.Conflict("No AI model that reads pictures is set up on this server; type the items instead.")
    from app.providers.base import ProviderError

    try:
        items = await autofill.menu_from_photo(router, body.data_url)
    except ProviderError as e:
        raise services.Conflict(f"Could not read the photo right now ({str(e)[:120]}). Try again soon.") from e
    return {"items": items}


# ------------------------------------------------------------------ customer reviews


class ReviewImport(BaseModel):
    website: str | None = Field(None, max_length=300)
    text: str | None = Field(None, max_length=20_000, description="Reviews pasted by the owner, one per paragraph")


@accounts.post("/businesses/{slug}/reviews/import")
async def import_reviews(user: CurrentUser, slug: str, body: ReviewImport, request: Request) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
    website = body.website or (None if body.text else b["profile"].get("website"))
    if not website and not (body.text or "").strip():
        raise services.Conflict("Add your website address, or paste some reviews.")
    try:
        out = await reviews.import_reviews(get_router(request), b, website=website, pasted=body.text)
    except photos.UnsafeURL as e:
        raise services.Conflict(str(e)) from e
    return out


class PhotoUpdate(BaseModel):
    status: Literal["active", "hidden"]


@accounts.patch("/photos/{photo_id}")
async def update_photo(user: CurrentUser, photo_id: str, body: PhotoUpdate) -> dict[str, Any]:
    async with connection() as conn:
        p = await fetch_one(conn, "select * from business_photos where id = %s", (photo_id,))
        if not p:
            raise services.NotFound("photo not found")
        await require_member(conn, user, p["business_id"])
        row = await fetch_one(conn, "update business_photos set status = %s where id = %s returning *",
                              (body.status, photo_id))
    return _photo_out(row)  # type: ignore[arg-type]


class PhotoChoice(BaseModel):
    photo_id: str


@accounts.post("/assets/{asset_id}/photo")
async def set_asset_photo(user: CurrentUser, asset_id: str, body: PhotoChoice) -> dict[str, Any]:
    """The owner swaps a post's picture for another photo from the library."""
    async with connection() as conn:
        asset = await services.get_asset(conn, asset_id)
        c = await services.get_campaign(conn, asset["campaign_id"])
        await require_member(conn, user, c["business_id"])
        p = await fetch_one(conn, "select * from business_photos where id = %s and business_id = %s",
                            (body.photo_id, c["business_id"]))
        if not p:
            raise services.NotFound("photo not found")
        await conn.execute("update asset_revisions set image_key = %s where asset_id = %s and n = %s",
                           (p["image_key"], asset_id, asset["current_revision"]))
        await ledger.record(conn, c["business_id"], "asset.visual",
                            f"You changed the picture of the {services.asset_label(asset)}", actor="owner",
                            campaign_id=c["id"], payload={"asset_id": asset_id, "photo_id": body.photo_id})
    return {"ok": True, "image_url": get_storage().url(p["image_key"])}


# ------------------------------------------------------------------ photo reels


@accounts.post("/assets/{asset_id}/reel")
async def reel(user: CurrentUser, asset_id: str) -> dict[str, Any]:
    """A short vertical video for a post: the business's own photos with a voice-over (Sarvam) that reads only the
    post's checked words and the locked offer. The browser turns it into a video; no AI pictures are used."""
    async with connection() as conn:
        asset = await services.get_asset(conn, asset_id)
        c = await services.get_campaign(conn, asset["campaign_id"])
        await require_member(conn, user, c["business_id"])
        rev = (await services.current_revision(conn, asset_id)) or {}
        r = rev.get("rendered") or {}
        tp = await fetch_one(conn, "select code from touchpoints where asset_id = %s", (asset_id,))
        lib = await fetch_all(conn, """select * from business_photos where business_id = %s and status = 'active'
                                       and coalesce(kind, 'other') <> all(%s)""", (c["business_id"], ["menu_or_text", "logo"]))
    concept = " ".join([r.get("headline", ""), r.get("body", ""), *(r.get("offer") or [])])
    own = [p for p in lib if p["image_key"] == rev.get("image_key")]
    rest = sorted((p for p in lib if p not in own), key=lambda p: -photos.score(p, concept, 0))
    shots = (own + rest)[:5]
    if not shots:
        raise services.Conflict("Add a few photos of your business first (Photos page). Reels use only your own photos.")
    lines = [x for x in [r.get("headline"), r.get("body"), *(r.get("offer") or []), r.get("cta")] if x]
    script = " ".join(x.strip() + ("" if x.strip()[-1:] in ".!?।" else ".") for x in lines)
    voice, why = None, None
    if sarvam.available():
        try:
            voice = get_storage().url(await sarvam.speak(script, asset["language"]))
        except (sarvam.SarvamError, httpx.HTTPError) as e:
            why = f"No voice-over this time: {e}"
    else:
        why = "No voice-over: Sarvam is not set up, so the reel has captions only."
    storage = get_storage()
    return {"language": asset["language"], "script": script, "voice_url": voice, "voice_note": why,
            "voice": get_settings().sarvam_tts_model if voice else None,
            "headline": r.get("headline"), "offer": r.get("offer") or [], "cta": r.get("cta"),
            "code": tp and tp["code"],
            "photos": [{"url": storage.url(p["image_key"]), "caption": p.get("caption"),
                        "attribution": p.get("attribution"), "source": p.get("source")} for p in shots]}


# ------------------------------------------------------------------ what the agents are doing


AGENTS = [
    {"role": "reasoning", "agent": "orchestrator", "name": "Orchestrator", "job": "Reads the situation and runs the "
     "team: hands the offer to the Offer agent, plans audiences and channels, hands writing to the Writer and "
     "checking to the Checker, and asks you for approvals."},
    {"role": "reasoning", "agent": "brief", "name": "Brief agent", "job": "Before anything is written, settles who "
     "the campaign is for, what it should achieve (a number), and which channels and languages to use, from what "
     "worked before and what you have connected. Asks you only when it cannot tell."},
    {"role": "reasoning", "agent": "offer", "name": "Offer agent", "job": "Turns your idea into exact offer details "
     "from your real menu, checks the margin, and asks you short questions about anything a customer would have to "
     "guess. Never locks the offer; you do."},
    {"role": "reasoning", "agent": "change", "name": "Change agent", "job": "When you change a running offer, shows "
     "which posts must be rewritten and which only get the new offer box, then drafts the new version for you to "
     "lock. Posts the change does not touch stay as they are."},
    {"role": "generation", "agent": "language", "name": "Language agent", "job": "Writes every offer detail in "
     "Kannada and Hindi with Sarvam, an Indian-language model, and replaces any wording that names a different day "
     "or number from the English. Each one is read back into English by another model."},
    {"role": "generation", "agent": "writer", "name": "Writer", "job": "Takes writing work from the Orchestrator and writes each post's "
     "headline and message in its language, in your brand voice. Never types offer details; the system adds those "
     "from the locked offer."},
    {"role": "verification", "name": "Checker", "job": "A different model from the Writer. Reads every post and "
     "translation back into English and blocks anything that does not match the locked offer. Never edits."},
    {"role": "verification", "agent": "analyst", "name": "Analyst", "job": "Once posts are live, reads who opened, "
     "claimed and came to the counter, and the A/B tests, then suggests the next move for you to say yes or no to. "
     "Every number it quotes is checked against the real results."},
    {"role": "reasoning", "agent": "listener", "name": "Customer listener", "job": "Reads reviews, comments and "
     "visit ratings, tells you about problems several customers raise (in their own words), drafts replies for "
     "you to send, and suggests a follow-up campaign when one fits."},
    {"role": "reasoning", "agent": "scout", "name": "Scout", "job": "Watches what is happening around you (rain "
     "this evening, the weekend, salary week, a match or fest you add) and suggests campaigns that fit it, using only "
     "your real menu. You pick one to start."},
    {"role": "vision", "name": "Photo reader", "job": "Looks at the photos of your business once, describes them, "
     "and sets aside blurry shots, logos and menus so each post gets a fitting real photo."},
    {"role": "image", "name": "Picture maker", "job": "Only when you have no photos yet: makes an AI picture, "
     "labelled as such."},
]


# ------------------------------------------------------------------ what is happening around the business


@accounts.get("/businesses/{slug}/moments")
async def list_moments(user: CurrentUser, slug: str) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        rows = await moments_mod.event_rows(conn, b["id"])
    weather = await moments_mod.forecast(b["city"])  # network call outside the transaction
    return {"moments": moments_mod.combine(rows, weather, date.today())}


class MomentIn(BaseModel):
    name: str = Field(min_length=3, max_length=80, description="e.g. 'IPL: RCB vs CSK' or 'College fest at BMS'")
    starts_on: date
    ends_on: date | None = None
    note: str | None = Field(None, max_length=120, description="e.g. '7:30 pm, on the big screens nearby'")


@accounts.post("/businesses/{slug}/moments")
async def add_moment(user: CurrentUser, slug: str, body: MomentIn) -> dict[str, Any]:
    """Something the owner knows is happening nearby. Stored as one of the business's events."""
    if body.ends_on and body.ends_on < body.starts_on:
        raise services.Conflict("It ends before it starts.")
    key = "own-" + re.sub(r"[^a-z0-9]+", "-", body.name.casefold()).strip("-")[:40]
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        await conn.execute(
            """insert into customer_insights (business_id, kind, key, period_start, period_end, data)
               values (%s, 'event', %s, %s, %s, %s)
               on conflict (business_id, kind, key, period_start) do update set period_end = excluded.period_end,
                   data = excluded.data""",
            (b["id"], key, body.starts_on, body.ends_on or body.starts_on,
             jsonb({"name": body.name, "note": body.note, "added_by": "owner"})))
        await ledger.record(conn, b["id"], "moment.added", f"Added: {body.name} ({body.starts_on:%-d %b})", actor="owner")
    return {"key": f"event-{key}"}


@accounts.delete("/businesses/{slug}/moments/{key}")
async def remove_moment(user: CurrentUser, slug: str, key: str) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        cur = await conn.execute(
            """delete from customer_insights where business_id = %s and kind = 'event' and key = %s
               and data->>'added_by' = 'owner'""", (b["id"], key.removeprefix("event-")))
    if not cur.rowcount:
        raise services.NotFound("moment not found")
    return {"ok": True}


@accounts.post("/businesses/{slug}/opportunities")
async def opportunities(user: CurrentUser, slug: str, request: Request) -> dict[str, Any]:
    """The Scout agent's campaign ideas for what is happening now."""
    from app.agent import situation
    from app.providers.base import ProviderError

    async with connection() as conn:
        b = await business_for(conn, user, slug)
        rows = await moments_mod.event_rows(conn, b["id"])
        themes = await situation.theme_trends(conn, b["id"])
    found = moments_mod.combine(rows, await moments_mod.forecast(b["city"]), date.today())
    if not found:
        return {"ideas": [], "moments": []}
    try:
        ideas = await moments_mod.scout(get_router(request), b, found, themes)
    except ProviderError as e:  # includes no model available
        raise services.Conflict(f"The Scout could not reach a model right now ({str(e)[:120]}). Try again soon.") from e
    async with connection() as conn:
        await ledger.record(conn, b["id"], "scout.ideas",
                            f"Scout: {len(ideas)} idea(s) for what is happening: "
                            + "; ".join(f"{i['title']} ({i['moment']['title']})" for i in ideas),
                            actor="agent", payload={"agent": "scout", "ideas": ideas})
    return {"ideas": ideas, "moments": found}


@accounts.get("/businesses/{slug}/checker-test")
async def checker_test(user: CurrentUser, slug: str) -> dict[str, Any]:
    """How the checks did on 50 known-bad drafts and 10 good ones: the last saved run (scripts.checker_eval), or a
    rules-only run now if none was saved."""
    from app import checker_eval

    async with connection() as conn:
        await business_for(conn, user, slug)
    return checker_eval.saved() or await checker_eval.run(None)


@accounts.get("/businesses/{slug}/agents")
async def agents(user: CurrentUser, slug: str, request: Request) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        recent = await fetch_all(
            conn, """select id, type, summary, actor, campaign_id, created_at from ledger_events
                     where business_id = %s and actor in ('agent', 'system') order by id desc limit 30""", (b["id"],))
    router = get_router(request)
    status = router.status()
    calls = router.calls_for(str(b["id"]))
    out = []
    tagged = {(a["role"], a["agent"]) for a in AGENTS if "agent" in a}
    for a in AGENTS:
        # Agents sharing a model role (Orchestrator, Offer agent) are told apart by the agent tag on each call; an
        # entry without a tag (Checker, Photo reader) gets the rest of its role's calls.
        mine = [c for c in calls if c["role"] == a["role"] and (
            c.get("agent") == a["agent"] if "agent" in a else (a["role"], c.get("agent")) not in tagged)]
        out.append({**a, "models": status["roles"].get(a["role"], []), "calls": len(mine),
                    "last": mine[-1] if mine else None})
    return {"agents": out, "calls": calls[::-1][:40], "activity": recent}


# ------------------------------------------------------------------ results


@accounts.get("/businesses/{slug}/results")
async def results(user: CurrentUser, slug: str) -> dict[str, Any]:
    """Per tracked post: scans (opened the link), claims (tapped 'get my code'), redeemed at the counter."""
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        rows = await fetch_all(
            conn, """select c.id as campaign_id, c.name as campaign, a.id as asset_id, a.channel, a.language,
                            a.segment, a.variant, t.code,
                            coalesce(sum(o.qty) filter (where o.type = 'scan'), 0)::int as scans,
                            coalesce(sum(o.qty) filter (where o.type = 'click'), 0)::int as claims,
                            coalesce(sum(o.qty) filter (where o.type = 'redeem'
                                     and not coalesce((o.meta->>'return')::boolean, false)), 0)::int as redeemed,
                            coalesce(sum(o.qty) filter (where o.type = 'redeem'
                                     and coalesce((o.meta->>'return')::boolean, false)), 0)::int as came_back,
                            coalesce(sum(o.qty) filter (where o.type = 'redeem' and not coalesce((o.meta->>'return')::boolean, false)
                                     and (coalesce((o.meta->>'from_link')::boolean, false) or exists (
                              select 1 from claims cl where cl.code = o.meta->>'claim' and cl.via = 'web'))), 0)::int as from_link,
                            coalesce(sum(o.qty) filter (where o.type = 'redeem' and not coalesce((o.meta->>'return')::boolean, false)
                                     and not (o.meta ? 'claim') and not coalesce((o.meta->>'from_link')::boolean, false)), 0)::int
                              as post_code,
                            coalesce(sum((o.meta->>'bill_amount')::numeric) filter (where o.type = 'redeem'), 0)::float
                              as sales,
                            coalesce(sum(o.qty) filter (where o.source = 'simulated'), 0)::int as simulated
                     from touchpoints t join assets a on a.id = t.asset_id join campaigns c on c.id = t.campaign_id
                     left join outcome_events o on o.touchpoint_code = t.code
                     where c.business_id = %s and not c.is_historical
                     group by c.id, c.name, a.id, t.code order by c.created_at desc, redeemed desc""", (b["id"],))
    base = get_settings().public_base_url.rstrip("/")
    for r in rows:
        r["link"] = f"{base}/r/{r['code']}"
        # Conversion = of the people who opened the link, how many came in with the code they got there. A post's code
        # typed at the counter (from a caption or poster) counts as redeemed, never as a link conversion.
        r["conversion"] = analytics.rate(r["from_link"], r["scans"])
    totals = {k: sum(r[k] for r in rows) for k in ("scans", "claims", "redeemed", "came_back", "from_link", "post_code",
                                                    "sales", "simulated")}
    totals["conversion"] = analytics.rate(totals["from_link"], totals["scans"])
    async with connection() as conn:
        spent = await usage.spent(conn, business_id=b["id"])
        live = {r["campaign_id"] for r in rows}
        efforts = [await results_mod.effort_for(conn, cid) for cid in live]
        hours = await results_mod.business_hours(conn, b["id"])
    return {"posts": rows, "totals": totals, "hours": hours,
            "ai": {**spent, **economics.return_on_ai(spent["rupees"], totals["sales"], totals["redeemed"])},
            "effort": effort.typical([e for e in efforts if e])}
