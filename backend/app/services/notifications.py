"""Best-effort Telegram-group notifications about a match's lifecycle.

The group join button (post_join_button) tells everyone the lobby exists;
these two announcements tell the group what actually happened without ever
leaking who holds which role. Both are deliberately vague — a game started /
a game ended with the winning faction — exactly the public information the
final role reveal shares anyway.

Sending is fire-and-forget and fails silently (see
app/services/telegram_bot_api.py's send_telegram_message): a bot that can't
reach Telegram (bad token, removed from the group, network hiccup) must
never slow down or crash a running game. Tests monkeypatch the send helper
to stay offline.

_state_phase remembers each game's last seen phase so the announcement fires
exactly once per transition, whether the change was noticed by the WebSocket
handler or the background phase ticker first — whichever call sees the
transition wins, and the other is a no-op.
"""
from __future__ import annotations
import asyncio
from collections import Counter
from html import escape
from time import monotonic

from app.game_engine.state import Phase
from app.services.game_service import BOT_GAME_CHAT_PREFIX
from app.services.telegram_bot_api import send_telegram_message

# game_id -> last phase value this process has announced/observed.
_state_phase: dict[str, str] = {}
_locks: dict[str, asyncio.Lock] = {}
_retry_after: dict[str, float] = {}
ROLE_LABELS = {
    "Citizen": "Tinch aholi", "Commissioner": "Komissar",
    "Sergeant": "Serjant", "Doctor": "Doktor", "Lucky": "Omadli",
    "Kamikaze": "Qasoskor", "Don": "Don", "Mafia": "Mafia",
    "Maniac": "Yakka o‘yinchi", "Mistress": "Xonim", "Lawyer": "Advokat",
    "Suicide": "Ayyor", "Vagabond": "Sayyoh",
}


def role_label(player) -> str:
    value = player.role.value if player.role else "?"
    return ROLE_LABELS.get(value, value)


def start_message(state) -> str:
    counts = Counter(role_label(p) for p in state.players.values())
    return "<b>Tarqatilgan rollar</b>\n" + "\n".join(
        f"• {escape(role)} — {count}" for role, count in sorted(counts.items())
    )


def end_message(state) -> str:
    winner = state.winner
    faction = winner.faction.value if winner.faction else None
    label = FACTION_LABELS.get(faction, "Yakka g‘alaba" if winner.winners else "Durang")
    winners = set(winner.winners + winner.individual_winners)
    lines = ["🏆 <b>O‘yin tugadi!</b>", f"Natija: <b>{label}</b>",
             f"👥 Ishtirokchilar: {len(state.players)} · Kun: {state.day_number}", ""]
    for pid, player in state.players.items():
        badge = "🏆" if pid in winners else "•"
        lines.append(f"{badge} {escape(player.display_name[:40])} — {escape(role_label(player))}")
    lines.extend(["", "Yangi o‘yin uchun /start"])
    return "\n".join(lines)

# game_id -> player_id -> how many of that player's state.outcome_messages
# this process has already sent as a personal Telegram DM. outcome_messages
# only ever grows (see GameState.outcome_messages), so "already sent" is
# just a count, and this function is safe to call as often as we like —
# exactly like _state_phase above for the group announcements.
_sent_message_counts: dict[str, dict[str, int]] = {}

# Public, language-neutral faction label for the group announcement. The
# group already has a dedicated join message; this read-out is the same
# single-message-shared-by-everyone scope, so Uzbek is the consistent choice.
FACTION_LABELS = {
    "mafia": "Mafia",
    "town": "Shahar",
    "neutral": "Neytral",
}


def remember_phase(game_id: str, phase: Phase) -> str | None:
    """Records the current phase for `game_id` and returns the previous one
    (or None on the first observation, e.g. after a server restart)."""
    previous = _state_phase.get(game_id)
    _state_phase[game_id] = phase.value
    return previous


def forget_game(game_id: str) -> None:
    _state_phase.pop(game_id, None)
    _sent_message_counts.pop(game_id, None)
    _locks.pop(game_id, None)
    _retry_after.pop(game_id, None)


async def notify_group_if_phase_changed(engine) -> None:
    """Announces the public game-start / game-over moments to the group
    bound to this engine. Individual player transitions are never routed
    here — only the two points the whole group cares about."""
    state = engine.state
    if not state.chat_id or state.chat_id.startswith(BOT_GAME_CHAT_PREFIX):
        return
    remember_phase(state.game_id, state.phase)
    async with _locks.setdefault(state.game_id, asyncio.Lock()):
        if monotonic() < _retry_after.get(state.game_id, 0):
            return
        flag = None
        if state.phase == Phase.GAME_OVER and state.winner and not state.group_end_announced:
            flag, text = "group_end_announced", end_message(state)
        elif state.phase != Phase.GAME_OVER and not state.group_start_announced and (
            state.phase == Phase.ROLE_ASSIGNMENT or any(p.role for p in state.players.values())
        ):
            flag, text = "group_start_announced", start_message(state)
        if flag:
            if await send_telegram_message(state.chat_id, text):
                setattr(state, flag, True)
                _retry_after.pop(state.game_id, None)
                from app.services.checkpoint_service import save_checkpoint
                await save_checkpoint(engine)
            else:
                _retry_after[state.game_id] = monotonic() + 30


async def notify_players_outcome_messages(engine) -> None:
    """Sends each real player, as a private Telegram message, any lines in
    their state.outcome_messages this process hasn't already sent for this
    game — Doctor saves, Mistress blocks, Commissioner reads, Mafia/Maniac
    kills, Lucky saves, Vagabond reports, the Sergeant's promotion, the
    Suicide's win, the Kamikaze's last strike, and so on (see
    app/game_engine/night_messages.py for the night-resolution half of this
    and app/game_engine/managers.py / engine.py for the day-phase half).

    Called after every state-changing WebSocket message and every ticker
    tick (like notify_group_if_phase_changed above), so it must be — and
    is — safe to call repeatedly without re-sending anything: it only ever
    sends the delta past what it already sent this process. Bot players are
    skipped; they have no real Telegram chat."""
    state = engine.state
    sent = _sent_message_counts.setdefault(state.game_id, {})
    for player_id, lines in state.outcome_messages.items():
        already_sent = sent.get(player_id, 0)
        new_lines = lines[already_sent:]
        if not new_lines:
            continue
        player = state.players.get(player_id)
        if not player or player.is_bot:
            sent[player_id] = len(lines)
            continue
        for line in new_lines:
            await send_telegram_message(player.telegram_user_id, line)
        sent[player_id] = len(lines)


async def notify_group_on_restart(engine) -> None:
    """Called once per engine recovered from a checkpoint at startup (see
    app/main.py's lifespan): seeds _state_phase so the ticker keeps the game
    moving without suddenly announcing "game started" for a match that began
    before the restart."""
    state = engine.state
    if state.phase != Phase.GAME_OVER:
        remember_phase(state.game_id, state.phase)
