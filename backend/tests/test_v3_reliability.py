import asyncio
from unittest.mock import AsyncMock

import pytest

from app.game_engine.engine import GameEngine
from app.game_engine.state import Phase
from app.websocket.manager import ConnectionManager
from app.websocket import handlers


@pytest.mark.asyncio
async def test_old_disconnect_preserves_new_connection():
    manager = ConnectionManager()
    old, new = AsyncMock(), AsyncMock()
    await manager.connect('g', 'p', old)
    await manager.connect('g', 'p', new)
    old.close.assert_awaited_once_with(code=4001)
    assert manager.disconnect('g', 'p', old) is False
    assert manager.is_current('g', 'p', new)
    await manager.send_personal('g', 'p', {'type': 'state'})
    new.send_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_old_broadcast_preserves_replacement():
    manager = ConnectionManager()
    old, new = AsyncMock(), AsyncMock()
    await manager.connect('g', 'p', old)
    async def replace_then_fail(message):
        await manager.connect('g', 'p', new)
        raise RuntimeError('Old transport closed')
    old.send_json.side_effect = replace_then_fail
    engine = GameEngine(game_id='g', host_telegram_id=1, host_name='Host')
    engine.get_player_view = lambda p: {}
    await manager.broadcast_state('g', engine)
    assert manager.is_current('g', 'p', new)


@pytest.mark.asyncio
async def test_next_night_cannot_skip_result_timer(monkeypatch):
    from time import time
    engine = GameEngine(game_id='g', host_telegram_id=1, host_name='Host')
    engine.state.phase = Phase.VOTE_RESULTS
    engine.state.phase_end = time() + 60
    reply = AsyncMock()
    monkeypatch.setattr(handlers.manager, 'send_personal', reply)
    await handlers._handle_message('g', engine, 'p', {'type': 'start_next_night'})
    assert engine.state.phase == Phase.VOTE_RESULTS
    assert reply.await_args.args[2]['type'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('message', [[], None, {'type': 'chat_message', 'text': []}, {'type': 'vote', 'target_id': {}}, {'type': 'lynch_confirm', 'yes': 'false'}])
async def test_malformed_message_does_not_mutate_game(monkeypatch, message):
    reply = AsyncMock()
    monkeypatch.setattr(handlers.manager, 'send_personal', reply)
    await handlers._handle_message('g', None, 'p', message)
    assert reply.await_args.args[2]['type'] == 'error'


@pytest.mark.asyncio
async def test_bad_game_does_not_stop_other_timers(monkeypatch):
    broken = GameEngine(game_id='bad', host_telegram_id=1, host_name='A')
    healthy = GameEngine(game_id='good', host_telegram_id=2, host_name='B')
    seen = []
    monkeypatch.setattr(handlers.registry, 'all_engines', lambda: [broken, healthy])
    def drive(engine):
        seen.append(engine.state.game_id)
        if engine is broken:
            raise RuntimeError('Broken match')
        return False
    monkeypatch.setattr(handlers, 'drive_bots', drive)
    monkeypatch.setattr(handlers, 'prune_finished_games', lambda: None)
    async def stop_after_tick(delay):
        raise asyncio.CancelledError
    monkeypatch.setattr(handlers.asyncio, 'sleep', stop_after_tick)
    with pytest.raises(asyncio.CancelledError):
        await handlers.phase_ticker()
    assert seen == ['bad', 'good']

@pytest.mark.asyncio
async def test_dead_transport_marks_player_offline():
    from fastapi import WebSocketDisconnect
    manager = ConnectionManager()
    engine = GameEngine(game_id='g', host_telegram_id=1, host_name='Host')
    pid = engine.state.host_id
    engine.state.players[pid].connected = True
    socket = AsyncMock()
    socket.send_json.side_effect = WebSocketDisconnect(code=1006)
    await manager.connect('g', pid, socket)
    await manager.broadcast_state('g', engine)
    assert not engine.state.players[pid].connected
    assert not manager.is_current('g', pid, socket)
