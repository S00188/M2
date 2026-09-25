import pytest
from app.game_engine.roles import RoleName as R
from app.game_engine.state import Phase
from app.game_engine.managers import PhaseManager
from tests.conftest import make_engine_with_roles


MAFIA_AND_CITIZENS = [
    R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
]


def _to_voting(eng):
    eng.state.phase = Phase.DAY_DISCUSSION
    PhaseManager.to_voting(eng.state)


def test_majority_vote_eliminates_target():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    _to_voting(eng)
    eng.submit_vote(ids["P1"], ids["P0"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.submit_vote(ids["P3"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.phase == Phase.LYNCH_CONFIRMATION
    for k in ids:
        eng.submit_lynch_confirm(ids[k], True)
    eng.resolve_lynch_confirmation_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is False
    assert eng.state.players[ids["P0"]].death_reason == "day_vote"


def test_first_tie_under_default_revote_rule_eliminates_nobody_yet():
    """Default tie_rule is "revote": a first tie doesn't eliminate anyone
    immediately — it restarts voting restricted to the tied candidates."""
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    _to_voting(eng)
    assert eng.state.settings.tie_rule == "revote"
    eng.submit_vote(ids["P0"], ids["P1"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is True
    assert eng.state.players[ids["P1"]].alive is True
    # still VOTING — a revote is in progress, not VOTE_RESULTS
    assert eng.state.phase == Phase.VOTING
    assert eng.state.revote_round == 1


def test_revote_restricts_ballots_to_tied_candidates():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    _to_voting(eng)
    eng.submit_vote(ids["P0"], ids["P1"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert set(eng.state.revote_candidates) == {ids["P0"], ids["P1"]}
    with pytest.raises(Exception):
        eng.submit_vote(ids["P3"], ids["P4"])  # not one of the tied candidates
    eng.submit_vote(ids["P3"], ids["P0"])  # allowed: one of the tied candidates
    assert eng.state.players[ids["P0"]].alive is True  # not yet resolved


def test_second_tie_after_revote_results_in_no_elimination():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    _to_voting(eng)
    eng.submit_vote(ids["P0"], ids["P1"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)   # first tie -> revote
    eng.submit_vote(ids["P3"], ids["P0"])
    eng.submit_vote(ids["P4"], ids["P1"])
    eng.resolve_voting_if_ready(force=True)   # second tie -> stop the lynch
    assert eng.state.players[ids["P0"]].alive is True
    assert eng.state.players[ids["P1"]].alive is True
    assert eng.state.phase == Phase.VOTE_RESULTS


def test_no_elimination_tie_rule_never_revotes():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    eng.state.settings.tie_rule = "no_elimination"
    _to_voting(eng)
    eng.submit_vote(ids["P0"], ids["P1"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is True
    assert eng.state.players[ids["P1"]].alive is True
    assert eng.state.phase == Phase.VOTE_RESULTS  # resolved immediately, no revote


def test_tie_rule_random_picks_a_leader_and_lynches():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    eng.state.settings.tie_rule = "random"
    _to_voting(eng)
    eng.submit_vote(ids["P0"], ids["P1"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.last_vote_result["reason"] == "tie_random"
    assert eng.state.phase == Phase.LYNCH_CONFIRMATION
    assert eng.state.players[ids["P0"]].alive is True
    assert eng.state.players[ids["P1"]].alive is True


def test_dead_player_cannot_vote():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    eng.state.players[ids["P1"]].alive = False
    _to_voting(eng)
    with pytest.raises(Exception):
        eng.submit_vote(ids["P1"], ids["P0"])


def test_cannot_vote_for_dead_target():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    eng.state.players[ids["P1"]].alive = False
    _to_voting(eng)
    with pytest.raises(Exception):
        eng.submit_vote(ids["P0"], ids["P1"])


def test_self_vote_disabled_by_default():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    _to_voting(eng)
    with pytest.raises(Exception):
        eng.submit_vote(ids["P0"], ids["P0"])


def test_self_vote_enabled_when_allowed():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    eng.state.settings.allow_self_vote = True
    _to_voting(eng)
    eng.submit_vote(ids["P0"], ids["P0"])
    assert ids["P0"] in eng.state.votes


def test_lynch_confirmation_approval_eliminates_target():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    _to_voting(eng)
    eng.submit_vote(ids["P1"], ids["P0"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.submit_vote(ids["P3"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.phase == Phase.LYNCH_CONFIRMATION
    for k in ids:
        eng.submit_lynch_confirm(ids[k], True)
    eng.resolve_lynch_confirmation_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is False
    assert eng.state.players[ids["P0"]].death_reason == "day_vote"


def test_lynch_confirmation_rejection_cancels_lynch():
    eng, ids = make_engine_with_roles(MAFIA_AND_CITIZENS)
    _to_voting(eng)
    eng.submit_vote(ids["P1"], ids["P0"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.submit_vote(ids["P3"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.phase == Phase.LYNCH_CONFIRMATION
    for k in ids:
        eng.submit_lynch_confirm(ids[k], False)
    eng.resolve_lynch_confirmation_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is True
    assert eng.state.phase == Phase.VOTE_RESULTS


def test_kamikaze_after_lynch_takes_someone_down():
    eng, ids = make_engine_with_roles(
        [R.KAMIKAZE, R.CITIZEN, R.CITIZEN, R.CITIZEN,
         R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    _to_voting(eng)
    eng.submit_vote(ids["P1"], ids["P0"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.submit_vote(ids["P3"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.phase == Phase.LYNCH_CONFIRMATION
    for k in ids:
        eng.submit_lynch_confirm(ids[k], True)
    eng.resolve_lynch_confirmation_if_ready(force=True)
    assert eng.state.phase == Phase.KAMIKAZE_STRIKE
    eng.submit_kamikaze_target(ids["P0"], ids["P1"])
    eng.resolve_kamikaze_strike_if_ready(force=True)
    assert eng.state.players[ids["P1"]].alive is False
    assert eng.state.players[ids["P1"]].death_reason == "kamikaze"
