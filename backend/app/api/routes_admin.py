"""
The bot owner's global admin panel — deliberately separate from any single
match's host_id. Every route here is gated by require_bot_admin (checked
against settings.admin_telegram_ids), not by being "in" a particular game
at all, so the bot owner can see and manage every currently-running match
across every Telegram group, plus aggregate stats, without ever having
joined any of them as a player.

The state-mutating endpoints are thin wrappers around the same GameEngine
methods the per-match host's WebSocket messages already call
(app/websocket/handlers.py) — they pass host_id=None, which
_require_host_or_system treats as "already authorized upstream".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.dependencies import require_bot_admin
from app.config import settings as app_settings
from app.game_engine.bot_players import bot_name_for
from app.services.game_service import (
    registry,
    BOT_GAME_CHAT_PREFIX,
)
from app.services.telegram_bot_api import send_admin_message, bot_deep_link
from app.game_engine.engine import EngineError
from app.websocket.manager import manager


router = APIRouter(prefix="/admin", tags=["admin"])


class SettingsUpdateRequest(BaseModel):
    settings: dict


class ExtendTimerRequest(BaseModel):
    seconds: int = 30


# NOTE: this router used to expose a /global-settings editor (night/day/
# voting duration, tie_rule, role-composition toggles) here. That's the
# "O'yin sozlamalari" surface the unified admin spec explicitly forbids
# re-adding to the admin panel, and the frontend never called it — removed
# outright rather than migrated. Game timing still has a single source of
# truth (app.services.game_service.load_global_settings, read at startup);
# there just isn't an HTTP editor for it anymore.


class BotGameRequest(BaseModel):
    bot_count: int = 5


@router.post("/bot-game")
async def create_bot_game(body: BotGameRequest, telegram_user_id: int = Depends(require_bot_admin)):
    """Spins up a practice match seated with AI players, so the owner can
    walk the whole night/day/vote loop alone instead of rounding up other
    people. The owner is the host and the only human: bot_count is how many
    seats the AI fills *besides* them, so 3 bots is the smallest startable
    game (4 players) and 19 is the largest (20 players)."""
    if not 3 <= body.bot_count <= 19:
        raise HTTPException(400, "Botlar soni 3 va 19 orasida bo'lishi kerak (jami 4-20 o'yinchi)")

    # A synthetic chat_id, not a real Telegram group. /games/for-chat
    # recognises this prefix and skips the group-membership check for bot
    # admins only — see the comment there for why that's safe.
    chat_id = f"{BOT_GAME_CHAT_PREFIX}{telegram_user_id}"

    # One practice game per owner at a time: a second click replaces the
    # old one rather than piling up abandoned lobbies in memory.
    existing = registry.get_by_chat(chat_id)
    if existing:
        registry.remove(existing.state.game_id)

    engine, _ = registry.get_or_create_for_chat(chat_id, telegram_user_id, "Admin")
    for i in range(body.bot_count):
        engine.add_bot_player(bot_name_for(i))

    link = await bot_deep_link(chat_id)
    if link:
        await send_admin_message(
            telegram_user_id,
            "\U0001F916 <b>Botlar bilan o'yin tayyor</b>\n\n"
            f"Botlar soni: <b>{body.bot_count}</b>\n"
            f"Jami o'yinchilar: <b>{body.bot_count + 1}</b>\n\n"
            "Quyidagi havola orqali kiring va \"O'yinni boshlash\" tugmasini bosing.",
            button_text="\U0001F3AD O'yinga kirish",
            button_url=link,
        )

    return {
        "ok": True,
        "game_id": engine.state.game_id,
        "chat_id": chat_id,
        "bot_count": body.bot_count,
        "player_count": len(engine.state.players),
        "link": link,
        "link_sent": bool(link),
    }


@router.get("/games")
async def list_active_games(_: int = Depends(require_bot_admin)):
    """Every currently in-memory match, across every Telegram group —
    the bot owner's entry point when they don't already know which
    game_id they're looking for."""
    games = []
    for engine in registry.all_engines():
        s = engine.state
        games.append({
            "game_id": s.game_id,
            "chat_id": s.chat_id,
            "phase": s.phase.value,
            "player_count": len(s.players),
            "alive_count": len(s.alive_players()),
            "night_number": s.night_number,
            "day_number": s.day_number,
            "host_display_name": s.players[s.host_id].display_name if s.host_id in s.players else None,
        })
    return {"games": games}


