"""
Personal player profile endpoints — "har bir foydalanuvchining o'z
interfeysi". The Mini App and the bot have always been group-scoped: there
was no way for one player to see their own data, games and stats unless the
bot's reply-keyboard "Statistikam" counted. These routes give the webapp a
per-user surface (opened from the bot's Profil button, or directly with no
group) that shows:

  GET /me/profile — who am I, my lifetime stats, which active matches I'm
                    currently sitting in (across every group), and my most
                    recent finished games.
  GET /me/games   — my full recent game history from GameHistory.

Both are gated by the same verified session token as every other route
(require_telegram_id) and never expose another player's data.
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.dependencies import require_telegram_id
from app.i18n import get_user_language
from app.services.game_service import registry, BOT_GAME_CHAT_PREFIX
from app.models.models import User, GameHistory, KnownGroup
from app.game_engine.state import Phase

router = APIRouter(prefix="/me", tags=["me"])

# Top-level public ranking for the WebApp's "Top / Reyting" screen,
# mirroring the bot's reply-keyboard leaderboard handler.
leaderboard_router = APIRouter(tags=["leaderboard"])

LEADERBOARD_LIMIT = 10


@leaderboard_router.get("/leaderboard")
async def get_leaderboard(limit: int = Query(LEADERBOARD_LIMIT, ge=1, le=50),
                          session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(User)
        .where(User.games_played > 0)
        .order_by(User.wins.desc())
        .limit(limit)
    )
    board = []
    for place, user in enumerate(result.scalars().all(), start=1):
        played = user.games_played or 0
        board.append({
            "place": place,
            "telegram_user_id": user.telegram_user_id,
            "display_name": _display_name(user),
            "username": user.username,
            "wins": user.wins or 0,
            "games_played": played,
            "win_rate": round(100 * (user.wins or 0) / played) if played else 0,
        })
    return {"leaderboard": board, "total": len(board)}

# How many finished games the profile screen's "recent" card shows.
PROFILE_RECENT_LIMIT = 5
# Hard cap on /me/games so one busy player can't pull a gigantic list.
GAMES_PAGE_LIMIT = 50

# botlab:<id> matches are the owner's solo AI practice lobbies — there is no
# Telegram group title behind them, so the profile labels them clearly.


def _display_name(user: User) -> str:
    if user.username:
        return user.username
    parts = [user.first_name, user.last_name or ""]
    return " ".join(p for p in parts if p).strip() or "O'yinchi"


def _group_title(chat_id: Optional[str], known: dict[int, str]) -> str:
    if not chat_id:
        return "O'yin"
    if chat_id.startswith(BOT_GAME_CHAT_PREFIX):
        return "\U0001F916 Botlar bilan mashq"
    try:
        return known.get(int(chat_id), "Guruh")
    except (TypeError, ValueError):
        return "Guruh"


async def _recent_history(session: AsyncSession, user_id: int, limit: int) -> list[dict]:
    result = await session.execute(
        select(GameHistory)
        .where(GameHistory.user_id == user_id)
        .order_by(GameHistory.played_at.desc())
        .limit(limit)
    )
    return [
        {
            "game_id": h.game_id,
            "played_at": h.played_at.isoformat() if h.played_at else None,
            "player_count": h.player_count,
            "role_name": h.role_name,
            "faction": h.faction,
            "won": h.won,
            "kills": h.kills,
            "investigations": h.successful_investigations,
            "protections": h.successful_protections,
        }
        for h in result.scalars().all()
    ]


async def _known_group_titles(session: AsyncSession) -> dict[int, str]:
    result = await session.execute(
        select(KnownGroup).where(KnownGroup.is_active.is_(True))
    )
    return {g.chat_id: g.title for g in result.scalars().all()}


@router.get("/profile")
async def get_profile(telegram_user_id: int = Depends(require_telegram_id),
                      session: AsyncSession = Depends(get_session)):
    user = (await session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Foydalanuvchi topilmadi")

    language = await get_user_language(telegram_user_id)
    played = user.games_played or 0
    win_rate = round(100 * user.wins / played) if played else 0

    # Active matches this player is a member of, across every group. Only
    # live (not GAME_OVER) matches count — a finished one is history.
    titles = await _known_group_titles(session)
    active_games = []
    for engine in registry.all_engines():
        s = engine.state
        if s.phase == Phase.GAME_OVER:
            continue
        player_id = engine.find_player_id(telegram_user_id)
        if player_id is None:
            continue
        active_games.append({
            "game_id": s.game_id,
            "chat_id": s.chat_id,
            "group_title": _group_title(s.chat_id, titles),
            "phase": s.phase.value,
            "night_number": s.night_number,
            "day_number": s.day_number,
            "player_count": len(s.players),
            "alive_count": len(s.alive_players()),
            "player_id": player_id,
        })

    return {
        "user": {
            "telegram_user_id": user.telegram_user_id,
            "display_name": _display_name(user),
            "first_name": user.first_name,
            "username": user.username,
            "photo_url": user.photo_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "language": language,
        },
        "stats": {
            "games_played": played,
            "wins": user.wins or 0,
            "losses": user.losses or 0,
            "win_rate": win_rate,
            "town_wins": user.town_wins or 0,
            "mafia_wins": user.mafia_wins or 0,
            "neutral_wins": user.neutral_wins or 0,
        },
        "active_games": active_games,
        "recent_games": await _recent_history(session, user.id, PROFILE_RECENT_LIMIT),
    }


@router.get("/games")
async def get_my_games(limit: int = Query(20, ge=1, le=GAMES_PAGE_LIMIT),
                        telegram_user_id: int = Depends(require_telegram_id),
                        session: AsyncSession = Depends(get_session)):
    user = (await session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return {
        "games": await _recent_history(session, user.id, limit),
        "total": user.games_played or 0,
    }