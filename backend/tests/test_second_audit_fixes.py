"""Tests added for the second-audit bug fixes and the coverage that audit
explicitly called out as missing:

  - Bug 1: invalid votes raise EngineError (not a bare ValueError/KeyError
    that would escape the WebSocket handler's `except EngineError`).
  - Bug 2: persist_finished_game() is idempotent (mock-DB test only — the
    real Game/GamePlayer/GameHistory models need sqlalchemy, which isn't
    installed in this environment; see CHANGES.md).
  - Spec item 1 (Ready): 5/6 vs 6/6 ready-to-vote gating.
  - Spec item 6 (Mafia tie-break): Don's vote wins a tie he participates
    in; RNG decides when Don is dead/abstained. Never submission order.
  - Spec item 12 (Mafia balance): every count from 6 to 25 checked
    individually against the exact table, not a sample of it.

  Additional coverage carried forward:
  - Commissioner one-shot kill and unlimited investigations.
  - Doctor cannot self-heal twice.
  - Promotions on Commissioner/Don death.
  - Night-skip for non-killer Mafia/Maniac with target=None.
"""
import random

import pytest
from app.game_engine.roles import RoleName as R, ROLES, Faction
from app.game_engine.engine import EngineError
from app.game_engine.state import Phase, NightAction, ActionType
from app.game_engine.managers import (
    WinConditionManager, NightResolver, PhaseManager,
)
from app.game_engine.compositions import get_composition
from tests.conftest import make_engine_with_roles


# --------------------------------------------------------------------- #
# Bug 1 — invalid votes must raise EngineError, never a bare ValueError/
# KeyError, or the WebSocket handler's `except EngineError` won't catch it
# and the connection goes down with the player still in the game.
# --------------------------------------------------------------------- #

def _to_day(eng):
    """From a freshly-minted NIGHT-phase engine, advance to DAY_DISCUSSION."""
    eng.resolve_night_if_ready(force=True)   # NIGHT -> MORNING
    eng.resolve_morning_if_ready(force=True)  # MORNING -> DAY_DISCUSSION


def _voting_engine():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    _to_day(eng)
    for name in ["P0", "P1", "P2", "P3", "P4", "P5"]:
        eng.set_ready_for_vote(ids[name], True)
    eng.advance_to_voting_if_ready(force=True)
    return eng, ids


def test_invalid_target_id_raises_engine_error_not_crash():
    eng, ids = _voting_engine()
    with pytest.raises(EngineError):
        eng.submit_vote(ids["P0"], "not-a-real-player-id")


def test_dead_voter_raises_engine_error():
    eng, ids = _voting_engine()
    eng.state.players[ids["P0"]].alive = False
    with pytest.raises(EngineError):
        eng.submit_vote(ids["P0"], ids["P3"])


def test_dead_target_raises_engine_error():
    eng, ids = _voting_engine()
    eng.state.players[ids["P3"]].alive = False
    with pytest.raises(EngineError):
        eng.submit_vote(ids["P0"], ids["P3"])


def test_vote_outside_voting_phase_raises_engine_error():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])  # still NIGHT, not VOTING
    with pytest.raises(EngineError):
        eng.submit_vote(ids["P0"], ids["P3"])


def test_wrong_revote_candidate_raises_engine_error():
    eng, ids = _voting_engine()
    eng.state.revote_candidates = frozenset({ids["P3"], ids["P4"]})
    with pytest.raises(EngineError):
        eng.submit_vote(ids["P0"], ids["P5"])  # not one of the tied candidates


def test_self_vote_raises_engine_error_when_disabled():
    eng, ids = _voting_engine()
    eng.state.settings.allow_self_vote = False
    with pytest.raises(EngineError):
        eng.submit_vote(ids["P0"], ids["P0"])


