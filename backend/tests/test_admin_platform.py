"""The premium Admin panel's seven modules (routes_admin_platform.py):
users, admins (permissions), texts, broadcasts, groups, statistics and
settings (buttons) — plus the /leaderboard public ranking and the blocked-
user gate on /auth/telegram.

Every /admin/* route is gated server-side: a super admin (from
settings.admin_telegram_ids) passes anything, a panel admin only the
permissions granted via AdminPermission rows, and a plain user nothing at
all. The tests below assert both the happy paths and that gating.
"""
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
settings.admin_telegram_ids = [900001]

from app.main import app  # noqa: E402
from app.database import AsyncSessionLocal, init_db  # noqa: E402
from app.models.models import AdminPermission, AdminUser, BlockedUser, KnownGroup, User  # noqa: E402
from app.services import bot_config  # noqa: E402
from app.services.game_service import registry  # noqa: E402

SUPER_ID = 900001
PANEL_ID = 900100
VICTIM_ID = 900200


@pytest.fixture(autouse=True)
async def _ensure_tables():
    await init_db()
    await bot_config.load_config()


@pytest.fixture(autouse=True)
async def _clear_admin_and_block_rows():
    """Each test owns its own admin/block state. A parallel in-memory DB is
    shared across tests, so without this, promote/block mutations would leak
    into the next test and break order-independent expectations."""
    yield
    async with AsyncSessionLocal() as session:
        for row in (await session.execute(select(AdminPermission))).scalars().all():
            await session.delete(row)
        for row in (await session.execute(select(AdminUser))).scalars().all():
            await session.delete(row)
        for row in (await session.execute(select(BlockedUser))).scalars().all():
            await session.delete(row)
        await session.commit()


@pytest.fixture(autouse=True)
def _clear_registry():
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


async def _make_lobby_game(ac: AsyncClient, chat_id: str, n_players: int = 6) -> str:
    """Populates a real match via the normal for-chat path (conftest's
    autouse fixture lets every membership check pass) and returns its game_id."""
    game_id = None
    for i in range(1, n_players + 1):
        body = await _login(ac, 800000 + i, f"P{i}")
        r = await ac.post("/games/for-chat", json={"chat_id": chat_id, "display_name": f"P{i}"},
                          headers={"Authorization": f"Bearer {body['session_token']}"})
        assert r.status_code == 200
        game_id = r.json()["game_id"]
    return game_id


# ----------------------------------------------------------------- gating ---

@pytest.mark.asyncio
async def test_plain_user_gets_403_on_every_module():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = await _login(ac, 900900, "Plain")
        headers = {"Authorization": f"Bearer {body['session_token']}"}
        for path in ("/admin/users", "/admin/admins", "/admin/texts", "/admin/broadcasts",
                     "/admin/groups", "/admin/statistics", "/admin/settings/buttons",
                     "/admin/permissions"):
            r = await ac.get(path, headers=headers)
            assert r.status_code == 403, path


@pytest.mark.asyncio
async def test_login_response_flags_super_but_gives_real_permission_list_to_admin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, SUPER_ID, "Owner")
        await _login(ac, PANEL_ID, "Panel Person")

        # Promote the panel user and grant a single module.
        super_body = await _login(ac, SUPER_ID, "Owner")
        h = {"Authorization": f"Bearer {super_body['session_token']}"}
        r = await ac.post(f"/admin/users/{PANEL_ID}/make-admin", headers=h)
        assert r.status_code == 200
        r = await ac.put(f"/admin/admins/{PANEL_ID}/permissions",
                         json={"permissions": ["users.view"]}, headers=h)
        assert r.status_code == 200

        # A fresh login reflects the granted permission (not the whole catalog).
        panel_body = await _login(ac, PANEL_ID, "Panel Person")
        assert panel_body["is_bot_admin"] is True
        assert panel_body["is_super_admin"] is False
        assert panel_body["permissions"] == ["users.view"]
        ph = {"Authorization": f"Bearer {panel_body['session_token']}"}

        assert (await ac.get("/admin/users", headers=ph)).status_code == 200
        assert (await ac.get("/admin/admins", headers=ph)).status_code == 403
        assert (await ac.get("/admin/statistics", headers=ph)).status_code == 403
        assert (await ac.post(f"/admin/users/{PANEL_ID}/block", headers=ph)).status_code == 403


