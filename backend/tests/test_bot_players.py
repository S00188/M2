import pytest
from app.services.game_service import registry, BOT_GAME_CHAT_PREFIX
from app.game_engine.bot_players import bot_name_for
from app.game_engine.engine import EngineError


def test_bot_names_unique_across_full_lobby():
    # The lobby caps at 20, and bot_count can reach 19 (host + 19 bots).
    names = [bot_name_for(i) for i in range(20)]
    assert len(set(names)) == 20


def test_bots_fill_lobby_and_are_flagged():
    chat = BOT_GAME_CHAT_PREFIX + "1"
    engine, _ = registry.get_or_create_for_chat(chat, 1, "Admin")
    for i in range(5):
        engine.add_bot_player(bot_name_for(i))
    bots = [p for p in engine.state.players.values() if p.is_bot]
    assert len(bots) == 5
    assert all(p.telegram_user_id < 0 for p in bots)
    assert not engine.state.players[engine.state.host_id].is_bot
    engine.start_game(engine.state.host_id)
    registry.remove(engine.state.game_id)


def test_bots_cannot_be_added_after_start():
    chat = BOT_GAME_CHAT_PREFIX + "2"
    engine, _ = registry.get_or_create_for_chat(chat, 2, "Admin")
    for i in range(5):
        engine.add_bot_player(bot_name_for(i))
    engine.start_game(engine.state.host_id)
    with pytest.raises(EngineError):
        engine.add_bot_player("Kech qolgan")
    registry.remove(engine.state.game_id)


def test_bots_send_exactly_one_simple_chat_message_per_day():
    """Feature request: bots should chat too, but very simply — one bland
    line per bot per day, using the same send_chat_message() a real
    player's WebSocket message would call (see bot_players.py's own
    design note about never having a second copy of the rules)."""
    from app.game_engine import bot_players
    from app.game_engine.state import Phase

    chat = BOT_GAME_CHAT_PREFIX + "3"
    engine, _ = registry.get_or_create_for_chat(chat, 3, "Admin")
    for i in range(5):
        engine.add_bot_player(bot_name_for(i))
    engine.start_game(engine.state.host_id)
    engine.advance_from_role_assignment_if_ready(force=True)
    engine.resolve_night_if_ready(force=True)
    engine.resolve_morning_if_ready(force=True)
    assert engine.state.phase == Phase.DAY_DISCUSSION

    bot_ids = {p.player_id for p in engine.state.players.values() if p.is_bot and p.alive}
    assert bot_ids, "expected at least one living bot in day_discussion"

    # Force every bot's random think-delay to elapse immediately so this
    # test doesn't depend on real wall-clock time.
    import time as time_module
    engine.state.phase_start = time_module.time() - 999

    # Drive the phase a few times — chat is staggered per-bot, same as
    # night actions/votes, so more than one pass may be needed.
    for _ in range(5):
        bot_players.drive(engine)

    bot_messages = [m for m in engine.state.chat_messages if m.player_id in bot_ids]
    senders = {m.player_id for m in bot_messages}
    assert senders == bot_ids, "every living bot should have sent exactly one message"
    assert len(bot_messages) == len(bot_ids), "each bot should send exactly one message, not more"
    for m in bot_messages:
        assert m.text in bot_players.BOT_CHAT_LINES

    registry.remove(engine.state.game_id)
