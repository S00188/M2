"""
Telegram bot logic, wired for WEBHOOK delivery instead of long-polling —
this is what lets the bot run inside the same process as the backend, with
no separate worker service. Used only when settings.telegram_webhook_enabled
is true (see app/config.py); for a VPS or Fly.io deployment that runs the
bot as its own long-polling process instead, bot/bot.py is unchanged and
still works exactly as before — a bot token can only be in one mode
(webhook or polling) at a time, so pick one deployment target per token,
not both at once.

bot/bot.py deliberately stays a minimal, standalone script (its own
requirements.txt, no database) so it can run on a bare VPS. Everything
below it (persistent menu, group picker, admin panel, support relay) needs
the backend's own DB and settings, so it only lives here — the two
commands they share (/start in a group vs. private chat) behave the same
in spirit, but bot/bot.py's private /start stays the short, DB-free
version.
"""
from __future__ import annotations
import asyncio
import logging
import os
from html import escape
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats, BotCommandScopeChat,
    CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, MenuButtonDefault, MenuButtonWebApp, Message, ReplyKeyboardMarkup,
    Update, WebAppInfo,
)
from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.i18n import (
    LANGUAGE_LABELS, SUPPORTED_LANGUAGES, button_text, button_texts,
    get_user_language, set_user_language, t,
)
from app.models.models import KnownGroup, SupportMessage, User, _utcnow
from app.services import admin_service, bot_config
from app.services.game_service import get_or_create_user
from app.services.telegram_bot_api import is_group_admin, verify_group_membership

logger = logging.getLogger("mafia.telegram_bot")

router = APIRouter(prefix="/bot", tags=["bot"])

# The Bot object validates its token's format the moment it's constructed
# (aiogram raises TokenValidationError for anything that isn't
# "<digits>:<35 chars>"). Building it at import time would crash every
# test and every deployment that doesn't set a real TELEGRAM_BOT_TOKEN —
# including this project's own test suite, which uses placeholder tokens.
# Building it lazily, only when webhook mode is actually used, avoids that
# entirely. Dispatcher() itself needs no token, so it's fine at import time.
dp = Dispatcher()
_bot: Optional[Bot] = None
_bot_username: Optional[str] = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=settings.telegram_bot_token,
                    default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return _bot


async def get_bot_username() -> str:
    """Cached so post_join_button doesn't call getMe() on every group
    message — the bot's own username never changes at runtime."""
    global _bot_username
    if _bot_username is None:
        me = await get_bot().get_me()
        _bot_username = me.username
    return _bot_username