# ---------------------------------------------------------------- users -----

@pytest.mark.asyncio
async def test_admin_lists_and_searches_users():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, 900300, "Alice")
        await _login(ac, 900301, "Bob")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}
        body = (await ac.get("/admin/users", headers=headers)).json()
        assert body["total"] >= 2
        names = {u["display_name"] for u in body["users"]}
        assert {"Alice", "Bob"} <= names

        by_id = (await ac.get("/admin/users?search=900301", headers=headers)).json()
        assert [u["telegram_user_id"] for u in by_id["users"]] == [900301]

        detail = (await ac.get("/admin/users/900300", headers=headers)).json()
        assert detail["display_name"] == "Alice"
        assert detail["blocked"] is False
        assert detail["is_admin"] is False


@pytest.mark.asyncio
async def test_admin_user_detail_carries_recent_games_and_permissions():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}
        await ac.post(f"/admin/users/{PANEL_ID}/make-admin", headers=headers)
        await ac.put(f"/admin/admins/{PANEL_ID}/permissions",
                     json={"permissions": ["users.view", "texts.view"]}, headers=headers)
        detail = (await ac.get(f"/admin/users/{PANEL_ID}", headers=headers)).json()
        assert detail["is_admin"] is True
        assert detail["permissions"] == ["texts.view", "users.view"]
        assert detail["recent_games"] == []


@pytest.mark.asyncio
async def test_blocked_user_cannot_login_until_unblocked():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, VICTIM_ID, "Victim")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}

        r = await ac.post(f"/admin/users/{VICTIM_ID}/block", headers=headers)
        assert r.status_code == 200
        r = await ac.post("/auth/telegram", json={"init_data": _init_data_for(VICTIM_ID, "Victim")})
        assert r.status_code == 403
        assert "bloklangansiz" in r.json()["detail"]

        r = await ac.post(f"/admin/users/{VICTIM_ID}/unblock", headers=headers)
        assert r.status_code == 200
        r = await ac.post("/auth/telegram", json={"init_data": _init_data_for(VICTIM_ID, "Victim")})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_super_admin_cannot_be_blocked():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}
        r = await ac.post(f"/admin/users/{SUPER_ID}/block", headers=headers)
        assert r.status_code == 400


# ---------------------------------------------------------------- admins ----

@pytest.mark.asyncio
async def test_add_and_remove_admin_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, PANEL_ID, "Panel Person")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}

        listed = (await ac.get("/admin/admins", headers=headers)).json()
        assert any(a["is_super"] for a in listed["admins"])
        before = len(listed["admins"])

        r = await ac.post("/admin/admins", json={"telegram_user_id": PANEL_ID}, headers=headers)
        assert r.status_code == 200
        listed = (await ac.get("/admin/admins", headers=headers)).json()
        assert len(listed["admins"]) == before + 1
        panel = next(a for a in listed["admins"] if a["telegram_user_id"] == PANEL_ID)
        assert panel["is_super"] is False

        # Duplicate add is rejected.
        assert (await ac.post("/admin/admins", json={"telegram_user_id": PANEL_ID},
                              headers=headers)).status_code == 400
        # Removal works and revokes panel access.
        assert (await ac.delete(f"/admin/admins/{PANEL_ID}", headers=headers)).status_code == 200
        listed = (await ac.get("/admin/admins", headers=headers)).json()
        assert all(a["telegram_user_id"] != PANEL_ID for a in listed["admins"])
        # The (now demoted) user is no longer an admin.
        body = await _login(ac, PANEL_ID, "Panel Person")
        assert body["is_bot_admin"] is False


