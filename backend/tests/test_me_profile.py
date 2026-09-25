"""Personal player profile: GET /me/profile and GET /me/games — the
per-user surface the Mini App's Profil screen is built on (see
app/static/app.js's openProfile). A player must only ever see their OWN
data here; these tests also cover the "a group supports at most one active
match, and history persists per user" invariants that the profile relies on."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.config import settings
settings.telegram_bot_token = "TEST-TOKEN"
settings.database_url = "sqlite+aiosqlite:///:memory:"

from app.main import app  # noqa: E402
from app.database import init_db, AsyncSessionLocal  # noqa: E402
from app.services.game_service import registry  # noqa: E402
from app.models.models import User, GameHistory, KnownGroup  # noqa: E402
from app.game_engine.state import Phase, WinResult  # noqa: E402
from app.game_engine.roles import Faction  # noqa: E402
from app.services.game_service import persist_finished_game  # noqa: E402

BASE_ID = 79001


@pytest.fixture(autouse=True)
async def _ensure_tables():
    await init_db()


@pytest.fixture(autouse=True)
def _clear_registry():
    """The GameRegistry is a module-level singleton shared through the
    whole suite — drop anything this file registered so it can't leak a
    chat_id/game into another test file (or vice versa)."""
    yield
    for engine in list(registry.all_engines()):
        registry.remove(engine.state.game_id)


def _init_data_for(user_id: int, name: str) -> str:
    fields = {
        "user": json.dumps({"id": user_id, "first_name": name}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


async def _login(ac: AsyncClient, user_id: int, name: str) -> dict:
    r = await ac.post("/auth/telegram", json={"init_data": _init_data_for(user_id, name)})
    assert r.status_code == 200
    return r.json()


async def _seed_game_history(telegram_user_id: int, game_id: str, role: str = "Doctor",
                              faction: str = "town", won: bool = True, games_played: int = 1) -> None:
    async with AsyncSessionLocal() as session:
        user = (await session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )).scalar_one()
        user.games_played = games_played
        if won:
            user.wins = games_played
        session.add(GameHistory(
            game_id=game_id, user_id=user.id, player_count=6,
            role_name=role, faction=faction, won=won, kills=2,
            successful_investigations=0, successful_protections=1,
        ))
        await session.commit()


# ------------------------------------------------------------ profile ----

@pytest.mark.asyncio
async def test_profile_for_new_player_has_zero_stats_and_no_games():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = await _login(ac, BASE_ID + 0, "Fresh")
        r = await ac.get("/me/profile", headers={"Authorization": f"Bearer {body['session_token']}"})
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["telegram_user_id"] == BASE_ID + 0
        assert data["user"]["display_name"] == "Fresh"
        assert data["stats"] == {
            "games_played": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "town_wins": 0, "mafia_wins": 0, "neutral_wins": 0,
        }
        assert data["active_games"] == []
        assert data["recent_games"] == []


@pytest.mark.asyncio
async def test_profile_lists_the_active_group_match_the_player_is_in():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = await _login(ac, BASE_ID + 1, "Ali")
        await ac.post("/games/for-chat", json={"chat_id": "-100500", "display_name": "Ali"},
                      headers={"Authorization": f"Bearer {body['session_token']}"})
        r = await ac.get("/me/profile", headers={"Authorization": f"Bearer {body['session_token']}"})
        data = r.json()
        assert len(data["active_games"]) == 1
        game = data["active_games"][0]
        assert game["phase"] == "lobby"
        assert game["player_count"] == 1
        assert game["group_title"] == "Guruh"  # no KnownGroup row yet


@pytest.mark.asyncio
async def test_profile_resolves_the_known_group_title():
    async with AsyncSessionLocal() as session:
        session.add(KnownGroup(chat_id=-100501, title="Do'stlar", is_active=True))
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = await _login(ac, BASE_ID + 2, "Bek")
        await ac.post("/games/for-chat", json={"chat_id": "-100501", "display_name": "Bek"},
                      headers={"Authorization": f"Bearer {body['session_token']}"})
        r = await ac.get("/me/profile", headers={"Authorization": f"Bearer {body['session_token']}"})
        data = r.json()
        assert data["active_games"][0]["group_title"] == "Do'stlar"


# --------------------------------------------------------------- games ----

@pytest.mark.asyncio
async def test_my_games_lists_history_and_totals():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = await _login(ac, BASE_ID + 3, "Sardor")
        await _seed_game_history(BASE_ID + 3, "finished-1", role="Commissioner", faction="town", won=True, games_played=1)
        await _seed_game_history(BASE_ID + 3, "finished-2", role="Doctor", faction="town", won=False, games_played=2)
        r = await ac.get("/me/games", headers={"Authorization": f"Bearer {body['session_token']}"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2
        games = {g["game_id"]: g for g in data["games"]}
        assert "finished-1" in games and "finished-2" in games
        assert games["finished-1"]["won"] is True
        assert games["finished-1"]["role_name"] == "Commissioner"
        assert games["finished-1"]["protections"] == 1


@pytest.mark.asyncio
async def test_me_endpoints_never_leak_another_players_data():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, BASE_ID + 4, "Sardor")
        await _seed_game_history(BASE_ID + 4, "others-game", role="Mafia", faction="mafia", won=True)
        other = await _login(ac, BASE_ID + 5, "NotSardor")
        r = await ac.get("/me/games", headers={"Authorization": f"Bearer {other['session_token']}"})
        assert r.json()["games"] == []
        assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_profil_reflects_a_really_finished_game_full_stack():
    """A real game ends (GAME_OVER -> persist_finished_game, exactly what
    the WebSocket handler runs), and the same player's /me/profile then
    shows the win in both stats and recent history."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        tokens = {}
        game_id = None
        for i in range(1, 7):
            uid = BASE_ID + 10 + i
            body = await _login(ac, uid, f"P{i}")
            tokens[uid] = body["session_token"]
            r = await ac.post("/games/for-chat",
                              json={"chat_id": "-999771", "display_name": f"P{i}"},
                              headers={"Authorization": f"Bearer {body['session_token']}"})
            game_id = r.json()["game_id"]

        engine = registry.get(game_id)
        host_pid = engine.state.host_id
        engine.start_game(host_pid)
        engine.state.phase = Phase.GAME_OVER
        engine.state.winner = WinResult(faction=Faction.TOWN, winners=[host_pid], reason="test")
        async with AsyncSessionLocal() as session:
            await persist_finished_game(session, engine)

        host_body = await _login(ac, BASE_ID + 11, "P1")
        r = await ac.get("/me/profile", headers={"Authorization": f"Bearer {host_body['session_token']}"})
        data = r.json()
        assert data["user"]["telegram_user_id"] == BASE_ID + 11
        assert data["stats"]["games_played"] == 1
        assert data["stats"]["wins"] == 1
        assert data["stats"]["win_rate"] == 100
        assert len(data["recent_games"]) == 1
        assert data["recent_games"][0]["game_id"] == game_id
        assert data["recent_games"][0]["won"] is True
        # The finished match must not come back as an *active* game.
        assert data["active_games"] == []