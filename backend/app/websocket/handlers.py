from __future__ import annotations
import asyncio
import json
import logging
from collections import deque
from time import monotonic
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.utils.helpers import verify_session_token, TokenError
from app.game_engine.bot_players import drive as drive_bots, forget_game
from app.services.game_service import registry, persist_finished_game
from app.services.checkpoint_service import save_checkpoint
from app.services.notifications import (
    notify_group_if_phase_changed, notify_players_outcome_messages,
    forget_game as forget_announced_game,
)
from app.game_engine.engine import EngineError
from app.game_engine.state import Phase
from app.websocket.manager import manager

router = APIRouter()
logger = logging.getLogger("mafia.ws")

# A finished (GAME_OVER) match stays in the in-memory registry for a while
# so a player can still open it (last words, the final role reveal, their
# stats screen) — but not forever. This period is how long it lingers after
# its game-over stats were persisted before the ticker drops it.
FINISHED_GAME_GRACE_S = 10 * 60
_finished_at: dict[str, float] = {}


@router.websocket("/ws/games/{game_id}")
async def game_websocket(websocket: WebSocket, game_id: str, token: str = Query(...)):
    try:
        telegram_user_id = verify_session_token(token, settings.session_secret)
    except TokenError:
        await websocket.close(code=4401)
        return
    from app.services.access_control import is_blocked, require_subscription
    from fastapi import HTTPException
    if await is_blocked(telegram_user_id):
        await websocket.close(code=4403)
        return
    try:
        await require_subscription(telegram_user_id)
    except HTTPException:
        await websocket.close(code=4403)
        return

    try:
        engine = registry.get(game_id)
    except KeyError:
        await websocket.close(code=4404)
        return

    player_id = engine.find_player_id(telegram_user_id)
    if not player_id:
        await websocket.close(code=4403)
        return

    await manager.connect(game_id, player_id, websocket)
    engine.state.players[player_id].connected = True
    recent_messages = deque()
    try:
        await manager.broadcast_state(game_id, engine)
        while True:
            raw = await websocket.receive_text()
            if await is_blocked(telegram_user_id):
                await websocket.close(code=4403)
                break
            if not manager.is_current(game_id, player_id, websocket):
                break
            if len(raw) > 8192:
                await websocket.close(code=1009)
                break
            now = monotonic()
            while recent_messages and now - recent_messages[0] >= 10:
                recent_messages.popleft()
            if len(recent_messages) >= 40:
                await websocket.close(code=4429)
                break
            recent_messages.append(now)
            try:
                msg = json.loads(raw)
            except (ValueError, RecursionError):
                await manager.send_personal(game_id, player_id, {"type": "error", "message": "Invalid JSON"})
                continue
            await _handle_message(game_id, engine, player_id, msg)
            await manager.broadcast_state(game_id, engine)
            await notify_group_if_phase_changed(engine)
            await notify_players_outcome_messages(engine)
            if engine.state.phase == Phase.GAME_OVER:
                async with AsyncSessionLocal() as session:
                    await persist_finished_game(session, engine)
            await save_checkpoint(engine)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket failed for game=%s player=%s", game_id, player_id)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if manager.disconnect(game_id, player_id, websocket):
            player = engine.state.players.get(player_id)
            if player:
                player.connected = False
            await manager.broadcast_state(game_id, engine)


