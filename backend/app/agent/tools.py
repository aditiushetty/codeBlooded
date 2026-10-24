"""Agent tool catalog.

Each tool declares an effect class. The policy layer (runtime.execute) uses it:
  read / internal     -> runs immediately
  customer_facing     -> queued as an owner approval unless already approved
  fact                -> queued as an owner approval unless already approved
Preconditions run before anything else and explain themselves to the agent.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, model_validator

from app import ledger, services
from app.agent import situation
from app.agent.prompts import GENERATION_SYSTEM
from app.config import Settings
from app.db import connection, fetch_all, fetch_one, jsonb
from app.domain import analyst as analyst_rules
from app.domain import brief as brief_rules
from app.domain import culture
from app.domain import offer as offer_rules
from app.domain.audit import intent_for_copy
from app.domain.economics import offer_economics
from app.domain.facts import AI_CLICHES, CHANNEL_LIMITS, AssetContent
from app.providers.base import ProviderError
from app.providers.router import ModelRouter, call_scope

Effect = Literal["read", "internal", "customer_facing", "fact"]
Channel = Literal["instagram_post", "instagram_story", "whatsapp", "poster"]
Language = Literal["en", "kn", "hi"]


@dataclass
class ToolContext:
    business: dict[str, Any]
    campaign_id: str | None
    router: ModelRouter
    settings: Settings
    actor: ledger.Actor = "agent"
    approved: bool = False  # set when the owner approved this exact call
    agent: str | None = None  # the team member whose loop made the call


Precondition = Callable[[ToolContext, Any], Awaitable[str | None]]


@dataclass
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    effect: Effect
    handler: Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]
    preconditions: list[Precondition] = field(default_factory=list)

    def schema(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.args.model_json_schema()}}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, args: type[BaseModel], effect: Effect,
         preconditions: list[Precondition] | None = None):
    def wrap(fn: Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]):
        REGISTRY[name] = Tool(name, description, args, effect, fn, preconditions or [])
        return fn
    return wrap


def schemas() -> list[dict[str, Any]]:
    return [t.schema() for t in REGISTRY.values()]


# ------------------------------------------------------------------ preconditions


async def needs_campaign(ctx: ToolContext, _: Any) -> str | None:
    return None if ctx.campaign_id else "No campaign is selected."


async def needs_locked_facts(ctx: ToolContext, _: Any) -> str | None:
    if not ctx.campaign_id:
        return "No campaign is selected."
    async with connection() as conn:
        sheet = await services.locked_sheet(conn, ctx.campaign_id)
    return None if sheet else "Offer facts are not locked yet. Draft them and call lock_facts."


async def needs_draft_facts(ctx: ToolContext, _: Any) -> str | None:
    async with connection() as conn:
        draft = await services.facts_row(conn, ctx.campaign_id, "draft") if ctx.campaign_id else None
    if not draft:
        return "There is no facts draft to lock. Call draft_offer_facts or revise_offer_facts first."
    if (draft.get("wording_check") or {}).get("status") == "failed":
        return ("The translated wording does not match the English; ask the Language agent (ask_language) to "
                "correct it: " + services.wording_issue_text(draft["wording_check"]["issues"]))
    async with connection() as conn:
        campaign = await services.get_campaign(conn, ctx.campaign_id)  # type: ignore[arg-type]
    if blocks := offer_rules.blocking(offer_gaps(ctx, campaign, draft["facts"])):
        return ("The offer still leaves customers guessing; ask the Offer agent to settle it with the owner: "
                + offer_rules.summary(blocks))
    if missing := missing_wording(ctx, draft["facts"]):
        return ("Some offer wording is missing; ask the Language agent (ask_language) to write it: "
                + ", ".join(missing))
    return None


def offer_gaps(ctx: ToolContext, campaign: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return offer_rules.gaps(facts, ctx.business["profile"].get("menu", []), today=date.today(),
                            starts_on=campaign.get("starts_on"), ends_on=campaign.get("ends_on"))


def offer_margin(ctx: ToolContext, facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The margin check of a drafted discount on its menu items, so nobody has to remember to run it."""
    menu = {m["name"].casefold(): m for m in ctx.business["profile"].get("menu", [])}
    items = [menu[n.casefold()] for f in facts if f.get("type") == "item"
             for n in offer_rules._names(f.get("value")) if n.casefold() in menu]
    pct = next((f["value"] for f in facts if f.get("type") == "percent" and isinstance(f.get("value"), int | float)), 0)
    price = next((f["value"] for f in facts if f.get("type") == "price" and isinstance(f.get("value"), int | float)), None)
    if not items or not (pct or price):
        return None
    flat = max(sum(float(i["price"]) for i in items) - float(price), 0.0) if price else 0.0
    return offer_economics(items, discount_pct=float(pct), flat_off=flat,
                           baseline_covers=int(ctx.business["profile"].get("baseline_covers_per_window", 40)))


class NoArgs(BaseModel):
    pass


# ------------------------------------------------------------------ read tools


@tool("get_situation", "Current campaign state, pending owner items and prioritised findings.", NoArgs, "read")
async def get_situation(ctx: ToolContext, _: NoArgs) -> dict[str, Any]:
    async with connection() as conn:
        return await situation.snapshot(conn, ctx.business, ctx.campaign_id)


class ThemesArgs(BaseModel):
    days: int = Field(14, ge=7, le=90, description="Window size; compared with the window before it.")


@tool("get_customer_themes", "What customers talk about: theme counts now vs before, sentiment, quotes with ids.",
      ThemesArgs, "read")
async def get_customer_themes(ctx: ToolContext, a: ThemesArgs) -> dict[str, Any]:
    async with connection() as conn:
        themes = await situation.theme_trends(conn, ctx.business["id"], days=a.days)
        segments = await fetch_all(
            conn, "select key, data from customer_insights where business_id = %s and kind in ('segment', 'event')",
            (ctx.business["id"],))
    return {"themes": themes[:12], "segments_and_events": segments}


@tool("get_brand_and_learnings", "Active brand voice and the learnings from past campaigns.", NoArgs, "read")
async def get_brand_and_learnings(ctx: ToolContext, _: NoArgs) -> dict[str, Any]:
    async with connection() as conn:
        brand = await services.active_brand(conn, ctx.business["id"])
        learnings = await fetch_all(
            conn,
            """select id, content, scope, confidence from memories
               where business_id = %s and kind in ('learning', 'brand_rule') and status = 'active'
               order by created_at desc limit 20""",
            (ctx.business["id"],))
    return {"brand": brand and {"version": brand["version"], "dna": brand["dna"]}, "learnings": learnings}


class OfferArgs(BaseModel):
    item_names: list[str] = Field(min_length=1, description="Menu items in one redemption, e.g. a combo.")
    discount_pct: float = Field(0, ge=0, le=100)
    flat_off: float = Field(0, ge=0)


@tool("evaluate_offer", "Margin and break-even check of a discount using the real menu costs.", OfferArgs, "read")
async def evaluate_offer(ctx: ToolContext, a: OfferArgs) -> dict[str, Any]:
    menu = {m["name"].lower(): m for m in ctx.business["profile"].get("menu", [])}
    missing = [n for n in a.item_names if n.lower() not in menu]
    if missing:
        return {"error": f"Not on the menu: {', '.join(missing)}", "menu": sorted(m["name"] for m in menu.values())}
    return offer_economics([menu[n.lower()] for n in a.item_names], discount_pct=a.discount_pct,
                           flat_off=a.flat_off,
                           baseline_covers=int(ctx.business["profile"].get("baseline_covers_per_window", 40)))


