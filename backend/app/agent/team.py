"""The agent team: an Orchestrator and the specialists it hands work to.

Each agent has one job, its own model role (so the Writer and the Checker never run on the same model chain) and
its own subset of tools. Agents never pass offer details to each other: they read and write the database (locked
facts, posts, approvals), and every tool call still goes through the policy gate in runtime.execute.

  Orchestrator --ask_brief----> Brief    (who it is for, the goal, channels and languages: the campaign plan)
               --ask_offer----> Offer    (draft/revise facts, margins, questions to the owner; never locks)
               --ask_change---> Change   (impact preview + revision of a locked offer; never locks)
               --ask_language-> Language (offer wording in every language: Sarvam + day/number checks)
               --ask_writer---> Writer   (generate_copy, generate_visual)
               --ask_checker--> Checker  (validate_assets; never writes)
               --ask_analyst--> Analyst  (reads the results, proposes the next move; A/B decisions, learnings)
               --ask_listener-> Customer listener (reviews and comments: issues, reply drafts, a follow-up campaign)

The Orchestrator keeps the tools no specialist owns (locking requests, experiments, publishing, recommendations). Locking the offer and publishing always go to the owner through the policy gate.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.agent.prompts import (
    ANALYST_SYSTEM,
    BRIEF_SYSTEM,
    CHANGE_SYSTEM,
    CHECKER_SYSTEM,
    LANGUAGE_SYSTEM,
    LISTENER_SYSTEM,
    OFFER_SYSTEM,
    ORCHESTRATOR_SYSTEM,
    WRITER_SYSTEM,
)
from app.agent.tools import REGISTRY, ToolContext, needs_campaign, needs_live_posts, needs_locked_facts, tool


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    role: str  # router role the agent's own reasoning runs on
    system: str
    tools: tuple[str, ...]


OFFER = AgentSpec(
    key="offer", name="Offer agent", role="reasoning", system=OFFER_SYSTEM,
    tools=("get_situation", "get_menu", "evaluate_offer", "draft_offer_facts", "revise_offer_facts", "ask_owner"),
)
CHANGE = AgentSpec(
    key="change", name="Change agent", role="reasoning", system=CHANGE_SYSTEM,
    tools=("get_situation", "get_menu", "evaluate_offer", "preview_change", "revise_offer_facts", "ask_owner"),
)
LANGUAGE = AgentSpec(
    key="language", name="Language agent", role="generation", system=LANGUAGE_SYSTEM,
    tools=("get_situation", "translate_offer"),
)
WRITER = AgentSpec(
    key="writer", name="Writer", role="generation", system=WRITER_SYSTEM,
    tools=("get_situation", "get_brand_and_learnings", "get_customer_themes", "generate_copy", "generate_visual"),
)
CHECKER = AgentSpec(
    key="checker", name="Checker", role="verification", system=CHECKER_SYSTEM,
    tools=("get_situation", "validate_assets"),
)
BRIEF = AgentSpec(
    key="brief", name="Brief agent", role="reasoning", system=BRIEF_SYSTEM,
    tools=("get_situation", "get_reach", "get_customer_themes", "get_brand_and_learnings", "ask_owner",
           "set_campaign_plan"),
)
ANALYST = AgentSpec(
    key="analyst", name="Analyst", role="verification", system=ANALYST_SYSTEM,
    tools=("get_situation", "get_results", "experiment_status", "decide_experiment", "record_learning",
           "propose_next_move"),
)
LISTENER = AgentSpec(
    key="listener", name="Customer listener", role="reasoning", system=LISTENER_SYSTEM,
    tools=("get_situation", "get_customer_themes", "get_reviews_to_answer", "get_menu", "draft_replies",
           "raise_issue", "suggest_campaign"),
)
SPECIALISTS = {a.key: a for a in (BRIEF, OFFER, CHANGE, LANGUAGE, WRITER, CHECKER, ANALYST, LISTENER)}
SHARED_READS = {"get_situation", "get_menu", "get_customer_themes", "get_brand_and_learnings"}
OWNED = {t for a in SPECIALISTS.values() for t in a.tools if t not in SHARED_READS}  # specialist-only tools
HANDOFFS = ("ask_brief", "ask_offer", "ask_change", "ask_language", "ask_writer", "ask_checker", "ask_analyst",
            "ask_listener")

ORCHESTRATOR = AgentSpec(
    key="orchestrator", name="Orchestrator", role="reasoning", system=ORCHESTRATOR_SYSTEM,
    tools=tuple(t for t in REGISTRY if t not in OWNED and t not in HANDOFFS) + HANDOFFS,
)
TEAM = {ORCHESTRATOR.key: ORCHESTRATOR, **SPECIALISTS}


def owner_of(tool_name: str) -> AgentSpec | None:
    """The specialist a tool belongs to, so an agent that calls it can be told whom to ask."""
    return next((a for a in SPECIALISTS.values() if tool_name in a.tools and tool_name in OWNED), None)


# ------------------------------------------------------------------ hand-off tools (Orchestrator only)


class BriefTask(BaseModel):
    task: str = Field(description="What to settle, e.g. 'Plan the campaign from the brief' or 'The owner answered: "
                                  "students from the colleges nearby. Finish the plan'.")


class AnalystTask(BaseModel):
    task: str = Field(description="What to look at, e.g. 'Read the results and propose the next move' or 'The A/B "
                                  "test may have a winner'.")


class ListenerTask(BaseModel):
    task: str = Field(description="What to do, e.g. 'New reviews arrived; find issues, draft replies and suggest a "
                                  "follow-up if one fits'.")


class OfferTask(BaseModel):
    task: str = Field(description="What to do with the offer, e.g. 'Turn the brief into offer facts' or 'The owner "
                                  "answered: whole bill. Update the draft' or 'The owner moved it to Saturday'.")


class ChangeTask(BaseModel):
    task: str = Field(description="The owner's change to the locked offer in their words, e.g. 'make it weekends "
                                  "only' or 'The owner answered: yes, keep 20%. Make the change'.")


class LanguageTask(BaseModel):
    task: str = Field(description="What to do, e.g. 'Write the offer in Kannada and Hindi' or 'The wording check "
                                  "failed for the Hindi days; fix it'.")


class WriterTask(BaseModel):
    task: str = Field(description="What to write or rewrite, e.g. 'Write the posts in the plan' or 'Rewrite the "
                                  "stale posts after the day change'. The Writer reads the plan and facts itself.")
    asset_ids: list[str] = Field(default_factory=list, description="Posts to rewrite, if any.")


class CheckerTask(BaseModel):
    task: str = Field(description="What to check, e.g. 'Re-check the posts whose meaning check is pending'.")
    asset_ids: list[str] = Field(default_factory=list, description="Posts to check; empty = the Checker picks.")


@tool("ask_brief", "Hand a new brief to the Brief agent first: it settles who the campaign is for, what it should "
      "achieve (a number), and which channels and languages to use, asks the owner if that is unclear, and saves "
      "the campaign plan.", BriefTask, "internal", [needs_campaign])
async def ask_brief(ctx: ToolContext, a: BriefTask) -> dict[str, Any]:
    from app.agent import runtime

    return await runtime.delegate(ctx, BRIEF, a.model_dump())


@tool("ask_analyst", "Hand the results to the Analyst: it reads the funnel and the A/B tests, decides a test when the "
      "statistics allow, records what was learned and proposes the next move to the owner.", AnalystTask, "internal",
      [needs_live_posts])
async def ask_analyst(ctx: ToolContext, a: AnalystTask) -> dict[str, Any]:
    from app.agent import runtime

    return await runtime.delegate(ctx, ANALYST, a.model_dump())


@tool("ask_listener", "Hand customer reviews and comments to the Customer listener: it raises issues several "
      "customers share, drafts replies for the owner to send, and suggests a follow-up campaign when one fits.",
      ListenerTask, "internal")
async def ask_listener(ctx: ToolContext, a: ListenerTask) -> dict[str, Any]:
    from app.agent import runtime

    return await runtime.delegate(ctx, LISTENER, a.model_dump())


@tool("ask_offer", "Hand offer work to the Offer agent: turn the brief into offer facts, settle unclear details "
      "with the owner, check the margin, or revise a locked offer. It never locks; you ask the owner to lock.",
      OfferTask, "internal", [needs_campaign])
async def ask_offer(ctx: ToolContext, a: OfferTask) -> dict[str, Any]:
    from app.agent import runtime

    return await runtime.delegate(ctx, OFFER, a.model_dump())


@tool("ask_change", "Hand a change to a locked offer to the Change agent: it previews which posts must be "
      "rewritten and which only get their offer box refilled, settles questions with the owner and drafts the new "
      "version. It never locks; you ask the owner to lock.", ChangeTask, "internal", [needs_locked_facts])
async def ask_change(ctx: ToolContext, a: ChangeTask) -> dict[str, Any]:
    from app.agent import runtime

    return await runtime.delegate(ctx, CHANGE, a.model_dump())


@tool("ask_language", "Hand the offer wording to the Language agent: it writes every detail in each of the "
      "business's languages (Sarvam translation, its own wording where that is wrong) and gets each one checked.",
      LanguageTask, "internal", [needs_campaign])
async def ask_language(ctx: ToolContext, a: LanguageTask) -> dict[str, Any]:
    from app.agent import runtime

    return await runtime.delegate(ctx, LANGUAGE, a.model_dump())


@tool("ask_writer", "Hand writing work to the Writer agent: new posts from the plan, or rewrites of stale or "
      "blocked posts. Returns what it wrote and what is still blocked.", WriterTask, "internal", [needs_locked_facts])
async def ask_writer(ctx: ToolContext, a: WriterTask) -> dict[str, Any]:
    from app.agent import runtime

    return await runtime.delegate(ctx, WRITER, a.model_dump())


@tool("ask_checker", "Hand checking work to the Checker agent, which runs on a different model from the Writer and "
      "re-runs the meaning check against the locked offer. It never edits posts.", CheckerTask, "internal",
      [needs_locked_facts])
async def ask_checker(ctx: ToolContext, a: CheckerTask) -> dict[str, Any]:
    from app.agent import runtime

    return await runtime.delegate(ctx, CHECKER, a.model_dump())
