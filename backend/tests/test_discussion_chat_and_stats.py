"""Discussion chat (spec sections 11/32), last words, the private mafia
channel, and final reveal + personal statistics (spec section 22). The
Telegram group is never involved in any of this — it's all inside GameState,
scoped to one game, using the True Mafia 13-role set."""
import pytest

from app.game_engine.roles import RoleName as R
from app.game_engine.engine import GameEngine, EngineError
from app.game_engine.state import Phase
from app.game_engine.managers import WinConditionManager, PhaseManager
from tests.conftest import make_engine_with_roles


BASE = [R.DON, R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.LUCKY]


def _to_discussion(eng):
    """Push a freshly-built engine (already in NIGHT) through an idle night
    and the morning report into DAY_DISCUSSION."""
    assert eng.state.phase == Phase.NIGHT
    eng.resolve_night_if_ready(force=True)
    assert eng.state.phase == Phase.MORNING
    eng.resolve_morning_if_ready(force=True)
    assert eng.state.phase == Phase.DAY_DISCUSSION


def _to_vote_results_from_everyone_votes_nobody(eng):
    """Advance from NIGHT to VOTE_RESULTS with no deaths and no elimination."""
    _to_discussion(eng)
    for p in eng.state.alive_players():
        eng.set_ready_for_vote(p.player_id, True)
    eng.advance_to_voting_if_ready(force=True)
    eng.resolve_voting_if_ready(force=True)  # no votes -> no lynch
    assert eng.state.phase == Phase.VOTE_RESULTS


# --------------------------------------------------------------------------
# day discussion chat
# --------------------------------------------------------------------------

def test_alive_player_can_send_and_everyone_sees_it():
    eng, ids = make_engine_with_roles(BASE)
    _to_discussion(eng)
    eng.send_chat_message(ids["P1"], "Menimcha Don shubhali")
    view = eng.get_player_view(ids["P2"])
    assert len(view["chat"]) == 1
    assert view["chat"][0]["text"] == "Menimcha Don shubhali"
    assert view["chat"][0]["display_name"] == "P1"
    assert view["chat"][0]["kind"] == "player"


def test_dead_player_cannot_send_but_still_sees_chat():
    eng, ids = make_engine_with_roles(BASE)
    _to_discussion(eng)
    eng.send_chat_message(ids["P1"], "salom")
    eng.state.players[ids["P2"]].alive = False
    with pytest.raises(EngineError):
        eng.send_chat_message(ids["P2"], "men o'lganman lekin yozaman")
    # still visible to the dead player as a spectator
    view = eng.get_player_view(ids["P2"])
    assert len(view["chat"]) == 1


def test_silenced_player_cannot_send_that_day():
    eng, ids = make_engine_with_roles(BASE)
    _to_discussion(eng)
    eng.state.players[ids["P2"]].silenced = True
    with pytest.raises(EngineError):
        eng.send_chat_message(ids["P2"], "sukut qilinganman")


def test_chat_only_open_during_discussion_phase():
    eng, ids = make_engine_with_roles(BASE)
    # engine starts in NIGHT (conftest's make_engine_with_roles ends with to_night)
    with pytest.raises(EngineError):
        eng.send_chat_message(ids["P1"], "tunda yozmoqchiman")


def test_empty_message_rejected():
    eng, ids = make_engine_with_roles(BASE)
    _to_discussion(eng)
    with pytest.raises(EngineError):
        eng.send_chat_message(ids["P1"], "   ")


def test_chat_history_is_capped():
    eng, ids = make_engine_with_roles(BASE)
    _to_discussion(eng)
    for i in range(250):
        eng.send_chat_message(ids["P1"], f"msg {i}")
    view = eng.get_player_view(ids["P1"])
    assert len(view["chat"]) == 200
    assert view["chat"][-1]["text"] == "msg 249"  # oldest trimmed, newest kept


# --------------------------------------------------------------------------
# last words
# --------------------------------------------------------------------------

