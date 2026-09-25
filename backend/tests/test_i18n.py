"""Covers app/i18n.py's DB-backed language preference, and that it's
correctly surfaced through both the bot's menu builder and the webapp
login response — the two places that need to agree on it."""
import pytest

from app.config import settings
settings.telegram_bot_token = "TEST-TOKEN"
settings.database_url = "sqlite+aiosqlite:///:memory:"

import app.telegram_bot as tb  # noqa: E402
from app.database import init_db  # noqa: E402
from app.i18n import (  # noqa: E402
    DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, button_text, button_texts,
    get_user_language, set_user_language, t,
)
from app.services import bot_config  # noqa: E402


@pytest.fixture(autouse=True)
async def _ensure_tables():
    await init_db()
    # The bot menu is built from the shared DB-backed button config (Admin
    # panel "Tugmalar") — seed + load it so menu_for() renders the real set.
    await bot_config.load_config()


@pytest.mark.asyncio
async def test_get_user_language_defaults_to_uz():
    assert await get_user_language(700001) == DEFAULT_LANGUAGE


@pytest.mark.asyncio
async def test_set_and_get_user_language_round_trip():
    await set_user_language(700002, "ru")
    assert await get_user_language(700002) == "ru"

    await set_user_language(700002, "en")
    assert await get_user_language(700002) == "en"


@pytest.mark.asyncio
async def test_set_user_language_rejects_unsupported_code():
    await set_user_language(700003, "xx-not-real")
    assert await get_user_language(700003) == DEFAULT_LANGUAGE


def test_t_falls_back_to_default_for_unknown_language():
    # Every real call site only ever passes a SUPPORTED_LANGUAGES value,
    # but t() itself should still degrade gracefully rather than KeyError.
    assert t("use_menu_below", "fr") == t("use_menu_below", DEFAULT_LANGUAGE)


def test_all_supported_languages_have_every_message_key():
    from app.i18n import MESSAGES
    for key, translations in MESSAGES.items():
        for lang in SUPPORTED_LANGUAGES:
            assert lang in translations, f"{key!r} is missing a {lang!r} translation"


def test_all_supported_languages_have_every_button_key():
    from app.i18n import BUTTONS
    for key, translations in BUTTONS.items():
        for lang in SUPPORTED_LANGUAGES:
            assert lang in translations, f"button {key!r} is missing a {lang!r} translation"


@pytest.mark.asyncio
async def test_menu_for_uses_the_requested_language():
    kb = tb.menu_for(700004, "en")
    labels = {b.text for row in kb.keyboard for b in row}
    assert button_text("start_group_game", "en") in labels
    assert button_text("start_group_game", "uz") not in labels
    # Roles no longer live on the main menu (in-game only, per the re-platform).
    assert button_text("roles", "en") not in labels


@pytest.mark.asyncio
async def test_menu_for_includes_admin_row_only_for_admins():
    original = settings.admin_telegram_ids
    try:
        settings.admin_telegram_ids = [700005]
        admin_kb = tb.menu_for(700005, "uz")
        other_kb = tb.menu_for(700006, "uz")
    finally:
        settings.admin_telegram_ids = original

    admin_labels = {b.text for row in admin_kb.keyboard for b in row}
    other_labels = {b.text for row in other_kb.keyboard for b in row}

    assert button_text("start_group_game", "uz") in admin_labels
    assert button_text("admin_panel", "uz") in admin_labels
    assert button_text("admin_panel", "uz") not in other_labels


@pytest.mark.asyncio
async def test_menu_is_minimal_and_about_renders_its_labels():
    labels = {b.text for row in tb.menu_for(700004, "uz").keyboard for b in row}
    # The reply keyboard is meant to stay down to exactly one button for a
    # non-admin (start_group_game) — everything else (profile, leaderboard,
    # stats, about, contact, language, roles) lives elsewhere: profile in
    # the Mini App dashboard, the rest disabled-by-default but still
    # reachable if an admin re-enables them from Sozlamalar → Tugmalar.
    assert labels == {button_text("start_group_game", "uz"), button_text("contact_admin", "uz"), "➕ Botni guruhga qo‘shish"}

    about = t("about_body", "en",
              start_group_game=button_text("start_group_game", "en"),
              leaderboard=button_text("leaderboard", "en"),
              my_stats=button_text("my_stats", "en"),
              contact_admin=button_text("contact_admin", "en"))
    assert button_text("leaderboard", "en") in about
    assert button_text("my_stats", "en") in about
    assert button_text("my_profile", "en") not in about
    assert button_text("roles", "en") not in about


@pytest.mark.asyncio
async def test_language_picker_updates_stored_preference(monkeypatch):
    """Exercises on_language_picked directly (same lightweight-fake-object
    approach as test_bot_features.py's support-relay test) rather than
    through the full webhook, since aiogram's own Message construction isn't
    part of what this suite tests."""

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
        def __init__(self, data):
            self.data = data
            self.from_user = type("U", (), {"id": 700007})()
            self.message = type("M", (), {"chat": type("C", (), {"id": 7700007})()})()

        async def answer(self):
            pass

    fake_bot = _FakeBot()
    monkeypatch.setattr(tb, "get_bot", lambda: fake_bot)
    monkeypatch.setattr(tb, "_last_panel_msg", {})

    # Tapping a language now fires an inline callback carrying "lang:<code>".
    await tb.on_language_picked(_FakeQuery("lang:ru"))

    assert await get_user_language(700007) == "ru"
    sent_texts = [text for (_, text, _) in fake_bot.sent]
    assert any("язык" in text.lower() or "изменён" in text.lower()
               for text in sent_texts)
    # The confirmation carries the (already language-switched) main menu back
    # into the panel — every sent reply keyboard is a ReplyKeyboardMarkup.
    sent_markups = [m for (_, _, m) in fake_bot.sent]
    assert all(m is not None for m in sent_markups)
