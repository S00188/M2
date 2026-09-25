import pytest
from app.game_engine.engine import EngineError
from app.game_engine.roles import RoleName as R
from app.game_engine.state import Phase
from tests.conftest import make_engine_with_roles


def test_mafia_kill_with_no_protection_kills_target():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])  # designated mafia killer -> P3
    ok = eng.resolve_night_if_ready(force=True)
    assert ok
    assert eng.state.players[ids["P3"]].alive is False
    assert eng.state.players[ids["P3"]].death_reason == "mafia"


def test_doctor_protects_target_from_mafia_kill():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])   # mafia -> P3
    eng.submit_night_action(ids["P2"], ids["P3"])   # doctor protects P3
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P3"]].alive is True


def test_doctor_can_self_heal_only_once_per_game():
    from app.game_engine.managers import PhaseManager
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    # Night 1: doctor self-heals while mafia targets someone else — allowed.
    eng.submit_night_action(ids["P0"], ids["P3"])
    eng.submit_night_action(ids["P2"], ids["P2"])
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is True

    # Night 2: the one-time self-heal is consumed, so a second self-heal is
    # silently skipped in resolution and the doctor dies to a mafia hit.
    PhaseManager.to_night(eng.state)
    eng.submit_night_action(ids["P0"], ids["P2"])
    eng.submit_night_action(ids["P2"], ids["P2"])
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is False


def test_doctor_cannot_self_heal_again_after_skipping_a_night():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    doc = eng.state.players[ids["P2"]]
    doc.last_self_heal_night = 1  # self-heal already used earlier in the game
    eng.submit_night_action(ids["P0"], ids["P2"])   # mafia -> doctor
    eng.submit_night_action(ids["P2"], ids["P2"])   # self-heal no longer available
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is False


def test_commissioner_clean_read_on_citizen():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P1"], ids["P3"])   # commissioner investigates citizen P3
    eng.resolve_night_if_ready(force=True)
    result = eng.get_player_view(ids["P1"])["me"]["night_result"]
    assert result["verdict"] == "not_mafia"


def test_commissioner_reads_mafia_role_as_mafia():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P2"], ids["P0"])  # commissioner investigates Don -> mafia
    eng.resolve_night_if_ready(force=True)
    result = eng.get_player_view(ids["P2"])["me"]["night_result"]
    assert result["verdict"] == "mafia"