def webapp_base_url() -> str:
    """Where this backend (and the Mini App it serves) is actually
    reachable from the outside — explicit WEBAPP_URL if set, otherwise
    Render's own auto-injected RENDER_EXTERNAL_URL (present automatically
    on every Render web service, no configuration needed)."""
    return (settings.webapp_url or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")


# ------------------------------------------------------- private menu ----
# A persistent reply keyboard (not inline) so it's always sitting above the
# keyboard in the private chat, not tied to any one message. The button set
# — which buttons exist, their labels, enable/disable state, order, and the
# admin-only flag — is the single source of truth in the Admin panel's
# "Tugmalar" module (app/services/bot_config.py, backed by the bot_buttons
# table the WebApp edits). menu_for() rebuilds the keyboard from that config
# on every render; since a ReplyKeyboardMarkup button is matched by its
# literal text, every handler below filters on button_texts(key) (all
# languages' configured + default labels), not a single fixed string.
#
# Per the premium spec, the main menu is minimal and the "Sizning profilyor"
# entry lives inside the Mini App dashboard (opened via the blue Menu
# button) rather than on this keyboard; the general "Rollar" section is
# also gone from the menu — roles are only ever shown in-game.


def menu_for(user_id: int, lang: str) -> ReplyKeyboardMarkup:
    from app.i18n import DEFAULT_LANGUAGE, button_text as _bt
    buttons = [b for b in bot_config.menu_button_order(user_id) if b["key"] not in ("admin_panel", "contact_admin")]
    buttons.append({"key": "contact_admin"})
    if bot_config.is_known_admin(user_id):
        buttons.append({"key": "admin_panel"})
    base_url = webapp_base_url()

    def _button(b: dict) -> KeyboardButton:
        label = b.get(f"label_{lang}") or b.get(f"label_{DEFAULT_LANGUAGE}") or _bt(b["key"], lang)
        # Admin paneli opens the WebApp straight from this one tap — no
        # intermediate "here's a button to open it" message. A web_app
        # KeyboardButton only works in private chats, which is exactly
        # where this keyboard is ever shown (see the ChatType.PRIVATE
        # filters on every handler below), and only when the backend has
        # a real public URL to hand Telegram; otherwise this falls back to
        # the plain-text button + /admin's inline-WebApp-button flow.
        if b["key"] == "admin_panel":
            return KeyboardButton(text=label)
        if b["key"] == "my_profile" and base_url:
            return KeyboardButton(text=label, web_app=WebAppInfo(url=f"{base_url}/?view=home&lang={lang}"))
        return KeyboardButton(text=label)

    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(
        keyboard=[[_button(b) for b in row] for row in rows] + [[KeyboardButton(text="➕ Botni guruhga qo‘shish")]],
        resize_keyboard=True,
    )


# ------------------------------------------------------- menu screens ----
# The bottom panel is the main menu only — a persistent reply keyboard.
# Every submenu (language, group picker, force-sub, admin panel, broadcast)
# is an INLINE keyboard instead: it appears as buttons under a message, so
# entering a section never swaps or pops a reply-keyboard panel over the
# input field. Mini App launchers (roles list, admin WebApp) are inline
# `web_app` buttons for the same reason — only inline buttons can carry a URL.
#
# The bot's current screen is tracked per user so (a) the back row knows
# which panel to restore and (b) free-text input (an admin's force-sub
# channel / broadcast body / a user's message for the admins) routes to the
# right consumer. Losing the map on a restart just resets everyone to the
# main menu — not worth persisting.
SCREEN_MAIN = "main"
SCREEN_LANG = "language"
SCREEN_GROUPS = "groups"
SCREEN_CONTACT = "contact"
SCREEN_ADMIN = "admin"

_menu_screen: dict[int, str] = {}


def _current_screen(user_id: int) -> str:
    return _menu_screen.get(user_id, SCREEN_MAIN)


def _enter_screen(user_id: int, screen: str) -> None:
    _menu_screen[user_id] = screen


def _reset_screen(user_id: int) -> None:
    """Back to the main menu; the group picker buttons stop being valid."""
    _menu_screen[user_id] = SCREEN_MAIN

# Track the last interactive message sent to each user in private chat, so
# subsequent menu taps can update that message instead of stacking new
# ones. Two kinds of updates happen:
#   - Inline panels (every submenu, the roles / admin Mini App launchers)
#     and pure-text screens edit the message in place — EditMessageText
#     allows both, and it never disturbs the bottom keyboard.
#   - A new main menu (ReplyKeyboardMarkup) can NOT be attached to an
#     edited message, so returning to the lobby-level panel deletes the old
#     screen message and posts a fresh one carrying the panel.
_last_panel_msg: dict[int, Message] = {}


async def _edit_or_send(chat_id: int, text: str, reply_markup=None) -> Message:
    """Show `text` with `reply_markup` as the user's active interactive
    message, editing the previous one where Telegram allows it. Returns the
    message that now holds the screen.

    Inline keyboards and text-only screens are edited in place. A
    ReplyKeyboardMarkup is never sent through edit_text: aiogram raises
    ValidationError for it (the field only accepts InlineKeyboardMarkup)
    and even a valid API call couldn't change the bottom panel — the reply
    keyboard on the previous message can only be replaced by a new message.
    A main-menu call therefore deletes the old screen message first and
    sends a fresh one, so the panel underneath really does update."""
    is_inline = isinstance(reply_markup, InlineKeyboardMarkup)
    prev = _last_panel_msg.get(chat_id)
    if prev:
        if is_inline or reply_markup is None:
            try:
                await prev.edit_text(text, reply_markup=reply_markup)
                return prev
            except TelegramBadRequest as exc:
                # "message is not modified" means the panel already shows
                # exactly this content — that's a success, NOT a reason to
                # post a duplicate message (which is what made buttons pile
                # up as separate chat messages on repeated taps).
                if "not modified" in str(exc):
                    return prev
                # Otherwise the tracked message is unusable (deleted / too
                # old / media-only). Retire it so the fresh panel below is
                # the only one left on screen.
                try:
                    await prev.delete()
                except TelegramBadRequest:
                    pass
        else:
            # Reply-keyboard panel: editing can't change it, so retire the
            # old panel message and let the new one below replace it.
            try:
                await prev.delete()
            except TelegramBadRequest:
                pass  # already gone — the send below owns the screen now
    msg = await get_bot().send_message(chat_id, text, reply_markup=reply_markup)
    _last_panel_msg[chat_id] = msg
    return msg


# ------------------------------------------------------------- language --
# An inline submenu now: the three languages render as buttons under the
# prompt message, and the bottom keyboard keeps showing the main menu —
# choosing a language never swaps in a reply-keyboard panel.
@dp.message(F.text.in_(button_texts("language")), F.chat.type == ChatType.PRIVATE)
async def on_language_button(message: Message) -> None:
    user_id = message.from_user.id
    _enter_screen(user_id, SCREEN_LANG)
    text, kb = await _render_screen(user_id, SCREEN_LANG)
    await _edit_or_send(message.chat.id, text, reply_markup=kb)


@dp.callback_query(F.data.in_(set(f"lang:{c}" for c in SUPPORTED_LANGUAGES)),
                   F.message.chat.type == ChatType.PRIVATE)
async def on_language_picked(query: CallbackQuery) -> None:
    await query.answer()
    lang = query.data.split(":", 1)[1]
    if lang not in SUPPORTED_LANGUAGES:
        return
    user_id = query.from_user.id
    await set_user_language(user_id, lang)
    _reset_screen(user_id)
    await _edit_or_send(query.message.chat.id, t("language_set", lang),
                        reply_markup=menu_for(user_id, lang))


async def _render_screen(user_id: int, screen: str) -> tuple[str, InlineKeyboardMarkup]:
    """(prompt text, inline keyboard) for a menu screen. Every submenu has
    a trailing "back" button — that's what makes navigation inline: opening
    a submenu shows its buttons under the message, tapping a leaf does its
    thing, tapping back restores the previous screen. The channel link on
    the force-sub screen lives in the message text as a hyperlink (a URL
    can't be a reply button), so the whole gate stays inline too. None of
    this ever disturbs the bottom keyboard — the main menu is the only
    ReplyKeyboardMarkup in the design."""
    lang = await get_user_language(user_id)
    if screen == SCREEN_LANG:
        rows = [[InlineKeyboardButton(text=LANGUAGE_LABELS[c], callback_data=f"lang:{c}")
                 for c in SUPPORTED_LANGUAGES],
                [InlineKeyboardButton(text=button_text("back", lang), callback_data="back")]]
        return t("language_prompt", lang), InlineKeyboardMarkup(inline_keyboard=rows)

    if screen == SCREEN_ADMIN:
        return "🛠 <b>Admin paneli</b>", _admin_keyboard(lang)

    return t("use_menu_below", lang), menu_for(user_id, lang)


# ------------------------------------------------------ menu: back button -
# Every submenu ends with a "back" button; tapping it restores the main
# menu. The admin panel no longer has nested bot-side sub-screens (its
# broadcast/statistics/etc. live in the WebApp now), so "back" always
# means the main menu.
@dp.callback_query(F.data == "back", F.message.chat.type == ChatType.PRIVATE)
async def on_back_button(query: CallbackQuery) -> None:
    await query.answer()
    user_id = query.from_user.id
    _reset_screen(user_id)
    text, kb = await _render_screen(user_id, SCREEN_MAIN)
    await _edit_or_send(query.message.chat.id, text, reply_markup=kb)


# --------------------------------------------------------- known groups --
async def upsert_known_group(chat_id: int, title: str, is_active: bool) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.get(KnownGroup, chat_id)
        if row is None:
            session.add(KnownGroup(chat_id=chat_id, title=title, is_active=is_active))
        else:
            row.title = title or row.title
            row.is_active = is_active
            row.updated_at = _utcnow()
        await session.commit()


@dp.my_chat_member(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def on_bot_membership_changed(event: ChatMemberUpdated) -> None:
    """Telegram's Bot API has no "list every group I'm in" call, so this is
    the only way the bot can ever know which groups exist for the "Guruhda
    o'yin boshlash" picker below — it has to notice itself being added or
    removed, as it happens, and remember."""
    status = event.new_chat_member.status
    is_active = status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
    was_active = event.old_chat_member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
    await upsert_known_group(event.chat.id, event.chat.title or "", is_active)

    # The moment the bot gains admin rights in this group, its left-menu
    # button should immediately offer just /start and /stop — set this on
    # every transition INTO administrator (not only the very first promote)
    # so re-promoting after a demote also re-applies it.
    if status == ChatMemberStatus.ADMINISTRATOR and event.old_chat_member.status != ChatMemberStatus.ADMINISTRATOR:
        try:
            await _ensure_group_commands_for_chat(event.chat.id)
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.warning("Could not set /start /stop command menu for group %s", event.chat.id)

    # When the bot is (re)added to a group, post the admin-editable welcome
    # (Bot matnlari module, "Guruhga qo'shilgandagi xabar"). Only on an
    # actual join transition, so a promote-to-admin later doesn't post it
    # again; group-shared message → always Uzbek.
    if is_active and not was_active:
        try:
            await get_bot().send_message(event.chat.id, bot_config.get_text("group_added", "uz"))
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.warning("Could not post welcome to group %s", event.chat.id)


# --------------------------------------------------- group command menu --
# Per-group requirement: whoever opens the bot's "/" menu inside a group
# (any member, not just admins) sees exactly two entries — /start and
# /stop. BotCommandScopeChat(chat_id) is what actually achieves "this one
# group, everyone in it"; the two broader scopes below are kept in sync too
# so a group the bot is already admin in from before this feature shipped
# (or one telegram is slow to notify us about) still gets a sane menu the
# next time the process reconciles its command scopes at startup.
GROUP_GAME_COMMANDS = [
    BotCommand(command="start", description="O'yinni boshlash"),
    BotCommand(command="stop", description="O'yinni to'xtatish"),
]

# Shown for a repeat /start (or the private group-picker) while a match —
# lobby/gathering included — is already running for that group.
GAME_ALREADY_ACTIVE_MESSAGE = (
    "⚠️ Hurmatli o'yinchilar, ushbu guruhda allaqachon o'yin ketmoqda. "
    "Yangi o'yin boshlash uchun amaldagi bahs tugashini kuting yoki "
    "o'yinni bekor qilish uchun /stop buyrug'idan foydalaning."
)


async def _ensure_group_commands_for_chat(chat_id: int) -> None:
    """Called the moment the bot is promoted to administrator in a group
    (see on_bot_membership_changed) — sets that specific chat's command
    menu to just /start and /stop, for every member and admin of that
    group alike."""
    await get_bot().set_my_commands(GROUP_GAME_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))


async def _ensure_group_commands_global() -> None:
    """Keeps the two catch-all group scopes in sync with the same two
    commands, as a fallback for groups the per-chat call above hasn't (yet)
    covered. Called once at webhook registration / startup."""
    bot = get_bot()
    await bot.set_my_commands(GROUP_GAME_COMMANDS, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(GROUP_GAME_COMMANDS, scope=BotCommandScopeAllChatAdministrators())


# ------------------------------------------------------------- /start ----
def group_message_link(chat, message_id: int) -> Optional[str]:
    """A t.me deep link that opens the group right on the join-button
    message. Public groups/supergroups have a @username, so the plain
    t.me/<username>/<message_id> form works. Private supergroups don't, but
    Telegram still resolves t.me/c/<internal_id>/<message_id> for anyone
    who is already a member — which is exactly who this link is shown to
    (membership was verified before we posted). Anything else (a basic
    group that was never migrated to a supergroup, so its id has no -100
    prefix) has no linkable message, so this returns None and the caller
    simply omits the button rather than sending a URL Telegram would
    reject."""
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}/{message_id}"
    chat_id_str = str(chat.id)
    if chat_id_str.startswith("-100"):
        return f"https://t.me/c/{chat_id_str[4:]}/{message_id}"
    return None


async def post_join_button(chat_id: int) -> Message:
    base_url = webapp_base_url()
    if not base_url:
        # Would otherwise build an invalid (relative) web_app URL that
        # Telegram rejects with a cryptic Bad Request — surface the real
        # cause plainly instead of letting that generic error confuse
        # whoever's debugging it. The bot STILL answers the /start (never a
        # silent 500 + infinite Telegram retries): the lobby text is posted
        # with a note about what's missing, so at least the group sees the
        # bot is alive and knows the admin has one env var to fix.
        logger.error(
            "post_join_button: no public URL known (WEBAPP_URL or RENDER_EXTERNAL_URL "
            "empty) — cannot build a Mini App join link for chat %s", chat_id,
        )
        return await get_bot().send_message(
            chat_id,
            bot_config.get_text("lobby", "uz")
            + "\n\n⚠️ <i>Botning WEBAPP_URL sozlanmagan — qo'shilish tugmasi "
              "yaratilmadi. Admin bilan bog'laning.</i>",
        )
    # Telegram's Bot API only allows a `web_app` inline button in a private
    # chat between a user and the bot ("Available only in private chats
    # between a user and the bot" — the docs are explicit about this).
    # This function always posts to a *group* chat_id, so building the
    # button that way gets rejected outright with "Bad Request:
    # BUTTON_TYPE_INVALID". The supported way to open a Mini App from a
    # group is a plain `url` button using Telegram's "Direct Link Mini
    # Apps" scheme (t.me/<bot>?startapp=<payload>) — Telegram recognizes
    # that link shape and launches the Mini App with initData intact
    # instead of opening a normal browser tab, so /games auth (which
    # requires real initData, see telegram_auth.py) still works.
    # One-time setup this relies on: the bot's Mini App URL must be
    # configured via @BotFather (Bot Settings > Mini App), set to this
    # same WEBAPP_URL — otherwise the link just opens the bot's chat.
    username = await get_bot_username()
    webapp_url = f"https://t.me/{username}?startapp={chat_id}"

    # Game State Lock: a group may only ever have one active match — the
    # lobby/gathering stage counts as "active" too (get_by_chat only
    # returns None once the previous match reached GAME_OVER). A repeat
    # /start while that's true is refused outright with the standard
    # warning rather than silently reposting a join button.
    from app.services.game_service import registry
    if registry.get_by_chat(str(chat_id)):
        return await get_bot().send_message(chat_id, GAME_ALREADY_ACTIVE_MESSAGE)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎭 O'yinga qo'shilish", url=webapp_url),
    ]])
    # The lobby message is admin-editable (Bot matnlari module, "Lobby
    # xabari"). Group-shared by nature, so it always renders in Uzbek, just
    # like the rest of the messages this function posts into a group chat.
    return await get_bot().send_message(
        chat_id,
        bot_config.get_text("lobby", "uz"),
        reply_markup=keyboard,
    )


