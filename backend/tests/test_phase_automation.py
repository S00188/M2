"""Server-side automatic phase advancement for the True Mafia 13-role chain
(spec items 1 & 3). Every phase's end is a real server timestamp
(TimerManager), and the role_assignment -> night -> morning -> day_discussion
-> voting -> lynch_confirmation -> (kamikaze_strike) -> vote_results -> next
night loop keeps moving on its own even if nobody in the WebApp taps anything.
Night, voting and the new morning / lynch_confirmation / kamikaze_strike
sub-phases all resolve through the *_if_ready helpers the background ticker
calls; tests use force=True throughout so nothing sleeps."""
import time

from app.game_engine.engine import GameEngine
from app.game_engine.roles import RoleName as R
from app.game_engine.state import Phase
from tests.conftest import make_engine_with_roles


# A realistic 6-player day with the full town-power set + 2 mafia.
BASE = [R.DON, R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.LUCKY]


def _base_engine():
    return make_engine_with_roles(BASE)


def _to_discussion(eng):
    """Start (already in NIGHT) and move cleanly into DAY_DISCUSSION with no
    deaths: resolve an idle night into the morning report, then open the day."""
    assert eng.state.phase == Phase.NIGHT
    eng.resolve_night_if_ready(force=True)
    assert eng.state.phase == Phase.MORNING
    eng.resolve_morning_if_ready(force=True)
    assert eng.state.phase == Phase.DAY_DISCUSSION


def _all_ready_to_voting(eng, ids):
    """Every alive player ready => the discussion ends and voting opens."""
    for p in eng.state.alive_players():
        eng.set_ready_for_vote(p.player_id, True)
    assert eng.advance_to_voting_if_ready() is True
    assert eng.state.phase == Phase.VOTING


def _lynch(eng, ids, target_name):
    """Vote `target_name` out of the game through a full day cycle (with a
    YES lynch-confirmation ballot), returning what phase the engine lands in."""
    _to_discussion(eng)
    _all_ready_to_voting(eng, ids)
    voters = [p for p in ids.values() if eng.state.players[p].alive and p != ids[target_name]]
    half = len(voters) // 2 + 1
    for p in voters[:half]:
        eng.submit_vote(p, ids[target_name])
    for p in voters[half:]:
        abstain = next(pid for pid in ids.values() if eng.state.players[pid].alive and pid != ids[target_name])
        eng.submit_vote(p, abstain)
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.phase == Phase.LYNCH_CONFIRMATION
    for p in eng.state.alive_players():
        eng.submit_lynch_confirm(p.player_id, True)
    eng.resolve_lynch_confirmation_if_ready(force=True)
    return eng.state.phase


# --------------------------------------------------------------------------
# role_assignment
# --------------------------------------------------------------------------

def test_role_assignment_does_not_advance_before_timer_expires():
    eng = GameEngine(game_id="g", host_telegram_id=1, host_name="P0")
    for i in range(1, 7):
        eng.add_player(telegram_user_id=100 + i, display_name=f"P{i}")
    eng.start_game(eng.state.host_id)
    assert eng.state.phase == Phase.ROLE_ASSIGNMENT
    assert eng.advance_from_role_assignment_if_ready() is False
    assert eng.state.phase == Phase.ROLE_ASSIGNMENT


def test_role_assignment_advances_to_night_when_forced():
    eng = GameEngine(game_id="g", host_telegram_id=1, host_name="P0")
    for i in range(1, 7):
        eng.add_player(telegram_user_id=100 + i, display_name=f"P{i}")
    eng.start_game(eng.state.host_id)
    assert eng.advance_from_role_assignment_if_ready(force=True) is True
    assert eng.state.phase == Phase.NIGHT
    assert eng.state.night_number == 1


# --------------------------------------------------------------------------
# night -> morning -> day_discussion
# --------------------------------------------------------------------------

def test_night_resolves_to_morning_not_day():
    eng, _ = _base_engine()
    assert eng.state.phase == Phase.NIGHT
    assert eng.resolve_night_if_ready(force=True) is True
    assert eng.state.phase == Phase.MORNING
    assert eng.state.day_number == 0


def test_morning_resolves_to_day_discussion():
    eng, _ = _base_engine()
    eng.resolve_night_if_ready(force=True)
    assert eng.resolve_morning_if_ready(force=True) is True
    assert eng.state.phase == Phase.DAY_DISCUSSION
    assert eng.state.day_number == 1


