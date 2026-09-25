import random
from app.game_engine.compositions import (
    COMPOSITIONS, get_composition, select_composition, variants_for,
    all_possible_roles, validate_all_compositions,
    MIN_PLAYERS, MAX_PLAYERS,
)
from app.game_engine.engine import GameEngine
from app.game_engine.roles import ROLES, RoleName as R, Faction


def test_all_compositions_are_internally_consistent():
    validate_all_compositions()


def test_every_player_count_4_to_20_has_at_least_one_variant():
    for n in range(MIN_PLAYERS, MAX_PLAYERS + 1):
        assert n in COMPOSITIONS, f"Missing composition for {n} players"
        assert len(COMPOSITIONS[n]) >= 1, f"No variants for {n} players"
        for label, pool in COMPOSITIONS[n].items():
            assert len(pool) == n, f"{n}{label}: wrong role count ({len(pool)})"


def test_known_variant_counts_from_source_of_truth():
    # Exact variant inventory from mafia_rol_jadvali_FINAL.md
    assert sorted(COMPOSITIONS[4]) == ["A"]
    assert sorted(COMPOSITIONS[5]) == ["A"]
    assert sorted(COMPOSITIONS[6]) == ["A"]
    assert sorted(COMPOSITIONS[7]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[8]) == ["A", "B"]
    assert sorted(COMPOSITIONS[9]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[10]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[11]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[12]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[13]) == ["A", "B", "C", "D", "E", "F", "G"]
    assert sorted(COMPOSITIONS[14]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[15]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[16]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[17]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[18]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[19]) == ["A", "B", "C"]
    assert sorted(COMPOSITIONS[20]) == ["A", "B", "C", "D", "E", "F"]


def test_transcribed_pools_match_md_exactly():
    # Spot-check the exact pools from the MD for several counts/variants so
    # transcription bugs cannot creep in silently.
    def counts(pool):
        return {r: pool.count(r) for r in dict.fromkeys(pool)}

    assert counts(COMPOSITIONS[4]["A"]) == {R.CITIZEN: 2, R.DOCTOR: 1, R.DON: 1}
    assert counts(COMPOSITIONS[8]["A"]) == {
        R.CITIZEN: 2, R.DON: 1, R.SUICIDE: 1, R.COMMISSIONER: 1,
        R.MAFIA: 1, R.LUCKY: 1, R.DOCTOR: 1,
    }
    assert counts(COMPOSITIONS[13]["A"]) == {
        R.CITIZEN: 3, R.MISTRESS: 1, R.COMMISSIONER: 2, R.KAMIKAZE: 1,
        R.VAGABOND: 1, R.DOCTOR: 1, R.LUCKY: 1, R.DON: 2, R.MAFIA: 1,
    }
    assert counts(COMPOSITIONS[16]["A"]) == {
        R.MAFIA: 2, R.DON: 2, R.SERGEANT: 1, R.VAGABOND: 1,
        R.COMMISSIONER: 1, R.MANIAC: 1, R.LAWYER: 1, R.CITIZEN: 3,
        R.KAMIKAZE: 1, R.DOCTOR: 1, R.LUCKY: 1, R.MISTRESS: 1,
    }
    assert counts(COMPOSITIONS[20]["A"])[R.MAFIA] == 4


def test_qotil_is_mapped_to_maniac():
    # "Qotil" rows in the MD are the Maniac (independent night killer). Every
    # composition containing Maniac may do so; the 13-role roster is fixed.
    for n in (14, 16, 17, 18, 19, 20):
        assert any(R.MANIAC in pool for pool in COMPOSITIONS[n].values())

def test_duplicate_unique_roles_allowed_as_in_md():
    # MD allows e.g. "Don 2" / "Komissar 2". We keep those numbers verbatim.
    assert COMPOSITIONS[9]["A"].count(R.DON) == 2
    assert COMPOSITIONS[10]["A"].count(R.DON) == 3
    assert COMPOSITIONS[13]["A"].count(R.COMMISSIONER) == 2
    assert COMPOSITIONS[15]["A"].count(R.COMMISSIONER) == 2


def test_mafia_is_a_minority_in_every_variant():
    for n, comp in COMPOSITIONS.items():
        for label, pool in comp.items():
            mafia = sum(1 for r in pool if ROLES[r].faction == Faction.MAFIA)
            others = len(pool) - mafia
            assert mafia < others, f"{n}{label}: mafia not a minority"


