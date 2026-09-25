"""
Holds all currently-running games in memory (fast, simple, correct as long
as the server process doesn't restart mid-game — see README for the
persistence roadmap) and persists a summary to the database when a game
finishes, for history/statistics screens.

This is the seam the WebSocket layer and REST routes both call through —
neither ever touches a GameEngine's internal GameState directly.
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import json
from dataclasses import asdict, fields

from app.game_engine.engine import GameEngine
from app.game_engine.roles import ROLES
from app.game_engine.state import Phase, GameSettings
from app.models.models import User, Game, GamePlayer, GameHistory, BotSetting
from app.utils.helpers import new_game_code

# Where the bot owner's *global* defaults live in bot_settings. These are
# not per-match: they're the settings every new match is created with, so
# the owner configures the game once instead of re-tuning every lobby.
GLOBAL_SETTINGS_KEY = "global_game_settings"

# Marks a practice match seated with AI players instead of a real Telegram
# group. Games created from the admin panel carry this as their chat_id, and
# /games/for-chat keys off it to skip the group-membership check (for bot
# admins only) — there is no group to be a member of.
BOT_GAME_CHAT_PREFIX = "botlab:"


class GameRegistry:
    def __init__(self) -> None:
        self._games: dict[str, GameEngine] = {}
        # In-memory mirror of the persisted global defaults. create() is a
        # synchronous call reached from request handlers and from the phase
        # ticker, so it can't await a database read; the row is loaded once
        # at startup (load_global_settings) and re-cached whenever the admin
        # saves, which keeps the hot path free of I/O.
        self._defaults: dict = {}

    @property
    def defaults(self) -> dict:
        return dict(self._defaults)

    def set_defaults(self, values: dict) -> None:
        self._defaults = dict(values)

    def build_settings(self) -> GameSettings:
        """A fresh GameSettings pre-filled with the owner's global defaults.
        Unknown or removed keys in the stored blob are ignored rather than
        raising, so an old row from a previous version can't break game
        creation — the dataclass default just wins for that field."""
        allowed = {f.name for f in fields(GameSettings)}
        return GameSettings(**{k: v for k, v in self._defaults.items() if k in allowed})

    def create(self, host_telegram_id: int, host_name: str, chat_id: Optional[str] = None,
                host_avatar_url: Optional[str] = None) -> GameEngine:
        if chat_id and self.get_by_chat(str(chat_id)):
            raise ValueError("Bu guruhda o'yin davom etmoqda.")
        game_id = new_game_code()
        while game_id in self._games:
            game_id = new_game_code()
        engine = GameEngine(game_id=game_id, host_telegram_id=host_telegram_id,
                             host_name=host_name, chat_id=chat_id,
                             host_avatar_url=host_avatar_url,
                             settings=self.build_settings())
        self._games[game_id] = engine
        return engine

    def get(self, game_id: str) -> GameEngine:
        engine = self._games.get(game_id)
        if not engine:
            raise KeyError("Game no longer exists")
        return engine

    def get_by_chat(self, chat_id: str) -> Optional[GameEngine]:
        """The one active (not finished) match bound to this Telegram group,
        if any. A group gets a fresh match once the previous one reaches
        GAME_OVER — this never returns a finished game."""
        for engine in self._games.values():
            if engine.state.chat_id == chat_id and engine.state.phase != Phase.GAME_OVER:
                return engine
        return None

    def get_or_create_for_chat(self, chat_id: str, host_telegram_id: int,
                                host_name: str,
                                host_avatar_url: Optional[str] = None) -> tuple[GameEngine, bool]:
        """Idempotent entry point for the 'tap the bot's button in the group'
        flow: no user ever calls create_game directly. Returns (engine, created)."""
        existing = self.get_by_chat(chat_id)
        if existing:
            return existing, False
        return self.create(host_telegram_id, host_name, chat_id, host_avatar_url), True

    def remove(self, game_id: str) -> None:
        self._games.pop(game_id, None)

    def register_recovered(self, engine: GameEngine) -> None:
        """Re-inserts an engine rebuilt from a checkpoint (spec item 3,
        see app/services/checkpoint_service.load_all_checkpoints and
        app/main.py's startup) directly under its own game_id, bypassing
        create()'s fresh-lobby setup entirely — it already has real
        players, roles, and phase state from before the restart."""
        self._games[engine.state.game_id] = engine

    def all_engines(self) -> list[GameEngine]:
        return list(self._games.values())


registry = GameRegistry()


async def load_global_settings() -> dict:
    """Reads the owner's global defaults out of bot_settings and primes the
    registry cache. Called once from the app's startup lifespan; a missing
    or corrupt row is treated as "no overrides" so a bad value can never
    stop the service from booting."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        row = await session.get(BotSetting, GLOBAL_SETTINGS_KEY)
        try:
            values = json.loads(row.value) if row and row.value else {}
        except (ValueError, TypeError):
            values = {}
    if not isinstance(values, dict):
        values = {}
    registry.set_defaults(values)
    return values


async def save_global_settings(session: AsyncSession, values: dict) -> dict:
    """Persists the merged global defaults and updates the registry cache
    in the same call, so the next match created picks them up immediately
    without waiting for a restart."""
    merged = registry.defaults
    merged.update(values)
    row = await session.get(BotSetting, GLOBAL_SETTINGS_KEY)
    if row is None:
        session.add(BotSetting(key=GLOBAL_SETTINGS_KEY, value=json.dumps(merged)))
    else:
        row.value = json.dumps(merged)
    await session.commit()
    registry.set_defaults(merged)
    return merged


def effective_global_settings() -> dict:
    """The full picture the admin panel renders: every GameSettings field,
    showing the owner's override where one exists and the built-in default
    everywhere else."""
    return asdict(registry.build_settings())


async def get_or_create_user(session: AsyncSession, telegram_user_id: int, first_name: str,
                              last_name: Optional[str], username: Optional[str],
                              photo_url: Optional[str]) -> User:
    result = await session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_user_id=telegram_user_id, first_name=first_name,
                     last_name=last_name, username=username, photo_url=photo_url)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    # Telegram's photo_url is a short-lived CDN link and a user can rename
    # themselves at any time, so a row created weeks ago would otherwise
    # keep serving a dead avatar URL to the lobby forever. Refresh the
    # profile fields on every login, but only when something actually
    # changed (avoids a write on every single auth call).
    changed = False
    for field, value in (("first_name", first_name), ("last_name", last_name),
                          ("username", username), ("photo_url", photo_url)):
        if value is not None and getattr(user, field) != value:
            setattr(user, field, value)
            changed = True
    if changed:
        await session.commit()
        await session.refresh(user)
    return user


