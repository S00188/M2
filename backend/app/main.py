import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.services.game_service import load_global_settings, registry
from app.services.checkpoint_service import load_all_checkpoints
from app.services.notifications import notify_group_on_restart
from app.services import bot_config
from app.database import init_db
from app.api.routes_auth import router as auth_router
from app.api.routes_game import router as game_router
from app.api.routes_admin import router as admin_router
from app.api.routes_admin_platform import router as admin_platform_router
from app.api.routes_me import router as me_router, leaderboard_router
from app.websocket.handlers import router as ws_router, phase_ticker
from app.telegram_bot import router as bot_router, register_webhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mafia")

STATIC_DIR = Path(__file__).parent / "static"


async def _retry_startup(name: str, coro_factory, retries: int = 4, delay: float = 5.0):
    """Run one startup DB step with retries. Neon's free compute endpoint
    suspends when idle; if it happens to be asleep exactly when Render boots
    a new deploy, the first connect can lag or fail and uvicorn otherwise
    exits with status 1 before ever opening a port. Retrying across that
    transient window (each connect is bounded by connect_timeout) keeps a
    cold redeploy from taking the whole service down."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001 — transient connect errors are retryable
            last_err = exc
            logger.warning("%s failed (attempt %d/%d): %s", name, attempt, retries, exc)
            await asyncio.sleep(delay)
    assert last_err is not None
    raise RuntimeError(f"{name} kept failing after {retries} attempts: {last_err}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_deployment()
    await _retry_startup("init_db", init_db)
    # Single source of truth for the bot's texts and buttons (app/services/
    # bot_config.py): seed the defaults on first run and load the cache.
    await _retry_startup("load bot config", bot_config.load_config)
    await _retry_startup("load global settings", load_global_settings)
    # Crash recovery (spec item 3): rebuild any match that was still
    # in-progress the last time the process stopped, from its last
    # checkpoint, before the ticker starts touching it.
    recovered = await _retry_startup("load checkpoints", load_all_checkpoints)
    for engine in recovered:
        registry.register_recovered(engine)
        # Remember where each recovered match is so a restart never
        # re-announces "game started" for a game that started before it.
        await notify_group_on_restart(engine)
    if recovered:
        logger.info("Recovered %d in-progress game(s) from checkpoint", len(recovered))
    ticker_task = asyncio.create_task(phase_ticker())
    broadcast_task = None
    if settings.telegram_webhook_enabled:
        # Only touches the Telegram API (and only constructs a real Bot,
        # which validates its token) when explicitly turned on — see
        # app/telegram_bot.py for why that matters for tests and for
        # deployments that run bot/bot.py's polling process instead.
        await register_webhook()
        from app.services.bot_broadcasts import worker
        broadcast_task = asyncio.create_task(worker())
    else:
        # The #1 reason a freshly deployed bot "does nothing": the webhook
        # is never registered (and nothing is polling), so Telegram never
        # delivers /start, no reply keyboard is ever shown, and the blue
        # Profil Menu button is never set. Surface it in the logs loudly —
        # the service still boots, but the operator must flip the env var.
        logger.error(
            "TELEGRAM_WEBHOOK_ENABLED is not true — the bot will NOT answer "
            "/start or any button, and the Profil Menu button will not be set. "
            "Set TELEGRAM_WEBHOOK_ENABLED=true (and WEBAPP_URL / RENDER_EXTERNAL_URL) "
            "and redeploy."
        )
    try:
        yield
    finally:
        if broadcast_task:
            broadcast_task.cancel()
            with suppress(asyncio.CancelledError):
                await broadcast_task
        ticker_task.cancel()
        with suppress(asyncio.CancelledError):
            await ticker_task


app = FastAPI(title="Mafia Mini App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces to clients (spec section 29).
    logger.exception("Unhandled error on %s", request.url)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})


app.include_router(auth_router)
app.include_router(game_router)
app.include_router(admin_router)
app.include_router(admin_platform_router)
app.include_router(me_router)
app.include_router(leaderboard_router)
app.include_router(ws_router)
app.include_router(bot_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# The Telegram Mini App itself. Everything under /static/* (app.js, and any
# future split-out assets) is served as plain files; "/" serves the shell
# so opening the bot's web_app URL with no path works with zero server-side
# templating — app.js does the rest once the browser has it.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def serve_app():
    return FileResponse(STATIC_DIR / "index.html")