@tool("get_menu", "The business's items with prices (and costs when known). Offers can only use these items.",
      NoArgs, "read")
async def get_menu(ctx: ToolContext, _: NoArgs) -> dict[str, Any]:
    p = ctx.business["profile"]
    return {"menu": [{"name": m["name"], "price": m.get("price"), "cost_known": m.get("unit_cost") is not None}
                     for m in p.get("menu", [])],
            "languages": ctx.business["languages"]}


class ExperimentRef(BaseModel):
    experiment_id: str


@tool("experiment_status", "Posterior results of an experiment and whether it can be decided.", ExperimentRef, "read")
async def get_experiment_status(ctx: ToolContext, a: ExperimentRef) -> dict[str, Any]:
    async with connection() as conn:
        return await services.experiment_status(conn, a.experiment_id)


# ------------------------------------------------------------------ facts


class FactIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    label: str
    type: Literal["percent", "price", "date_range", "time_range", "item", "condition", "text"]
    value: Any
    display: dict[str, str] = Field(description=(
        "Exact customer-facing wording per language code (en, kn, hi). It is inserted mid-sentence, so write a "
        "short phrase, not a sentence or label: lowercase start (except names), no full stop, no 'Label:' prefix. "
        "Good: '15% off', 'haircut + beard trim', '4 to 7 pm', 'Monday to Friday', 'with a valid college ID'."))
    required: bool = True


class DraftFactsArgs(BaseModel):
    facts: list[FactIn] = Field(min_length=1)
    forbidden_claims: dict[str, list[str]] = Field(
        default_factory=dict, description="Phrases that must never appear, per language (e.g. 'free', 'all day').")
    reason: str | None = None


async def _wording(ctx: ToolContext) -> dict[str, Any] | None:
    check = await services.check_fact_wording(ctx.router, connection, ctx.campaign_id)  # type: ignore[arg-type]
    return check and {"status": check["status"], "issues": check["issues"]}


@tool("draft_offer_facts", "Write the offer down as structured facts with per-language wording. "
      "The owner reviews and locks them.", DraftFactsArgs, "internal", [needs_campaign])
async def draft_offer_facts(ctx: ToolContext, a: DraftFactsArgs) -> dict[str, Any]:
    async with connection() as conn:
        campaign = await services.get_campaign(conn, ctx.campaign_id)  # type: ignore[arg-type]
        row = await services.save_draft_facts(conn, campaign, facts=[f.model_dump() for f in a.facts],
                                              forbidden_claims=a.forbidden_claims, reason=a.reason, actor=ctx.actor)
    return {"draft_version": row["version"], **_review(ctx, campaign, row["facts"]), "wording_check": await _wording(ctx)}


def _review(ctx: ToolContext, campaign: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    found = offer_gaps(ctx, campaign, facts)
    return {"gaps": found, "can_ask_to_lock": not offer_rules.blocking(found), "margin": offer_margin(ctx, facts)}


class FactPatch(BaseModel):
    key: str
    label: str | None = Field(None, description="Only to add a new fact, with type, value and display.")
    type: Literal["percent", "price", "date_range", "time_range", "item", "condition", "text"] | None = None
    value: Any | None = None
    display: dict[str, str] | None = None
    required: bool | None = None
    remove: bool = False


class ReviseFactsArgs(BaseModel):
    changes: list[FactPatch] = Field(min_length=1)
    reason: str


def apply_patches(current: list[dict[str, Any]], changes: list[FactPatch]) -> list[dict[str, Any]] | str:
    """The facts after the changes, or why they cannot apply. Display wording is merged per language; when the
    English changes without new translations, the old ones are dropped so the Language agent writes them again."""
    facts = {f["key"]: {**f, "display": dict(f.get("display") or {})} for f in current}
    for p in changes:
        if p.remove:
            facts.pop(p.key, None)
            continue
        if p.key not in facts:
            if not (p.label and p.type and p.value is not None and p.display):
                return f"Unknown fact '{p.key}'. To add it, give its label, type, value and display."
            facts[p.key] = {"key": p.key, "label": p.label, "type": p.type, "value": p.value,
                            "display": dict(p.display), "required": True if p.required is None else p.required}
            continue
        f = facts[p.key]
        if p.value is not None:
            f["value"] = p.value
        if p.required is not None:
            f["required"] = p.required
        if p.display:
            if "en" in p.display and p.display["en"] != f["display"].get("en"):
                f["display"] = {"en": p.display["en"]}
            f["display"].update(p.display)
    return list(facts.values())


async def needs_any_facts(ctx: ToolContext, _: Any) -> str | None:
    if not ctx.campaign_id:
        return "No campaign is selected."
    async with connection() as conn:
        draft = await services.facts_row(conn, ctx.campaign_id, "draft")
        sheet = draft or await services.locked_sheet(conn, ctx.campaign_id)
    return None if sheet else "There are no offer facts yet. Use draft_offer_facts."


async def _current_facts(conn: Any, campaign_id: Any) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict]:
    """(draft row or None, the facts being worked on: the draft's or else the locked ones, forbidden claims)."""
    draft = await services.facts_row(conn, campaign_id, "draft")
    if draft:
        return draft, draft["facts"], draft["forbidden_claims"]
    locked = await services.locked_sheet(conn, campaign_id)
    assert locked
    return None, [f.model_dump() for f in locked.facts], locked.forbidden_claims


@tool("revise_offer_facts", "Change only some facts of the current offer (the unlocked draft, or else a new draft "
      "from the locked version), e.g. the owner gave the end date or moved the days. Then the owner locks it.",
      ReviseFactsArgs, "internal", [needs_any_facts])
async def revise_offer_facts(ctx: ToolContext, a: ReviseFactsArgs) -> dict[str, Any]:
    async with connection() as conn:
        campaign = await services.get_campaign(conn, ctx.campaign_id)  # type: ignore[arg-type]
        _draft, current, claims = await _current_facts(conn, campaign["id"])
        facts = apply_patches(current, a.changes)
        if isinstance(facts, str):
            return {"error": facts}
        row = await services.save_draft_facts(conn, campaign, facts=facts,
                                              forbidden_claims=claims, reason=a.reason, actor=ctx.actor)
    return {"draft_version": row["version"], "changed": [p.key for p in a.changes], **_review(ctx, campaign, row["facts"]),
            "missing_languages": missing_wording(ctx, row["facts"]), "wording_check": await _wording(ctx)}


def missing_wording(ctx: ToolContext, facts: list[dict[str, Any]]) -> list[str]:
    """'Discount (kn)' for each required fact without wording in one of the business's languages."""
    langs = [lang for lang in ctx.business["languages"] if lang != "en"]
    return [f"{f.get('label', f['key'])} ({lang})" for f in facts if f.get("required", True)
            for lang in langs if not (f.get("display") or {}).get(lang)]


# ------------------------------------------------------------------ languages (Language agent)


class TranslateArgs(BaseModel):
    wording: dict[str, dict[str, str]] = Field(default_factory=dict, description=(
        "Your own wording for details the machine translation got wrong: {fact_key: {language: short phrase}}. "
        "Leave empty on the first call."))
    redo: bool = Field(False, description="Translate again even where wording already exists.")


