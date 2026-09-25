"""
Drives the AI players the bot owner can seat from the admin panel, so a
match can be played through end to end without gathering five other people.

Design notes worth keeping in mind before changing anything here:

* This module never reaches into GameState to set outcomes. It calls the
  exact same public engine methods a real client's WebSocket message would
  (submit_night_action, submit_vote), so bots are bound by every rule real
  players are — target validity, self-target restrictions, silencing,
  charge caps. If a rule changes in the engine, bots inherit it for free
  and there is no second copy of the rules to keep in sync.

* Bots act on a delay rather than instantly. An entire night resolving the
  microsecond it begins would leave the admin staring at a screen that
  flickers between phases with nothing readable on it; the stagger also
  makes the "waiting for players" states actually observable, which is the
  main reason to run a bot game at all.

* The play is deliberately simple, not clever. It exists to exercise the
  state machine, not to be a challenging opponent: mafia avoid killing
  their own, town roles pick someone other than themselves, and everyone
  votes for a random living player. Anything smarter would make failures
  harder to interpret, since you could no longer tell an engine bug from a
  strategy quirk.
"""
from __future__ import annotations

import random
from time import time
from typing import Optional

from app.game_engine.roles import ROLES, ActionType, Faction, RoleName
from app.game_engine.state import GameState, Phase, PlayerState

# Seconds a bot waits, from the moment a phase starts, before acting. Spread
# across a window so they don't all move on the same tick.
MIN_THINK_S = 2.0
MAX_THINK_S = 7.0

# Filler names for seated bots. Ordinary Uzbek first names on purpose: in a
# screenshot or a bug report they should look like the lobby they're
# standing in for, not like BOT_01..BOT_12.
BOT_NAMES = [
    "Alisher", "Dilnoza", "Rustam", "Nigora", "Sanjar", "Kamola",
    "Otabek", "Zilola", "Bekzod", "Madina", "Ulug'bek", "Sevara",
    "Jahongir", "Nodira", "Temur", "Gulnora", "Shohruh", "Feruza",
    "Aziza", "Doniyor", "Malika", "Bobur", "Nasiba", "Islom",
]


def bot_name_for(index: int) -> str:
    """Stable, non-repeating display name for the index-th bot in a lobby."""
    if index < len(BOT_NAMES):
        return BOT_NAMES[index]
    return f"{BOT_NAMES[index % len(BOT_NAMES)]} {index // len(BOT_NAMES) + 1}"


class _Memory:
    """Per-game scratch space: which bots have already acted this phase, and
    how long each intends to wait. Keyed off the engine object rather than
    stored on GameState, because none of it is game truth — losing it on a
    restart just means the bots think again."""

    def __init__(self) -> None:
        self.phase_token: Optional[tuple] = None
        self.delays: dict[str, float] = {}
        self.acted: set[str] = set()

    def reset_for(self, token: tuple, rng: random.Random) -> None:
        self.phase_token = token
        self.delays = {}
        self.acted = set()
        self._rng = rng

    def delay_for(self, player_id: str, rng: random.Random) -> float:
        if player_id not in self.delays:
            self.delays[player_id] = rng.uniform(MIN_THINK_S, MAX_THINK_S)
        return self.delays[player_id]


_memories: dict[str, _Memory] = {}
_rng = random.Random()


def forget_game(game_id: str) -> None:
    _memories.pop(game_id, None)


def _phase_token(state: GameState) -> tuple:
    """Changes whenever the bots should reconsider: a new phase, or a new
    night/day number within the same kind of phase."""
    return (state.phase, state.night_number, state.day_number)


def _elapsed_in_phase(state: GameState) -> float:
    """Seconds since the current phase began. GameState already records a
    server-authoritative phase_start (see TimerManager), so the stagger
    needs no clock of its own."""
    return max(0.0, time() - state.phase_start)


def _living_bots(state: GameState) -> list[PlayerState]:
    return [p for p in state.alive_players() if p.is_bot]


def _pick_night_target(state: GameState, bot: PlayerState) -> Optional[str]:
    """A legal target for this bot's night action, or None (skip) when nothing
    legal is available. The True Mafia 13-role night actions are all
    targetable: KILL (Mafia/Don, Maniac), PROTECT (Doctor), INVESTIGATE/SHOOT
    (Commissioner), BLOCK (Mistress), WATCH (Vagabond)."""
    role_def = ROLES[bot.role]
    action = role_def.night_action
    if action is None:
        return None

    candidates = [p for p in state.alive_players() if p.player_id != bot.player_id]

    if role_def.faction is Faction.MAFIA:
        # Never target a fellow mafioso — an all-mafia crossfire would end
        # most bot games in the first two nights and test nothing.
        candidates = [p for p in candidates if ROLES[p.role].faction is not Faction.MAFIA]
    elif action is ActionType.PROTECT:
        # The Doctor is the one case where targeting yourself is both legal
        # (once per game) and sensible, so let it into the pool when allowed.
        if role_def.can_target_self:
            candidates = candidates + [bot]

    if action is ActionType.KILL and role_def.faction is not Faction.MAFIA:
        # The Maniac is an independent killer and may skip a night now and
        # then; occasionally firing is enough to keep the game moving.
        if _rng.random() < 0.15:
            return None

    if not candidates:
        return None
    return _rng.choice(candidates).player_id


