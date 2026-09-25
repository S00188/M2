import pytest
from app.game_engine.roles import RoleName as R
from app.game_engine.engine import EngineError
from app.game_engine.state import Phase
from tests.conftest import make_engine_with_roles


def build():
    return make_engine_with_roles(
        [R.DON, R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN]
    )


def test_mafia_can_chat_and_sees_each_others_messages():
    eng, ids = build()
    eng.send_mafia_chat_message(ids["P0"], "kimni o'ldiramiz?")
    view = eng.get_player_view(ids["P1"])  # Mafia, teammate of Don (P0)
    assert [m["text"] for m in view["mafia_chat"]] == ["kimni o'ldiramiz?"]


def test_town_player_never_sees_mafia_chat():
    eng, ids = build()
    eng.send_mafia_chat_message(ids["P0"], "sir")
    town_view = eng.get_player_view(ids["P2"])  # Commissioner
    assert "mafia_chat" not in town_view
    assert "mafia_teammates" not in town_view.get("me", {})


def test_non_mafia_player_cannot_send_mafia_chat():
    eng, ids = build()
    with pytest.raises(EngineError):
        eng.send_mafia_chat_message(ids["P2"], "men ham yozaman")


def test_dead_mafia_cannot_send_but_can_still_read():
    eng, ids = build()
    eng.send_mafia_chat_message(ids["P0"], "birinchi xabar")
    eng.state.players[ids["P1"]].alive = False
    with pytest.raises(EngineError):
        eng.send_mafia_chat_message(ids["P1"], "men o'lganman")
    view = eng.get_player_view(ids["P1"])
    assert len(view["mafia_chat"]) == 1


def test_mafia_chat_closed_before_roles_assigned_and_after_game_over():
    eng, ids = build()
    eng.state.phase = Phase.LOBBY
    with pytest.raises(EngineError):
        eng.send_mafia_chat_message(ids["P0"], "hali erta")
    eng.state.phase = Phase.GAME_OVER
    with pytest.raises(EngineError):
        eng.send_mafia_chat_message(ids["P0"], "endi kech")


def test_mafia_chat_open_during_day_and_voting_not_just_night():
    eng, ids = build()
    eng.state.phase = Phase.DAY_DISCUSSION
    eng.send_mafia_chat_message(ids["P0"], "kunduzi ham yoza olamiz")
    eng.state.phase = Phase.VOTING
    eng.send_mafia_chat_message(ids["P0"], "ovoz paytida ham")
    view = eng.get_player_view(ids["P0"])
    assert len(view["mafia_chat"]) == 2


def test_can_mafia_chat_flag_reflects_alive_and_phase():
    eng, ids = build()
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["can_mafia_chat"] is True
    eng.state.players[ids["P0"]].alive = False
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["can_mafia_chat"] is False


def test_neutral_lawyer_cannot_send_or_see_mafia_chat():
    eng, ids = make_engine_with_roles(
        [R.DON, R.LAWYER, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    with pytest.raises(EngineError):
        eng.send_mafia_chat_message(ids["P1"], "men ham yozaman")
    view = eng.get_player_view(ids["P1"])
    assert "mafia_chat" not in view
    assert "mafia_teammates" not in view.get("me", {})


def test_mafia_team_membership_reciprocal():
    eng, ids = build()
    don_view = eng.get_player_view(ids["P0"])  # Don
    mafia_view = eng.get_player_view(ids["P1"])  # Mafia
    assert set(don_view["me"]["mafia_teammates"]) == {ids["P1"]}
    assert set(mafia_view["me"]["mafia_teammates"]) == {ids["P0"]}


def test_dead_teammate_still_listed_in_mafia_teammates():
    eng, ids = build()
    eng.state.players[ids["P1"]].alive = False
    view = eng.get_player_view(ids["P0"])
    assert ids["P1"] in view["me"]["mafia_teammates"]