@dp.message(Command("start"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def start_in_group(message: Message) -> None:
    """The one and only entry point into a match — same as bot/bot.py's
    polling version. There is no "create game" command; every tap of this
    button lands on POST /games/for-chat, which creates the group's match
    on the first tap and joins everyone else into that same match after."""
    try:
        await upsert_known_group(message.chat.id, message.chat.title or "", True)
        await post_join_button(message.chat.id)
    except Exception as e:
        # Never leave the group with a silent /start — whatever went wrong
        # (Telegram API hiccup, DB error, missing config), say something.
        logger.exception("start_in_group failed for chat %s", message.chat.id)
        try:
            await message.answer(
                "⚠️ <b>O'yinni boshlashda xatolik yuz berdi.</b>\n"
                f"<i>{escape(str(e)[:300])}</i>"
            )
        except Exception:
            logger.exception("Could not even post the /start error message")


async def _force_stop_game(engine) -> None:
    """Fully tears down one running match — lobby or mid-game, any phase.

    There's no per-game asyncio.Task or interval timer to cancel outright:
    every phase deadline is just a timestamp on GameState that the single
    global phase_ticker (app/websocket/handlers.py) polls once a second
    across every engine currently in the registry. Removing the engine
    from the registry IS "cancel all active timers" in this architecture
    — the very next tick simply stops seeing this game at all. What's left
    is cleaning up everything else that would otherwise dangle: connected
    Mini App clients (told and disconnected), the bot-players module's
    per-game bookkeeping, the notifications module's last-announced-phase
    memory, and the DB checkpoint a restart could otherwise resurrect this
    match from.
    """
    from app.game_engine.bot_players import forget_game as forget_bot_state
    from app.services.checkpoint_service import delete_checkpoint
    from app.services.game_service import registry
    from app.services.notifications import forget_game as forget_announced_game
    from app.websocket.manager import manager

    game_id = engine.state.game_id
    registry.remove(game_id)
    forget_bot_state(game_id)
    forget_announced_game(game_id)
    await delete_checkpoint(game_id)
    await manager.broadcast_and_close(game_id, {
        "type": "game_stopped",
        "message": "O'yin admin tomonidan to'xtatildi.",
    })


@dp.message(Command("stop"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def stop_in_group(message: Message) -> None:
    """Cancels whatever match — lobby or any in-progress phase — is
    currently bound to this group, regardless of stage. Restricted to
    group admins and whoever's /start actually created this match (the
    host); anyone else gets a polite refusal and nothing happens."""
    chat_id = message.chat.id
    user_id = message.from_user.id

    from app.services.game_service import registry
    engine = registry.get_by_chat(str(chat_id))
    if engine is None:
        await message.reply("ℹ️ Hozircha bu guruhda faol o'yin yo'q.")
        return

    host_telegram_id = engine.state.players[engine.state.host_id].telegram_user_id
    is_bot_admin = await admin_service.is_admin(user_id)
    if user_id != host_telegram_id and not await is_group_admin(chat_id, user_id) and not is_bot_admin:
        await message.reply(
            "⛔ Faqat guruh administratorlari, bot adminlari yoki o'yinni boshlagan foydalanuvchi "
            "/stop buyrug'idan foydalana oladi."
        )
        return

    try:
        await _force_stop_game(engine)
        await message.answer(
            "🛑 <b>O'yin to'xtatildi.</b>\n\n"
            "Amaldagi bahs bekor qilindi va guruh yangi o'yin uchun bo'shatildi. "
            "Yangi o'yin boshlash uchun /start buyrug'ini yuboring."
        )
    except Exception as e:
        logger.exception("stop_in_group failed for chat %s", chat_id)
        await message.answer(
            "⚠️ O'yinni to'xtatishda xatolik yuz berdi.\n"
            f"<i>{escape(str(e)[:300])}</i>"
        )


@dp.message(Command("start"), F.chat.type == ChatType.PRIVATE)
async def start_in_private(message: Message) -> None:
    tg_user = message.from_user
    try:
        async with AsyncSessionLocal() as session:
            await get_or_create_user(session, tg_user.id, tg_user.first_name,
                                      tg_user.last_name, tg_user.username, None)

        lang = await get_user_language(tg_user.id)
        _reset_screen(tg_user.id)
        # The /start message is admin-editable (Bot matnlari module) — the
        # configured value comes from the shared config with the code default
        # as fallback.
        await _edit_or_send(message.chat.id, bot_config.get_text("start", lang),
                            reply_markup=menu_for(tg_user.id, lang))
    except Exception as e:
        logger.exception("start_in_private failed for user %s", tg_user.id)
        try:
            await message.answer(
                "⚠️ Ishlashda xatolik yuz berdi.\n"
                f"<i>{escape(str(e)[:300])}</i>"
            )
        except Exception:
            logger.exception("Could not even post the /start error message")


@dp.message(Command("admin"), F.chat.type == ChatType.PRIVATE)
async def admin_panel_command(message: Message) -> None:
    await _open_admin_panel(message)


# ------------------------------------------------------ menu: Admin paneli
# The primary way in — a row on the bottom keyboard itself (see menu_for),
# shown only to admin_telegram_ids, so the panel never needs the /admin
# command to be remembered. /admin above is kept as a harmless alternative
# for anyone who prefers to type it.
@dp.message(F.text.in_(button_texts("admin_panel")), F.chat.type == ChatType.PRIVATE)
async def on_admin_panel_button(message: Message) -> None:
    await _open_admin_panel(message)


# ----------------------------------------------------- menu: Bot haqida --
@dp.message(F.text.in_(button_texts("about")), F.chat.type == ChatType.PRIVATE)
async def on_about(message: Message) -> None:
    user_id = message.from_user.id
    _reset_screen(user_id)
    lang = await get_user_language(user_id)
    await _edit_or_send(message.chat.id, t(
        "about_body", lang,
        start_group_game=button_text("start_group_game", lang),
        leaderboard=button_text("leaderboard", lang),
        my_stats=button_text("my_stats", lang),
        contact_admin=button_text("contact_admin", lang),
    ))


# --------------------------------------------------- menu: Top / Reyting --
@dp.message(Command("leaderboard"), F.chat.type == ChatType.PRIVATE)
@dp.message(F.text.in_(button_texts("leaderboard")), F.chat.type == ChatType.PRIVATE)
async def on_leaderboard(message: Message) -> None:
    user_id = message.from_user.id
    _reset_screen(user_id)
    lang = await get_user_language(user_id)
    async with AsyncSessionLocal() as session:
        top = (await session.execute(
            select(User).where(User.games_played > 0).order_by(User.wins.desc()).limit(10)
        )).scalars().all()
    if not top:
        await _edit_or_send(message.chat.id, t("leaderboard_empty", lang))
        return
    lines = [t("leaderboard_title", lang), ""]
    for place, u in enumerate(top, start=1):
        name = f"@{u.username}" if u.username else u.first_name
        lines.append(t("leaderboard_line", lang, place=place, name=name,
                        wins=u.wins, games=u.games_played))
    await _edit_or_send(message.chat.id, "\n".join(lines))


# ----------------------------------------------------- menu: Statistikam -
@dp.message(F.text.in_(button_texts("my_stats")), F.chat.type == ChatType.PRIVATE)
async def on_my_stats(message: Message) -> None:
    user_id = message.from_user.id
    _reset_screen(user_id)
    lang = await get_user_language(user_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == user_id)
        )
        user = result.scalar_one_or_none()

    if user is None or user.games_played == 0:
        await _edit_or_send(message.chat.id, t("stats_none_yet", lang))
        return

    win_rate = round(100 * user.wins / user.games_played)
    await _edit_or_send(message.chat.id, t(
        "stats_body", lang,
        games_played=user.games_played, wins=user.wins, win_rate=win_rate,
        losses=user.losses, town_wins=user.town_wins,
        mafia_wins=user.mafia_wins, neutral_wins=user.neutral_wins,
    ))


# ----------------------------------------------------- menu: Profilim -
@dp.message(Command("profile"), F.chat.type == ChatType.PRIVATE)
@dp.message(F.text.in_(button_texts("my_profile")), F.chat.type == ChatType.PRIVATE)
async def on_profile_button(message: Message) -> None:
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    _reset_screen(user_id)
    # ?view=profile makes the webapp (app/static/app.js) open straight into
    # the player's own dashboard — avatar, lifetime stats, faction wins,
    # current game and recent finished games. lang= skips the default-Uzbek
    # flash and opens already translated.
    base_url = webapp_base_url()
    if not base_url:
        # Telegram rejects a web_app button whose URL isn't absolute — say
        # why instead of failing silently.
        logger.error("on_profile_button: no public URL known for user %s", user_id)
        await _edit_or_send(
            message.chat.id,
            t("profile_prompt", lang)
            + "\n\n⚠️ <i>Harakat bajarilmadi: botning <code>WEBAPP_URL</code> "
              "sozlanmagan.</i>",
        )
        return
    url = f"{base_url}/?view=home&lang={lang}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("profile_open_button", lang), web_app=WebAppInfo(url=url)),
    ]])
    await _edit_or_send(message.chat.id, t("profile_prompt", lang), reply_markup=kb)