def test_lynched_player_can_leave_last_words_in_vote_results():
    eng, ids = make_engine_with_roles(
        [R.DON, R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.LUCKY])
    _to_discussion(eng)
    for p in eng.state.alive_players():
        eng.set_ready_for_vote(p.player_id, True)
    eng.advance_to_voting_if_ready(force=True)
    voters = [p for p in ids.values() if eng.state.players[p].alive and p != ids["P2"]]
    half = len(voters) // 2 + 1
    for p in voters[:half]:
        eng.submit_vote(p, ids["P2"])
    abstain = next(pid for pid in ids.values() if eng.state.players[pid].alive and pid != ids["P2"])
    for p in voters[half:]:
        eng.submit_vote(p, abstain)
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.phase == Phase.LYNCH_CONFIRMATION
    for p in eng.state.alive_players():
        eng.submit_lynch_confirm(p.player_id, True)
    eng.resolve_lynch_confirmation_if_ready(force=True)
    assert eng.state.phase == Phase.VOTE_RESULTS

    # only the eliminated player may speak; P4 (alive) cannot
    with pytest.raises(EngineError):
        eng.submit_last_words(ids["P4"], "men tirikman")
    eng.submit_last_words(ids["P2"], "bu mening so'nggi so'zlarim")
    with pytest.raises(EngineError):
        eng.submit_last_words(ids["P2"], "ikkinchi marta yo'q")

    view = eng.get_player_view(ids["P3"])
    last_words_msgs = [m for m in view["chat"] if m["kind"] == "last_words"]
    assert len(last_words_msgs) == 1
    assert last_words_msgs[0]["text"] == "bu mening so'nggi so'zlarim"
    assert last_words_msgs[0]["player_id"] == ids["P2"]


def test_dead_player_cannot_send_last_words_when_alive_guard_fails():
    eng, ids = make_engine_with_roles(BASE)
    _to_discussion(eng)
    # alive player trying to leave last words is rejected
    with pytest.raises(EngineError):
        eng.submit_last_words(ids["P1"], "men o'lganim yo'q lekin")


# --------------------------------------------------------------------------
# mafia chat
# --------------------------------------------------------------------------

def test_only_mafia_can_send_mafia_chat():
    eng, ids = make_engine_with_roles(BASE)
    assert eng.state.phase == Phase.NIGHT  # mafia chat is open outside lobby/over
    with pytest.raises(EngineError):
        eng.send_mafia_chat_message(ids["P2"], "men komisar man")  # Commissioner
    eng.send_mafia_chat_message(ids["P0"], "Don bu kecha o'ldiradi")


def test_mafia_chat_visible_only_to_mafia():
    eng, ids = make_engine_with_roles(BASE)
    eng.send_mafia_chat_message(ids["P0"], "maxfiy xabar")
    don_view = eng.get_player_view(ids["P0"])
    assert len(don_view["mafia_chat"]) == 1
    assert don_view["mafia_chat"][0]["text"] == "maxfiy xabar"
    assert don_view["me"]["can_mafia_chat"] is True
    # a town player never even sees the channel exist
    town_view = eng.get_player_view(ids["P2"])
    assert "mafia_chat" not in town_view
    assert "mafia_chat" not in town_view["me"]


def test_dead_mafia_cannot_send_mafia_chat_but_sees_spectate():
    eng, ids = make_engine_with_roles(BASE)
    eng.send_mafia_chat_message(ids["P0"], "oldin")
    eng.state.players[ids["P0"]].alive = False
    with pytest.raises(EngineError):
        eng.send_mafia_chat_message(ids["P0"], "endi yo'q")
    view = eng.get_player_view(ids["P1"])  # living mafia still sees history
    assert len(view["mafia_chat"]) == 1


# --------------------------------------------------------------------------
# final reveal + personal stats
# --------------------------------------------------------------------------

