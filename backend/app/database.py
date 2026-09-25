from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import asyncio
import logging

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool
from app.config import settings

logger = logging.getLogger("mafia.database")


class Base(DeclarativeBase):
    pass


def _prepare_asyncpg_url(url: str) -> tuple[str, dict]:
    """Neon (and most managed Postgres dashboards) hand you a connection
    string with libpq-style query params — ?sslmode=require&channel_binding=require
    — copy-pasted straight from their UI. asyncpg doesn't understand either
    one: SQLAlchemy forwards unrecognized query params as **kwargs straight
    into asyncpg.connect(), which raises TypeError on "sslmode" and
    "channel_binding" since neither is a real asyncpg parameter (asyncpg
    uses ssl=, not sslmode=). Strip them out of the URL and translate into
    the connect_args asyncpg actually accepts, so a connection string
    pasted in verbatim just works instead of crashing on first connect.

    statement_cache_size=0 is set unconditionally for asyncpg+Postgres:
    it's what lets asyncpg work behind a transaction-mode pooler (Neon's
    pooled endpoint, PgBouncer, Supabase, RDS Proxy, ...) without
    "prepared statement already exists" errors — a small, safe tradeoff
    even against a direct (non-pooled) connection.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break
    if "+asyncpg" not in url or "://" not in url:
        return url, {}
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    connect_args = {"statement_cache_size": 0, "timeout": 20}
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = sslmode
    return cleaned, connect_args


def _pool_kwargs_for(database_url: str) -> dict:
    """Extra create_async_engine() kwargs for a Postgres+asyncpg URL only.

    Neon's free tier suspends its compute endpoint after a few minutes of
    inactivity (this app's own WebSocket-heavy traffic rarely touches the
    database in between games, so that idle window is easy to hit). A
    connection sitting in the pool from before a suspend is dead on the
    wire — the driver doesn't know that until it tries to use it — which
    otherwise surfaces mid-request as "connection was closed in the middle
    of operation". pool_pre_ping pings each pooled connection right before
    handing it out and transparently reconnects if Neon has since
    suspended/resumed; pool_recycle forces a periodic reconnect regardless,
    well under Neon's suspend window, so a connection is never trusted for
    long enough to go stale in the first place. SQLite (tests, local dev)
    has no such server-side suspend concept, so it gets neither.
    """
    if "+asyncpg" not in database_url:
        return {}
    return {"pool_pre_ping": True, "pool_recycle": 180}


_database_url, _connect_args = _prepare_asyncpg_url(settings.database_url)

if "+asyncpg" not in _database_url:
    # No Neon/Postgres DATABASE_URL configured (or it didn't parse as one)
    # — app/config.py's validator already fell back to a local SQLite file
    # instead of crashing the service. That's enough to keep the bot alive
    # and playable without Neon, but it's worth being loud about the
    # tradeoff once, at boot: on Render's free tier specifically, the local
    # disk is NOT persistent — it's wiped on every redeploy and again every
    # time the service spins back up after 15 minutes idle (see
    # https://render.com/docs/free and https://render.com/docs/disks).
    # SQLite here means "works right now, data may vanish later", not a
    # real substitute for Neon for anything you want to keep long-term.
    logger.warning(
        "DATABASE_URL is not a Postgres/Neon connection string — falling back to local "
        "SQLite at %r. The bot will run fine, but on Render's free tier this file does NOT "
        "survive a redeploy or a spin-down/wake cycle, so match history, stats, and settings "
        "saved here can reset unexpectedly. Add a Neon DATABASE_URL in the Render dashboard "
        "(Environment tab) whenever you want that data to actually persist.",
        _database_url,
    )

_engine_kwargs = {"echo": False, "connect_args": _connect_args, **_pool_kwargs_for(_database_url)}
if ":memory:" in settings.database_url:
    # An in-memory SQLite DB only survives on a single shared connection —
    # used for tests; production always points at a real file or Postgres.
    _engine_kwargs["poolclass"] = StaticPool
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(_database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    # Neon's free tier suspends its compute endpoint when idle; the first
    # connect after a suspend can stall for several seconds (or fail) while
    # Neon resumes it. Retry so a cold boot never dies on that transient
    # delay — pool_pre_ping/pool_recycle cover the later, mid-request case.
    last_err: Exception | None = None
    for attempt in range(1, 5):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            return
        except Exception as exc:  # noqa: BLE001 — any connect/DDL error is retryable
            last_err = exc
            logger.warning("init_db attempt %d/4 failed: %s", attempt, exc)
            await asyncio.sleep(5)
    assert last_err is not None
    raise last_err


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
