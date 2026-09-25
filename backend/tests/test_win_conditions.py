from app.game_engine.roles import RoleName as R, Faction
from app.game_engine.managers import WinConditionManager, DeathManager
from tests.conftest import make_engine_with_roles


def test_town_wins_when_all_mafia_eliminated():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P0"]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.TOWN
    assert result.reason == "All Mafia and the Maniac eliminated"


def test_mafia_wins_when_mafia_outnumbers_the_rest():
    eng, ids = make_engine_with_roles([R.MAFIA, R.MAFIA, R.MAFIA, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    for p in ["P4", "P5", "P6", "P7"]:
        eng.state.players[ids[p]].alive = False
    # alive now: 3 mafia vs 1 citizen (P3)
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.MAFIA
    assert result.reason == "Mafia can no longer be outvoted"


def test_maniac_wins_when_mafia_gone_and_outnumbers_town():
    eng, ids = make_engine_with_roles([R.MAFIA, R.MANIAC, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    # kill the mafia, leaving maniac (P1) vs 1 citizen (P2)
    eng.state.players[ids["P0"]].alive = False
    for p in ["P3", "P4", "P5", "P6", "P7"]:
        eng.state.players[ids[p]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.NEUTRAL
    assert ids["P1"] in result.winners
    assert result.reason == "Maniac remains and the Mafia are gone"


def test_no_winner_mid_game():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    result = WinConditionManager.check(eng.state)
    assert result is None


def test_suicide_lynched_by_day_vote_is_individual_winner():
    eng, ids = make_engine_with_roles([R.MAFIA, R.SUICIDE, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    # town wins (all mafia gone, no maniac)
    DeathManager.eliminate(eng.state, ids["P0"], "mafia")
    # the Suicide (P1) is lynched by the day vote
    DeathManager.eliminate(eng.state, ids["P1"], "day_vote")
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.TOWN
    assert ids["P1"] in result.individual_winners
    assert ids["P1"] not in result.winners


def test_alive_mistress_rides_along_as_individual_winner():
    eng, ids = make_engine_with_roles([R.MAFIA, R.MISTRESS, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P0"]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.TOWN
    assert ids["P1"] in result.individual_winners


def test_alive_vagabond_rides_along_as_individual_winner():
    eng, ids = make_engine_with_roles([R.MAFIA, R.VAGABOND, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P0"]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.TOWN
    assert ids["P1"] in result.individual_winners


def test_lawyer_does_not_ride_along():
    eng, ids = make_engine_with_roles([R.MAFIA, R.LAWYER, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P0"]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.TOWN
    assert ids["P1"] not in result.individual_winners


def test_lone_maniac_wins_neutral():
    eng, ids = make_engine_with_roles([R.MAFIA, R.MANIAC, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    for p in ["P0", "P2", "P3", "P4", "P5", "P6", "P7"]:
        eng.state.players[ids[p]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.NEUTRAL
    assert result.winners == [ids["P1"]]
    assert result.reason == "Maniac is the last one standing"


def test_sole_remaining_town_wins():
    eng, ids = make_engine_with_roles([R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    for p in ["P0", "P2", "P3", "P4", "P5", "P6", "P7"]:
        eng.state.players[ids[p]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.TOWN
    assert result.winners == [ids["P1"]]
    assert result.reason == "The last player alive is Town"


def test_lone_neutral_survivor_wins_neutral():
    eng, ids = make_engine_with_roles([R.MAFIA, R.MISTRESS, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    for p in ["P0", "P2", "P3", "P4", "P5", "P6", "P7"]:
        eng.state.players[ids[p]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.NEUTRAL
    assert result.winners == [ids["P1"]]
    assert result.reason == "The last one standing wins"
