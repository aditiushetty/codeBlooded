"""Thin async Postgres access. Plain SQL, dict rows, one pool per process."""

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None

Conn = AsyncConnection[dict[str, Any]]


async def _configure(conn: AsyncConnection) -> None:
    # Supabase poolers share server connections between clients, so never keep
    # named prepared statements around.
    conn.prepare_threshold = None


_used: dict[int, float] = {}  # connection id -> when it was last handed back
FRESH_SECONDS = 20


async def _check(conn: AsyncConnection) -> None:
    """A laptop sleep or the Supabase pooler's idle timeout silently kills pooled connections, so a connection that
    sat unused is tested before it is handed out (one round trip). One used a moment ago is not: a page loads
    several resources at once, and testing each would add a round trip to every request."""
    if time.monotonic() - _used.get(id(conn), 0) > FRESH_SECONDS:
        await AsyncConnectionPool.check_connection(conn)


async def _returned(conn: AsyncConnection) -> None:
    _used[id(conn)] = time.monotonic()


# Supabase's session pooler takes at most 15 clients for the whole project, shared by every server and script that
# connects (the deployed API, a laptop running it too, migrations). Six each leaves room for two servers and tools.
async def open_pool(dsn: str, *, min_size: int = 2, max_size: int = 6) -> AsyncConnectionPool:
    global _pool
    _pool = AsyncConnectionPool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        kwargs={"row_factory": dict_row, "autocommit": False},
        configure=_configure,
        check=_check,  # replace a dead connection instead of failing that request with a 500
        reset=_returned,
        max_idle=120,  # hand back connections a burst of requests opened, so other clients can connect
        open=False,
    )
    await _pool.open(wait=True)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def connection() -> AsyncIterator[Conn]:
    """A connection inside a transaction: commits on success, rolls back on error."""
    if _pool is None:
        raise RuntimeError("database pool is not open")
    async with _pool.connection() as conn:
        yield conn  # pool.connection() commits/rolls back for us


async def fetch_one(conn: Conn, sql: str, params: Any = None) -> dict[str, Any] | None:
    cur = await conn.execute(sql, params)
    return await cur.fetchone()


async def fetch_all(conn: Conn, sql: str, params: Any = None) -> list[dict[str, Any]]:
    cur = await conn.execute(sql, params)
    return await cur.fetchall()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)  # UUIDs, datetimes, Decimals from rows


def jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=_dumps)