def test_lawyer_shields_chosen_client_from_investigation():
    eng, ids = make_engine_with_roles([
        R.DON, R.LAWYER, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P1"], ids["P0"])   # lawyer picks the Don as client
    eng.submit_night_action(ids["P2"], ids["P0"])   # commissioner investigates the Don
    eng.resolve_night_if_ready(force=True)
    result = eng.get_player_view(ids["P2"])["me"]["night_result"]
    # Without the shield this would read "mafia" (see
    # test_commissioner_reads_mafia_role_as_mafia) — the point of the role.
    assert result["verdict"] == "not_mafia"


def test_lawyer_cannot_target_self():
    eng, ids = make_engine_with_roles([
        R.DON, R.LAWYER, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P1"], ids["P1"])


def test_lawyer_shield_does_not_apply_to_a_different_target():
    eng, ids = make_engine_with_roles([
        R.DON, R.LAWYER, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P1"], ids["P3"])   # lawyer shields an innocent citizen
    eng.submit_night_action(ids["P2"], ids["P0"])   # commissioner investigates the Don instead
    eng.resolve_night_if_ready(force=True)
    result = eng.get_player_view(ids["P2"])["me"]["night_result"]
    assert result["verdict"] == "mafia"


def test_mistress_block_cancels_lawyer_shield():
    eng, ids = make_engine_with_roles([
        R.DON, R.LAWYER, R.COMMISSIONER, R.MISTRESS, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P3"], ids["P1"])   # mistress blocks the lawyer
    eng.submit_night_action(ids["P1"], ids["P0"])   # lawyer still tries to shield the Don
    eng.submit_night_action(ids["P2"], ids["P0"])   # commissioner investigates the Don
    eng.resolve_night_if_ready(force=True)
    result = eng.get_player_view(ids["P2"])["me"]["night_result"]
    assert result["verdict"] == "mafia"


def test_doctor_protection_blocks_every_killer():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.MANIAC, R.DOCTOR, R.COMMISSIONER, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    # Both the mafia team and the Maniac hit the same Doctor-protected citizen.
    eng.submit_night_action(ids["P0"], ids["P3"])   # mafia -> P3
    eng.submit_night_action(ids["P1"], ids["P3"])   # maniac -> P3
    eng.submit_night_action(ids["P2"], ids["P3"])   # doctor protects P3
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P3"]].alive is True
    assert eng.state.players[ids["P0"]].alive is True
    assert eng.state.players[ids["P1"]].alive is True


def test_vagabond_watch_reports_visitors():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.VAGABOND, R.CITIZEN, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P2"])   # mafia visits P2
    eng.submit_night_action(ids["P1"], ids["P2"])   # vagabond watches P2
    eng.resolve_night_if_ready(force=True)
    result = eng.get_player_view(ids["P1"])["me"]["night_result"]
    assert ids["P0"] in result["visitors"]


def test_maniac_kills_independently_of_mafia():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.MANIAC, R.CITIZEN, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P2"])   # mafia -> P2
    eng.submit_night_action(ids["P1"], ids["P3"])   # maniac -> P3
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is False
    assert eng.state.players[ids["P3"]].alive is False
    assert eng.state.players[ids["P2"]].death_reason == "mafia"
    assert eng.state.players[ids["P3"]].death_reason == "maniac"


def test_mafia_mistress_blocks_a_kill_action():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.MISTRESS, R.CITIZEN, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P1"], ids["P0"])   # mistress blocks the mafia killer
    eng.submit_night_action(ids["P0"], ids["P2"])   # mafia kill -> dropped
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is True


def test_only_first_mafia_can_kill_without_don():
    from app.game_engine.engine import EngineError
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.MAFIA, R.CITIZEN, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    # P0 (first Mafia) is the designated killer — accepted.
    eng.submit_night_action(ids["P0"], ids["P2"])
    assert ids["P0"] in eng.state.night_actions
    # P1 (second Mafia) is rejected.
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P1"], ids["P3"])
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is False
    assert eng.state.players[ids["P3"]].alive is True


# --------------------------------------------------------------------- #
# Don / Mafia kill delegation
# --------------------------------------------------------------------- #

def test_only_don_can_submit_mafia_kill_while_alive():
    from app.game_engine.engine import EngineError
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    # Don (P0) is alive and is the designated killer — his kill is accepted.
    eng.submit_night_action(ids["P0"], ids["P3"])
    assert ids["P0"] in eng.state.night_actions
    # The Mafia's kill submission is rejected outright.
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P1"], ids["P4"])
    assert ids["P1"] not in eng.state.night_actions


def test_mafia_inherits_kill_after_don_dies():
    from app.game_engine.engine import EngineError
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    don = eng.state.players[ids["P0"]]
    don.alive = False  # Don dies before night
    eng.state.night_actions.clear()
    # Now the first living Mafia (P1) is the designated killer.
    eng.submit_night_action(ids["P1"], ids["P3"])
    assert ids["P1"] in eng.state.night_actions


def test_non_killer_mafia_gets_no_kill_ui_in_view():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    don_view = eng.get_player_view(ids["P0"])["me"]
    mafia_view = eng.get_player_view(ids["P1"])["me"]
    assert don_view["night_action_type"] == "kill"
    assert don_view["is_mafia_killer"] is True
    assert mafia_view["night_action_type"] is None
    assert mafia_view["is_mafia_killer"] is False


def test_mafia_becomes_killer_in_view_after_don_dies():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIA, R.MAFIA, R.COMMISSIONER, R.DOCTOR,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.state.players[ids["P0"]].alive = False  # Don dies
    v1 = eng.get_player_view(ids["P1"])["me"]
    v2 = eng.get_player_view(ids["P2"])["me"]
    assert v1["is_mafia_killer"] is True
    assert v1["night_action_type"] == "kill"
    assert v2["is_mafia_killer"] is False
    assert v2["night_action_type"] is None


# --------------------------------------------------------------------- #
# Public death announcements + last words in chat
# --------------------------------------------------------------------- #

def test_night_death_announced_in_public_chat_with_killer_and_victim_roles():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])  # mafia kills citizen P3
    eng.resolve_night_if_ready(force=True)
    deaths = [m for m in eng.state.chat_messages if m.kind == "death"]
    assert len(deaths) == 1
    d = deaths[0]
    assert d.payload["victim"] == ids["P3"]
    assert d.payload["killer_role"] == "Mafia"
    assert d.payload["victim_role"] == "Citizen"
    chat = eng.get_player_view(ids["P2"])["chat"]
    sys = [m for m in chat if m["kind"] == "death"]
    assert len(sys) == 1
    assert sys[0]["payload"]["victim_role"] == "Citizen"


def test_death_announcement_hides_victim_role_when_reveal_disabled():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.state.settings.reveal_role_on_death = False
    eng.submit_night_action(ids["P0"], ids["P3"])
    eng.resolve_night_if_ready(force=True)
    d = [m for m in eng.state.chat_messages if m.kind == "death"][0]
    assert d.payload["victim_role"] is None


def test_night_killed_player_leaves_last_words_during_day_discussion():
    from app.game_engine.engine import EngineError
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])
    eng.resolve_night_if_ready(force=True)
    eng.resolve_morning_if_ready(force=True)
    assert eng.state.phase == Phase.DAY_DISCUSSION
    me = eng.get_player_view(ids["P3"])["me"]
    assert me["can_last_words"] is True
    assert me["last_words"] is None
    eng.submit_last_words(ids["P3"], "Men shaharni sevaman!")
    lw = [m for m in eng.state.chat_messages if m.kind == "last_words"]
    assert len(lw) == 1
    assert lw[0].text == "Men shaharni sevaman!"
    assert lw[0].payload["victim"] == ids["P3"]
    assert lw[0].display_name == "P3"
    with pytest.raises(EngineError):
        eng.submit_last_words(ids["P3"], "Yana so'z")
    me = eng.get_player_view(ids["P3"])["me"]
    assert me["can_last_words"] is False
    assert me["last_words"] == "Men shaharni sevaman!"


def test_alive_player_cannot_leave_last_words():
    from app.game_engine.engine import EngineError
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])
    eng.resolve_night_if_ready(force=True)
    eng.resolve_morning_if_ready(force=True)
    assert eng.get_player_view(ids["P2"])["me"]["can_last_words"] is False
    with pytest.raises(EngineError):
        eng.submit_last_words(ids["P2"], "Men hali tirikman")


def test_commissioner_one_shot_shoot_death_announced_in_public_chat():
    eng, ids = make_engine_with_roles([
        R.MAFIA, R.COMMISSIONER, R.CITIZEN, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P1"], ids["P3"], action_override="shoot")
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P3"]].alive is False
    deaths = [m for m in eng.state.chat_messages if m.kind == "death"]
    assert len(deaths) == 1
    d = deaths[0]
    assert d.payload["killer_role"] == "Commissioner"


def test_day_vote_death_announced_in_public_chat():
    from app.game_engine.managers import PhaseManager
    eng, ids = make_engine_with_roles([R.CITIZEN] * 8)
    PhaseManager.to_voting(eng.state)
    for pid in ids.values():
        if pid != ids["P3"]:
            eng.submit_vote(pid, ids["P3"])
    eng.submit_vote(ids["P3"], None)
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.phase == Phase.LYNCH_CONFIRMATION
    for pid in eng.state.alive_players():
        eng.submit_lynch_confirm(pid.player_id, True)
    eng.resolve_lynch_confirmation_if_ready(force=True)
    assert eng.state.players[ids["P3"]].alive is False
    deaths = [m for m in eng.state.chat_messages if m.kind == "death"]
    assert len(deaths) == 1
    d = deaths[0]
    assert d.payload["victim"] == ids["P3"]
    assert d.payload["killer_role"] == "town_vote"
    assert d.payload["victim_role"] == "Citizen"


# --------------------------------------------------------------------- #
# Bot-role picks (#21): host chooses bots' roles in the lobby
# --------------------------------------------------------------------- #

def _bot_engine():
    from app.game_engine.engine import GameEngine
    eng = GameEngine(game_id="bot-game", host_telegram_id=1, host_name="Admin")
    host_id = eng.state.host_id
    for i in range(1, 6):  # 5 bots -> 6 players total
        eng.add_bot_player(f"Bot{i}")
    return eng, host_id


def test_host_can_pick_bot_role_and_it_is_honored():
    from app.game_engine.engine import EngineError
    eng, host_id = _bot_engine()
    bot_ids = [pid for pid, p in eng.state.players.items() if p.is_bot]
    eng.set_bot_role(host_id, bot_ids[0], "Doctor")
    eng.set_bot_role(host_id, bot_ids[1], "Don")
    eng.start_game(host_id)
    assert eng.state.players[bot_ids[0]].role.value == "Doctor"
    assert eng.state.players[bot_ids[1]].role.value == "Don"
    assert eng.state.players[bot_ids[0]].bot_role_pick is None
    assert eng.state.players[host_id].role is not None


def test_pick_must_be_in_composition():
    from app.game_engine.engine import EngineError
    eng, host_id = _bot_engine()
    bot_ids = [pid for pid, p in eng.state.players.items() if p.is_bot]
    with pytest.raises(EngineError):
        eng.set_bot_role(host_id, bot_ids[0], "Vagabond")  # not in a 6p lineup
    assert eng.state.players[bot_ids[0]].bot_role_pick is None


def test_cannot_exceed_composition_copies():
    from app.game_engine.engine import EngineError
    eng, host_id = _bot_engine()
    bot_ids = [pid for pid, p in eng.state.players.items() if p.is_bot]
    eng.set_bot_role(host_id, bot_ids[0], "Don")
    with pytest.raises(EngineError):
        eng.set_bot_role(host_id, bot_ids[1], "Don")
    eng.set_bot_role(host_id, bot_ids[1], "Doctor")
    assert eng.state.players[bot_ids[1]].bot_role_pick == "Doctor"


def test_only_host_can_pick():
    from app.game_engine.engine import EngineError
    eng, host_id = _bot_engine()
    bot_ids = [pid for pid, p in eng.state.players.items() if p.is_bot]
    with pytest.raises(EngineError):
        eng.set_bot_role("some-other-id", bot_ids[0], "Doctor")


def test_player_role_picks_visible_to_host_in_lobby_view():
    eng, host_id = _bot_engine()
    bot_ids = [pid for pid, p in eng.state.players.items() if p.is_bot]
    eng.set_bot_role(host_id, bot_ids[0], "Doctor")
    admin = eng.get_player_view(host_id)["admin"]
    assert "available_roles" in admin
    assert "Doctor" in admin["available_roles"]
    assert "Vagabond" not in admin["available_roles"]
    assert admin["role_picks"][bot_ids[0]] == "Doctor"
    # Variant is chosen at start, so the lobby can't show a resolved single
    # lineup. role_count is the max copies a role can hold across that
    # player count's variants (mirrors set_bot_role's limit), so the role
    # picker stays usable before any pick is made.
    assert "role_variants" in admin
    doctors = max(v["roles"]["Doctor"] for v in admin["role_variants"])
    assert doctors >= 1
    assert admin["role_count"]["Doctor"] == doctors
    assert admin["role_count"]["Don"] >= 1