def _act_night(engine) -> bool:
    state = engine.state
    changed = False
    memory = _memories[state.game_id]
    for bot in _living_bots(state):
        if bot.player_id in memory.acted or bot.player_id in state.night_actions:
            continue
        if ROLES[bot.role].night_action is None:
            memory.acted.add(bot.player_id)
            continue
        if _elapsed_in_phase(state) < memory.delay_for(bot.player_id, _rng):
            continue
        role_def = ROLES[bot.role]
        action = role_def.night_action
        override = None
        if bot.role == RoleName.COMMISSIONER and action is ActionType.INVESTIGATE:
            # The single-shot special kill is only worth pulling occasionally;
            # otherwise the Commissioner keeps investigating.
            if bot.commissioner_kills_used == 0 and _rng.random() < 0.2:
                override = "shoot"
                action = ActionType.SHOOT
        target = _pick_night_target(state, bot)
        if action is ActionType.SHOOT and target is None:
            memory.acted.add(bot.player_id)
            continue
        try:
            engine.submit_night_action(bot.player_id, target, action_override=override)
            changed = True
        except Exception:
            # Any rule the engine rejects (a charge cap, a target that died
            # between choosing and submitting) just means this bot sits the
            # night out — never a crash of the ticker that drives every
            # other game on the server.
            pass
        memory.acted.add(bot.player_id)
    return changed


# A handful of neutral, generic discussion lines — deliberately bland and
# game-agnostic (no accusations, no claimed roles) so a bot's chat can
# never leak information the engine wouldn't otherwise reveal, and never
# needs updating just because a role or a strategy changes. One line per
# bot per day is enough to make the discussion feel populated without
# turning bots into something that looks like it's actually reasoning.
BOT_CHAT_LINES = [
    "Kim gumon ostida qoldi?",
    "Menimcha, hali erta xulosa chiqarish.",
    "Kecha nima bo'lganini birga tahlil qilaylik.",
    "Ovoz berishdan oldin yana o'ylab ko'raylik.",
    "Menda hech kimga aniq gumon yo'q hozircha.",
    "Ehtiyot bo'laylik, shoshilinch qaror qabul qilmaylik.",
]


def _act_chat(engine) -> bool:
    state = engine.state
    changed = False
    memory = _memories[state.game_id]
    for bot in _living_bots(state):
        if bot.player_id in memory.acted:
            continue
        if getattr(bot, "silenced", False):
            memory.acted.add(bot.player_id)
            continue
        if _elapsed_in_phase(state) < memory.delay_for(bot.player_id, _rng):
            continue
        try:
            engine.send_chat_message(bot.player_id, _rng.choice(BOT_CHAT_LINES))
            changed = True
        except Exception:
            # Same policy as night actions/votes: a rejected message just
            # means this bot stays quiet today, never a crashed ticker.
            pass
        memory.acted.add(bot.player_id)
    return changed


def _act_vote(engine) -> bool:
    state = engine.state
    changed = False
    memory = _memories[state.game_id]
    for bot in _living_bots(state):
        if bot.player_id in memory.acted or bot.player_id in state.votes:
            continue
        if getattr(bot, "silenced", False):
            memory.acted.add(bot.player_id)
            continue
        if _elapsed_in_phase(state) < memory.delay_for(bot.player_id, _rng):
            continue
        others = [p for p in state.alive_players() if p.player_id != bot.player_id]
        if not others:
            memory.acted.add(bot.player_id)
            continue
        try:
            engine.submit_vote(bot.player_id, _rng.choice(others).player_id)
            changed = True
        except Exception:
            pass
        memory.acted.add(bot.player_id)
    return changed


def _act_lynch_confirm(engine) -> bool:
    """In the LYNCH_CONFIRMATION phase every alive player casts a YES/NO
    ballot; bots just approve the lynch (carry it out)."""
    state = engine.state
    changed = False
    memory = _memories[state.game_id]
    for bot in _living_bots(state):
        if bot.player_id in memory.acted or bot.player_id in getattr(state, "_confirm_voters", set()):
            continue
        if _elapsed_in_phase(state) < memory.delay_for(bot.player_id, _rng):
            continue
        try:
            engine.submit_lynch_confirm(bot.player_id, True)
            changed = True
        except Exception:
            pass
        memory.acted.add(bot.player_id)
    return changed


def _act_kamikaze(engine) -> bool:
    """If a lynched bot was a Kamikaze, they get one window to drag someone
    down with them. The striker is already dead when this runs, so the
    'living bots' pool wouldn't include them — scan all players instead."""
    state = engine.state
    changed = False
    memory = _memories[state.game_id]
    for bot in state.players.values():
        if bot.player_id in memory.acted:
            continue
        if bot.role != RoleName.KAMIKAZE:
            memory.acted.add(bot.player_id)
            continue
        if _elapsed_in_phase(state) < memory.delay_for(bot.player_id, _rng):
            continue
        others = [p for p in state.alive_players() if p.player_id != bot.player_id]
        if not others:
            memory.acted.add(bot.player_id)
            continue
        try:
            engine.submit_kamikaze_target(bot.player_id, _rng.choice(others).player_id)
            changed = True
        except Exception:
            pass
        memory.acted.add(bot.player_id)
    return changed


def drive(engine) -> bool:
    """Give every bot in this match its chance to act for the current phase.
    Returns True if any bot actually did something, so the caller knows to
    push fresh state to the real players watching."""
    state = engine.state
    if state.phase in (Phase.LOBBY, Phase.GAME_OVER):
        return False
    if not any(p.is_bot for p in state.players.values()):
        return False

    memory = _memories.setdefault(state.game_id, _Memory())
    token = _phase_token(state)
    if memory.phase_token != token:
        memory.reset_for(token, _rng)

    if state.phase is Phase.NIGHT:
        return _act_night(engine)
    if state.phase is Phase.VOTING:
        return _act_vote(engine)
    if state.phase is Phase.LYNCH_CONFIRMATION:
        return _act_lynch_confirm(engine)
    if state.phase is Phase.KAMIKAZE_STRIKE:
        return _act_kamikaze(engine)
    if state.phase is Phase.DAY_DISCUSSION:
        return _act_chat(engine)
    return False