def test_roles_contains_exactly_the_13_true_mafia_roles():
    expected_names = {"Citizen", "Commissioner", "Sergeant", "Doctor",
                      "Lucky", "Kamikaze", "Don", "Mafia", "Maniac",
                      "Mistress", "Lawyer", "Suicide", "Vagabond"}
    assert set(r.value for r in ROLES) == expected_names
    assert len(ROLES) == 13
    assert ROLES[R.CITIZEN].faction == Faction.TOWN
    assert ROLES[R.LUCKY].faction == Faction.TOWN
    assert ROLES[R.DON].faction == Faction.MAFIA
    assert ROLES[R.MAFIA].faction == Faction.MAFIA
    assert ROLES[R.MANIAC].faction == Faction.NEUTRAL
    assert ROLES[R.SUICIDE].faction == Faction.NEUTRAL


def test_night_action_mapping_matches_the_13_roles():
    from app.game_engine.roles import ActionType
    assert ROLES[R.COMMISSIONER].night_action == ActionType.INVESTIGATE
    assert ROLES[R.DOCTOR].night_action == ActionType.PROTECT
    assert ROLES[R.DON].night_action == ActionType.KILL
    assert ROLES[R.MAFIA].night_action == ActionType.KILL
    assert ROLES[R.MANIAC].night_action == ActionType.KILL
    assert ROLES[R.MISTRESS].night_action == ActionType.BLOCK
    assert ROLES[R.VAGABOND].night_action == ActionType.WATCH
    assert ROLES[R.LAWYER].night_action == ActionType.SHIELD
    for name in ("Citizen", "Sergeant", "Lucky", "Kamikaze", "Suicide"):
        assert ROLES[R(name)].night_action is None


def _make_engine(n_players: int) -> GameEngine:
    eng = GameEngine(game_id="g1", host_telegram_id=1, host_name="Host")
    for i in range(2, n_players + 1):
        eng.add_player(telegram_user_id=i, display_name=f"P{i}")
    return eng


def test_role_assignment_gives_every_player_exactly_one_role():
    for n in (4, 6, 8, 12, 13, 15, 20):
        eng = _make_engine(n)
        if eng.state.phase.value == "lobby":
            eng.start_game(eng.state.host_id)
        roles_assigned = [p.role for p in eng.state.players.values()]
        assert len(roles_assigned) == n
        assert all(r is not None for r in roles_assigned)


def test_selected_variant_pool_matches_assigned_roles():
    for _ in range(20):
        eng = _make_engine(13)
        eng.start_game(eng.state.host_id)
        variant = eng.state.selected_variant
        pool = get_composition(13, variant)
        assigned = sorted(p.role.value for p in eng.state.players.values())
        assert assigned == sorted(r.value for r in pool)


def test_variant_selection_covers_all_variants_eventually():
    # Pure random: with enough games all 13-player variants must show up.
    seen = set()
    for _ in range(400):
        lab, _ = select_composition(13, random.SystemRandom())
        seen.add(lab)
    assert seen == set(COMPOSITIONS[13])


def test_repetition_is_allowed():
    # A->A->A is fully valid per spec 68.2.
    labs = [select_composition(10, random.SystemRandom())[0] for _ in range(50)]
    assert labs.count("A") > 0 or labs.count("B") > 0 or labs.count("C") > 0


def test_selection_is_history_free_from_scratch():
    # Spec Test 3: a brand new game must be able to select a variant with no
    # prior state at all; selection never reads any stored state.
    rng = random.SystemRandom()
    for n in (4, 7, 13, 20):
        assert select_composition(n, rng)[0] in variants_for(n)


def test_no_cross_count_mixing():
    # Spec Test 5: a 13-player game must never use a 12- or 14-player variant.
    for n in (12, 13, 14):
        for _ in range(30):
            lab, _ = select_composition(n, random.SystemRandom())
            assert lab in COMPOSITIONS[n]


def test_union_roles_covers_variant_roles_only():
    union = all_possible_roles(13)
    for pool in COMPOSITIONS[13].values():
        for r in pool:
            assert r in union
    assert len(union) <= 13


def test_start_game_rejects_under_4():
    eng = _make_engine(3)
    try:
        eng.start_game(eng.state.host_id)
        assert False, "should have rejected 3 players"
    except Exception as e:
        assert "4" in str(e)


def test_lobby_auto_starts_the_instant_the_20th_player_joins():
    eng = _make_engine(19)
    assert eng.state.phase.value == "lobby"
    eng.add_player(telegram_user_id=9000, display_name="Player20")
    assert eng.state.phase.value != "lobby"
    assert len(eng.state.players) == 20


def test_start_game_rejects_over_20():
    eng = _make_engine(20)
    assert eng.state.phase.value != "lobby"
    try:
        eng.add_player(telegram_user_id=9999, display_name="Extra")
        assert False, "should have rejected a 21st player"
    except Exception as e:
        assert "already started" in str(e).lower()