# ----------------------------------------------------------- menu: Rollar -
@dp.message(F.text.in_(button_texts("roles")), F.chat.type == ChatType.PRIVATE)
async def on_roles_button(message: Message) -> None:
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    _reset_screen(user_id)
    # ?view=roles tells the webapp (app/static/app.js) to open straight into
    # the Roles tab with the rest of the navigation hidden — see that
    # file's boot() for how the query param is read. lang= lets the webapp
    # open already translated instead of defaulting to Uzbek and flashing
    # a language switch a moment later. Without a public URL a web_app
    # button would be rejected by Telegram, so say why instead of failing
    # silently.
    base_url = webapp_base_url()
    if not base_url:
        logger.error("on_roles_button: no public URL known for user %s", user_id)
        await _edit_or_send(
            message.chat.id,
            t("roles_prompt", lang)
            + "\n\n⚠️ <i>Harakat bajarilmadi: botning <code>WEBAPP_URL</code> "
              "sozlanmagan.</i>",
        )
        return
    url = f"{base_url}/?view=roles&lang={lang}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("roles_open_button", lang), web_app=WebAppInfo(url=url)),
    ]])
    # A Mini App can only launch from an inline web_app button, so this leaf
    # stays one in-place message — the reply keyboard under it is untouched.
    await _edit_or_send(message.chat.id, t("roles_prompt", lang), reply_markup=kb)


