import json
import pytest
from app.game_engine.engine import GameEngine
from app.game_engine.state import Phase, EngineError
from app.game_engine.roles import RoleName as R, Faction
from app.game_engine.managers import PhaseManager, WinConditionManager
from app.game_engine.persistence import state_to_dict, state_from_dict
from tests.conftest import make_engine_with_roles


def ballot():
    e, ids = make_engine_with_roles([R.DON, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.DOCTOR, R.COMMISSIONER])
    PhaseManager.to_voting(e.state)
    for pid in e.state.players:
        e.submit_vote(pid, ids['P1'] if pid != ids['P1'] else None)
    assert e.resolve_voting_if_ready()
    return e, ids


@pytest.mark.parametrize('approved', [True, False])
def test_confirmation_survives_serialization(approved):
    e, ids = ballot()
    for pid in e.state.players:
        e.submit_lynch_confirm(pid, approved)
    restored = GameEngine.from_state(state_from_dict(json.loads(json.dumps(state_to_dict(e.state)))))
    assert restored.get_player_view(ids['P0'])['lynch_target'] == ids['P1']
    assert restored.resolve_lynch_confirmation_if_ready()
    assert restored.state.players[ids['P1']].alive is not approved
    if not approved:
        assert restored.state.last_vote_result['eliminated'] is None
        assert restored.state.last_vote_result['reason'] == 'confirmation_rejected'


def test_rejected_confirmation_preserves_tallies_not_elimination():
    e, ids = ballot()
    totals = e.state.last_vote_result['totals'].copy()
    for pid in e.state.players:
        e.submit_lynch_confirm(pid, False)
    e.resolve_lynch_confirmation_if_ready()
    assert e.state.players[ids['P1']].alive
    assert e.state.last_vote_result['eliminated'] is None
    assert e.state.last_vote_result['totals'] == totals


@pytest.mark.parametrize('role', [R.DON, R.MAFIA])
def test_single_mafia_has_mafia_faction(role):
    e, ids = make_engine_with_roles([role, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    for pid in list(e.state.players)[1:]:
        e.state.players[pid].alive = False
    assert WinConditionManager.check(e.state).faction == Faction.MAFIA


@pytest.mark.parametrize('attacker', [R.DON, R.MANIAC])
def test_neutral_players_prevent_premature_parity(attacker):
    e, _ = make_engine_with_roles([attacker, R.CITIZEN, R.MISTRESS, R.VAGABOND])
    assert WinConditionManager.check(e.state) is None


def test_silenced_player_cannot_confirm_and_does_not_delay_ballot():
    e, ids = ballot()
    e.state.players[ids['P2']].silenced = True
    with pytest.raises(EngineError):
        e.submit_lynch_confirm(ids['P2'], True)
    assert not e.get_player_view(ids['P2'])['me']['can_confirm']
    for pid in e.state.players:
        if pid != ids['P2']:
            e.submit_lynch_confirm(pid, False)
    assert e.resolve_lynch_confirmation_if_ready()


def test_silenced_player_does_not_delay_first_ballot():
    e, ids = make_engine_with_roles([R.DON, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    PhaseManager.to_voting(e.state)
    e.state.players[ids['P2']].silenced = True
    assert not e.get_player_view(ids['P2'])['me']['can_vote']
    with pytest.raises(EngineError):
        e.submit_vote(ids['P2'], ids['P1'])
    for pid in e.state.players:
        if pid != ids['P2']:
            e.submit_vote(pid, None)
    assert e.resolve_voting_if_ready()
    assert e.state.phase == Phase.VOTE_RESULTS