async def needs_draft(ctx: ToolContext, _: Any) -> str | None:
    async with connection() as conn:
        draft = await services.facts_row(conn, ctx.campaign_id, "draft") if ctx.campaign_id else None
    return None if draft else "There is no offer draft to translate. The Offer or Change agent drafts it first."


def _clean(phrase: str) -> str:
    return phrase.strip().rstrip("।.").strip()


@tool("translate_offer", "Write the offer wording in every language of the business. Sarvam (an Indian-language "
      "translation model) translates the English; your own wording replaces any it got wrong. Every wording is then "
      "checked: same numbers and days as the English, and read back into English by a different model.",
      TranslateArgs, "internal", [needs_campaign, needs_draft])
async def translate_offer(ctx: ToolContext, a: TranslateArgs) -> dict[str, Any]:
    from app import sarvam

    langs = [lang for lang in ctx.business["languages"] if lang != "en"]
    async with connection() as conn:
        campaign = await services.get_campaign(conn, ctx.campaign_id)  # type: ignore[arg-type]
        draft = await services.facts_row(conn, campaign["id"], "draft")
    assert draft
    facts = [{**f, "display": dict(f["display"])} for f in draft["facts"]]
    source: dict[tuple[str, str], str] = {}
    jobs: list[tuple[dict[str, Any], str, str]] = []
    for f in facts:
        en = f["display"].get("en")
        for lang in langs:
            if given := (a.wording.get(f["key"]) or {}).get(lang):
                f["display"][lang], source[f["key"], lang] = _clean(given), "agent"
            elif f["display"].get(lang) and not a.redo:
                source[f["key"], lang] = "kept"
            elif en and sarvam.available():
                jobs.append((f, lang, en))

    async def one(text: str, lang: str) -> str | None:
        try:
            return await sarvam.translate(text, "en", lang)
        except (sarvam.SarvamError, httpx.HTTPError):
            return None

    for (f, lang, _en), out in zip(jobs, await asyncio.gather(*(one(en, lang) for _f, lang, en in jobs)), strict=True):
        if out:
            f["display"][lang], source[f["key"], lang] = _clean(out), "sarvam"
    if facts != draft["facts"]:
        async with connection() as conn:
            await services.save_draft_facts(conn, campaign, facts=facts, forbidden_claims=draft["forbidden_claims"],
                                            reason="Wrote the offer in every language", actor=ctx.actor)
    check = await _wording(ctx)
    issues = {(i["key"], i["lang"]): i["issue"] for i in (check or {}).get("issues", [])}
    rows = [{"key": f["key"], "language": lang, "wording": f["display"].get(lang),
             "from": source.get((f["key"], lang), "missing"), "issue": issues.get((f["key"], lang))}
            for f in facts for lang in langs]
    missing = missing_wording(ctx, facts)
    ready = not missing and (check or {}).get("status") != "failed"
    out = {"wording": rows, "missing": missing, "wording_check": check and check["status"], "ready": ready,
           "sarvam": sarvam.available()}
    if not ready:
        out["next_step"] = (f"Not ready: {sum(bool(r['issue']) for r in rows)} wording(s) have an issue. Write your own "
                            "phrase for each and call translate_offer again with them in `wording`. Do not report "
                            "ready until this tool says ready: true.")
    return out


# ------------------------------------------------------------------ offer changes (Change agent)


class PreviewArgs(BaseModel):
    changes: list[FactPatch] = Field(min_length=1)


@tool("preview_change", "What a change to the locked offer would do, before making it: which details change, "
      "which posts the Writer must rewrite (their own text uses a changed detail), which only get their offer box "
      "refilled by the system, which stay as they are, and whether the new offer still has gaps.",
      PreviewArgs, "read", [needs_locked_facts])
async def preview_change(ctx: ToolContext, a: PreviewArgs) -> dict[str, Any]:
    from app.domain import impact
    from app.domain.facts import FactSheet

    async with connection() as conn:
        campaign = await services.get_campaign(conn, ctx.campaign_id)  # type: ignore[arg-type]
        locked = await services.locked_sheet(conn, campaign["id"])
        revisions = await services.revisions_for_change(conn, campaign["id"])
    assert locked
    facts = apply_patches([f.model_dump() for f in locked.facts], a.changes)
    if isinstance(facts, str):
        return {"error": facts}
    new = FactSheet(version=locked.version + 1, facts=facts, forbidden_claims=locked.forbidden_claims)
    changed = impact.changed_fact_keys(locked, new)
    plan = impact.change_plan(revisions, changed)
    label = {r["asset_id"]: {"label": services.asset_label(r), "status": r["status"]} for r in revisions}
    return {"changed": sorted(changed),
            "posts": {k: [{"asset_id": i, **label[i]} for i in ids] for k, ids in plan.items()},
            "live_posts_affected": sum(label[i]["status"] == "live" for i in plan["rewrite"] + plan["refill"]),
            "gaps": offer_gaps(ctx, campaign, facts), "margin": offer_margin(ctx, facts)}


class LockArgs(BaseModel):
    summary: str = Field(description="One line for the owner: what the offer is and anything they should check.")


@tool("lock_facts", "Lock the drafted offer facts so all copy uses them. Needs the owner.", LockArgs, "fact",
      [needs_draft_facts])
async def lock_facts(ctx: ToolContext, a: LockArgs) -> dict[str, Any]:
    await services.check_fact_wording(ctx.router, connection, ctx.campaign_id)  # type: ignore[arg-type]
    async with connection() as conn:
        campaign = await services.get_campaign(conn, ctx.campaign_id)  # type: ignore[arg-type]
        res = await services.lock_facts(conn, campaign, actor=ctx.actor,
                                        verifier_available=ctx.router.available("verification"))
    return {"locked_version": res["facts"]["version"], "changed": res["changed"], "stale_assets": res["stale_assets"],
            "refilled": res["refilled"]}


class QuestionArgs(BaseModel):
    question: str = Field(min_length=5, max_length=200, description="One short question in plain words, e.g. "
                          "'Is the 15% on the whole bill or only on filter coffee?'")
    options: list[str] = Field(default_factory=list, max_length=4, description="Up to 4 likely answers the owner "
                               "can tap, e.g. ['Whole bill', 'Only filter coffee']. They can always type their own.")
    why: str = Field(max_length=200, description="What a customer or the counter would otherwise have to guess.")


MAX_OPEN_QUESTIONS = 3


@tool("ask_owner", "Ask the owner one short question when something the campaign needs (who it is for, what it should "
      "achieve, or a detail a customer would have to guess) is missing or unclear. Do not ask about things the "
      "menu, the brief or the results already say.", QuestionArgs, "internal",
      [needs_campaign])
async def ask_owner(ctx: ToolContext, a: QuestionArgs) -> dict[str, Any]:
    async with connection() as conn:
        open_ = await fetch_all(conn, """select id, title from inbox_items
                                         where campaign_id = %s and kind = 'question' and status = 'pending'""",
                                (ctx.campaign_id,))
        if same := next((q for q in open_ if q["title"].casefold() == a.question.casefold()), None):
            return {"question_id": str(same["id"]), "already_asked": True}
        if len(open_) >= MAX_OPEN_QUESTIONS:
            return {"error": f"{len(open_)} questions are already waiting for the owner. Stop and wait for answers."}
        row = await fetch_one(
            conn, """insert into inbox_items (business_id, campaign_id, kind, title, body, payload, priority)
                     values (%s, %s, 'question', %s, %s, %s, 1) returning id""",
            (ctx.business["id"], ctx.campaign_id, a.question, a.why,
             jsonb({"options": a.options, "asked_by": ctx.agent or "offer"})))
        await ledger.record(conn, ctx.business["id"], "question.asked", a.question, actor=ctx.actor,
                            campaign_id=ctx.campaign_id, payload={"inbox_item_id": str(row["id"])})  # type: ignore[index]
    return {"question_id": str(row["id"]), "message": "The owner has been asked. Stop; you will be woken with the answer."}  # type: ignore[index]


