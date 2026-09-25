"""
Verifies, via Telegram's own Bot API, that the person calling
POST /games/for-chat with a given chat_id is actually a member of that
Telegram group right now.

Without this, chat_id is just a client-supplied URL query string —
initData proves *who* is calling, but says nothing about *which group*
they claim to be sitting in. A valid Telegram user could otherwise type
any group's chat_id into the Mini App URL and join (or even become host
of, and start) a match for a group they were never a member of. This
closes that gap.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("mafia.telegram_bot_api")

# Telegram's ChatMember.status values for someone currently in the chat.
# "left" and "kicked" (and anything else/unexpected) are NOT membership.
ACTIVE_MEMBER_STATUSES = {"creator", "administrator", "member", "restricted"}


async def verify_group_membership(chat_id: str, telegram_user_id: int) -> bool:
    """True only if Telegram itself confirms telegram_user_id is currently
    a member of chat_id (via getChatMember). Fails closed: a bad token, an
    unresolvable chat_id, a network hiccup, or any unexpected response is
    treated as "not a member" — the whole point of this check is to be the
    thing that says no when it can't be sure."""
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getChatMember"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"chat_id": chat_id, "user_id": telegram_user_id})
        data = resp.json()
    except Exception:
        logger.exception(
            "getChatMember failed for chat_id=%s user_id=%s — denying by default",
            chat_id, telegram_user_id,
        )
        return False

    if not data.get("ok"):
        return False
    status: Optional[str] = data.get("result", {}).get("status")
    return status in ACTIVE_MEMBER_STATUSES


GROUP_ADMIN_STATUSES = {"creator", "administrator"}


async def is_group_admin(chat_id: str | int, telegram_user_id: int) -> bool:
    """True only if Telegram itself confirms telegram_user_id currently
    holds creator/administrator status in chat_id (via getChatMember).
    Fails closed, same contract as verify_group_membership above — used to
    gate /stop so a plain player can't cancel someone else's match."""
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getChatMember"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"chat_id": chat_id, "user_id": telegram_user_id})
        data = resp.json()
    except Exception:
        logger.exception(
            "getChatMember failed for chat_id=%s user_id=%s — denying admin check by default",
            chat_id, telegram_user_id,
        )
        return False

    if not data.get("ok"):
        return False
    status: Optional[str] = data.get("result", {}).get("status")
    return status in GROUP_ADMIN_STATUSES


async def bot_deep_link(chat_id: str) -> Optional[str]:
    """A t.me direct-link Mini App URL that opens this match. Same shape the
    group join button uses, so the Mini App still launches with real
    initData rather than in a plain browser tab. Returns None if the bot's
    own username can't be resolved, so callers can degrade to showing the
    link inline instead of failing outright."""
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        data = resp.json()
    except Exception:
        logger.exception("getMe failed — cannot build a deep link")
        return None
    if not data.get("ok"):
        return None
    username = data.get("result", {}).get("username")
    if not username:
        return None
    return f"https://t.me/{username}?startapp={chat_id}"


async def send_telegram_message(chat_id: str | int, text: str,
                                button_text: Optional[str] = None,
                                button_url: Optional[str] = None) -> bool:
    """Best-effort Telegram Bot API sendMessage to any chat (a group or a
    user's private chat). Never raises: a failure here (bot never started,
    removed from the group, network hiccup) is reported to the caller and
    logged, but nothing upstream should ever crash or block on it."""
    api = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if button_text and button_url:
        payload["reply_markup"] = json.dumps(
            {"inline_keyboard": [[{"text": button_text, "url": button_url}]]}
        )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(api, json=payload)
        return bool(resp.json().get("ok"))
    except Exception:
        logger.exception("sendMessage to chat %s failed", chat_id)
        return False


async def send_telegram_media(chat_id: str | int, media_type: str, file_id: str,
                              caption: str = "",
                              button_text: Optional[str] = None,
                              button_url: Optional[str] = None) -> bool:
    """Best-effort Bot API sendPhoto/sendVideo/sendDocument for broadcast
    content (media_type: photo | video | document, `file_id` from an
    already-uploaded file). Never raises — same contract as
    send_telegram_message above."""
    if media_type not in ("photo", "video", "document"):
        return False
    api = f"https://api.telegram.org/bot{settings.telegram_bot_token}/send{media_type.capitalize()}"
    payload: dict = {"chat_id": chat_id, media_type: file_id}
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "HTML"
    if button_text and button_url:
        payload["reply_markup"] = json.dumps(
            {"inline_keyboard": [[{"text": button_text, "url": button_url}]]}
        )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(api, json=payload)
        return bool(resp.json().get("ok"))
    except Exception:
        logger.exception("send%s to chat %s failed", media_type.capitalize(), chat_id)
        return False


async def send_admin_message(telegram_user_id: int, text: str,
                              button_text: Optional[str] = None,
                              button_url: Optional[str] = None) -> bool:
    """Sends a message to one user's private chat with the bot. Used to hand
    the owner a tappable link out of the admin panel. Best-effort: a failure
    here (bot never started by that user, network hiccup) is reported to the
    caller so the UI can fall back to showing the link on screen, but it
    never raises into a request handler."""
    return await send_telegram_message(telegram_user_id, text, button_text, button_url)
