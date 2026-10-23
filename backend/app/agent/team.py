"""The agent team: an Orchestrator and the specialists it hands work to.

Each agent has one job, its own model role (so the Writer and the Checker never run on the same model chain) and
its own subset of tools. Agents never pass offer details to each other: they read and write the database (locked
facts, posts, approvals), and every tool call still goes through the policy gate in runtime.execute.

  Orchestrator --ask_writer--> Writer   (generate_copy, generate_visual)
               --ask_checker-> Checker  (validate_assets; never writes)

The Orchestrator keeps the tools no specialist owns yet (offer facts, plan, experiments, publishing, learnings).
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.agent.prompts import CHECKER_SYSTEM, ORCHESTRATOR_SYSTEM, WRITER_SYSTEM
from app.agent.tools import REGISTRY, ToolContext, needs_locked_facts, tool


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    role: str  # router role the agent's own reasoning runs on
    system: str
    tools: tuple[str, ...]


WRITER = AgentSpec(
    key="writer", name="Writer", role="generation", system=WRITER_SYSTEM,
    tools=("get_situation", "get_brand_and_learnings", "get_customer_themes", "generate_copy", "generate_visual"),
)
CHECKER = AgentSpec(
    key="checker", name="Checker", role="verification", system=CHECKER_SYSTEM,
    tools=("get_situation", "validate_assets"),
)
SPECIALISTS = {a.key: a for a in (WRITER, CHECKER)}
OWNED = {t for a in SPECIALISTS.values() for t in a.tools if not t.startswith("get_")}  # specialist-only tools

ORCHESTRATOR = AgentSpec(
    key="orchestrator", name="Orchestrator", role="reasoning", system=ORCHESTRATOR_SYSTEM,
    tools=tuple(t for t in REGISTRY if t not in OWNED) + ("ask_writer", "ask_checker"),
)
TEAM = {ORCHESTRATOR.key: ORCHESTRATOR, **SPECIALISTS}


def owner_of(tool_name: str) -> AgentSpec | None:
    """The specialist a tool belongs to, so an agent that calls it can be told whom to ask."""
    return next((a for a in SPECIALISTS.values() if tool_name in a.tools and tool_name in OWNED), None)


# ------------------------------------------------------------------ hand-off tools (Orchestrator only)


class WriterTask(BaseModel):
    task: str = Field(description="What to write or rewrite, e.g. 'Write the posts in the plan' or 'Rewrite the "
                                  "stale posts after the day change'. The Writer reads the plan and facts itself.")
    asset_ids: list[str] = Field(default_factory=list, description="Posts to rewrite, if any.")


class CheckerTask(BaseModel):
    task: str = Field(description="What to check, e.g. 'Re-check the posts whose meaning check is pending'.")
    asset_ids: list[str] = Field(default_factory=list, description="Posts to check; empty = the Checker picks.")


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