# ------------------------------------------------------------------ plan


class PlanArgs(BaseModel):
    name: str = Field(description="Short campaign name for the owner, 2-5 words, e.g. 'Midterm study break'.")
    goal: dict[str, Any] = Field(description="{statement, kpi: {metric, target, window_days}}")
    plan: dict[str, Any] = Field(description="{cells: [{segment, channel, language, rationale}], hypotheses: [...]}")
    intent: dict[str, Any] = Field(description="{core_message, must_say, must_not_say, tone}. No call to action: "
                                   "the system always adds 'Show this at the counter'.")


@tool("set_campaign_plan", "Save the goal, the audience × channel × language plan and the intent contract.",
      PlanArgs, "internal", [needs_campaign])
async def set_campaign_plan(ctx: ToolContext, a: PlanArgs) -> dict[str, Any]:
    async with connection() as conn:
        connected = frozenset(r["channel"] for r in await fetch_all(
            conn, "select channel from channel_accounts where business_id = %s", (ctx.business["id"],)))
    if problems := brief_rules.problems(a.goal, a.plan, ctx.business["languages"], connected):
        return {"error": "The plan cannot be carried out: " + " ".join(problems)}
    async with connection() as conn:
        c = await services.update_campaign_plan(conn, ctx.campaign_id,  # type: ignore[arg-type]
                                                goal=a.goal, plan=a.plan, intent=intent_for_copy(a.intent), name=a.name)
        await ledger.record(conn, ctx.business["id"], "campaign.planned",
                            f"Plan saved: {len(a.plan.get('cells', []))} audience/channel/language cells",
                            actor=ctx.actor, campaign_id=c["id"], payload={"plan": a.plan})
    return {"status": c["status"]}


# ------------------------------------------------------------------ generation


class Cell(BaseModel):
    segment: str | None = None
    channel: Channel | None = None
    language: Language | None = None
    variant: str | None = Field(None, description="'A'/'B' when this cell is an experiment arm.")
    angle: str = Field(description="The idea or hook this piece leads with.")
    asset_id: str | None = Field(None, description="Set to rewrite an existing (stale/invalid) asset; segment, "
                                                   "channel and language then come from it.")

    @model_validator(mode="after")
    def _new_cells_are_complete(self) -> "Cell":
        if not self.asset_id and not (self.segment and self.channel and self.language):
            raise ValueError("a new cell needs segment, channel and language (or asset_id to rewrite one)")
        return self


class GenerateArgs(BaseModel):
    cells: list[Cell] = Field(min_length=1, max_length=12)


class CopyFeatures(BaseModel):
    hook: Literal["nostalgia", "urgency", "value", "community", "novelty", "quality", "convenience", "other"]
    cta_strength: int = Field(ge=1, le=3)
    tone: str


class Generated(BaseModel):
    cell: int
    content: AssetContent
    features: CopyFeatures


class GenerationOut(BaseModel):
    assets: list[Generated]


@tool("generate_copy", "Write copy for several cells in one batch. Offer details go in as fact slots; "
      "every piece is checked by the fact guard.", GenerateArgs, "internal", [needs_locked_facts])