def test_night_resolution_ends_game_early_on_mafia_win():
    eng, ids = make_engine_with_roles(
        [R.DON, R.MAFIA, R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    # 3 mafia vs 3 citizens. One citizen dies -> 3 mafia >= 2 town -> mafia win.
    eng.submit_night_action(ids["P0"], ids["P4"])
    eng.resolve_night_if_ready(force=True)
    assert eng.state.phase == Phase.GAME_OVER
    assert eng.state.winner.faction.value == "mafia"


# --------------------------------------------------------------------------
# day_discussion -> voting readiness
# --------------------------------------------------------------------------

def test_discussion_does_not_advance_before_timer_expires():
    eng, _ = _base_engine()
    _to_discussion(eng)
    assert eng.advance_to_voting_if_ready() is False
    assert eng.state.phase == Phase.DAY_DISCUSSION


def test_discussion_auto_advances_once_timer_expires():
    eng, _ = _base_engine()
    _to_discussion(eng)
    eng.state.phase_end = time.time() - 1
    assert eng.advance_to_voting_if_ready() is True
    assert eng.state.phase == Phase.VOTING


def test_discussion_advances_immediately_when_forced():
    eng, _ = _base_engine()
    _to_discussion(eng)
    assert eng.advance_to_voting_if_ready(force=True) is True
    assert eng.state.phase == Phase.VOTING


def test_single_ready_player_cannot_force_end_discussion():
    eng, ids = _base_engine()
    _to_discussion(eng)
    eng.set_ready_for_vote(ids["P0"], True)
    assert eng.advance_to_voting_if_ready() is False
    assert eng.state.phase == Phase.DAY_DISCUSSION


def test_all_alive_players_ready_advances_to_voting():
    eng, ids = _base_engine()
    _to_discussion(eng)
    _all_ready_to_voting(eng, ids)


def test_dead_players_are_not_counted_toward_ready():
    eng, ids = _base_engine()
    _to_discussion(eng)
    eng.state.players[ids["P5"]].alive = False
    for p in eng.state.alive_players():
        eng.set_ready_for_vote(p.player_id, True)
    assert eng.advance_to_voting_if_ready() is True
    assert eng.state.phase == Phase.VOTING


def test_ready_flags_reset_on_a_fresh_discussion_phase():
    eng, ids = _base_engine()
    _to_discussion(eng)
    eng.set_ready_for_vote(ids["P0"], True)
    assert eng.state.players[ids["P0"]].ready_for_vote is True
    _all_ready_to_voting(eng, ids)
    assert eng.resolve_voting_if_ready(force=True) is True
    assert eng.state.phase == Phase.VOTE_RESULTS
    # simulated next loop: reopen a fresh discussion
    eng.force_advance_phase(ids["P0"])  # vote_results -> night
    eng.force_advance_phase(ids["P0"])  # night -> morning
    eng.force_advance_phase(ids["P0"])  # morning -> day
    assert eng.state.players[ids["P0"]].ready_for_vote is False


# --------------------------------------------------------------------------
# lynch_confirmation
# --------------------------------------------------------------------------

def test_lynch_confirmation_approval_eliminates_victim_then_continues():
    eng, ids = _base_engine()
    phase = _lynch(eng, ids, "P2")  # lynch the Commissioner
    assert eng.state.players[ids["P2"]].alive is False
    assert eng.state.phase == Phase.VOTE_RESULTS


def test_lynch_confirmation_rejected_cancels_the_lynch():
    eng, ids = _base_engine()
    _to_discussion(eng)
    _all_ready_to_voting(eng, ids)
    voters = [p for p in ids.values() if eng.state.players[p].alive and p != ids["P2"]]
    half = len(voters) // 2 + 1
    for p in voters[:half]:
        eng.submit_vote(p, ids["P2"])
    for p in voters[half:]:
        abstain = next(pid for pid in ids.values() if eng.state.players[pid].alive and pid != ids["P2"])
        eng.submit_vote(p, abstain)
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.phase == Phase.LYNCH_CONFIRMATION
    for p in eng.state.alive_players():
        eng.submit_lynch_confirm(p.player_id, False)
    eng.resolve_lynch_confirmation_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is True
    assert eng.state.phase == Phase.VOTE_RESULTS


# --------------------------------------------------------------------------
# kamikaze_strike
# --------------------------------------------------------------------------

def test_kamikaze_strikes_after_being_lynched():
    eng, ids = make_engine_with_roles(
        [R.DON, R.MAFIA, R.KAMIKAZE, R.DOCTOR, R.CITIZEN, R.LUCKY])
    assert _lynch(eng, ids, "P2") == Phase.KAMIKAZE_STRIKE  # lynched a Kamikaze
    assert eng.state.players[ids["P2"]].alive is False
    # the striker (dead) picks a living target to take with them
    eng.submit_kamikaze_target(ids["P2"], ids["P4"])
    assert eng.state.players[ids["P4"]].alive is False
    eng.resolve_kamikaze_strike_if_ready(force=True)
    assert eng.state.phase == Phase.VOTE_RESULTS


# --------------------------------------------------------------------------
# vote_results -> next night / full cycle
# --------------------------------------------------------------------------

def test_vote_results_does_not_advance_before_timer_expires():
    eng, ids = _base_engine()
    eng.resolve_night_if_ready(force=True)
    eng.resolve_morning_if_ready(force=True)
    eng.advance_to_voting_if_ready(force=True)
    eng.resolve_voting_if_ready(force=True)  # no votes -> vote_results
    assert eng.state.phase == Phase.VOTE_RESULTS
    assert eng.start_next_night_if_ready() is False
    assert eng.state.phase == Phase.VOTE_RESULTS


def test_vote_results_auto_advances_to_next_night_once_timer_expires():
    eng, _ = _base_engine()
    eng.resolve_night_if_ready(force=True)
    eng.resolve_morning_if_ready(force=True)
    eng.advance_to_voting_if_ready(force=True)
    eng.resolve_voting_if_ready(force=True)  # no votes -> vote_results
    assert eng.state.phase == Phase.VOTE_RESULTS
    eng.state.phase_end = time.time() - 1
    assert eng.start_next_night_if_ready() is True
    assert eng.state.phase == Phase.NIGHT
    assert eng.state.night_number == 2


def test_vote_results_advances_immediately_when_forced():
    eng, _ = _base_engine()
    eng.resolve_night_if_ready(force=True)
    eng.resolve_morning_if_ready(force=True)
    eng.advance_to_voting_if_ready(force=True)
    eng.resolve_voting_if_ready(force=True)
    assert eng.start_next_night_if_ready(force=True) is True
    assert eng.state.phase == Phase.NIGHT


# --------------------------------------------------------------------------
# force_advance_phase walk
# --------------------------------------------------------------------------

def test_force_advance_phase_walks_one_phase_at_a_time():
    eng, ids = _base_engine()
    host = ids["P0"]
    assert eng.state.phase == Phase.NIGHT
    eng.force_advance_phase(host)
    assert eng.state.phase == Phase.MORNING
    eng.force_advance_phase(host)
    assert eng.state.phase == Phase.DAY_DISCUSSION
    eng.force_advance_phase(host)
    assert eng.state.phase == Phase.VOTING
    eng.force_advance_phase(host)  # no votes -> vote_results (no lynch target)
    assert eng.state.phase == Phase.VOTE_RESULTS
    eng.force_advance_phase(host)  # vote_results -> next night
    assert eng.state.phase == Phase.NIGHT
    assert eng.state.night_number == 2


def test_full_cycle_repeats_without_any_client_action():
    """The exact spec loop: Night -> Morning -> Day -> Discussion -> Voting ->
    Results -> next Night, driven only by the *_if_ready calls the background
    ticker makes — nothing here is clicked."""
    eng, _ = _base_engine()
    assert eng.state.phase == Phase.NIGHT
    assert eng.resolve_night_if_ready(force=True) is True
    assert eng.state.phase == Phase.MORNING
    assert eng.resolve_morning_if_ready(force=True) is True
    assert eng.state.phase == Phase.DAY_DISCUSSION
    assert eng.advance_to_voting_if_ready(force=True) is True
    assert eng.state.phase == Phase.VOTING
    assert eng.resolve_voting_if_ready(force=True) is True
    assert eng.state.phase == Phase.VOTE_RESULTS
    assert eng.start_next_night_if_ready(force=True) is True
    assert eng.state.phase == Phase.NIGHT
    assert eng.state.night_number == 2


def test_multi_night_loop_through_lynch_confirmation():
    """A real, full day where a player is actually lynched (approval ballot)
    and the game moves on past VOTE_RESULTS into a second night."""
    eng, ids = make_engine_with_roles(
        [R.DON, R.MAFIA, R.KAMIKAZE, R.DOCTOR, R.CITIZEN, R.LUCKY])
    phase = _lynch(eng, ids, "P2")
    if phase == Phase.KAMIKAZE_STRIKE:
        eng.submit_kamikaze_target(ids["P2"], ids["P5"])
        eng.resolve_kamikaze_strike_if_ready(force=True)
    assert eng.state.phase == Phase.VOTE_RESULTS
    assert eng.start_next_night_if_ready(force=True) is True
    assert eng.state.phase == Phase.NIGHT
    assert eng.state.night_number == 2