# ------------------------------------------- menu: Guruhda o'yin boshlash -
@dp.message(Command("addgroup"), F.chat.type == ChatType.PRIVATE)
@dp.message(F.text == "➕ Botni guruhga qo‘shish", F.chat.type == ChatType.PRIVATE)
async def on_add_group(message: Message) -> None:
    username = await get_bot_username()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="➕ Guruhni tanlash",
            url=f"https://t.me/{username}?startgroup=mafia&admin=manage_chat",
        ),
    ]])
    await _edit_or_send(
        message.chat.id,
        "Guruhni tanlang va Telegram oynasida botning admin huquqini tasdiqlang. "
        "Buning uchun guruhda admin tayinlash huquqingiz bo‘lishi kerak.",
        reply_markup=kb,
    )


@dp.message(F.text.in_(button_texts("start_group_game")), F.chat.type == ChatType.PRIVATE)
async def on_start_group_game(message: Message) -> None:
    user_id = message.from_user.id
    lang = await get_user_language(user_id)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(KnownGroup).where(KnownGroup.is_active.is_(True)))
        groups = result.scalars().all()

    if not groups:
        _reset_screen(user_id)
        await _edit_or_send(message.chat.id, t("no_groups_known", lang),
                            reply_markup=menu_for(user_id, lang))
        return

    # Telegram's Bot API has no "which groups is this user in" call, so
    # membership is checked against the known groups. These run CONCURRENTLY
    # (each getChatMember call may take up to its 5s timeout): a naive
    # for-loop would take 5s × N sequentially, which for a handful of groups
    # already exceeds Telegram's webhook delivery timeout and the user would
    # see "no reply" while the handler is still grinding through checks.
    matches = [g for pair, g in zip(
        await asyncio.gather(*(verify_group_membership(str(g.chat_id), user_id) for g in groups[:20])),
        groups[:20],
    ) if pair]

    if not matches:
        _reset_screen(user_id)
        await _edit_or_send(message.chat.id, t("no_matching_groups", lang),
                            reply_markup=menu_for(user_id, lang))
        return

    # The group list becomes an inline submenu: one callback button per
    # matching group (two to a row) plus a back row. Each callback carries
    # the group's chat id, so no text->id lookup map is needed.
    buttons = []
    for g in matches[:20]:
        label = f"🏁 {g.title or f'Guruh {g.chat_id}'}"
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"grp:{g.chat_id}"))
    rows_inline = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows_inline.append([InlineKeyboardButton(text=button_text("back", lang), callback_data="back")])
    _enter_screen(user_id, SCREEN_GROUPS)
    kb = InlineKeyboardMarkup(inline_keyboard=rows_inline)
    await _edit_or_send(message.chat.id, t("pick_a_group", lang), reply_markup=kb)