async def generate_copy(ctx: ToolContext, a: GenerateArgs) -> dict[str, Any]:
    # 1. read context (short transaction)
    async with connection() as conn:
        campaign = await services.get_campaign(conn, ctx.campaign_id)  # type: ignore[arg-type]
        sheet = await services.locked_sheet(conn, campaign["id"])
        brand = await services.active_brand(conn, ctx.business["id"])
        themes = await situation.theme_trends(conn, ctx.business["id"], days=30)
        learnings = await fetch_all(
            conn, """select id, content from memories where business_id = %s and kind = 'learning'
                     and status = 'active' order by created_at desc limit 10""", (ctx.business["id"],))
        existing = {}
        for c in a.cells:
            if c.asset_id:
                existing[c.asset_id] = await services.get_asset(conn, c.asset_id)
    assert sheet
    langs = sorted({c.language for c in a.cells if c.language} | {e["language"] for e in existing.values()})
    facts_text = "\n".join(
        f"- {{{{{f.key}}}}} ({f.label}{', required' if f.required else ''}) is replaced by exactly: "
        + " | ".join(f"{lang}: “{f.display[lang]}”" for lang in langs if lang in f.display)
        for f in sheet.facts)
    festivals = culture.relevant(
        " ".join(str(x or "") for x in (campaign.get("name"), campaign.get("brief"), json.dumps(campaign.get("intent") or {}))),
        campaign.get("starts_on"), campaign.get("ends_on")) if ctx.settings.festivals else []
    system = GENERATION_SYSTEM.format(
        culture=json.dumps([{**culture.card(f, langs), "cite_as": f"culture:{f.key}"} for f in festivals],
                           ensure_ascii=False) if festivals else "(none)",
        cliches=", ".join(f'"{c}"' for c in AI_CLICHES),
        business_name=ctx.business["name"], locality=ctx.business["locality"], city=ctx.business["city"],
        brand=json.dumps(brand["dna"] if brand else {}, ensure_ascii=False),
        facts=facts_text, intent=json.dumps(intent_for_copy(campaign.get("intent")), ensure_ascii=False),
        insights=json.dumps([{"id": f"insight:theme:{t['theme']}", "theme": t["theme"], "mentions": t["recent"] + t["previous"],
                              "sentiment": t["sentiment"], "quotes": t["quotes"]} for t in themes[:8]],
                            ensure_ascii=False, default=str),
        learnings=json.dumps([{"id": f"learning:{r['id']}", "text": r["content"]} for r in learnings],
                             ensure_ascii=False, default=str),
    )
    cells = []
    for i, c in enumerate(a.cells):
        src = existing.get(c.asset_id) if c.asset_id else None
        channel = src["channel"] if src else c.channel
        cells.append({"cell": i, "segment": src["segment"] if src else c.segment, "channel": channel,
                      "language": src["language"] if src else c.language, "variant": c.variant, "angle": c.angle,
                      "max_chars": CHANNEL_LIMITS.get(channel, {})})  # type: ignore[arg-type]

    async def ask(payload: dict[str, Any]) -> tuple[GenerationOut, Any]:  # no transaction held
        return await ctx.router.chat_json(
            "generation",
            [{"role": "system", "content": system},
             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            GenerationOut, temperature=0.7)

    assets_by_cell: dict[int, dict[str, Any]] = {}
    written: dict[int, Generated] = {}

    async def store(generated: list[Generated], reason: str) -> dict[int, dict[str, Any]]:
        stored = {}
        async with connection() as conn:
            for g in generated:
                if g.cell >= len(cells):
                    continue
                spec = cells[g.cell]
                asset = assets_by_cell.get(g.cell) or existing.get(a.cells[g.cell].asset_id or "") or \
                    await services.create_asset(conn, campaign["id"], segment=spec["segment"],
                                                channel=spec["channel"], language=spec["language"],
                                                variant=spec["variant"])
                assets_by_cell[g.cell], written[g.cell] = asset, g
                rev = await services.add_revision(
                    conn, asset, g.content, created_by="agent", reason=f"{reason}: {spec['angle']}",
                    verifier_available=ctx.router.available("verification"),
                    features=g.features.model_dump() | {"angle": spec["angle"]})
                stored[g.cell] = {"asset_id": str(asset["id"]), "channel": spec["channel"],
                                  "language": spec["language"], "status": rev["asset_status"],
                                  "blocked_by": [c["detail"] for c in rev["validation"]["checks"]
                                                 if not c["passed"] and c["severity"] == "block"],
                                  "reads_now": rev.get("rendered")}
        return stored

    async def repair(problems: dict[int, list[str]], reason: str) -> None:
        """One rewrite of the given pieces, showing the model its text as customers would read it."""
        fix = [cells[i] | {"your_previous_version": written[i].content.model_dump(),
                           "how_it_reads_after_slots_are_filled": results[i].get("reads_now"), "problems": why}
               for i, why in problems.items()]
        try:
            fixed, _ = await ask({"fix_these": fix, "how": REPAIR_HINT})
        except (ProviderError, ValueError):
            return  # the drafts stay as they are, marked invalid
        for i, r in (await store([g for g in fixed.assets if g.cell in problems], reason)).items():
            results[i] = r | {"first_draft_blocked_by": problems[i]}

    async def meaning_check(cell_ids: list[int]) -> None:
        ids = {results[i]["asset_id"]: i for i in cell_ids if results[i]["status"] == "valid"}
        if not ids:
            return
        with call_scope(agent="checker"):  # the Checker's model, never the Writer's, reads them back
            audited = (await services.audit_assets(ctx.router, connection, list(ids))).get("results", {})
        async with connection() as conn:
            for asset_id, i in ids.items():
                if asset_id in audited:
                    results[i]["meaning_check"] = audited[asset_id].get("l3")
                    rev = await services.current_revision(conn, asset_id)
                    results[i]["status"] = "valid" if audited[asset_id]["passed"] else "invalid"
                    results[i]["blocked_by"] = [c["detail"] for c in (rev or {}).get("validation", {}).get("checks", [])
                                                if not c["passed"] and c["severity"] == "block"]

    # 2. write, store and guard
    out, res = await ask({"write_these": cells})
    results = await store(out.assets, "angle")
    # 3. rules first: the guard's exact reasons go back once
    if blocked := {i: r["blocked_by"] for i, r in results.items() if r["blocked_by"]}:
        await repair(blocked, "fixed")
    # 4. the meaning check always runs, by the verification model (not the writer); failures get one more rewrite
    await meaning_check(list(results))
    if failed := {i: r["blocked_by"] for i, r in results.items() if r.get("meaning_check") == "failed"}:
        await repair(failed, "reworded")
        await meaning_check(list(failed))
    # 5. every passing picture-led piece gets its picture now, in parallel (the system writes the offer onto it)
    items = " and ".join(f.display.get("en", "") for f in sheet.facts if f.type == "item") or "what the business sells"
    todo = [(i, r) for i, r in results.items() if r["status"] == "valid" and r["channel"] in VISUAL_CHANNELS
            and not (existing.get(a.cells[i].asset_id or "") or {}).get("image_key")]
    pictures = await asyncio.gather(*(make_visual(ctx, r["asset_id"], f"{items}, for {cells[i]['segment']}: "
                                                  f"{cells[i]['angle']}") for i, r in todo), return_exceptions=True)
    for (_, r), pic in zip(todo, pictures, strict=True):
        r["picture"] = (pic.get("source", "made") if isinstance(pic, dict) and "error" not in pic
                        else f"failed: {str(pic.get('error') if isinstance(pic, dict) else pic)[:120]}")
    for r in results.values():
        r.pop("reads_now", None)
    out = {"assets": [results[i] for i in sorted(results)], "model": res.model, "saved_output": res.replayed}
    if live := await _autopublish(ctx):
        out["went_live"] = {"assets": live, "why": "The owner approved in advance every post that passes all checks."}
    return out


VISUAL_CHANNELS = {"instagram_post", "instagram_story", "poster"}


REPAIR_HINT = ("Each piece failed a check for the listed problems. Rewrite it so it passes, keeping the same cell "
               "number, angle and language. how_it_reads_after_slots_are_filled shows what customers would see "
               "(the offer box and call to action are added by the system). Make your headline and body read "
               "naturally; state no offer details yourself (no numbers, days, times, prices or conditions); avoid "
               "forbidden words; stay well under max_chars.")


class AssetIds(BaseModel):
    asset_ids: list[str] = Field(min_length=1)


@tool("validate_assets", "Re-run the meaning check (back-translation + every customer promise vs the facts) "
      "on assets that passed the deterministic guard. generate_copy already runs it once.", AssetIds, "internal", [needs_locked_facts])
async def validate_assets(ctx: ToolContext, a: AssetIds) -> dict[str, Any]:
    out = await services.audit_assets(ctx.router, connection, a.asset_ids)
    # A piece that passes on a later check still needs its picture (generate_copy only adds pictures to
    # pieces that pass first time).
    async with connection() as conn:
        missing = await fetch_all(
            conn, """select a.id, a.segment from assets a join asset_revisions r
                     on r.asset_id = a.id and r.n = a.current_revision
                     where a.id = any(%s::uuid[]) and a.status = 'valid' and a.channel = any(%s)
                     and r.image_key is null""", (a.asset_ids, list(VISUAL_CHANNELS)))
        facts = await services.facts_row(conn, ctx.campaign_id, "locked") if missing else None  # type: ignore[arg-type]
    if missing:
        items = " and ".join(f.get("display", {}).get("en", "") for f in (facts or {}).get("facts", [])
                             if f.get("type") == "item") or "what the business sells"
        pics = await asyncio.gather(*(make_visual(ctx, str(m["id"]), f"{items}, for {m['segment']}") for m in missing),
                                    return_exceptions=True)
        out = {**out, "pictures_added": sum(isinstance(p, dict) and "error" not in p for p in pics)}
    if live := await _autopublish(ctx):
        out = {**out, "went_live": live}
    return out


RATIOS = {"poster": "3:4", "instagram_post": "1:1", "instagram_story": "9:16", "whatsapp": "1:1"}


class VisualArgs(BaseModel):
    asset_id: str
    concept: str = Field(description="What the picture shows. No text, letters or numbers will be drawn.")
    replace: bool = Field(False, description="Make a new picture even if the piece already has one.")


@tool("generate_visual", "Create the background picture for an asset. Offer text is overlaid exactly by the "
      "system, never drawn by the image model.", VisualArgs, "internal", [needs_locked_facts])
async def generate_visual(ctx: ToolContext, a: VisualArgs) -> dict[str, Any]:
    if not a.replace:
        async with connection() as conn:
            rev = await services.current_revision(conn, a.asset_id)
        if rev and rev.get("image_key"):  # generate_copy already made one
            return {"image_key": rev["image_key"], "note": "This piece already has a picture; pass replace=true for a new one."}
    return await make_visual(ctx, a.asset_id, a.concept)


_photo_locks: dict[str, asyncio.Lock] = {}


async def make_visual(ctx: ToolContext, asset_id: str, concept: str) -> dict[str, Any]:
    """A real photo of the business when the library has a fitting one; otherwise an AI picture (labelled)."""
    from app import photos
    from app.storage import get_storage

    async with _photo_locks.setdefault(str(ctx.campaign_id), asyncio.Lock()), connection() as conn:
        # one at a time per campaign, so parallel posts see each other's picks and spread over the library
        asset = await services.get_asset(conn, asset_id)
        photo = await photos.choose(conn, ctx.business["id"], asset["campaign_id"], concept)
        if photo:
            await conn.execute("update asset_revisions set image_key = %s where asset_id = %s and n = %s",
                               (photo["image_key"], asset_id, asset["current_revision"]))
            await ledger.record(conn, ctx.business["id"], "asset.visual",
                                f"Picked a photo for the {services.asset_label(asset)}: {photo.get('caption') or 'from your library'}",
                                actor=ctx.actor, campaign_id=ctx.campaign_id,
                                payload={"asset_id": asset_id, "photo_id": str(photo["id"]), "image_key": photo["image_key"]})
            return {"image_key": photo["image_key"], "photo": photo.get("caption"), "source": photo["source"]}
        brand = await services.active_brand(conn, ctx.business["id"])
    if not ctx.settings.ai_picture_fallback:
        return {"error": "No photos of the business yet. Ask the owner to add photos."}
    dna = (brand or {}).get("dna", {})
    prompt = (f"{concept}. {dna.get('imagery', 'Photographic, warm natural light.')} {ctx.business['locality']}, "
              f"{ctx.business['city']}. Colour accents: {', '.join(dna.get('palette', []))}. Keep the lower third "
              "calm and uncluttered for an offer box. Absolutely no text, letters, numbers, logos or watermarks.")
    try:
        img = await asyncio.wait_for(ctx.router.image(prompt, size="1K", ratio=RATIOS[asset["channel"]]),
                                     timeout=ctx.settings.picture_timeout_s)
    except TimeoutError:
        return {"error": "The AI picture took too long. Add photos of the business, or try again later."}
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(img.mime, "bin")
    key = await get_storage().put(f"{ctx.business['slug']}/{asset_id}/{asset['current_revision']}.{ext}",
                                  img.data, img.mime)
    async with connection() as conn:
        await conn.execute(
            "update asset_revisions set image_key = %s where asset_id = %s and n = %s",
            (key, asset_id, asset["current_revision"]))
        await ledger.record(conn, ctx.business["id"], "asset.visual", f"Made a new picture for the {services.asset_label(asset)}",
                            actor=ctx.actor, campaign_id=ctx.campaign_id,
                            payload={"asset_id": asset_id, "image_key": key, "saved_output": img.replayed})
    return {"image_key": key, "source": "generated", "saved_output": img.replayed}


# ------------------------------------------------------------------ experiments


class ExperimentArgs(BaseModel):
    asset_ids: list[str] = Field(min_length=2, max_length=4)
    hypothesis: str
    dimension: str = Field(description="The single thing that differs between arms, e.g. 'hook'.")
    trial_type: Literal["impression", "scan", "click", "reply"] = "scan"
    success_type: Literal["click", "reply", "redeem"] = "redeem"


@tool("create_experiment", "Run assets that differ in one thing as competing arms.", ExperimentArgs, "internal",
      [needs_campaign])
async def create_experiment(ctx: ToolContext, a: ExperimentArgs) -> dict[str, Any]:
    async with connection() as conn:
        exp = await fetch_one(
            conn,
            """insert into experiments (campaign_id, hypothesis, dimension, trial_type, success_type, status)
               values (%s, %s, %s, %s, %s, 'running') returning id""",
            (ctx.campaign_id, a.hypothesis, a.dimension, a.trial_type, a.success_type))
        assert exp
        for i, aid in enumerate(a.asset_ids):
            await conn.execute(
                """update assets set experiment_id = %s, variant = coalesce(variant, %s)
                   where id = %s and campaign_id = %s""",
                (exp["id"], "ABCD"[i], aid, ctx.campaign_id))
        await ledger.record(conn, ctx.business["id"], "experiment.created", f"Experiment: {a.hypothesis}",
                            actor=ctx.actor, campaign_id=ctx.campaign_id, payload={"experiment_id": str(exp["id"])})
    return {"experiment_id": str(exp["id"])}


@tool("decide_experiment", "Close an experiment if the statistics support a winner.", ExperimentRef, "internal")
async def decide_experiment(ctx: ToolContext, a: ExperimentRef) -> dict[str, Any]:
    async with connection() as conn:
        st = await services.experiment_status(conn, a.experiment_id)
        if not st["decision"]["winner"]:
            return {"decided": False, "reason": st["decision"]["reason"]}
        await conn.execute(
            "update experiments set status = 'decided', decision = %s, decided_at = now() where id = %s",
            (jsonb({**st["decision"], "arms": st["arms"]}), a.experiment_id))
        await ledger.record(conn, ctx.business["id"], "experiment.decided", st["decision"]["reason"],
                            actor=ctx.actor, campaign_id=st["experiment"]["campaign_id"],
                            payload={"experiment_id": a.experiment_id, "winner": st["decision"]["winner"]})
    return {"decided": True, **st["decision"]}


# ------------------------------------------------------------------ customer-facing


class PublishArgs(BaseModel):
    asset_ids: list[str] = Field(min_length=1)
    summary: str = Field(description="One line for the owner describing what goes out.")


@tool("publish_assets", "Approve and put assets live, issuing a tracking code for each. Needs the owner.",
      PublishArgs, "customer_facing", [needs_locked_facts])
async def publish_assets(ctx: ToolContext, a: PublishArgs) -> dict[str, Any]:
    async with connection() as conn:
        out = await services.publish(conn, ctx.campaign_id, ctx.business["id"], a.asset_ids, actor=ctx.actor)
    return {"published": out}


async def _autopublish(ctx: ToolContext) -> list[dict[str, Any]]:
    async with connection() as conn:
        return await services.autopublish(conn, ctx.campaign_id)


# ------------------------------------------------------------------ memory & recommendations


class LearningArgs(BaseModel):
    content: str
    scope: dict[str, str] = Field(default_factory=dict, description="{segment, channel, language, hook}")
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)


