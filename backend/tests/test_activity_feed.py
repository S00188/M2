"""Tests for the anonymous, phase-scoped activity feed. Every assertion is
either:
  (a) the feed contains the RIGHT anonymous entries at the right time, or
  (b) the feed does NOT contain a player_id / target_id anywhere, ever,
      even serialized as a string inside a message_key or extra field.
"""
import json

from app.game_engine.roles import RoleName as R
from app.game_engine.managers import PhaseManager
from app.game_engine.engine import EngineError
from tests.conftest import make_engine_with_roles


def _feed_for(eng, player_id):
    return eng.get_player_view(player_id)["activity_feed"]


def test_night_begins_event_is_public_and_anonymous():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    for pid in ids.values():
        feed = _feed_for(eng, pid)
        assert any(e["message_key"] == "night.begins" and e["phase_number"] == 1 for e in feed)


def test_mafia_kill_target_selected_is_anonymous_to_everyone():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])  # Don kills P3
    for pid in ids.values():
        feed = _feed_for(eng, pid)
        keys = [e["message_key"] for e in feed]
        assert "night.mafia.kill_target_selected" in keys
        blob = json.dumps(feed)
        assert ids["P0"] not in blob
        assert ids["P3"] not in blob


def test_mafia_can_explicitly_choose_not_to_attack():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], None)
    assert ids["P0"] in eng.state.night_actions
    assert eng.state.night_actions[ids["P0"]].target_id is None
    feed = _feed_for(eng, ids["P1"])
    assert any(e["message_key"] == "night.mafia.kill_skipped" for e in feed)
    eng.resolve_night_if_ready(force=True)
    assert all(p.alive for p in eng.state.players.values())


def test_maniac_can_also_explicitly_skip():
    eng, ids = make_engine_with_roles([
        R.MANIAC, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], None)
    assert eng.state.night_actions[ids["P0"]].target_id is None
    feed = _feed_for(eng, ids["P1"])
    assert any(e["message_key"] == "night.maniac.kill_skipped" for e in feed)


def test_other_roles_still_require_a_target():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    try:
        eng.submit_night_action(ids["P2"], None)  # doctor, PROTECT
        assert False, "expected EngineError"
    except EngineError:
        pass


def test_night_action_can_skip_target_flag_only_true_for_kill_roles():
    eng, ids = make_engine_with_roles([
        R.DON, R.DOCTOR, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    don_view = eng.get_player_view(ids["P0"])["me"]
    doctor_view = eng.get_player_view(ids["P1"])["me"]
    commissioner_view = eng.get_player_view(ids["P2"])["me"]
    assert don_view["night_action_can_skip_target"] is True
    assert doctor_view["night_action_can_skip_target"] is False
    assert commissioner_view["night_action_can_skip_target"] is False


def test_investigation_results_never_appear_in_the_public_feed():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])   # Don kill
    eng.submit_night_action(ids["P1"], ids["P2"])   # Commissioner investigates Doctor
    eng.resolve_night_if_ready(force=True)
    for pid in ids.values():
        feed = _feed_for(eng, pid)
        blob = json.dumps(feed)
        assert "verdict" not in blob
        assert "not_mafia" not in blob and '"mafia"' not in blob


def test_night_resolved_transition_is_public():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])
    eng.resolve_night_if_ready(force=True)
    feed = _feed_for(eng, ids["P4"])
    assert any(e["message_key"] == "night.resolved" and e["phase_number"] == 1 for e in feed)


def test_day_begins_and_night1_events_are_phase_segmented():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])
    eng.resolve_night_if_ready(force=True)     # -> MORNING
    eng.resolve_morning_if_ready(force=True)    # -> DAY_DISCUSSION
    feed = _feed_for(eng, ids["P4"])
    night1 = [e for e in feed if e["phase"] == "night" and e["phase_number"] == 1]
    day1 = [e for e in feed if e["phase"] == "day_discussion" and e["phase_number"] == 1]
    assert any(e["message_key"] == "night.mafia.kill_target_selected" for e in night1)
    assert any(e["message_key"] == "day.begins" for e in day1)
    assert not any(e["message_key"].startswith("night.mafia") for e in day1)


def test_night2_events_are_a_fresh_segment_from_night1():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])
    eng.resolve_night_if_ready(force=True)       # MORNING
    eng.resolve_morning_if_ready(force=True)      # DAY_DISCUSSION
    for p in eng.state.alive_players():
        eng.set_ready_for_vote(p.player_id, True)
    eng.advance_to_voting_if_ready(force=True)    # VOTING
    eng.resolve_voting_if_ready(force=True)        # VOTE_RESULTS (no votes cast)
    eng.start_next_night()                         # NIGHT 2
    eng.submit_night_action(ids["P0"], None)       # skip attack night 2
    feed = _feed_for(eng, ids["P4"])
    night1 = [e for e in feed if e["phase"] == "night" and e["phase_number"] == 1]
    night2 = [e for e in feed if e["phase"] == "night" and e["phase_number"] == 2]
    assert any(e["message_key"] == "night.mafia.kill_target_selected" for e in night1)
    assert any(e["message_key"] == "night.mafia.kill_skipped" for e in night2)
    assert not any(e["message_key"] == "night.mafia.kill_skipped" for e in night1)


def test_voting_begins_and_revote_events_are_public():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.resolve_night_if_ready(force=True)
    eng.resolve_morning_if_ready(force=True)
    for p in eng.state.alive_players():
        eng.set_ready_for_vote(p.player_id, True)
    eng.advance_to_voting_if_ready(force=True)
    feed = _feed_for(eng, ids["P4"])
    assert any(e["message_key"] == "voting.begins" for e in feed)

    # Create a tie to trigger a revote (default tie_rule="revote")
    eng.submit_vote(ids["P0"], ids["P1"])
    eng.submit_vote(ids["P1"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.revote_round == 1

    feed = _feed_for(eng, ids["P4"])
    voting_begins_events = [e for e in feed if e["message_key"] == "voting.begins"]
    assert len(voting_begins_events) == 2  # original + revote


def test_activity_feed_has_no_visible_to_field_leaked_to_client():
    eng, ids = make_engine_with_roles([
        R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    feed = _feed_for(eng, ids["P0"])
    for entry in feed:
        assert "visible_to" not in entry