@dp.callback_query(F.data.startswith("grp:"), F.message.chat.type == ChatType.PRIVATE)
async def on_group_picked(query: CallbackQuery) -> None:
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_language(user_id)

    try:
        chat_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        # Stale screen (app restarted mid-pick) — drop back to the main
        # menu and ask them to pick again.
        _reset_screen(user_id)
        await _edit_or_send(query.message.chat.id, t("no_matching_groups", lang),
                            reply_markup=menu_for(user_id, lang))
        return

    # Re-verify at tap time too — the list shown could be stale by now.
    if not await verify_group_membership(str(chat_id), user_id):
        _reset_screen(user_id)
        await _edit_or_send(query.message.chat.id, t("not_a_member_alert", lang),
                            reply_markup=menu_for(user_id, lang))
        return

    # Prevent duplicate game creation — if a game is already active in this
    # group, just tell them instead of posting a second join message.
    from app.services.game_service import registry
    existing = registry.get_by_chat(str(chat_id))
    if existing:
        _reset_screen(user_id)
        await _edit_or_send(query.message.chat.id, GAME_ALREADY_ACTIVE_MESSAGE,
                            reply_markup=menu_for(user_id, lang))
        return

    try:
        posted = await post_join_button(chat_id)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        # Whatever Telegram actually said (not a guess) — logged in full for
        # the bot owner, and shown to the user too: a swallowed "may have
        # been removed" guess hides real causes like an invalid webapp URL
        # or a group that restricts messaging to admins-only.
        logger.warning("post_join_button failed for chat_id=%s: %s: %s",
                       chat_id, type(e).__name__, e)
        _reset_screen(user_id)
        text = t("could_not_post_to_group_details", lang, error=str(e))
        await _edit_or_send(query.message.chat.id, text, reply_markup=menu_for(user_id, lang))
        return

    _reset_screen(user_id)
    # The join button lives in the group, but the confirmation is nothing
    # more than text + a hyperlink, so the main menu comes straight back
    # under it — no stray inline message to dismiss.
    link = group_message_link(posted.chat, posted.message_id)
    text = t("group_link_sent", lang)
    if link:
        text += f'\n\n<a href="{link}">{t("open_group_button", lang)}</a>'
    await _edit_or_send(query.message.chat.id, text, reply_markup=menu_for(user_id, lang))


# --------------------------------------------- menu: Admin bilan bog'lanish
@dp.message(F.text.in_(button_texts("contact_admin")), F.chat.type == ChatType.PRIVATE)
async def on_contact_admin(message: Message) -> None:
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    from app.bot_controls import support_admins
    if not await support_admins():
        _reset_screen(user_id)
        await _edit_or_send(message.chat.id, t("admin_not_configured", lang),
                            reply_markup=menu_for(user_id, lang))
        return
    # The main menu stays visible underneath: the next free text they type
    # is routed to _relay_to_admins by the catch-all, and tapping any
    # main-menu button instead naturally leaves the screen (each handler
    # resets it). See on_private_text.
    _enter_screen(user_id, SCREEN_CONTACT)
    await _edit_or_send(message.chat.id, t("ask_admin_message", lang))