@tool("record_learning", "Remember something the results showed, with evidence, for future campaigns.",
      LearningArgs, "internal")
async def record_learning(ctx: ToolContext, a: LearningArgs) -> dict[str, Any]:
    if ctx.agent == "analyst" and ctx.campaign_id:  # a learning outlives the campaign: only what the data make likely
        r = await _results(ctx)
        if not (sure := analyst_rules.sure_findings(r)):
            return {"error": "Nothing in these results is sure enough to remember yet (no difference is at least 90% "
                             "likely). Record a learning once a tip says one option converts better."}
        if bad := analyst_rules.unsupported(a.content, r):
            return {"error": f"These numbers are not in the results: {', '.join(bad)}. Sure findings: {'; '.join(sure)}"}
    async with connection() as conn:
        row = await fetch_one(
            conn,
            """insert into memories (business_id, campaign_id, kind, content, scope, evidence, confidence, created_by)
               values (%s, %s, 'learning', %s, %s, %s, %s, 'agent') returning id""",
            (ctx.business["id"], ctx.campaign_id, a.content, jsonb(a.scope), jsonb(a.evidence), a.confidence))
        await ledger.record(conn, ctx.business["id"], "memory.learning", a.content, actor=ctx.actor,
                            campaign_id=ctx.campaign_id)
    return {"learning_id": str(row["id"])}  # type: ignore[index]