@pytest.mark.asyncio
async def test_permissions_are_validated_against_catalog():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, PANEL_ID, "Panel Person")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}
        await ac.post(f"/admin/users/{PANEL_ID}/make-admin", headers=headers)

        r = await ac.put(f"/admin/admins/{PANEL_ID}/permissions",
                         json={"permissions": ["hack.everything"]}, headers=headers)
        assert r.status_code == 400

        catalogue = (await ac.get("/admin/permissions", headers=headers)).json()
        assert set(catalogue["all"]) == {
            "support.view", "support.reply",
            "users.view", "users.manage", "admins.view", "admins.manage",
            "texts.view", "texts.manage", "broadcast.view", "broadcast.send",
            "groups.view", "groups.manage", "statistics.view",
            "settings.view", "settings.manage",
        }


# ----------------------------------------------------------------- texts ----

@pytest.mark.asyncio
async def test_texts_are_listed_edited_and_pick_up_a_language():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}

        texts = (await ac.get("/admin/texts", headers=headers)).json()["texts"]
        keys = {t["key"] for t in texts}
        assert keys == {"start", "group_added", "lobby"}

        r = await ac.put("/admin/texts/start/uz", json={"value": "Salom dunyo!"}, headers=headers)
        assert r.status_code == 200
        texts = (await ac.get("/admin/texts", headers=headers)).json()["texts"]
        start = next(t for t in texts if t["key"] == "start")
        assert start["uz"] == "Salom dunyo!"
        # The bot-facing cache saw it too.
        from app.services.bot_config import get_text
        assert get_text("start", "uz") == "Salom dunyo!"


@pytest.mark.asyncio
async def test_texts_require_manage_permission_to_write():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, PANEL_ID, "Panel Person")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}
        await ac.post(f"/admin/users/{PANEL_ID}/make-admin", headers=headers)
        await ac.put(f"/admin/admins/{PANEL_ID}/permissions",
                     json={"permissions": ["texts.view"]}, headers=headers)
        panel_body = await _login(ac, PANEL_ID, "Panel Person")
        ph = {"Authorization": f"Bearer {panel_body['session_token']}"}

        assert (await ac.get("/admin/texts", headers=ph)).status_code == 200
        assert (await ac.put("/admin/texts/start/uz", json={"value": "nope"}, headers=ph)).status_code == 403


# ------------------------------------------------------------ broadcasts ----

@pytest.mark.asyncio
async def test_broadcast_create_list_preview_and_send(monkeypatch):
    """Offline: the delivery loop is swapped for a counting stub."""
    from app.api import routes_admin_platform as platform

    sent = []

    async def _fake_send(chat_id, text, button_text=None, button_url=None):
        sent.append(str(chat_id))
        return True

    monkeypatch.setattr(platform, "send_telegram_message", _fake_send)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, 900400, "Ann")
        await _login(ac, 900401, "Ben")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}

        r = await ac.post("/admin/broadcasts", headers=headers, json={
            "title": "Test", "text": "Xabar matni", "kind": "users",
            "user_ids": [900400, 900401],
        })
        assert r.status_code == 200
        bcast_id = r.json()["id"]
        assert r.json()["recipients"] == 2

        preview = (await ac.get(f"/admin/broadcasts/{bcast_id}/preview", headers=headers)).json()
        assert preview["recipient_count"] == 2
        assert preview["text"] == "Xabar matni"

        history = (await ac.get("/admin/broadcasts", headers=headers)).json()["broadcasts"]
        assert history[0]["id"] == bcast_id
        assert history[0]["status"] == "pending"

        r = await ac.post(f"/admin/broadcasts/{bcast_id}/send", headers=headers)
        assert r.status_code == 200
        assert r.json() == {"ok": True, "total": 2, "delivered": 2, "failed": 0}
        assert sorted(sent) == ["900400", "900401"]

        history = (await ac.get("/admin/broadcasts", headers=headers)).json()["broadcasts"]
        assert history[0]["status"] == "sent"
        # A second send is refused.
        assert (await ac.post(f"/admin/broadcasts/{bcast_id}/send", headers=headers)).status_code == 400


