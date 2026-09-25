import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.database import _prepare_asyncpg_url
from app.game_engine.engine import GameEngine
from app.game_engine.persistence import state_from_dict, state_to_dict
from app.game_engine.roles import RoleName, Faction
from app.game_engine.state import Phase, WinResult
from app.services.game_service import GameRegistry
from app.services import notifications as n


def match():
    engine = GameEngine("v7", 1, "<Ali & Vali>", chat_id="-100")
    engine.state.players[engine.state.host_id].role = RoleName.CITIZEN
    engine.state.phase = Phase.ROLE_ASSIGNMENT
    return engine


@pytest.fixture
def sender(monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(n, "send_telegram_message", send)
    monkeypatch.setattr("app.services.checkpoint_service.save_checkpoint", AsyncMock())
    n.forget_game("v7")
    return send


def test_duplicate_group_blocked_until_finished():
    reg = GameRegistry()
    first = reg.create(1, "Ali", "-100")
    for phase in (Phase.LOBBY, Phase.NIGHT, Phase.VOTING):
        first.state.phase = phase
        with pytest.raises(ValueError):
            reg.create(2, "Vali", "-100")
        assert reg.get_or_create_for_chat("-100", 2, "Vali") == (first, False)
    first.state.phase = Phase.GAME_OVER
    assert reg.create(2, "Vali", "-100") is not first


@pytest.mark.asyncio
async def test_start_first_observation_private_and_concurrent(sender):
    engine = match()
    await asyncio.gather(*(n.notify_group_if_phase_changed(engine) for _ in range(5)))
    sender.assert_awaited_once()
    text = sender.call_args.args[1]
    assert "Tinch aholi — 1" in text
    assert "Ali" not in text
    restored = GameEngine.from_state(state_from_dict(state_to_dict(engine.state)))
    await n.notify_group_on_restart(restored)
    await n.notify_group_if_phase_changed(restored)
    sender.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_send_retried(sender):
    sender.side_effect = [False, True]
    engine = match()
    await n.notify_group_if_phase_changed(engine)
    assert not engine.state.group_start_announced
    n._retry_after.clear()
    await n.notify_group_if_phase_changed(engine)
    assert engine.state.group_start_announced
    assert sender.await_count == 2


@pytest.mark.asyncio
async def test_end_escaped_and_individual_winner(sender):
    engine = match()
    engine.state.phase = Phase.GAME_OVER
    engine.state.winner = WinResult(faction=Faction.TOWN, winners=[],
        individual_winners=[engine.state.host_id], reason="test")
    await n.notify_group_if_phase_changed(engine)
    await n.notify_group_if_phase_changed(engine)
    sender.assert_awaited_once()
    text = sender.call_args.args[1]
    assert "🏆 &lt;Ali &amp; Vali&gt;" in text
    assert "Tinch aholi" in text and "/start" in text


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_pasted_postgres_url(scheme):
    url, args = _prepare_asyncpg_url(f"{scheme}://user:pw@host/db?sslmode=require")
    assert url == "postgresql+asyncpg://user:pw@host/db"
    assert args["ssl"] == "require"


def test_production_rejects_default_secrets():
    # DATABASE_URL is intentionally not in this list any more — a missing
    # Neon/Postgres URL now falls back to local SQLite instead of crashing
    # the service (see test_production_without_database_url_falls_back_to_sqlite
    # below). SESSION_SECRET and TELEGRAM_BOT_TOKEN still block startup:
    # there's no safe fallback for either of those.
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(_env_file=None, environment="production").validate_deployment()


def test_production_without_database_url_falls_back_to_sqlite():
    """The #1 cause of a freshly-deployed bot going totally silent used to
    be this: production mode required a Postgres DATABASE_URL and raised
    ValueError at boot if Neon wasn't set up yet, so the service never
    opened a port, the webhook never got registered, and /start (and the
    reply keyboard) got zero response. Now a missing/blank DATABASE_URL
    quietly becomes local SQLite and startup succeeds."""
    s = Settings(
        _env_file=None,
        environment="production",
        session_secret="x" * 40,
        telegram_bot_token="123456:real-looking-token",
    )
    assert s.database_url == "sqlite+aiosqlite:///./mafia.db"
    s.validate_deployment()  # must not raise


def test_blank_database_url_env_falls_back_to_sqlite():
    """Render's dashboard sends DATABASE_URL="" (not an unset var) when the
    field is left blank, which would otherwise override the sqlite default
    with an empty string and break create_async_engine(\"\")."""
    s = Settings(_env_file=None, database_url="")
    assert s.database_url == "sqlite+aiosqlite:///./mafia.db"


@pytest.mark.asyncio
async def test_add_admin_link(monkeypatch):
    from app import telegram_bot as bot
    monkeypatch.setattr(bot, "get_bot_username", AsyncMock(return_value="sample_bot"))
    send = AsyncMock()
    monkeypatch.setattr(bot, "_edit_or_send", send)
    await bot.on_add_group(SimpleNamespace(chat=SimpleNamespace(id=123)))
    button = send.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.url == "https://t.me/sample_bot?startgroup=mafia&admin=manage_chat"


@pytest.mark.asyncio
async def test_profile_opens_home(monkeypatch):
    from app import telegram_bot as bot
    monkeypatch.setattr(bot, "get_user_language", AsyncMock(return_value="uz"))
    monkeypatch.setattr(bot, "webapp_base_url", lambda: "https://example.test")
    send = AsyncMock()
    monkeypatch.setattr(bot, "_edit_or_send", send)
    await bot.on_profile_button(SimpleNamespace(chat=SimpleNamespace(id=123), from_user=SimpleNamespace(id=123)))
    url = send.call_args.kwargs["reply_markup"].inline_keyboard[0][0].web_app.url
    assert "?view=home&lang=uz" in url