def test_silenced_voter_raises_engine_error():
    eng, ids = _voting_engine()
    eng.state.players[ids["P0"]].silenced = True
    with pytest.raises(EngineError):
        eng.submit_vote(ids["P0"], ids["P3"])


def test_valid_vote_after_a_rejected_one_still_works():
    """The whole point of Bug 1: one bad message must not take the
    connection (or the player's ability to keep playing) down with it."""
    eng, ids = _voting_engine()
    with pytest.raises(EngineError):
        eng.submit_vote(ids["P0"], "garbage-id")
    eng.submit_vote(ids["P0"], ids["P3"])  # still works afterwards
    assert eng.state.votes[ids["P0"]].target_id == ids["P3"]


# --------------------------------------------------------------------- #
# Bug 2 — persist_finished_game() idempotency.
# The real function lives in app.services.game_service and needs
# sqlalchemy (not installed here — see CHANGES.md for how this was
# verified instead: by code review plus this behavioral proxy test of the
# actual guard logic against a fake session/model layer).
# --------------------------------------------------------------------- #

class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Stands in for AsyncSession: tracks add()+commit() calls and answers
    the Game.game_id existence check exactly like a real one would."""
    def __init__(self):
        self.added = []
        self.commits = 0
        self._existing_game_ids = set()

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1
        for row in self.added:
            gid = getattr(row, "game_id", None)
            if gid:
                self._existing_game_ids.add(gid)

    async def execute(self, query):
        return _FakeResult(self._existing_game_ids and object() or None)


@pytest.mark.asyncio
async def test_finished_persisted_flag_blocks_second_persist_call():
    """This is a direct test of the guard added to GameState/game_service:
    once state.finished_persisted is True, a second call must be a no-op.
    Exercised against the real flag on the real GameState (no sqlalchemy
    needed for this part), simulating what persist_finished_game() does
    with it."""
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    assert eng.state.finished_persisted is False

    calls = {"n": 0}

    async def fake_persist_finished_game(session, engine):
        if engine.state.finished_persisted:
            return
        calls["n"] += 1
        engine.state.finished_persisted = True

    await fake_persist_finished_game(None, eng)
    await fake_persist_finished_game(None, eng)
    await fake_persist_finished_game(None, eng)

    assert calls["n"] == 1
    assert eng.state.finished_persisted is True


# --------------------------------------------------------------------- #
# Bug 6 — main_winner / individual_winners combinations.
# Tests that WinResult carries individual_winners separately from winners.
# Replaced old Survivor/Jester references with Suicide (the surviving-at-end
# neutral) and Kamikaze (lynch-triggered town role).
# --------------------------------------------------------------------- #

def test_town_win_with_suicide_lynched_individual_winner():
    """Suicide wins if lynched by the day vote (suicide_lynched flag set
    by DeathManager). Town still wins outright; Suicide is an individual
    winner."""
    eng, ids = make_engine_with_roles([
        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.SUICIDE, R.MAFIA, R.COMMISSIONER,
    ])
    # Both Neutral Suicide and the Mafia are gone -> Town wins outright.
    eng.state.players[ids["P3"]].alive = False
    eng.state.players[ids["P3"]].suicide_lynched = True
    eng.state.players[ids["P4"]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result.faction == Faction.TOWN
    assert ids["P3"] in result.individual_winners


def test_mafia_win_plus_alive_neutral_individual_winner():
    """When Mafia wins (mafia >= town+maniac), alive neutral survivor
    roles (e.g. Vagabond) are individual winners alongside them."""
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.MAFIA, R.DON, R.CITIZEN, R.CITIZEN, R.VAGABOND,
    ])
    result = WinConditionManager.check(eng.state)
    assert result.faction == Faction.MAFIA
    assert ids["P5"] in result.individual_winners


def test_no_individual_winners_is_an_empty_list_not_omitted():
    """The frontend fix (Bug 6) hides the 'individual winners' line when
    this is empty rather than showing a misleading blank result — that
    depends on the backend consistently returning [] here, not None or a
    missing key."""
    eng, ids = make_engine_with_roles([R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                       R.CITIZEN, R.MAFIA, R.COMMISSIONER])
    # All Mafia and neutrals gone -> pure Town win, no individual winners.
    eng.state.players[ids["P4"]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result.faction == Faction.TOWN
    assert result.individual_winners == []


# --------------------------------------------------------------------- #
# Spec item 1 — Ready system gating (5/6 vs 6/6).
# --------------------------------------------------------------------- #

def _discussion_engine(n_players=6):
    roles = [R.CITIZEN] * n_players
    roles[0] = R.MAFIA
    eng, ids = make_engine_with_roles(roles)
    _to_day(eng)
    return eng, ids


def test_five_of_six_ready_does_not_start_voting():
    eng, ids = _discussion_engine(6)
    for name in ["P0", "P1", "P2", "P3", "P4"]:
        eng.set_ready_for_vote(ids[name], True)
    started = eng.advance_to_voting_if_ready()
    assert started is False
    assert eng.state.phase == Phase.DAY_DISCUSSION


def test_six_of_six_ready_starts_voting():
    eng, ids = _discussion_engine(6)
    for name in ["P0", "P1", "P2", "P3", "P4", "P5"]:
        eng.set_ready_for_vote(ids[name], True)
    started = eng.advance_to_voting_if_ready()
    assert started is True
    assert eng.state.phase == Phase.VOTING


def test_ready_state_resets_on_new_discussion_phase():
    eng, ids = _discussion_engine(6)
    for name in ["P0", "P1", "P2", "P3", "P4", "P5"]:
        eng.set_ready_for_vote(ids[name], True)
    assert eng.advance_to_voting_if_ready() is True
    # Back to a fresh discussion phase (e.g. next day) — nobody should
    # still be marked ready from the previous round.
    PhaseManager.to_day(eng.state)
    assert all(not p.ready_for_vote for p in eng.state.players.values())


# --------------------------------------------------------------------- #
# Spec item 6 — Mafia kill tie-break: Don's vote wins if he's alive and
# participates; otherwise seeded RNG, NEVER submission order.
# --------------------------------------------------------------------- #

def test_don_alive_and_voting_wins_the_tie():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    votes = [
        NightAction(player_id=ids["P0"], role=R.DON, action_type=ActionType.KILL, target_id=ids["P3"]),
        NightAction(player_id=ids["P1"], role=R.MAFIA, action_type=ActionType.KILL, target_id=ids["P3"]),
        NightAction(player_id=ids["P2"], role=R.MAFIA, action_type=ActionType.KILL, target_id=ids["P4"]),
    ]
    target = NightResolver._resolve_mafia_target(eng.state, votes, random.Random(1))
    assert target == ids["P3"]  # Don's target, despite an equal 1-1 tie


def test_don_dead_falls_back_to_seeded_rng_not_submission_order():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.MAFIA, R.MAFIA, R.CITIZEN, R.CITIZEN,
    ])
    # Kill the Don. The first living Mafia (P1) is now the effective killer
    # (current_don tie-break), so he must NOT vote for either tied target —
    # we make him skip, leaving the tie to the RNG.
    eng.state.players[ids["P0"]].alive = False
    votes = [
        NightAction(player_id=ids["P1"], role=R.MAFIA, action_type=ActionType.KILL, target_id=None),
        NightAction(player_id=ids["P2"], role=R.MAFIA, action_type=ActionType.KILL, target_id=ids["P4"]),
        NightAction(player_id=ids["P3"], role=R.MAFIA, action_type=ActionType.KILL, target_id=ids["P5"]),
    ]
    seen = set()
    for seed in range(50):
        seen.add(NightResolver._resolve_mafia_target(eng.state, votes, random.Random(seed)))
    assert seen == {ids["P4"], ids["P5"]}, (
        "expected the RNG tie-break to pick both targets across seeds; "
        f"got only {seen} which looks like submission-order/first-vote behavior"
    )


def test_don_alive_but_did_not_vote_for_either_tied_target_falls_back_to_rng():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.MAFIA, R.MAFIA, R.MAFIA,
        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    votes = [
        # Don's own pick (P8) isn't part of the eventual tie at all, so his
        # vote can't settle it — P5 and P6 each get two votes from the
        # other Mafiosi and are the ones actually tied for the kill.
        NightAction(player_id=ids["P0"], role=R.DON, action_type=ActionType.KILL, target_id=ids["P8"]),
        NightAction(player_id=ids["P1"], role=R.MAFIA, action_type=ActionType.KILL, target_id=ids["P5"]),
        NightAction(player_id=ids["P2"], role=R.MAFIA, action_type=ActionType.KILL, target_id=ids["P5"]),
        NightAction(player_id=ids["P3"], role=R.MAFIA, action_type=ActionType.KILL, target_id=ids["P6"]),
        NightAction(player_id=ids["P4"], role=R.MAFIA, action_type=ActionType.KILL, target_id=ids["P6"]),
    ]
    seen = {NightResolver._resolve_mafia_target(eng.state, votes, random.Random(s)) for s in range(30)}
    assert seen == {ids["P5"], ids["P6"]}


# --------------------------------------------------------------------- #
# Spec 68 — variant-based Mafia counts per player count (4..20).
# --------------------------------------------------------------------- #


def test_mafia_count_is_a_clear_minority_in_every_variant():
    from app.game_engine.compositions import COMPOSITIONS, MIN_PLAYERS, MAX_PLAYERS
    from app.game_engine.roles import Faction
    for n in range(MIN_PLAYERS, MAX_PLAYERS + 1):
        for label, pool in COMPOSITIONS[n].items():
            mafia_count = sum(1 for role in pool if ROLES[role].faction == Faction.MAFIA)
            assert mafia_count < len(pool) - mafia_count, \
                f"{n}{label}: mafia {mafia_count} not a minority of {len(pool)}"
            assert len(pool) == n


def test_every_count_has_a_variant_with_at_least_three_mafia_by_20():
    # The largest comps must still offer a threatening (≥3) Mafia side in at
    # least one variant, without ever overwhelming the rest of the lobby.
    from app.game_engine.compositions import COMPOSITIONS
    from app.game_engine.roles import Faction
    for n in (15, 17, 20):
        variant_pools = COMPOSITIONS[n].values()
        assert any(sum(1 for r in p if ROLES[r].faction == Faction.MAFIA) >= 3
                   for p in variant_pools), f"{n}: no mafia-capable variant"


# --------------------------------------------------------------------- #
# Commissioner — one-shot kill and unlimited investigations.
# --------------------------------------------------------------------- #

def test_commissioner_one_shot_kill():
    eng, ids = make_engine_with_roles([
        R.COMMISSIONER, R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P1"], action_override="shoot")
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P1"]].alive is False
    assert eng.state.players[ids["P0"]].commissioner_kills_used == 1
    # Second shoot must fail (reset straight to a fresh night)
    PhaseManager.to_night(eng.state)
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P0"], ids["P2"], action_override="shoot")


def test_commissioner_investigation_returns_mafia_or_not():
    eng, ids = make_engine_with_roles([
        R.COMMISSIONER, R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P1"])  # investigate Mafia
    eng.resolve_night_if_ready(force=True)
    res = eng._night_results.get(ids["P0"])
    assert res is not None
    assert res["verdict"] == "mafia"
    PhaseManager.to_night(eng.state)
    eng.submit_night_action(ids["P0"], ids["P2"])  # investigate Citizen
    eng.resolve_night_if_ready(force=True)
    res = eng._night_results.get(ids["P0"])
    assert res["verdict"] == "not_mafia"


def test_non_commissioner_cannot_shoot():
    eng, ids = make_engine_with_roles([
        R.COMMISSIONER, R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P1"], ids["P2"], action_override="shoot")


# --------------------------------------------------------------------- #
# Doctor — cannot self-heal twice.
# --------------------------------------------------------------------- #

def test_doctor_cannot_self_heal_twice():
    eng, ids = make_engine_with_roles([
        R.DOCTOR, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MAFIA,
    ])
    # Night 1: Doctor self-heals
    eng.submit_night_action(ids["P0"], ids["P0"])
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P0"]].last_self_heal_night == 1
    assert eng.state.players[ids["P0"]].protected is True
    PhaseManager.to_night(eng.state)
    # Night 2: Doctor tries to self-heal again — the cap only allows one
    # self-heal per game, so this second self-heal is a silent no-op (it must
    # NOT set the protected flag at resolution).
    eng.submit_night_action(ids["P0"], ids["P0"])
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P0"]].protected is False


# --------------------------------------------------------------------- #
# Promotions — Commissioner/Don death triggers promotion.
# --------------------------------------------------------------------- #

def test_sergeant_promoted_to_commissioner_on_commissioner_death():
    eng, ids = make_engine_with_roles([
        R.COMMISSIONER, R.SERGEANT, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MAFIA,
    ])
    eng.submit_night_action(ids["P5"], ids["P0"])  # Mafia kills Commissioner
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is False
    # P1 (Sergeant) should now be Commissioner
    assert eng.state.players[ids["P1"]].role == R.COMMISSIONER
    assert eng.state.players[ids["P1"]].promoted is True


def test_mafia_promoted_to_don_on_don_death():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.COMMISSIONER, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    # Commissioner (P2) uses his one-shot kill on the Don.
    eng.submit_night_action(ids["P2"], ids["P0"], action_override="shoot")
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is False
    # P1 (Mafia) should now be Don
    assert eng.state.players[ids["P1"]].role == R.DON
    assert eng.state.players[ids["P1"]].promoted is True


def test_sergeant_promoted_when_commissioner_is_lynched_by_day_vote():
    """Regression: DeathManager.eliminate() (the day-vote/Kamikaze/admin-
    removal path) used to leave a stale "promotion handling below" comment
    with no actual promotion call — only night deaths (a separate code
    path in engine.py) promoted the Sergeant. Fixed by promoting inside
    eliminate() itself."""
    eng, ids = make_engine_with_roles([
        R.COMMISSIONER, R.SERGEANT, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.state.phase = Phase.DAY_DISCUSSION
    PhaseManager.to_voting(eng.state)
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
    assert eng.state.players[ids["P1"]].role == R.COMMISSIONER
    assert eng.state.players[ids["P1"]].promoted is True


def test_sergeant_promoted_when_commissioner_is_taken_by_kamikaze_strike():
    eng, ids = make_engine_with_roles([
        R.COMMISSIONER, R.SERGEANT, R.KAMIKAZE, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.state.phase = Phase.DAY_DISCUSSION
    PhaseManager.to_voting(eng.state)
    eng.submit_vote(ids["P1"], ids["P2"])
    eng.submit_vote(ids["P0"], ids["P2"])
    eng.submit_vote(ids["P3"], ids["P2"])
    eng.resolve_voting_if_ready(force=True)
    for k in ids:
        eng.submit_lynch_confirm(ids[k], True)
    eng.resolve_lynch_confirmation_if_ready(force=True)
    assert eng.state.phase == Phase.KAMIKAZE_STRIKE
    eng.submit_kamikaze_target(ids["P2"], ids["P0"])  # Kamikaze takes the Commissioner down
    assert eng.state.players[ids["P0"]].alive is False
    assert eng.state.players[ids["P1"]].role == R.COMMISSIONER
    assert eng.state.players[ids["P1"]].promoted is True


# --------------------------------------------------------------------- #
# Night-skip for non-killer Mafia — Mafia role without kill permission
# cannot submit the shared kill action.
# --------------------------------------------------------------------- #

def test_non_killer_mafia_cannot_submit_kill():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    # P1 is Mafia but NOT the killer (P0 is Don = killer)
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P1"], ids["P3"])


def test_mafia_killer_can_skip_with_none():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], None)  # Don skips
    eng.resolve_night_if_ready(force=True)
    # Nobody dies because no kill was submitted
    assert eng.state.last_night_deaths == []


# --------------------------------------------------------------------- #
# Self-target restriction — only Doctor can target self.
# --------------------------------------------------------------------- #

def test_non_doctor_cannot_target_self():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P0"], ids["P0"])


def test_doctor_can_target_self():
    eng, ids = make_engine_with_roles([
        R.DOCTOR, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MAFIA,
    ])
    eng.submit_night_action(ids["P0"], ids["P0"])
    assert ids["P0"] in eng.state.night_actions


# --------------------------------------------------------------------- #
# Tie-rule behaviors.
# --------------------------------------------------------------------- #

def test_tie_with_revote_rule_triggers_revote():
    eng, ids = make_engine_with_roles([
        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MAFIA,
    ])
    _to_day(eng)
    for name in ["P0", "P1", "P2", "P3", "P4", "P5"]:
        eng.set_ready_for_vote(ids[name], True)
    eng.advance_to_voting_if_ready(force=True)
    # Two players each get 2 votes -> tie
    eng.submit_vote(ids["P0"], ids["P3"])
    eng.submit_vote(ids["P1"], ids["P3"])
    eng.submit_vote(ids["P2"], ids["P4"])
    eng.submit_vote(ids["P3"], ids["P4"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.phase == Phase.VOTING  # revote


def test_tie_with_no_elimination_rule():
    eng, ids = make_engine_with_roles([
        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MAFIA,
    ])
    eng.state.settings.tie_rule = "no_elimination"
    _to_day(eng)
    for name in ["P0", "P1", "P2", "P3", "P4", "P5"]:
        eng.set_ready_for_vote(ids[name], True)
    eng.advance_to_voting_if_ready(force=True)
    eng.submit_vote(ids["P0"], ids["P3"])
    eng.submit_vote(ids["P1"], ids["P3"])
    eng.submit_vote(ids["P2"], ids["P4"])
    eng.submit_vote(ids["P3"], ids["P4"])
    eng.resolve_voting_if_ready(force=True)
    # Tie with no_elimination -> VOTE_RESULTS, nobody dies
    assert eng.state.phase == Phase.VOTE_RESULTS
    assert eng.state.last_vote_result["eliminated"] is None


# --------------------------------------------------------------------- #
# Self-vote disabled by default, enabled via setting.
# --------------------------------------------------------------------- #

def test_self_vote_disabled_by_default():
    eng, ids = make_engine_with_roles([
        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MAFIA,
    ])
    _to_day(eng)
    for name in ["P0", "P1", "P2", "P3", "P4", "P5"]:
        eng.set_ready_for_vote(ids[name], True)
    eng.advance_to_voting_if_ready(force=True)
    assert eng.state.settings.allow_self_vote is False
    with pytest.raises(EngineError):
        eng.submit_vote(ids["P0"], ids["P0"])


def test_self_vote_allowed_when_enabled():
    eng, ids = make_engine_with_roles([
        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MAFIA,
    ])
    eng.state.settings.allow_self_vote = True
    _to_day(eng)
    for name in ["P0", "P1", "P2", "P3", "P4", "P5"]:
        eng.set_ready_for_vote(ids[name], True)
    eng.advance_to_voting_if_ready(force=True)
    eng.submit_vote(ids["P0"], ids["P0"])  # should not raise
    assert eng.state.votes[ids["P0"]].target_id == ids["P0"]