@pytest.mark.asyncio
async def test_broadcast_validation_and_permission_gating():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, PANEL_ID, "Panel Person")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}
        await ac.post(f"/admin/users/{PANEL_ID}/make-admin", headers=headers)
        await ac.put(f"/admin/admins/{PANEL_ID}/permissions",
                     json={"permissions": ["broadcast.view"]}, headers=headers)
        panel_body = await _login(ac, PANEL_ID, "Panel Person")
        ph = {"Authorization": f"Bearer {panel_body['session_token']}"}

        # viewer can't create or send
        assert (await ac.post("/admin/broadcasts", headers=ph, json={"text": "x", "kind": "all"})).status_code == 403

        # empty draft rejected even for the owner
        r = await ac.post("/admin/broadcasts", headers=headers,
                          json={"text": "", "kind": "all"})
        assert r.status_code == 400


# ---------------------------------------------------------------- groups ----

@pytest.mark.asyncio
async def test_groups_listed_with_activity_and_toggleable():
    async with AsyncSessionLocal() as session:
        session.add(KnownGroup(chat_id=-100777, title="Mafia Test Guruh", is_active=True))
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}

        body = (await ac.get("/admin/groups", headers=headers)).json()
        group = next(g for g in body["groups"] if g["chat_id"] == -100777)
        assert group["title"] == "Mafia Test Guruh"
        assert group["is_active"] is True

        r = await ac.post("/admin/groups/-100777/status",
                          json={"is_active": False}, headers=headers)
        assert r.status_code == 200
        body = (await ac.get("/admin/groups", headers=headers)).json()
        group = next(g for g in body["groups"] if g["chat_id"] == -100777)
        assert group["is_active"] is False

        # Unknown chat cannot be toggled.
        assert (await ac.post("/admin/groups/-999999/status",
                              json={"is_active": True}, headers=headers)).status_code == 404

        body = (await ac.get("/admin/groups?only_active=1", headers=headers)).json()
        assert all(g["chat_id"] != -100777 for g in body["groups"])


@pytest.mark.asyncio
async def test_group_status_requires_manage_permission():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _make_lobby_game(ac, "-100778")
        await _login(ac, PANEL_ID, "Panel Person")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}
        await ac.post(f"/admin/users/{PANEL_ID}/make-admin", headers=headers)
        await ac.put(f"/admin/admins/{PANEL_ID}/permissions",
                     json={"permissions": ["groups.view"]}, headers=headers)
        panel_body = await _login(ac, PANEL_ID, "Panel Person")
        ph = {"Authorization": f"Bearer {panel_body['session_token']}"}

        assert (await ac.get("/admin/groups", headers=ph)).status_code == 200
        r = await ac.post("/admin/groups/-100778/status", json={"is_active": False}, headers=ph)
        assert r.status_code == 403


# ------------------------------------------------------------ statistics ----

@pytest.mark.asyncio
async def test_statistics_shape():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, 900500, "Stat-Me")
        await _make_lobby_game(ac, "-100779")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}
        body = (await ac.get("/admin/statistics", headers=headers)).json()
        kp = body["kp"]
        assert kp["total_users"] >= 1
        assert kp["active_games"] >= 1
        assert kp["players_in_play"] >= 4
        assert kp["total_finished_games"] >= 0
        assert isinstance(body["daily_new_users"], list) and len(body["daily_new_users"]) == 7
        assert "top_players" in body and "active_games" in body


# -------------------------------------------------------------- settings ----

