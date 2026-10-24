"""Reads every connected Instagram account on its own while the backend runs: new comments become reviews, a comment
asking for the offer gets a personal code, and post insights are refreshed. Pages still read on open; this only means
nothing waits for the owner to look. Each step keeps its own pace (comments every few minutes, insights hourly).
"""

import asyncio
import logging
from typing import Any

from app.channels import instagram, meta
from app.db import connection, fetch_all

log = logging.getLogger(__name__)


async def once(router: Any) -> int:
    """One pass over every business with Instagram connected. -> comments added."""
    async with connection() as conn:
        businesses = await fetch_all(conn, """select b.* from businesses b join channel_accounts ca on ca.business_id = b.id
                                              where ca.channel = 'instagram'""")
    added = 0
    for b in businesses:
        try:
            added += await instagram.sync_comments(router, b)
            await instagram.sync(b["id"])
        except meta.MetaError as e:  # an expired token or a Meta outage: the Channels page shows the state
            log.warning("Instagram read failed for %s: %s", b["slug"], e)
    return added


async def run(router: Any, every: int) -> None:
    while True:
        try:
            await once(router)
        except Exception:  # never let one bad pass stop the watch
            log.exception("channel watch pass failed")
        await asyncio.sleep(every)
