from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from fastapi import HTTPException
from sqlalchemy import delete, select

from app import bot_controls as controls, telegram_bot as tb
from app.api.dependencies import require_telegram_id
from app.config import settings
from app.database import AsyncSessionLocal, init_db
from app.models.models import (BlockedUser, Broadcast, BroadcastDelivery, RequiredChannel,
                               SupportMessage, User, KnownGroup)
from app.services import access_control as access, bot_broadcasts as ads, bot_config
from app.utils.helpers import create_session_token

OWNER, USER = 991000, 991001


@pytest.fixture(autouse=True)
async def setup(monkeypatch):
    monkeypatch.setattr(settings, "admin_telegram_ids", [OWNER])
    await init_db()
    controls._inputs.clear()
    controls._support_times.clear()
    async with AsyncSessionLocal() as s:
        for cls in (RequiredChannel, BroadcastDelivery):
            await s.execute(delete(cls))
        await s.commit()
    yield
    async with AsyncSessionLocal() as s:
        for cls in (RequiredChannel, BroadcastDelivery):
            await s.execute(delete(cls))
        await s.execute(delete(Broadcast).where(Broadcast.created_by == OWNER))
        await s.execute(delete(BlockedUser).where(BlockedUser.telegram_user_id >= OWNER))
        await s.execute(delete(SupportMessage).where(SupportMessage.user_telegram_id == USER))
        await s.commit()
    controls._inputs.clear()


@pytest.fixture
def bot(monkeypatch):
    bot = NS(id=123, get_chat=AsyncMock(return_value=NS(id=-100991001, type="channel", title="Test kanal", username="testkanal")),
             get_chat_member=AsyncMock(return_value=NS(status="administrator")),
             send_message=AsyncMock(return_value=NS(message_id=993)),
             edit_message_reply_markup=AsyncMock(), send_photo=AsyncMock(), send_video=AsyncMock(),
             copy_message=AsyncMock())
    monkeypatch.setattr(tb, "get_bot", lambda: bot)
    return bot


def message(uid=OWNER, text="Salom"):
    return NS(from_user=NS(id=uid, is_bot=False, username=None, first_name="Test", last_name=None),
              chat=NS(id=uid, type="private"), text=text, reply_to_message=None,
              photo=None, video=None, html_text=text, html_caption=None, message_id=992,
              answer=AsyncMock(), reply=AsyncMock())


def callback_handler():
    return next(h.callback for h in tb.dp.callback_query.handlers if h.callback.__name__ == "controls")


@pytest.mark.asyncio
async def test_bottom_panel_opens_native_controls():
    await bot_config.load_config()
    own = [b for row in tb.menu_for(OWNER, "uz").keyboard for b in row]
    plain = [b for row in tb.menu_for(USER, "uz").keyboard for b in row]
    label = tb.button_text("admin_panel", "uz")
    assert any(b.text == label and b.web_app is None for b in own)
    assert all(b.text != label for b in plain)
    assert any(b.text == tb.button_text("contact_admin", "uz") for b in plain)
    callbacks = [b.callback_data for row in tb._admin_keyboard("uz").inline_keyboard for b in row]
    assert all("ctl:" + key in callbacks for key in ("inbox", "ad", "history", "channels", "block", "unblock"))


@pytest.mark.asyncio
async def test_block_revokes_existing_token_and_can_unblock():
    token = create_session_token(USER, settings.session_secret, 3600)
    await controls.set_block(USER, OWNER)
    with pytest.raises(HTTPException) as exc:
        await require_telegram_id("Bearer " + token)
    assert exc.value.status_code == 403
    await controls.set_block(USER, OWNER, False)
    assert await require_telegram_id("Bearer " + token) == USER
    with pytest.raises(ValueError):
        await controls.set_block(OWNER, OWNER)
    with pytest.raises(HTTPException):
        await controls.set_block(USER, USER)


@pytest.mark.asyncio
async def test_unauthorized_callback_cannot_block(bot):
    q = NS(from_user=NS(id=USER), data=f"ctl:ban:{USER}", answer=AsyncMock(), message=message(USER))
    await callback_handler()(q)
    assert not await access.is_blocked(USER)
    q.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_channel_add_validates_bot_admin_and_updates(bot):
    bot.get_chat_member.return_value = NS(status="member")
    with pytest.raises(ValueError, match="admin"):
        await controls.add_channel("@testkanal", OWNER)
    assert not await access.required_channels()
    bot.get_chat_member.return_value = NS(status="administrator")
    await controls.add_channel("@testkanal", OWNER)
    await controls.add_channel("https://t.me/testkanal", OWNER)
    channels = await access.required_channels()
    assert len(channels) == 1
    assert channels[0].join_url == "https://t.me/testkanal"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,is_member,missing", [
    ("member", True, False), ("administrator", True, False), ("creator", True, False),
    ("left", False, True), ("kicked", False, True),
    ("restricted", False, True), ("restricted", True, False),
])
async def test_subscription_statuses(bot, status, is_member, missing):
    await controls.add_channel("@testkanal", OWNER)
    bot.get_chat_member.return_value = NS(status=status, is_member=is_member)
    assert bool(await access.missing_channels(USER)) == missing
    if missing:
        with pytest.raises(HTTPException) as exc:
            await access.require_subscription(USER)
        assert exc.value.detail["channels"][0]["url"] == "https://t.me/testkanal"