async def _handle_message(game_id: str, engine, player_id: str, msg: dict) -> None:
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        await manager.send_personal(game_id, player_id, {"type": "error", "message": "Invalid message"})
        return
    for field in ("target_id", "action_override", "role", "text"):
        if field in msg and msg[field] is not None and not isinstance(msg[field], str):
            await manager.send_personal(game_id, player_id, {"type": "error", "message": "Invalid field: " + field})
            return
    for field in ("ready", "yes"):
        if field in msg and not isinstance(msg[field], bool):
            await manager.send_personal(game_id, player_id, {"type": "error", "message": "Invalid field: " + field})
            return
    if msg.get("text", "") is None:
        msg["text"] = ""
    msg_type = msg.get("type")
    try:
        if msg_type == "night_action":
            engine.submit_night_action(player_id, msg.get("target_id"),
                                       action_override=msg.get("action_override"))
            engine.resolve_night_if_ready()
        elif msg_type == "ready_for_vote":
            # Replaces the old unrestricted "advance_to_voting" message
            # (spec item 1): a single player can only mark themselves
            # ready, never force everyone into voting on their own.
            engine.set_ready_for_vote(player_id, msg.get("ready", True))
            engine.advance_to_voting_if_ready()
        elif msg_type == "vote":
            engine.submit_vote(player_id, msg.get("target_id"))
            engine.resolve_voting_if_ready()
        elif msg_type == "lynch_confirm":
            engine.submit_lynch_confirm(player_id, bool(msg.get("yes", False)))
            engine.resolve_lynch_confirmation_if_ready()
        elif msg_type == "kamikaze_target":
            engine.submit_kamikaze_target(player_id, msg.get("target_id"))
            engine.resolve_kamikaze_strike_if_ready()
        elif msg_type == "start_next_night":
            if not engine.start_next_night_if_ready():
                raise EngineError("Natijalar vaqti tugashini kuting")
        elif msg_type == "last_words":
            engine.submit_last_words(player_id, msg.get("text", ""))
        elif msg_type == "chat_message":
            engine.send_chat_message(player_id, msg.get("text", ""))
        elif msg_type == "mafia_chat_message":
            engine.send_mafia_chat_message(player_id, msg.get("text", ""))
        elif msg_type == "start_game":
            engine.start_game(player_id)
        elif msg_type == "admin_update_settings":
            engine.update_settings(player_id, msg.get("settings") or {})
        elif msg_type == "admin_force_advance":
            engine.force_advance_phase(player_id)
        elif msg_type == "admin_extend_timer":
            engine.extend_current_phase(player_id, msg.get("seconds", 30))
        elif msg_type == "admin_remove_player":
            engine.admin_remove_player(player_id, msg.get("target_id"))
        elif msg_type == "set_bot_role":
            engine.set_bot_role(player_id, msg.get("target_id"), msg.get("role"))
        else:
            await manager.send_personal(game_id, player_id, {"type": "error", "message": "Unknown action"})
    except EngineError as e:
        await manager.send_personal(game_id, player_id, {"type": "error", "message": str(e)})


async def phase_ticker() -> None:
    """Runs forever in the background: force-resolves any phase whose
    server-side timer has expired, even if not every player acted.

    This is what makes the whole role-assignment -> night -> day ->
    discussion -> voting -> results -> next night loop keep going on its
    own: every phase's end is a real server timestamp (see TimerManager),
    and this loop is the thing that actually acts on it once it passes,
    for every phase that has a timer — not just night and voting."""
    while True:
        for engine in registry.all_engines():
            try:
                game_id = engine.state.game_id
                await notify_group_if_phase_changed(engine)
                changed = False
                # Bots act first: if they complete the last outstanding night
                # action or vote, the resolve checks below pick it up on this
                # same tick instead of idling until the next one.
                if drive_bots(engine):
                    changed = True
                if engine.state.phase == Phase.ROLE_ASSIGNMENT and engine.advance_from_role_assignment_if_ready():
                    changed = True
                elif engine.state.phase == Phase.NIGHT and engine.resolve_night_if_ready():
                    changed = True
                elif engine.state.phase == Phase.MORNING and engine.resolve_morning_if_ready():
                    changed = True
                elif engine.state.phase == Phase.VOTING and engine.resolve_voting_if_ready():
                    changed = True
                elif engine.state.phase == Phase.LYNCH_CONFIRMATION and engine.resolve_lynch_confirmation_if_ready():
                    changed = True
                elif engine.state.phase == Phase.KAMIKAZE_STRIKE and engine.resolve_kamikaze_strike_if_ready():
                    changed = True
                elif engine.state.phase == Phase.DAY_DISCUSSION and engine.advance_to_voting_if_ready():
                    changed = True
                elif engine.state.phase == Phase.VOTE_RESULTS and engine.start_next_night_if_ready():
                    changed = True
                if changed:
                    await manager.broadcast_state(game_id, engine)
                    await notify_group_if_phase_changed(engine)
                    await notify_players_outcome_messages(engine)
                    if engine.state.phase == Phase.GAME_OVER:
                        async with AsyncSessionLocal() as session:
                            await persist_finished_game(session, engine)
                    await save_checkpoint(engine)
            except Exception:
                logger.exception("Phase update failed for game=%s; retrying next tick", engine.state.game_id)
        prune_finished_games()
        await asyncio.sleep(1)


def prune_finished_games(now: float | None = None) -> None:
    """"Drops finished matches from the in-memory registry after the grace
    period. GAME_OVER engines are still useful briefly (last words, stats,
    final reveal) but would otherwise stay in memory forever — every
    finished group match the bot ever hosted would pile up."""
    from time import time as _time
    now = now if now is not None else _time()
    for engine in list(registry.all_engines()):
        game_id = engine.state.game_id
        if engine.state.phase != Phase.GAME_OVER or not engine.state.finished_persisted:
            _finished_at.pop(game_id, None)
            continue
        if game_id not in _finished_at:
            _finished_at[game_id] = now
            continue
        if now - _finished_at[game_id] >= FINISHED_GAME_GRACE_S:
            registry.remove(game_id)
            _finished_at.pop(game_id, None)
            forget_announced_game(game_id)
