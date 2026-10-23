"""Model calls kept per business and campaign, so a campaign's AI cost sits next to what it brought in.

The router reports every call (`ModelRouter.on_call`); `keep` stores the ones made for a business, without
holding up the caller. Cost is estimated from measured tokens at the list price in settings.
"""

import asyncio
import logging
from typing import Any

from app.config import get_settings
from app.db import Conn, connection, fetch_one
from app.providers.router import CallRecord

log = logging.getLogger(__name__)
_pending: set[asyncio.Task[None]] = set()


async def _store(r: CallRecord) -> None:
    try:
        async with connection() as conn:
            await conn.execute(
                """insert into model_calls (business_id, campaign_id, agent, task, role, provider, model, ok, replayed,
                                            input_tokens, output_tokens, latency_ms)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (r.business_id, r.campaign_id, r.agent, r.task, r.role, r.provider, r.model, r.ok, r.replayed,
                 r.input_tokens, r.output_tokens, r.latency_ms))
    except Exception:  # a lost usage row must never break the work it describes
        log.debug("model call not stored", exc_info=True)


def keep(r: CallRecord) -> None:
    if not r.business_id:
        return
    try:
        task = asyncio.get_running_loop().create_task(_store(r))
    except RuntimeError:
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def rupees(input_tokens: int, output_tokens: int) -> float:
    s = get_settings()
    usd = (input_tokens * s.ai_price_in_usd_per_m + output_tokens * s.ai_price_out_usd_per_m) / 1e6
    return round(usd * s.usd_inr, 4)


async def spent(conn: Conn, *, campaign_id: Any = None, business_id: Any = None) -> dict[str, Any]:
    """Calls, tokens and estimated ₹ for one campaign, or for a whole business."""
    col, val = ("campaign_id", campaign_id) if campaign_id else ("business_id", business_id)
    row = await fetch_one(conn, f"""select count(*)::int as calls, coalesce(sum(input_tokens), 0)::int as input_tokens,
                                          coalesce(sum(output_tokens), 0)::int as output_tokens, min(created_at) as since
                                   from model_calls where {col} = %s and not replayed""", (val,))
    row = row or {"calls": 0, "input_tokens": 0, "output_tokens": 0, "since": None}
    s = get_settings()
    return {**row, "rupees": rupees(row["input_tokens"], row["output_tokens"]),
            "price": {"in_usd_per_m": s.ai_price_in_usd_per_m, "out_usd_per_m": s.ai_price_out_usd_per_m,
                      "usd_inr": s.usd_inr}}