@pytest.mark.asyncio
async def test_subscription_errors_fail_closed_admin_exempt(bot):
    await controls.add_channel("@testkanal", OWNER)
    bot.get_chat_member.side_effect = RuntimeError("offline")
    assert await access.missing_channels(USER)
    assert not await access.missing_channels(OWNER)


@pytest.mark.asyncio
async def test_middleware_blocks_messages_and_prompts_subscription(bot):
    msg = message(USER)
    handler = AsyncMock()
    middleware = controls.AccessMiddleware()
    await controls.set_block(USER, OWNER)
    await middleware(handler, msg, {})
    handler.assert_not_awaited()
    await controls.set_block(USER, OWNER, False)
    await controls.add_channel("@testkanal", OWNER)
    bot.get_chat_member.return_value = NS(status="left")
    await middleware(handler, msg, {})
    handler.assert_not_awaited()
    assert bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard[-1][0].callback_data == "subscription:check"


@pytest.mark.asyncio
async def test_support_text_escaped_and_reply_marked_only_on_success(bot):
    msg = message(USER, "<b>Oddiy & matn</b>")
    await tb._relay_to_admins(msg)
    assert "&lt;b&gt;Oddiy &amp; matn&lt;/b&gt;" in bot.send_message.call_args.args[1]
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(SupportMessage).where(SupportMessage.user_telegram_id == USER))).scalars().first()
        row_id = row.id
    controls._inputs[OWNER] = (f"reply:{row_id}", controls.monotonic())
    bot.send_message.side_effect = TelegramForbiddenError(method=SendMessage(chat_id=USER, text="x"), message="blocked")
    await controls.consume_admin_input(message())
    async with AsyncSessionLocal() as s:
        assert not (await s.get(SupportMessage, row_id)).replied
    bot.send_message.side_effect = None
    await controls.consume_admin_input(message())
    async with AsyncSessionLocal() as s:
        assert (await s.get(SupportMessage, row_id)).replied


@pytest.mark.asyncio
async def test_ad_queue_idempotent_and_worker_delivery(bot, monkeypatch):
    monkeypatch.setattr(ads, "audience", AsyncMock(return_value=[str(USER)]))
    draft = await ads.create_draft(message())
    assert await ads.enqueue(draft, OWNER, "all") == 1
    with pytest.raises(ValueError):
        await ads.enqueue(draft, OWNER, "all")
    assert await ads.process_next(bot)
    assert await ads.process_next(bot)
    async with AsyncSessionLocal() as s:
        row = await s.get(Broadcast, draft)
        assert (row.status, row.delivered, row.failed) == ("sent", 1, 0)
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_blocked_after_queue_not_sent(bot, monkeypatch):
    monkeypatch.setattr(ads, "audience", AsyncMock(return_value=[str(USER)]))
    draft = await ads.create_draft(message())
    await ads.enqueue(draft, OWNER, "all")
    await controls.set_block(USER, OWNER)
    await ads.process_next(bot)
    await ads.process_next(bot)
    bot.send_message.assert_not_awaited()
    async with AsyncSessionLocal() as s:
        assert (await s.get(Broadcast, draft)).failed == 1


@pytest.mark.asyncio
async def test_cancelled_draft_cannot_send(bot, monkeypatch):
    monkeypatch.setattr(ads, "audience", AsyncMock(return_value=[str(USER)]))
    monkeypatch.setattr(tb, "_edit_or_send", AsyncMock())
    draft = await ads.create_draft(message())
    query = NS(from_user=NS(id=OWNER), data=f"ctl:cancel:{draft}", answer=AsyncMock(), message=message())
    await callback_handler()(query)
    with pytest.raises(ValueError):
        await ads.enqueue(draft, OWNER, "all")


@pytest.mark.asyncio
async def test_photo_ad_uses_file_id(bot, monkeypatch):
    monkeypatch.setattr(ads, "audience", AsyncMock(return_value=[str(USER)]))
    msg = message()
    msg.photo = [NS(file_id="photo123")]
    msg.html_text = None
    msg.html_caption = "Namuna"
    draft = await ads.create_draft(msg)
    await ads.enqueue(draft, OWNER, "all")
    await ads.process_next(bot)
    assert bot.send_photo.call_args.args == (USER, "photo123")
    assert bot.send_photo.call_args.kwargs["caption"] == "Namuna"