async def _relay_to_admins(message: Message) -> None:
    """Copies a user's free-text message to every configured admin and
    remembers which admin got which copy, so whichever one replies (a
    Telegram reply-to on their own copy) gets routed back to this same
    user — see on_admin_reply below. The forwarded copy the ADMIN sees
    stays Uzbek-only, same scope note as the rest of the admin panel."""
    lang = await get_user_language(message.from_user.id)
    if len(message.text or "") > 3000:
        _enter_screen(message.from_user.id, SCREEN_CONTACT)
        await message.answer("Murojaatni 3000 belgigacha qisqartirib yuboring.")
        return
    tg_user = message.from_user
    display_name = (f"@{tg_user.username}" if tg_user.username
                     else f"{tg_user.first_name} {tg_user.last_name or ''}".strip())

    sent_to_anyone = False
    async with AsyncSessionLocal() as session:
        from app.bot_controls import support_admins, support_keyboard
        for admin_id in await support_admins():
            try:
                copy = await get_bot().send_message(
                    admin_id,
                    f"✉️ <b>{escape(display_name)}</b> (id: <code>{tg_user.id}</code>) dan xabar:\n\n"
                    f"{escape(message.text[:3000])}",
                )
            except (TelegramForbiddenError, TelegramBadRequest):
                # That admin has never started the bot, or has blocked it —
                # skip them, other admins may still be reachable.
                continue
            sent_to_anyone = True
            session.add(SupportMessage(
                user_telegram_id=tg_user.id, user_display_name=display_name,
                admin_telegram_id=admin_id, admin_copy_message_id=copy.message_id,
                original_text=message.text[:4096],
            ))
        await session.commit()
        # Durable copy IDs support Telegram replies after a restart.
        rows = (await session.execute(select(SupportMessage).where(
            SupportMessage.user_telegram_id == tg_user.id,
            SupportMessage.replied.is_(False),
        ).order_by(SupportMessage.id.desc()).limit(len(await support_admins())))).scalars().all()
        for row in rows:
            try:
                await get_bot().edit_message_reply_markup(
                    chat_id=row.admin_telegram_id, message_id=row.admin_copy_message_id,
                    reply_markup=support_keyboard(row.id, row.user_telegram_id),
                )
            except (TelegramForbiddenError, TelegramBadRequest):
                pass

    if sent_to_anyone:
        await message.answer(t("admin_message_sent", lang))
    else:
        await message.answer(t("admin_message_failed", lang))


async def on_admin_reply(message: Message) -> None:
    """An admin, in their own private chat with the bot, replied to one of
    the forwarded copies from _relay_to_admins — route their reply text
    back to the original user, in THAT user's own language (not the
    admin's), since this part is player-facing."""
    replied_to = message.reply_to_message
    if len(message.text or "") > 3000:
        await message.reply("Javobni 3000 belgigacha qisqartiring.")
        return
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SupportMessage).where(
                SupportMessage.admin_telegram_id == message.from_user.id,
                SupportMessage.admin_copy_message_id == replied_to.message_id,
            )
        )
        support_row = result.scalar_one_or_none()
        if support_row is None:
            return
        target_user_id = support_row.user_telegram_id
        row_id = support_row.id

    target_lang = await get_user_language(target_user_id)
    try:
        await get_bot().send_message(target_user_id, t("admin_reply_label", target_lang, text=escape(message.text[:3000])))
        async with AsyncSessionLocal() as session:
            row = await session.get(SupportMessage, row_id)
            row.replied = True
            await session.commit()
        await message.reply("✅ Yuborildi.")
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.reply("Foydalanuvchiga yubora olmadim — u botni bloklagan bo'lishi mumkin.")


