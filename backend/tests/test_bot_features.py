"""Covers the new DB-backed helpers behind the bot's private-chat menu
(app/telegram_bot.py): known-group tracking for the "Guruhda o'yin
boshlash" picker. These are plain async functions with no aiogram Message/
CallbackQuery involved, so they're tested directly rather than through a
simulated conversation — see test_telegram_webhook.py for why constructing
real aiogram objects is avoided in this suite."""
import pytest

from app.config import settings
settings.telegram_bot_token = "TEST-TOKEN"
settings.database_url = "sqlite+aiosqlite:///:memory:"

import app.telegram_bot as tb  # noqa: E402
from app.database import AsyncSessionLocal, init_db  # noqa: E402
from app.models.models import KnownGroup  # noqa: E402


@pytest.fixture(autouse=True)
async def _ensure_tables():
    await init_db()


# ------------------------------------------------------- known groups ----
@pytest.mark.asyncio
async def test_upsert_known_group_inserts_then_updates():
    await tb.upsert_known_group(chat_id=-100123, title="Do'stlar", is_active=True)

    async with AsyncSessionLocal() as session:
        row = await session.get(KnownGroup, -100123)
        assert row.title == "Do'stlar"
        assert row.is_active is True

    # Bot removed from the group later — same row, flipped to inactive.
    await tb.upsert_known_group(chat_id=-100123, title="Do'stlar", is_active=False)

    async with AsyncSessionLocal() as session:
        row = await session.get(KnownGroup, -100123)
        assert row.is_active is False


@pytest.mark.asyncio
async def test_upsert_known_group_keeps_title_when_blank():
    await tb.upsert_known_group(chat_id=-100456, title="Real Title", is_active=True)
    # A later event with no title (edge case Telegram could send) shouldn't
    # blank out a title we already have.
    await tb.upsert_known_group(chat_id=-100456, title="", is_active=True)

    async with AsyncSessionLocal() as session:
        row = await session.get(KnownGroup, -100456)
        assert row.title == "Real Title"


# ------------------------------------------------------- support relay ---
# _edit_or_send (the private-chat panel renderer) has to route reply
# keyboards and inline keyboards differently: aiogram raises ValidationError
# if edit_text ever gets a ReplyKeyboardMarkup (the field only accepts an
# InlineKeyboardMarkup), which used to kill every panel button tap with no
# reply to the user at all. Reply panels must go out as fresh messages.
class _FakePanelMessage:
    """Stands in for the stored aiogram Message (_last_panel_msg): records
    what the bot would have done to it, so _edit_or_send's two keyboard
    paths can be asserted without a real Telegram API call."""

    def __init__(self):
        self.edits = []  # list of (text, reply_markup)
        self.deleted = False

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))

    async def delete(self):
        self.deleted = True


class _FakeSendBot:
    """get_bot() stub whose send_message returns messages _edit_or_send can
    store back into _last_panel_msg."""

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        msg = _FakePanelMessage()
        self.sent.append((chat_id, text, kwargs.get("reply_markup")))
        return msg


@pytest.mark.asyncio
async def test_edit_or_send_never_edits_with_a_reply_keyboard(monkeypatch):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Tugma")]], resize_keyboard=True)
    prev = _FakePanelMessage()
    send_bot = _FakeSendBot()
    monkeypatch.setattr(tb, "get_bot", lambda: send_bot)
    monkeypatch.setattr(tb, "_last_panel_msg", {42: prev})

    result = await tb._edit_or_send(42, "Panel", reply_markup=kb)

    # The old panel message is retired and a NEW message carries the panel —
    # edit_text is never attempted with a reply keyboard (that's the
    # ValidationError regression).
    assert prev.deleted is True
    assert prev.edits == []
    assert len(send_bot.sent) == 1
    chat_id, text, sent_kb = send_bot.sent[0]
    assert (chat_id, text, sent_kb) == (42, "Panel", kb)
    assert tb._last_panel_msg[42] is result


@pytest.mark.asyncio
async def test_edit_or_send_edits_inline_launchers_in_place(monkeypatch):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Ochish", url="https://t.me/example"),
    ]])
    prev = _FakePanelMessage()
    send_bot = _FakeSendBot()
    monkeypatch.setattr(tb, "get_bot", lambda: send_bot)
    monkeypatch.setattr(tb, "_last_panel_msg", {42: prev})

    result = await tb._edit_or_send(42, "Launcher", reply_markup=kb)

    assert prev.edits and prev.edits[0][1] is kb  # edited in place
    assert prev.deleted is False
    assert send_bot.sent == []
    assert tb._last_panel_msg[42] is result


