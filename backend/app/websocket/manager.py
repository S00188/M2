from __future__ import annotations
import logging
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger("mafia.ws")


class ConnectionManager:
    def __init__(self) -> None:
        # game_id -> {player_id: WebSocket}
        self._rooms: dict[str, dict[str, WebSocket]] = {}

    async def connect(self, game_id: str, player_id: str, ws: WebSocket) -> None:
        await ws.accept()
        old = self._rooms.get(game_id, {}).get(player_id)
        self._rooms.setdefault(game_id, {})[player_id] = ws
        if old is not None and old is not ws:
            try:
                await old.close(code=4001)
            except Exception:
                logger.debug("Previous socket already closed")

    def is_current(self, game_id: str, player_id: str, ws: WebSocket) -> bool:
        return self._rooms.get(game_id, {}).get(player_id) is ws

    def disconnect(self, game_id: str, player_id: str, ws: WebSocket | None = None) -> bool:
        if ws is not None and not self.is_current(game_id, player_id, ws):
            return False
        room = self._rooms.get(game_id)
        if room:
            room.pop(player_id, None)
            if not room:
                self._rooms.pop(game_id, None)
            return True
        return False

    async def send_personal(self, game_id: str, player_id: str, message: dict) -> None:
        ws = self._rooms.get(game_id, {}).get(player_id)
        if ws:
            await asyncio.wait_for(ws.send_json(message), timeout=5)

    async def broadcast_state(self, game_id: str, engine) -> None:
        """Send every connected player their own authoritative, hidden-info-safe view."""
        room = self._rooms.get(game_id, {})
        for player_id, ws in list(room.items()):
            if not self.is_current(game_id, player_id, ws):
                continue
            try:
                await asyncio.wait_for(ws.send_json({"type": "state", "state": engine.get_player_view(player_id)}), timeout=5)
            except (WebSocketDisconnect, OSError, asyncio.TimeoutError):
                if self.disconnect(game_id, player_id, ws):
                    player = engine.state.players.get(player_id)
                    if player:
                        player.connected = False
                logger.debug("Socket disconnected for game=%s player=%s", game_id, player_id)
            except RuntimeError:
                if getattr(ws, "application_state", None) != WebSocketState.DISCONNECTED:
                    logger.exception("broadcast_state failed for game=%s player=%s", game_id, player_id)
                if self.disconnect(game_id, player_id, ws):
                    player = engine.state.players.get(player_id)
                    if player:
                        player.connected = False
            except Exception:
                # A bug in get_player_view (or a genuinely dead socket) must
                # never vanish silently — it used to, and it hid a real
                # crash behind what looked like a client-side hang.
                logger.exception("broadcast_state failed for game=%s player=%s", game_id, player_id)
                self.disconnect(game_id, player_id, ws)

    async def broadcast_and_close(self, game_id: str, message: dict) -> None:
        """Used by an admin/host force-stop (/stop in the group): tells every
        connected Mini App client the match was cancelled, then drops the
        room entirely so no stray socket keeps thinking a game exists once
        the engine itself has been removed from the registry."""
        room = self._rooms.pop(game_id, {})
        for player_id, ws in list(room.items()):
            try:
                await asyncio.wait_for(ws.send_json(message), timeout=5)
            except Exception:
                logger.exception("broadcast_and_close send failed for game=%s player=%s", game_id, player_id)
            try:
                await ws.close(code=4000)
            except Exception:
                pass


manager = ConnectionManager()