@pytest.mark.asyncio
async def test_buttons_listed_reordered_and_updated():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}

        buttons = (await ac.get("/admin/settings/buttons", headers=headers)).json()["buttons"]
        keys = [b["key"] for b in buttons]
        assert keys == sorted(keys, key=lambda k: next(b["order"] for b in buttons if b["key"] == k))

        # Rename a label and flip it off.
        r = await ac.put("/admin/settings/buttons/leaderboard", headers=headers,
                         json={"label_uz": "Reyting", "enabled": False})
        assert r.status_code == 200
        buttons = (await ac.get("/admin/settings/buttons", headers=headers)).json()["buttons"]
        lb = next(b for b in buttons if b["key"] == "leaderboard")
        assert lb["label_uz"] == "Reyting"
        assert lb["enabled"] is False
        # The bot-facing menu honors the change immediately.
        from app.services.bot_config import menu_button_order
        menu = menu_button_order(SUPER_ID)
        assert not any(b["key"] == "leaderboard" for b in menu)
        assert any(b["key"] == "admin_panel" for b in menu)

        # Reorder: leaderboard goes first.
        r = await ac.post("/admin/settings/buttons/reorder", headers=headers,
                          json={"keys": ["leaderboard"] + [k for k in keys if k != "leaderboard"]})
        assert r.status_code == 200
        buttons = (await ac.get("/admin/settings/buttons", headers=headers)).json()["buttons"]
        assert buttons[0]["key"] == "leaderboard"
        assert buttons[0]["order"] == 10


@pytest.mark.asyncio
async def test_settings_require_manage_permission_to_write():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac, PANEL_ID, "Panel Person")
        super_body = await _login(ac, SUPER_ID, "Owner")
        headers = {"Authorization": f"Bearer {super_body['session_token']}"}
        await ac.post(f"/admin/users/{PANEL_ID}/make-admin", headers=headers)
        await ac.put(f"/admin/admins/{PANEL_ID}/permissions",
                     json={"permissions": ["settings.view"]}, headers=headers)
        panel_body = await _login(ac, PANEL_ID, "Panel Person")
        ph = {"Authorization": f"Bearer {panel_body['session_token']}"}

        assert (await ac.get("/admin/settings/buttons", headers=ph)).status_code == 200
        r = await ac.put("/admin/settings/buttons/about", headers=ph, json={"label_uz": "x"})
        assert r.status_code == 403
        r = await ac.post("/admin/settings/buttons/reorder", headers=ph, json={"keys": []})
        assert r.status_code == 403


# ----------------------------------------------------------- language ------

@pytest.mark.asyncio
async def test_language_endpoint_sets_and_persists_preference():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = await _login(ac, 900600, "Ling")
        headers = {"Authorization": f"Bearer {body['session_token']}"}
        assert body["language"] == "uz"

        r = await ac.post("/auth/language", headers=headers, json={"language": "ru"})
        assert r.status_code == 200
        body2 = await _login(ac, 900600, "Ling")
        assert body2["language"] == "ru"

        # Unsupported codes never raise — they're coerced to the default
        # (the WebApp only ever sends supported languages anyway).
        assert (await ac.post("/auth/language", headers=headers,
                              json={"language": "xx"})).status_code == 200
        body3 = await _login(ac, 900600, "Ling")
        assert body3["language"] == "uz"


# ---------------------------------------------------------- leaderboard -----

@pytest.mark.asyncio
async def test_leaderboard_ranks_by_wins_with_limit():
    async with AsyncSessionLocal() as session:
        session.add(User(telegram_user_id=900700, first_name="Top", username="topdog", wins=9, games_played=10))
        session.add(User(telegram_user_id=900701, first_name="Mid", username="mid", wins=5, games_played=10))
        session.add(User(telegram_user_id=900702, first_name="Fresh", username="fresh", wins=0, games_played=0))
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/leaderboard?limit=2")).json()
        assert body["total"] == 2
        assert [row["telegram_user_id"] for row in body["leaderboard"]] == [900700, 900701]
        assert body["leaderboard"][0]["win_rate"] == 90
        assert body["leaderboard"][0]["place"] == 1

        fresh_excluded = (await ac.get("/leaderboard")).json()
        assert all(row["telegram_user_id"] != 900702 for row in fresh_excluded["leaderboard"])

        assert (await ac.get("/leaderboard?limit=0")).status_code in (400, 422)