@router.get("/games/{game_id}")
async def get_game_admin_detail(game_id: str, _: int = Depends(require_bot_admin)):
    """Everything about one match, including real roles for every
    player — the one place in the whole app allowed to show that,
    because this is the bot owner, not a player in the game."""
    try:
        engine = registry.get(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")
    s = engine.state
    return {
        "game_id": s.game_id,
        "chat_id": s.chat_id,
        "phase": s.phase.value,
        "night_number": s.night_number,
        "day_number": s.day_number,
        "phase_ends_in": engine.get_player_view(s.host_id)["phase_ends_in"],
        "host_id": s.host_id,
        "settings": {
            "night_duration_s": s.settings.night_duration_s,
            "day_duration_s": s.settings.day_duration_s,
            "voting_duration_s": s.settings.voting_duration_s,
            "tie_rule": s.settings.tie_rule,
            "anonymous_voting": s.settings.anonymous_voting,
            "allow_self_vote": s.settings.allow_self_vote,
            "reveal_role_on_death": s.settings.reveal_role_on_death,
        },
        "players": [
            {
                "player_id": p.player_id, "display_name": p.display_name,
                "alive": p.alive, "is_host": p.is_host, "connected": p.connected,
                "role": p.role.value if p.role else None,
            }
            for p in s.players.values()
        ],
    }


@router.post("/games/{game_id}/settings")
async def admin_update_game_settings(game_id: str, body: SettingsUpdateRequest,
                                      _: int = Depends(require_bot_admin)):
    engine = _get_engine_or_404(game_id)
    try:
        engine.update_settings(None, body.settings)
    except EngineError as e:
        raise HTTPException(400, str(e))
    await manager.broadcast_state(game_id, engine)
    return {"ok": True}


@router.post("/games/{game_id}/force-advance")
async def admin_force_advance(game_id: str, _: int = Depends(require_bot_admin)):
    engine = _get_engine_or_404(game_id)
    try:
        advanced = engine.force_advance_phase(None)
    except EngineError as e:
        raise HTTPException(400, str(e))
    await manager.broadcast_state(game_id, engine)
    return {"ok": True, "advanced": advanced}


@router.post("/games/{game_id}/extend-timer")
async def admin_extend_timer(game_id: str, body: ExtendTimerRequest, _: int = Depends(require_bot_admin)):
    engine = _get_engine_or_404(game_id)
    try:
        engine.extend_current_phase(None, body.seconds)
    except EngineError as e:
        raise HTTPException(400, str(e))
    await manager.broadcast_state(game_id, engine)
    return {"ok": True}


@router.post("/games/{game_id}/remove/{target_id}")
async def admin_remove_player_route(game_id: str, target_id: str, _: int = Depends(require_bot_admin)):
    engine = _get_engine_or_404(game_id)
    try:
        engine.admin_remove_player(None, target_id)
    except EngineError as e:
        raise HTTPException(400, str(e))
    await manager.broadcast_state(game_id, engine)
    return {"ok": True}


@router.post("/games/{game_id}/terminate")
async def admin_terminate_game(game_id: str, _: int = Depends(require_bot_admin)):
    """Drops a stuck/abandoned match entirely — the one action here with
    no per-match-host equivalent, since a host removing their own game
    isn't a thing a normal player action ever needs to do."""
    _get_engine_or_404(game_id)
    registry.remove(game_id)
    return {"ok": True}


# NOTE: this router used to also have /stats and /top-players — both are
# a strict subset of the unified /admin/statistics endpoint (see
# routes_admin_platform.py's admin_statistics), which the WebApp panel
# already calls exclusively. Removed rather than kept as a second path to
# the same numbers.


def _get_engine_or_404(game_id: str):
    try:
        return registry.get(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")