class RecommendArgs(BaseModel):
    title: str
    body: str
    evidence: list[str] = Field(default_factory=list)
    expected_impact: str | None = None


@tool("recommend", "Put a recommendation in the owner's inbox (for ideas that are not a single tool call).",
      RecommendArgs, "internal")
async def recommend(ctx: ToolContext, a: RecommendArgs) -> dict[str, Any]:
    async with connection() as conn:
        row = await fetch_one(
            conn,
            """insert into inbox_items (business_id, campaign_id, kind, title, body, payload)
               values (%s, %s, 'recommendation', %s, %s, %s) returning id""",
            (ctx.business["id"], ctx.campaign_id, a.title, a.body,
             jsonb({"evidence": a.evidence, "expected_impact": a.expected_impact})))
    return {"inbox_item_id": str(row["id"])}  # type: ignore[index]


# ------------------------------------------------------------------ Brief agent: who, why and where


@tool("get_reach", "Who the business can reach and what worked before: its languages, connected channels (WhatsApp "
      "contacts, Instagram), customer segments it knows, and past results per channel, language and audience.",
      NoArgs, "read")
async def get_reach(ctx: ToolContext, _: NoArgs) -> dict[str, Any]:
    bid = ctx.business["id"]
    async with connection() as conn:
        connected = [r["channel"] for r in await fetch_all(
            conn, "select channel from channel_accounts where business_id = %s", (bid,))]
        contacts = await fetch_one(conn, """select count(*) filter (where opted_out_at is null)::int as n
                                            from wa_contacts where business_id = %s""", (bid,))
        segments = await fetch_all(conn, """select key, data from customer_insights
                                            where business_id = %s and kind = 'segment'""", (bid,))
        past = await fetch_all(
            conn, """select a.channel, a.language, a.segment,
                            coalesce(sum(o.qty) filter (where o.type = 'scan'), 0)::int as scans,
                            coalesce(sum(o.qty) filter (where o.type = 'redeem'
                                     and not coalesce((o.meta->>'return')::boolean, false)), 0)::int as redeems
                     from assets a join campaigns c on c.id = a.campaign_id
                     left join outcome_events o on o.asset_id = a.id
                     where c.business_id = %s and a.status in ('live', 'retired') group by 1, 2, 3""", (bid,))

    def by(dim: str) -> list[dict[str, Any]]:
        g: dict[str, dict[str, Any]] = {}
        for r in past:
            row = g.setdefault(r[dim] or "none", {dim: r[dim] or "none", "posts": 0, "scans": 0, "redeems": 0})
            row["posts"] += 1
            row["scans"] += r["scans"]
            row["redeems"] += r["redeems"]
        return sorted(g.values(), key=lambda x: -x["redeems"])

    return {"languages": ctx.business["languages"],
            "channels": {"whatsapp": {"connected": "whatsapp" in connected, "contacts": (contacts or {}).get("n", 0)},
                         "instagram": {"connected": "instagram" in connected},
                         "poster": {"connected": True, "note": "printed at the counter, always available"}},
            "known_segments": segments,
            "past_results": {"channel": by("channel"), "language": by("language"), "segment": by("segment")}}


# ------------------------------------------------------------------ Analyst agent: what the results say


async def needs_live_posts(ctx: ToolContext, _: Any) -> str | None:
    if not ctx.campaign_id:
        return "No campaign is selected."
    async with connection() as conn:
        live = await fetch_one(conn, "select count(*)::int as n from touchpoints where campaign_id = %s",
                               (ctx.campaign_id,))
    return None if live and live["n"] else "Nothing in this campaign is live yet, so there are no results to read."


async def _results(ctx: ToolContext) -> dict[str, Any]:
    from app import results

    async with connection() as conn:
        c = await services.get_campaign(conn, ctx.campaign_id)  # type: ignore[arg-type]
        return await results.campaign(conn, c, ctx.business)


@tool("get_results", "This campaign's results: the funnel (opened, claimed, redeemed, came back), sales typed at the "
      "counter, breakdowns by channel, language and audience with their likely ranges, each post, best hours, the "
      "A/B tests and the system's own rule-based tips.", NoArgs, "read", [needs_live_posts])
async def get_results(ctx: ToolContext, _: NoArgs) -> dict[str, Any]:
    r = await _results(ctx)
    return {"totals": r["totals"], "by": r["by"], "repeat": r["repeat"], "experiments": r["experiments"],
            "posts": [{k: p.get(k) for k in ("code", "asset_id", "channel", "language", "segment", "variant", "headline",
                                             "scans", "claims", "redeems", "returns", "conversion")} for p in r["posts"]],
            "last_7_days": r["daily"][-7:], "busiest_hours": sorted(r["hours"], key=lambda h: -h["active"])[:3],
            "tips": [{k: t[k] for k in ("kind", "title", "detail", "ask")} for t in r["tips"]],
            "simulated_events": r["simulated"], "too_early": analyst_rules.too_early(r)}


class MoveArgs(BaseModel):
    kind: Literal["more_of_what_works", "rewrite_weak_post", "remind_claimers", "change_offer", "extend",
                  "end_campaign", "use_ab_winner", "share_more"]
    title: str = Field(min_length=5, max_length=90, description="The move in a few plain words, e.g. 'Make more "
                       "Kannada WhatsApp posts'.")
    why: str = Field(max_length=300, description="One or two sentences from the results, quoting their numbers.")
    evidence: list[str] = Field(min_length=1, max_length=4, description="Short lines, each with a number from the "
                                "results, e.g. 'Kannada WhatsApp: 9 of 40 who opened came in (23%)'.")
    instruction: str = Field(max_length=300, description="What the team will do if the owner says yes, as an "
                             "instruction to the Orchestrator, e.g. 'Write two more Kannada WhatsApp posts for "
                             "students and retire the English poster'.")


MAX_OPEN_MOVES = 2


@tool("propose_next_move", "Suggest the next move to the owner, backed by the campaign's results. Every number in it "
      "must come from get_results. The owner says yes or no; on yes the team does the instruction.", MoveArgs,
      "internal", [needs_live_posts])
async def propose_next_move(ctx: ToolContext, a: MoveArgs) -> dict[str, Any]:
    r = await _results(ctx)
    if (early := analyst_rules.too_early(r)) and a.kind != "share_more":
        return {"error": early}
    if why_not := analyst_rules.unsupported_move(a.kind, r):
        return {"error": why_not}
    if bad := analyst_rules.unsupported(" ".join([a.title, a.why, *a.evidence]), r):
        return {"error": f"These numbers are not in the results: {', '.join(bad)}. Quote only what get_results says "
                         f"({analyst_rules.numbers_hint(r)})."}
    async with connection() as conn:
        open_ = await fetch_all(conn, """select title from inbox_items where campaign_id = %s and status = 'pending'
                                         and kind = 'recommendation' and payload->>'asked_by' = 'analyst'""",
                                (ctx.campaign_id,))
        if any(o["title"].casefold() == a.title.casefold() for o in open_):
            return {"already_suggested": True}
        if len(open_) >= MAX_OPEN_MOVES:
            return {"error": f"{len(open_)} suggestions are already waiting for the owner. Stop."}
        row = await fetch_one(
            conn, """insert into inbox_items (business_id, campaign_id, kind, title, body, payload, priority)
                     values (%s, %s, 'recommendation', %s, %s, %s, 2) returning id""",
            (ctx.business["id"], ctx.campaign_id, a.title, a.why,
             jsonb({"asked_by": "analyst", "move": a.kind, "evidence": a.evidence, "instruction": a.instruction})))
        await ledger.record(conn, ctx.business["id"], "analyst.suggested", a.title, actor="agent",
                            campaign_id=ctx.campaign_id, payload={"agent": "analyst", "inbox_item_id": str(row["id"])})  # type: ignore[index]
    return {"inbox_item_id": str(row["id"]), "message": "The owner has been asked."}  # type: ignore[index]