async def persist_finished_game(session: AsyncSession, engine: GameEngine) -> None:
    """Writes this game's Game/GamePlayer/GameHistory rows and bumps user
    stats. Meant to run exactly once per finished game, right after
    WinConditionManager produces a result — but the WebSocket loop calls
    this after *every* message received while the game is already in
    GAME_OVER (see app/websocket/handlers.py), not just the one that
    triggered it, and the background phase_ticker can independently reach
    the same call. Without a guard, a stray post-game message (or a race
    between the two callers) would insert a second full set of rows and
    double-count that game in every player's win/loss stats.

    Two layers of protection, cheapest first:
      1. `state.finished_persisted` — an in-memory flag so every call
         after the first is a no-op with no DB round trip at all.
      2. A `Game.game_id` existence check — covers the process having more
         than one path reach here before the flag was set (e.g. the
         WebSocket handler and phase_ticker both observing GAME_OVER on
         the same tick), and doubles as a safety net in general rather
         than trusting the in-memory flag alone.
    Neither replaces the other: (1) is what makes the common case cheap,
    (2) is what makes the guarantee actually hold.
    """
    state = engine.state
    if state.finished_persisted:
        return
    existing = await session.execute(select(Game).where(Game.game_id == state.game_id))
    if existing.scalar_one_or_none() is not None:
        state.finished_persisted = True
        return
    game_row = Game(
        game_id=state.game_id, chat_id=state.chat_id,
        host_telegram_id=state.players[state.host_id].telegram_user_id,
        mode=state.settings.mode, phase=state.phase.value,
        player_count=len(state.players),
        winner_faction=state.winner.faction.value if state.winner and state.winner.faction else "draw",
    )
    session.add(game_row)
    await session.flush()

    for pid, p in state.players.items():
        result = await session.execute(select(User).where(User.telegram_user_id == p.telegram_user_id))
        user = result.scalar_one_or_none()
        if not user:
            continue
        won = bool(state.winner and (pid in state.winner.winners
                                      or pid in state.winner.individual_winners))
        session.add(GamePlayer(
            game_id=game_row.id, user_id=user.id, role_name=p.role.value if p.role else None,
            is_host=p.is_host, alive=p.alive, death_reason=p.death_reason,
            death_night=p.death_night, survived_to_end=p.alive,
        ))
        session.add(GameHistory(
            game_id=state.game_id, user_id=user.id, player_count=len(state.players),
            role_name=p.role.value if p.role else "?",
            faction=ROLES[p.role].faction.value if p.role else "?",
            won=won,
        ))
        user.games_played += 1
        if won:
            user.wins += 1
            if state.winner.faction:
                setattr(user, f"{state.winner.faction.value}_wins",
                        getattr(user, f"{state.winner.faction.value}_wins") + 1)
        else:
            user.losses += 1
    await session.commit()
    state.finished_persisted = True
