"""Group lifecycle announcements (app/services/notifications.py) and the
finished-game pruning (/app/websocket/handlers.py's prune_finished_games
plus the tidy-up it performs). These are the "the group hears what happened"
and "finished matches don't live in RAM forever" behaviours.

Both modules reach into Telegram and the shared GameRegistry, so every test
here uses the same offline stand-ins as the rest of the suite (conftest's
autouse monkeypatches) and constructs lightweight engines by hand."""
import uuid
from time import time

import pytest

from app.game_engine.engine import GameEngine
from app.game_engine.state import Phase, WinResult
from app.game_engine.roles import Faction, RoleName
from app.services import notifications
from app.services.game_service import registry
from app.websocket.handlers import prune_finished_games, FINISHED_GAME_GRACE_S


@pytest.fixture(autouse=True)
def _reset_notification_state():
    notifications._state_phase.clear()
    yield
    notifications._state_phase.clear()


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    for engine in list(registry.all_engines()):
        registry.remove(engine.state.game_id)


class _RecordSend:
    def __init__(self):
        self.calls = []

    async def __call__(self, chat_id, text, button_text=None, button_url=None):
        self.calls.append((chat_id, text))
        return True


def _make_engine(chat_id="-1000123", host_name="P0", n_players=6) -> GameEngine:
    eng = GameEngine(game_id=f"g-{uuid.uuid4().hex[:8]}", host_telegram_id=1,
                     host_name=host_name, chat_id=chat_id)
    for i in range(1, n_players):
        eng.add_player(telegram_user_id=100 + i, display_name=f"P{i}")
    return eng


# --------------------------------------------------------- notifications ----

@pytest.mark.asyncio
async def test_game_start_announced_on_role_assignment_transition():
    recorder = _RecordSend()
    notifications.send_telegram_message = recorder
    eng = _make_engine()
    # First observation seeds the previous phase and sends nothing (the match
    # may already have been running before this process noticed it).
    await notifications.notify_group_if_phase_changed(eng)
    assert recorder.calls == []

    eng.state.phase = Phase.ROLE_ASSIGNMENT
    await notifications.notify_group_if_phase_changed(eng)
    assert len(recorder.calls) == 1
    chat_id, text = recorder.calls[0]
    assert chat_id == "-1000123"
    assert "Tarqatilgan rollar" in text
    assert "6" in text  # role count


@pytest.mark.asyncio
async def test_game_start_announced_exactly_once():
    recorder = _RecordSend()
    notifications.send_telegram_message = recorder
    eng = _make_engine()
    await notifications.notify_group_if_phase_changed(eng)  # seed lobby
    eng.state.phase = Phase.ROLE_ASSIGNMENT
    await notifications.notify_group_if_phase_changed(eng)
    await notifications.notify_group_if_phase_changed(eng)
    assert len(recorder.calls) == 1


@pytest.mark.asyncio
async def test_game_over_announced_with_winning_faction_and_winners():
    recorder = _RecordSend()
    notifications.send_telegram_message = recorder
    eng = _make_engine()
    await notifications.notify_group_if_phase_changed(eng)  # seed lobby
    eng.state.phase = Phase.VOTE_RESULTS
    await notifications.notify_group_if_phase_changed(eng)  # no send (not a boundary)
    assert recorder.calls == []

    host_pid = eng.state.host_id
    winner_pid = next(pid for pid, p in eng.state.players.items() if not p.is_host)
    eng.state.phase = Phase.GAME_OVER
    eng.state.winner = WinResult(faction=Faction.TOWN, winners=[host_pid, winner_pid], reason="test")
    await notifications.notify_group_if_phase_changed(eng)
    assert len(recorder.calls) == 1
    chat_id, text = recorder.calls[0]
    assert chat_id == "-1000123"
    assert "Shahar" in text
    assert "P0" in text
    assert "P1" in text


@pytest.mark.asyncio
async def test_bot_games_and_chatless_games_never_notified():
    recorder = _RecordSend()
    notifications.send_telegram_message = recorder

    bot_eng = _make_engine(chat_id="botlab:training-1")
    await notifications.notify_group_if_phase_changed(bot_eng)
    bot_eng.state.phase = Phase.ROLE_ASSIGNMENT
    await notifications.notify_group_if_phase_changed(bot_eng)

    nochat_eng = _make_engine(chat_id=None)
    await notifications.notify_group_if_phase_changed(nochat_eng)
    nochat_eng.state.phase = Phase.ROLE_ASSIGNMENT
    await notifications.notify_group_if_phase_changed(nochat_eng)

    assert recorder.calls == []


@pytest.mark.asyncio
async def test_restart_seed_prevents_false_game_start_announcement():
    """After a server restart the ticker's first observation of a
    mid-game engine must NOT announce "game started" for a match that began
    before the restart — notify_group_on_restart pre-seeds the phase."""
    recorder = _RecordSend()
    notifications.send_telegram_message = recorder
    eng = _make_engine()
    eng.state.phase = Phase.NIGHT
    await notifications.notify_group_on_restart(eng)  # seeds NIGHT
    await notifications.notify_group_if_phase_changed(eng)  # ticker sees NIGHT
    assert recorder.calls == []


# ---------------------------------------------------------- prune games ----

def test_finished_game_is_pruned_after_grace_period():
    eng = _make_engine()
    game_id = eng.state.game_id
    eng.state.phase = Phase.GAME_OVER
    eng.state.finished_persisted = True
    registry.register_recovered(eng)

    now = time()
    prune_finished_games(now)                      # first call just stamps it
    assert registry.get(game_id)
    prune_finished_games(now + FINISHED_GAME_GRACE_S + 1)
    with pytest.raises(KeyError):
        registry.get(game_id)


def test_unfinished_and_unpersisted_games_are_never_pruned():
    active = _make_engine()
    active_id = active.state.game_id
    fresh_finished = _make_engine()
    fresh_id = fresh_finished.state.game_id
    fresh_finished.state.phase = Phase.GAME_OVER   # but not persisted yet

    registry.register_recovered(active)
    registry.register_recovered(fresh_finished)

    now = time()
    prune_finished_games(now)
    prune_finished_games(now + FINISHED_GAME_GRACE_S * 10)
    assert registry.get(active_id)
    assert registry.get(fresh_id)


def test_pruning_forgets_announced_phase():
    eng = _make_engine()
    game_id = eng.state.game_id
    eng.state.phase = Phase.GAME_OVER
    eng.state.finished_persisted = True
    registry.register_recovered(eng)
    notifications.remember_phase(game_id, Phase.GAME_OVER)

    now = time()
    prune_finished_games(now)
    prune_finished_games(now + FINISHED_GAME_GRACE_S + 1)
    assert game_id not in notifications._state_phase
    with pytest.raises(KeyError):
        registry.get(game_id)