# ------------------------------------------------------------------ Customer listener: reviews and comments


@tool("get_reviews_to_answer", "Reviews and comments from the last 30 days that still need the owner: complaints, "
      "questions and low ratings without a reply, with their language, English reading and themes.", NoArgs, "read")
async def get_reviews_to_answer(ctx: ToolContext, _: NoArgs) -> dict[str, Any]:
    async with connection() as conn:
        rows = await fetch_all(
            conn, """select id::text, source, rating, category, language, body, translation, themes, sentiment,
                            occurred_at::date as day, reply_draft is not null as has_draft
                     from customer_interactions
                     where business_id = %s and reply is null and occurred_at > now() - interval '30 days'
                       and category is distinct from 'spam'
                       and (category in ('complaint', 'question') or rating <= 3 or sentiment < -0.2)
                     order by occurred_at desc limit 25""", (ctx.business["id"],))
    return {"reviews": rows}


class ReplyArgs(BaseModel):
    review_ids: list[str] = Field(min_length=1, max_length=8)


async def _business_reviews(ctx: ToolContext, ids: list[str]) -> list[dict[str, Any]]:
    async with connection() as conn:
        return await fetch_all(conn, """select * from customer_interactions where business_id = %s
                                        and id::text = any(%s)""", (ctx.business["id"], ids))


@tool("draft_replies", "Draft a reply to each review, in its own language and the owner's voice, never promising an "
      "offer. Drafts wait on the Customers page; only the owner sends them.", ReplyArgs, "internal")
async def draft_replies(ctx: ToolContext, a: ReplyArgs) -> dict[str, Any]:
    from app import reviews

    found = await _business_reviews(ctx, a.review_ids)
    if missing := sorted(set(a.review_ids) - {str(r["id"]) for r in found}):
        return {"error": f"No such review for this business: {', '.join(missing)}"}
    async with connection() as conn:
        brand = await services.active_brand(conn, ctx.business["id"])
    drafts = await asyncio.gather(*[reviews.draft_reply(ctx.router, ctx.business, r, brand) for r in found],
                                  return_exceptions=True)
    out = []
    async with connection() as conn:
        for r, d in zip(found, drafts, strict=True):
            if isinstance(d, BaseException) or not d:
                out.append({"review_id": str(r["id"]), "error": "no draft"})
                continue
            await conn.execute("update customer_interactions set reply_draft = %s, reply_drafted_at = now() where id = %s",
                               (d, r["id"]))
            out.append({"review_id": str(r["id"]), "language": r["language"], "draft": d})
        await ledger.record(conn, ctx.business["id"], "listener.drafted",
                            f"Drafted {sum('draft' in o for o in out)} replies for you to read and send", actor="agent",
                            payload={"agent": "listener", "review_ids": a.review_ids})
    return {"drafts": out}


class IssueArgs(BaseModel):
    theme: str = Field(min_length=2, max_length=40, description="The theme, as in get_customer_themes, e.g. 'queue'.")
    title: str = Field(min_length=5, max_length=90, description="What customers are saying, e.g. 'Evening queue is "
                       "too long'.")
    detail: str = Field(max_length=300, description="How many said it and since when, in plain words.")
    review_ids: list[str] = Field(min_length=2, max_length=6, description="Reviews that say it (real ids).")
    fix: str | None = Field(None, max_length=200, description="One practical thing the owner could do about it.")


@tool("raise_issue", "Tell the owner about a problem several customers raised, quoting their own words. Needs at least "
      "two real reviews that mention it.", IssueArgs, "internal")
async def raise_issue(ctx: ToolContext, a: IssueArgs) -> dict[str, Any]:
    found = await _business_reviews(ctx, a.review_ids)
    if len(found) < 2:
        return {"error": "Raise an issue only with at least two real reviews (ids from get_reviews_to_answer or "
                         "get_customer_themes)."}
    theme = a.theme.casefold().replace(" ", "_")
    if not any(theme in (r["themes"] or []) for r in found):
        return {"error": f"None of these reviews is tagged with '{a.theme}'. Use the theme the reviews carry."}
    async with connection() as conn:
        dupe = await fetch_one(conn, """select id from inbox_items where business_id = %s and status = 'pending'
                                        and kind = 'finding' and payload->>'theme' = %s""", (ctx.business["id"], theme))
        if dupe:
            return {"already_raised": True}
        quotes = [f"“{(r['translation'] or r['body'])[:140]}” ({r['source'].replace('_', ' ')})" for r in found[:4]]
        row = await fetch_one(
            conn, """insert into inbox_items (business_id, kind, title, body, payload, priority)
                     values (%s, 'finding', %s, %s, %s, 2) returning id""",
            (ctx.business["id"], a.title, a.detail + (f" Idea: {a.fix}" if a.fix else ""),
             jsonb({"asked_by": "listener", "theme": theme, "evidence": quotes, "review_ids": a.review_ids})))
        await ledger.record(conn, ctx.business["id"], "listener.issue", a.title, actor="agent",
                            payload={"agent": "listener", "inbox_item_id": str(row["id"])})  # type: ignore[index]
    return {"inbox_item_id": str(row["id"])}  # type: ignore[index]


class FollowUpArgs(BaseModel):
    title: str = Field(min_length=5, max_length=80)
    brief: str = Field(min_length=10, max_length=300, description="A brief the owner could send as is, e.g. 'Free "
                       "extra decoction shot with any filter coffee for regulars this week, to win back...'.")
    why: str = Field(max_length=300, description="Which reviews it answers and how.")
    items: list[str] = Field(default_factory=list, description="Menu items the brief uses, spelled as on the menu.")
    review_ids: list[str] = Field(min_length=1, max_length=6)


@tool("suggest_campaign", "Suggest a follow-up campaign that answers what customers said (win back people who "
      "complained, reward praise). The owner starts it with one tap.", FollowUpArgs, "internal")
async def suggest_campaign(ctx: ToolContext, a: FollowUpArgs) -> dict[str, Any]:
    menu = {m["name"].casefold() for m in ctx.business["profile"].get("menu", [])}
    if off := [i for i in a.items if i.casefold() not in menu]:
        return {"error": f"Not on the menu: {', '.join(off)}."}
    if not await _business_reviews(ctx, a.review_ids):
        return {"error": "Base the suggestion on real reviews (ids from get_reviews_to_answer)."}
    async with connection() as conn:
        row = await fetch_one(
            conn, """insert into inbox_items (business_id, kind, title, body, payload, priority)
                     values (%s, 'recommendation', %s, %s, %s, 2) returning id""",
            (ctx.business["id"], a.title, a.why,
             jsonb({"asked_by": "listener", "brief": a.brief, "items": a.items, "review_ids": a.review_ids})))
        await ledger.record(conn, ctx.business["id"], "listener.suggested", a.title, actor="agent",
                            payload={"agent": "listener", "inbox_item_id": str(row["id"])})  # type: ignore[index]
    return {"inbox_item_id": str(row["id"])}  # type: ignore[index]