def test_final_role_reveal_shows_everyone_once_game_is_over():
    eng, ids = make_engine_with_roles(BASE)
    eng.state.players[ids["P0"]].alive = False
    eng.state.players[ids["P1"]].alive = False
    win = WinConditionManager.check(eng.state)
    assert win is not None and win.faction.value == "town"
    PhaseManager.to_game_over(eng.state, win)

    view = eng.get_player_view(ids["P3"])  # P3 is an alive Citizen
    roles_by_name = {p["display_name"]: p["role"] for p in view["players"]}
    assert roles_by_name["P1"] == "Mafia"
    assert roles_by_name["P2"] == "Commissioner"
    assert roles_by_name["P0"] == "Don"


def test_personal_stats_present_only_at_game_over():
    eng, ids = make_engine_with_roles(BASE)
    mid_game_view = eng.get_player_view(ids["P1"])
    assert "stats" not in mid_game_view["me"]

    eng.state.players[ids["P0"]].alive = False
    eng.state.players[ids["P1"]].alive = False
    win = WinConditionManager.check(eng.state)
    PhaseManager.to_game_over(eng.state, win)
    end_view = eng.get_player_view(ids["P1"])
    stats = end_view["me"]["stats"]
    assert stats["role"] == "Mafia"
    assert stats["won"] is False  # dead mafia in a town win
    assert set(stats) >= {"role", "won", "survived", "death_night",
                          "kills", "investigations", "protections", "votes_cast"}


def test_votes_cast_counter_increments_on_a_real_vote():
    eng, ids = make_engine_with_roles(BASE)
    _to_discussion(eng)
    for p in eng.state.alive_players():
        eng.set_ready_for_vote(p.player_id, True)
    eng.advance_to_voting_if_ready(force=True)
    eng.submit_vote(ids["P0"], ids["P2"])
    assert eng.state.players[ids["P0"]].votes_cast == 1
    eng.submit_vote(ids["P1"], None)  # abstain must NOT count as a cast vote
    assert eng.state.players[ids["P1"]].votes_cast == 0


def test_real_engine_commissioner_investigation_and_game_over_stats_schema():
    eng = GameEngine(game_id="g1", host_telegram_id=1, host_name="Host")
    for i in range(2, 8):
        eng.add_player(telegram_user_id=i, display_name=f"P{i}")
    eng.start_game(eng.state.host_id)
    eng.advance_from_role_assignment_if_ready(force=True)

    comm = next(pid for pid, p in eng.state.players.items()
                if p.role == R.COMMISSIONER)
    maf = next(pid for pid, p in eng.state.players.items()
               if p.role and p.role in (R.DON, R.MAFIA))
    eng.submit_night_action(comm, maf)  # Commissioner checks a mafia member
    don = next(pid for pid, p in eng.state.players.items() if p.role == R.DON)
    if don and don != comm:
        eng.submit_night_action(don, comm)  # mafia kills the Commissioner

    eng.resolve_night_if_ready(force=True)
    assert eng.state.phase == Phase.MORNING
    eng.resolve_morning_if_ready(force=True)
    assert eng.state.phase == Phase.DAY_DISCUSSION

    for p in eng.state.alive_players():
        eng.set_ready_for_vote(p.player_id, True)
    eng.advance_to_voting_if_ready(force=True)
    eng.resolve_voting_if_ready(force=True)
    eng.start_next_night_if_ready(force=True)
    assert eng.state.phase == Phase.NIGHT

    # game-over stats carry the full schema regardless of counter values
    for p in eng.state.players.values():
        p.alive = False
    eng.state.players[list(eng.state.players)[0]].alive = True
    win = WinConditionManager.check(eng.state)
    PhaseManager.to_game_over(eng.state, win)
    view = eng.get_player_view(list(eng.state.players)[0])
    assert set(view["me"]["stats"]) >= {"role", "won", "survived", "death_night",
                                        "kills", "investigations", "protections",
                                        "votes_cast"}