# ------------------------------------------------------------ admin panel -
# Single source of truth: the bot side of the admin surface is just a
# launcher for the WebApp Admin Panel (Foydalanuvchilar, Adminlar, Bot
# matnlari, Xabarlar, Guruhlar, Statistika, Sozlamalar all live there).
# There used to be a second, independent inline menu here — Statistika/Top/
# Xabar yuborish/Majburiy obuna as bot-side callbacks with their own,
# thinner logic (no admin-permission checks, no targeting on broadcasts,
# and the mandatory-subscription gate the unified spec removes outright).
# That duplicate has been deleted rather than kept in sync by hand; this is
# now the only admin entry point the bot itself renders.
def _admin_keyboard(lang: str) -> InlineKeyboardMarkup:
    url = webapp_base_url()
    rows = [
        [InlineKeyboardButton(text="✉️ Murojaatlar", callback_data="ctl:inbox")],
        [InlineKeyboardButton(text="📢 Reklama yuborish", callback_data="ctl:ad"),
         InlineKeyboardButton(text="📊 Reklama tarixi", callback_data="ctl:history")],
        [InlineKeyboardButton(text="📣 Majburiy kanallar", callback_data="ctl:channels")],
        [InlineKeyboardButton(text="🚫 Bloklash", callback_data="ctl:block"),
         InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data="ctl:unblock")],
    ]
    if url:
        rows.append([InlineKeyboardButton(
            text="🖥 Admin WebApp",
            web_app=WebAppInfo(url=f"{url}/?view=admin"),
        )])
    rows.append([InlineKeyboardButton(text=button_text("back", lang), callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _open_admin_panel(message: Message) -> None:
    user_id = message.from_user.id
    if not await admin_service.is_admin(user_id):
        return
    _enter_screen(user_id, SCREEN_ADMIN)
    text, kb = await _render_screen(user_id, SCREEN_ADMIN)
    await _edit_or_send(message.chat.id, text, reply_markup=kb)


from app.bot_controls import register_controls, consume_admin_input
register_controls(dp)

# ------------------------------------------------- private catch-all text -
# Registered last on purpose: every specific handler above (menu buttons,
# submenu buttons, the back row) matches first when it applies, so this only
# ever catches free-form text — an admin's reply-to on a relayed message,
# admin-panel input (force-sub channel, broadcast body), a user's message
# while on the "contact admin" screen, or (falling through) a nudge back to
# the menu. admin_telegram_ids is read here at call time (not baked into a
# filter at import time), so it always reflects whatever
# settings.admin_telegram_ids currently holds.
@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def on_private_text(message: Message) -> None:
    user_id = message.from_user.id
    if await consume_admin_input(message):
        return
    is_admin = await admin_service.is_admin(user_id)

    if is_admin and message.reply_to_message is not None:
        try:
            await admin_service.ensure_permission(user_id, "support.reply")
        except HTTPException:
            await message.answer("Javob yozish uchun ruxsatingiz yo‘q.")
            return
        await on_admin_reply(message)
        return
    if _current_screen(user_id) == SCREEN_CONTACT:
        _reset_screen(user_id)
        await _relay_to_admins(message)
        return
    lang = await get_user_language(user_id)
    await _edit_or_send(message.chat.id, t("command_not_understood", lang),
                        reply_markup=menu_for(user_id, lang))


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> dict:
    """Telegram POSTs every update here instead of us polling for them.
    The secret-token header is Telegram's own mechanism for proving a
    request really came from them (set via set_webhook(secret_token=...)
    in register_webhook() below) — without checking it, this public URL
    would accept a forged update from anyone who found it."""
    if not settings.telegram_webhook_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid secret token")
    bot = get_bot()
    update = Update.model_validate(await request.json(), context={"bot": bot})
    # A single bad update (a transient DB error, a dropped Telegram call, a
    # request from a chat the bot can no longer reach) must never turn into
    # a permanent 500 that Telegram keeps redelivering forever — the bot
    # would look completely unresponsive ("no reply at all") while the real
    # failure is sitting in the logs. Catch and log it here, tell Telegram
    # the delivery was fine, and move on to the next update.
    try:
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("Exception while handling update %s", update.update_id)
    return {"ok": True}


async def _register_bot_commands() -> None:
    """Sets the blue Menu button to a single "Profil" Mini App launcher and
    clears the bot's command list.

    This bot went through the opposite of this once already: a prior
    revision replaced a WebApp-only Menu button with a full command list
    (/start, /profile, /rules, /leaderboard, /help) via set_my_commands.
    The current requirement reverses that on purpose — one Menu button,
    one action, straight into the Profile Mini App — so this call also
    clears the command lists with an empty set_my_commands per scope;
    otherwise a bot that had already registered those five commands with
    Telegram's servers would keep suggesting them when someone types "/",
    even though nothing here still points to them.

    Group chats are the one exception to "empty command list": every group
    the bot is admin in needs exactly /start and /stop in its menu (see
    _ensure_group_commands_global), so private chats are cleared but group
    scopes are (re)populated instead of cleared.
    """
    bot = get_bot()
    await bot.set_my_commands([], scope=BotCommandScopeAllPrivateChats())
    await _ensure_group_commands_global()
    base_url = webapp_base_url()
    if base_url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text="Profil",
            web_app=WebAppInfo(url=f"{base_url}/?view=home"),
        ))
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def register_webhook() -> None:
    """Called once from the backend's own startup (see app/main.py's
    lifespan) — the single deployed web service registers its own webhook
    with Telegram, no separate bot process or manual setWebhook call
    needed."""
    base_url = webapp_base_url()
    if not base_url:
        # This is the #1 reason a freshly deployed bot "does nothing": the
        # webhook never gets registered (nothing polls, so Telegram has
        # nowhere to deliver updates) and the blue Profil Menu button is
        # never set to the Mini App. Preview deploys / render.yaml have
        # RENDER_EXTERNAL_URL injected automatically; Fly/VPS deploys must
        # set WEBAPP_URL. Log it as an ERROR so the failure is impossible
        # to miss — but stay non-fatal so the rest of the service still
        # boots and the owner can read this from the logs.
        logger.error(
            "telegram_webhook_enabled is set but no public URL is known "
            "(WEBAPP_URL or RENDER_EXTERNAL_URL empty). The bot will NOT answer "
            "/start and the Profil Menu button will not open the Mini App. "
            "Set WEBAPP_URL=<https://...> (or deploy on Render so "
            "RENDER_EXTERNAL_URL is injected) and redeploy."
        )
        return
    try:
        await get_bot().set_webhook(
            url=f"{base_url}/bot/webhook",
            secret_token=settings.telegram_webhook_secret,
            drop_pending_updates=True,
        )
    except (TelegramBadRequest, TelegramForbiddenError, TelegramAPIError) as exc:
        # A failed set_webhook (bad token, wrong token for the Mini App,
        # network) must not crash the whole service — the backend part of
        # the app should still boot. The log message carries the exact API
        # error so the owner can act on it.
        logger.error("set_webhook failed: %s", exc)
        return
    try:
        await _register_bot_commands()
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not register the bot command menu")
    try:
        info = await get_bot().get_webhook_info()
        logger.info(
            "Webhook registered at %s/bot/webhook — Telegram reports: url=%r, "
            "has_custom_certificate=%s, pending_update_count=%s",
            base_url, info.url, info.has_custom_certificate, info.pending_update_count,
        )
        if info.url != f"{base_url}/bot/webhook":
            logger.warning(
                "Telegram currently has webhook %r — expected %s/bot/webhook. "
                "A previous deploy may have left a stale URL; this deploy overwrote it.",
                info.url, base_url,
            )
        if info.last_error_message:
            logger.error(
                "Telegram webhook delivery errors: %s (last error at %s)",
                info.last_error_message, info.last_error_date,
            )
    except (TelegramBadRequest, TelegramForbiddenError, TelegramAPIError) as exc:
        logger.warning("get_webhook_info failed: %s", exc)
    logger.info("Admin telegram IDs for this bot: %s", settings.admin_telegram_ids or "NONE (Admin tugmasi ko'rinmaydi)")
