"""Full-stack regression test for the activity feed feature: drives a real
game through the actual WebSocket endpoint (not the bare GameEngine) to
confirm activity_feed actually reaches a real client exactly as app.js
expects it, and that no player_id ever leaks into the payload.
"""
import json

from fastapi.testclient import TestClient

from app.config import settings
settings.telegram_bot_token = "TEST-TOKEN"
settings.database_url = "sqlite+aiosqlite:///:memory:"

from app.main import app  # noqa: E402
from tests.test_api_smoke import _init_data_for  # noqa: E402


def test_activity_feed_reaches_real_websocket_clients_end_to_end():
    with TestClient(app) as c:
        tokens = []
        game_id = None
        for i in range(1, 7):
            login = c.post("/auth/telegram", json={"init_data": _init_data_for(910 + i, f"F{i}")})
            tok = login.json()["session_token"]
            tokens.append(tok)
            joined = c.post("/games/for-chat", json={"chat_id": "-100902345", "display_name": f"F{i}"},
                             headers={"Authorization": f"Bearer {tok}"})
            game_id = joined.json()["game_id"]

        with c.websocket_connect(f"/ws/games/{game_id}?token={tokens[0]}") as ws:
            first = ws.receive_json()["state"]
            my_pid = first["me"]["player_id"]
            assert first["phase"] == "lobby"

            ws.send_json({"type": "start_game"})
            after_start = ws.receive_json()["state"]
            assert after_start["phase"] == "role_assignment"

            from app.services.game_service import registry
            engine = registry.get(game_id)
            engine.advance_from_role_assignment_if_ready(force=True)
            assert engine.state.phase.value == "night"
            engine.resolve_night_if_ready(force=True)
            engine.resolve_morning_if_ready(force=True)
            assert engine.state.phase.value == "day_discussion"

            ws.send_json({"type": "ready_for_vote", "ready": False})
            state = ws.receive_json()["state"]

            assert "activity_feed" in state
            feed = state["activity_feed"]
            assert any(e["message_key"] == "night.begins" for e in feed)
            assert any(e["message_key"] == "night.resolved" for e in feed)
            assert any(e["message_key"] == "morning.begins" for e in feed)
            assert any(e["message_key"] == "day.begins" for e in feed)
            for e in feed:
                assert "visible_to" not in e

            feed_blob = json.dumps(feed)
            assert my_pid not in feed_blob
            for p in state["players"]:
                assert p["player_id"] not in feed_blob

        from app.services.game_service import registry
        registry.remove(game_id)