class _FakeSentMessage:
    def __init__(self, message_id: int):
        self.message_id = message_id


class _FakeBot:
    async def edit_message_reply_markup(self, **kwargs):
        return True

    """Stands in for get_bot() so _relay_to_admins/on_admin_reply can be
    tested without a real Telegram Bot object or network call."""

    def __init__(self):
        self.sent = []  # list of (chat_id, text)
        self._next_id = 1

    async def send_message(self, chat_id, text, **kwargs):
        msg = _FakeSentMessage(self._next_id)
        self._next_id += 1
        self.sent.append((chat_id, text, msg.message_id))
        return msg


class _FakeUser:
    def __init__(self, id, username=None, first_name="Test", last_name=None):
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name


class _FakeMessage:
    def __init__(self, from_user, text, reply_to_message=None):
        self.from_user = from_user
        self.text = text
        self.reply_to_message = reply_to_message
        self.answered = []
        self.replied = []

    async def answer(self, text, **kwargs):
        self.answered.append(text)

    async def reply(self, text, **kwargs):
        self.replied.append(text)


class _FakeRepliedTo:
    def __init__(self, message_id):
        self.message_id = message_id


@pytest.mark.asyncio
async def test_relay_to_admins_and_admin_reply_round_trip(monkeypatch):
    settings.admin_telegram_ids = [900001]
    fake_bot = _FakeBot()
    monkeypatch.setattr(tb, "get_bot", lambda: fake_bot)

    user_msg = _FakeMessage(_FakeUser(id=555, username="asker"), "Salom, savolim bor")
    await tb._relay_to_admins(user_msg)

    # The admin got a copy, and the user was told it went through.
    assert len(fake_bot.sent) == 1
    admin_chat_id, forwarded_text, admin_copy_id = fake_bot.sent[0]
    assert admin_chat_id == 900001
    assert "Salom, savolim bor" in forwarded_text
    assert any("yuborildi" in t for t in user_msg.answered)

    # Admin replies to that forwarded copy.
    admin_reply = _FakeMessage(
        _FakeUser(id=900001), "Albatta, mana javob",
        reply_to_message=_FakeRepliedTo(admin_copy_id),
    )
    await tb.on_admin_reply(admin_reply)

    # The original user (555) receives the admin's reply text.
    relayed = [s for s in fake_bot.sent if s[0] == 555]
    assert len(relayed) == 1
    assert "Albatta, mana javob" in relayed[0][1]
    assert any("Yuborildi" in t for t in admin_reply.replied)


# ------------------------------------------------ group-post error surfacing
@pytest.mark.asyncio
async def test_on_group_picked_surfaces_the_real_telegram_error(monkeypatch):
    """Regression test: a failed post used to always show a generic 'may
    have been removed' guess regardless of the actual cause. It should now
    surface Telegram's own error text instead of hiding it — through the
    inline group-tap handler (on_group_picked), since the group picker is
    an inline callback submenu now."""
    from aiogram.exceptions import TelegramBadRequest

    async def fake_membership_ok(chat_id, telegram_user_id):
        return True

    async def fake_post_join_button_fails(chat_id):
        raise TelegramBadRequest(method=None, message="chat not found")

    monkeypatch.setattr(tb, "verify_group_membership", fake_membership_ok)
    monkeypatch.setattr(tb, "post_join_button", fake_post_join_button_fails)

    class _FakeMsg:
        async def edit_text(self, text, **kwargs):
            pass

    class _FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, **kwargs):
            m = _FakeMsg()
            m.chat = type("C", (), {"id": chat_id})()
            m.message_id = 1
            self.sent.append((chat_id, text, kwargs.get("reply_markup")))
            return m

    class _FakeQuery:
        def __init__(self):
            self.data = "grp:-100999"
            self.from_user = type("U", (), {"id": 800001})()
            self.message = type("M", (), {"chat": type("C", (), {"id": 8800001})()})()

        async def answer(self):
            pass

    fake_bot = _FakeBot()
    monkeypatch.setattr(tb, "get_bot", lambda: fake_bot)
    monkeypatch.setattr(tb, "_last_panel_msg", {})

    # The callback button a real tap would have sent carries the group chat
    # id in its data, so no text->id lookup map is needed.
    await tb.on_group_picked(_FakeQuery())

    sent_texts = [text for (_, text, _) in fake_bot.sent]
    # The follow-up message shows Telegram's actual reason, not a guess.
    assert any("chat not found" in t for t in sent_texts)
    # And it must NOT have fabricated the old "removed from group" guess.
    assert not any("removed" in t.lower() for t in sent_texts)
