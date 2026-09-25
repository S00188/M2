import pytest
from app.game_engine.roles import RoleName as R
from app.game_engine.engine import GameEngine, EngineError
from app.game_engine.state import Phase
from app.game_engine.managers import PhaseManager
from tests.conftest import make_engine_with_roles


def test_player_view_works_in_lobby_before_any_role_is_assigned():
    eng = GameEngine(game_id="g1", host_telegram_id=1, host_name="Host")
    eng.add_player(telegram_user_id=2, display_name="P2")
    view = eng.get_player_view(eng.state.host_id)
    assert view["phase"] == "lobby"
    assert view["me"]["role"] is None
    assert all(p["role"] is None for p in view["players"])


def test_dead_player_cannot_submit_night_action():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P0"]].alive = False
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P0"], ids["P1"])


def test_cannot_act_outside_night_phase():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.phase = Phase.DAY_DISCUSSION
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P0"], ids["P1"])


def test_duplicate_night_action_rejected():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.submit_night_action(ids["P0"], ids["P1"])
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P0"], ids["P2"])


def test_citizen_has_no_night_action():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P1"], ids["P2"])


def test_player_view_never_leaks_other_alive_players_roles():
    eng, ids = make_engine_with_roles([R.MAFIA, R.DOCTOR, R.COMMISSIONER, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(ids["P1"])
    for p in view["players"]:
        if p["player_id"] != ids["P1"]:
            assert p["role"] is None
    assert view["me"]["role"] == "Doctor"


def test_mafia_teammates_are_visible_only_to_mafia():
    eng, ids = make_engine_with_roles([R.DON, R.MAFIA, R.MAFIA, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    don_view = eng.get_player_view(ids["P0"])
    citizen_view = eng.get_player_view(ids["P3"])
    assert set(don_view["me"]["mafia_teammates"]) == {ids["P1"], ids["P2"]}
    assert "mafia_teammates" not in citizen_view["me"]


def test_reconnect_returns_consistent_authoritative_state():
    eng, ids = make_engine_with_roles([R.MAFIA, R.DOCTOR, R.COMMISSIONER, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.submit_night_action(ids["P0"], ids["P3"])
    view_before = eng.get_player_view(ids["P0"])
    view_after = eng.get_player_view(ids["P0"])
    assert view_before["me"]["has_submitted_night_action"] is True
    assert view_after["me"]["has_submitted_night_action"] is True
    assert view_before["me"]["role"] == view_after["me"]["role"]


# ---------- night_action_type per role ----------

def test_mafia_killer_night_action_type():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["night_action_type"] == "kill"
    assert view["me"]["is_mafia_killer"] is True


def test_non_killer_mafia_has_no_night_action_type():
    eng, ids = make_engine_with_roles([R.DON, R.MAFIA, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(ids["P1"])
    assert view["me"]["night_action_type"] is None
    assert view["me"]["is_mafia_killer"] is False


def test_commissioner_night_action_type():
    eng, ids = make_engine_with_roles([R.CITIZEN, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(ids["P1"])
    assert view["me"]["night_action_type"] == "investigate"


def test_doctor_night_action_type():
    eng, ids = make_engine_with_roles([R.CITIZEN, R.DOCTOR, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(ids["P1"])
    assert view["me"]["night_action_type"] == "protect"


def test_citizen_night_action_type_is_none():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(ids["P1"])
    assert view["me"]["night_action_type"] is None


# ---------- commissioner_can_shoot ----------

def test_commissioner_can_shoot_before_using_kill():
    eng, ids = make_engine_with_roles([R.COMMISSIONER, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["commissioner_can_shoot"] is True


def test_commissioner_cannot_shoot_after_using_kill():
    eng, ids = make_engine_with_roles([R.COMMISSIONER, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    eng.submit_night_action(ids["P0"], ids["P1"], action_override="shoot")
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["commissioner_can_shoot"] is False


# ---------- has_lynch_confirmed ----------

def test_has_lynch_confirmed_false_initially():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    PhaseManager.to_lynch_confirmation(eng.state, [ids["P1"]])
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["has_lynch_confirmed"] is False


def test_has_lynch_confirmed_true_after_voting():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    PhaseManager.to_lynch_confirmation(eng.state, [ids["P1"]])
    eng.submit_lynch_confirm(ids["P0"], yes=True)
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["has_lynch_confirmed"] is True


# ---------- kamikaze flags ----------

def test_kamikaze_striker_flag():
    eng, ids = make_engine_with_roles([R.KAMIKAZE, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    PhaseManager.to_kamikaze_strike(eng.state)
    eng._lynch_target = ids["P0"]
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["kamikaze_striker"] is True


def test_kamikaze_not_striker_for_other_players():
    eng, ids = make_engine_with_roles([R.KAMIKAZE, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    PhaseManager.to_kamikaze_strike(eng.state)
    eng._lynch_target = ids["P0"]
    view = eng.get_player_view(ids["P1"])
    assert view["me"]["kamikaze_striker"] is False


# ---------- no day action in the 13-role view ----------

def test_no_day_action_key_in_view():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    PhaseManager.to_day(eng.state)
    view = eng.get_player_view(ids["P0"])
    # The day-action mechanic (Mayor reveal / Gunner shot) was removed — the
    # view no longer exposes any day_action_type for any role.
    assert "day_action_type" not in view["me"]


# ---------- lucky_survived ----------

def test_lucky_survived_flag_for_lucky_player():
    eng, ids = make_engine_with_roles([R.LUCKY, R.MAFIA, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P0"]].lucky_survived_lethal = True
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["lucky_survived"] is True


def test_lucky_survived_none_for_non_lucky():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(ids["P0"])
    assert view["me"]["lucky_survived"] is None


# ---------- admin block content ----------

def test_admin_block_settings_in_lobby():
    eng = GameEngine(game_id="g1", host_telegram_id=1, host_name="Host")
    for i in range(2, 7):
        eng.add_player(telegram_user_id=i, display_name=f"P{i}")
    view = eng.get_player_view(eng.state.host_id)
    assert "settings" in view["admin"]
    assert "night_duration_s" in view["admin"]["settings"]
    assert "day_duration_s" in view["admin"]["settings"]
    assert "voting_duration_s" in view["admin"]["settings"]
    assert "tie_rule" in view["admin"]["settings"]
    assert "anonymous_voting" in view["admin"]["settings"]
    assert "allow_self_vote" in view["admin"]["settings"]
    assert "reveal_role_on_death" in view["admin"]["settings"]


def test_admin_block_vote_progress():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    PhaseManager.to_voting(eng.state)
    eng.submit_vote(ids["P0"], ids["P1"])
    view = eng.get_player_view(eng.state.host_id)
    assert view["admin"]["votes_cast"] == 1
    assert view["admin"]["votes_expected"] == len(eng.state.alive_players())


def test_admin_block_can_force_advance_and_extend():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(eng.state.host_id)
    assert view["admin"]["can_force_advance"] is True
    assert view["admin"]["can_extend_timer"] is True
