"""Private-chat admin controls, registered before the generic text handler."""
import asyncio
from html import escape
import re
from time import monotonic

from aiogram import BaseMiddleware, F
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard
from fastapi import HTTPException
from sqlalchemy import select, update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.models import AdminPermission, AdminUser, BlockedUser, Broadcast, RequiredChannel, SupportMessage
from app.services import admin_service
from app.services.access_control import is_blocked, missing_channels, required_channels

_inputs: dict[int, tuple[str, float]] = {}
_support_times: dict[int, float] = {}


def tb():
    from app import telegram_bot
    return telegram_bot


def panel_back():
    return Keyboard(inline_keyboard=[[Button(text="⬅️ Admin panel", callback_data="ctl:home")]])


def support_keyboard(row_id, user_id):
    return Keyboard(inline_keyboard=[[
        Button(text="↩️ Javob yozish", callback_data=f"ctl:reply:{row_id}"),
        Button(text="🚫 Bloklash", callback_data=f"ctl:ban:{user_id}"),
    ]])


async def support_admins():
    async with AsyncSessionLocal() as session:
        ids = (await session.execute(select(AdminPermission.admin_id).join(
            AdminUser, AdminUser.telegram_user_id == AdminPermission.admin_id
        ).where(AdminPermission.permission == "support.reply"))).scalars().all()
    return sorted(set(settings.admin_telegram_ids) | set(ids))


async def subscription_prompt(user_id, chat_id):
    missing = await missing_channels(user_id)
    if not missing:
        return False
    rows = [[Button(text=c.title[:60], url=c.join_url)] for c in missing]
    rows.append([Button(text="✅ Obunani tekshirish", callback_data="subscription:check")])
    await tb().get_bot().send_message(chat_id, "Davom etish uchun quyidagi kanallarga obuna bo‘ling.",
                                     reply_markup=Keyboard(inline_keyboard=rows))
    return True


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if not user or user.is_bot:
            return await handler(event, data)
        text = getattr(event, "text", None)
        if text in ("/start", "/admin") or any(text in tb().button_texts(key) for key in (
            "admin_panel", "contact_admin", "start_group_game", "language", "my_profile"
        )):
            _inputs.pop(user.id, None)
        message = getattr(event, "message", event)
        private = getattr(getattr(message, "chat", None), "type", None) == ChatType.PRIVATE
        if await is_blocked(user.id):
            if hasattr(event, "data"):
                await event.answer("Siz bloklangansiz.", show_alert=True)
            elif private:
                await event.answer("Siz botdan foydalanishdan bloklangansiz.")
            return
        if private and not await admin_service.is_admin(user.id):
            # Support remains reachable if a channel is unavailable.
            contact = getattr(event, "text", None) in tb().button_texts("contact_admin")
            in_contact = tb()._current_screen(user.id) == tb().SCREEN_CONTACT
            checking = getattr(event, "data", None) == "subscription:check"
            if not contact and not in_contact and not checking:
                if await subscription_prompt(user.id, message.chat.id):
                    if hasattr(event, "data"):
                        await event.answer()
                    return
            if in_contact and getattr(event, "text", None) and not contact:
                now = monotonic()
                if now - _support_times.get(user.id, -100) < 15:
                    await event.answer("Keyingi murojaat uchun 15 soniya kuting.")
                    return
                _support_times[user.id] = now
        return await handler(event, data)


async def set_block(user_id, actor, blocked=True):
    await admin_service.ensure_permission(actor, "users.manage")
    if user_id <= 0 or await admin_service.is_admin(user_id):
        raise ValueError("Adminni bloklab bo‘lmaydi. To‘g‘ri foydalanuvchi ID kiriting.")
    async with AsyncSessionLocal() as session:
        row = await session.get(BlockedUser, user_id)
        if blocked and row is None:
            session.add(BlockedUser(telegram_user_id=user_id, blocked_by=actor))
        elif not blocked and row:
            await session.delete(row)
        await session.commit()
    if blocked:
        from app.services.game_service import registry
        from app.websocket.manager import manager
        for engine in registry.all_engines():
            for pid, player in engine.state.players.items():
                if player.telegram_user_id == user_id:
                    socket = manager._rooms.get(engine.state.game_id, {}).get(pid)
                    if socket:
                        manager.disconnect(engine.state.game_id, pid, socket)
                        try:
                            await socket.close(code=4403)
                        except Exception:
                            pass


async def add_channel(text, actor):
    await admin_service.ensure_permission(actor, "settings.manage")
    parts = [part.strip() for part in text.split("|", 1)]
    name = parts[0]
    if name.startswith("https://t.me/"):
        name = "@" + name.removeprefix("https://t.me/").strip("/")
    if not re.fullmatch(r"@[A-Za-z0-9_]{5,32}|-100\d+", name):
        raise ValueError("Ochiq kanal: @kanal. Yopiq kanal: -1001234567890 | https://t.me/+taklif")
    bot = tb().get_bot()
    chat = await bot.get_chat(int(name) if name.startswith("-") else name)
    if chat.type != "channel":
        raise ValueError("Faqat kanal qo‘shish mumkin.")
    member = await bot.get_chat_member(chat.id, bot.id)
    if member.status not in ("creator", "administrator"):
        raise ValueError("Avval botni shu kanalga admin qiling.")
    link = f"https://t.me/{chat.username}" if chat.username else (parts[1] if len(parts) == 2 else "")
    if not re.fullmatch(r"https://t\.me/(?:[A-Za-z0-9_]+|\+[A-Za-z0-9_-]+|joinchat/[A-Za-z0-9_-]+)", link):
        raise ValueError("Yopiq kanal uchun amaldagi Telegram taklif havolasini kiriting.")
    async with AsyncSessionLocal() as session:
        row = await session.get(RequiredChannel, str(chat.id))
        if not row:
            if len(await required_channels()) >= 10:
                raise ValueError("Ko‘pi bilan 10 ta majburiy kanal qo‘shiladi.")
            row = RequiredChannel(chat_id=str(chat.id), created_by=actor)
            session.add(row)
        row.title, row.join_url = chat.title, link
        await session.commit()
    return chat.title


def register_controls(dp):
    middleware = AccessMiddleware()
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)

    @dp.callback_query(F.data == "subscription:check", F.message.chat.type == ChatType.PRIVATE)
    async def check_subscription(query):
        await query.answer()
        if not await subscription_prompt(query.from_user.id, query.message.chat.id):
            await tb()._edit_or_send(query.message.chat.id, "✅ Obuna tasdiqlandi. O‘yinga qayta kirishingiz mumkin.",
                                    reply_markup=tb().menu_for(query.from_user.id, await tb().get_user_language(query.from_user.id)))

    @dp.callback_query(F.data.startswith("ctl:"), F.message.chat.type == ChatType.PRIVATE)
    async def controls(query):
        uid = query.from_user.id
        if not await admin_service.is_admin(uid):
            await query.answer("Faqat admin uchun.", show_alert=True)
            return
        await query.answer()
        action = query.data.split(":")[1]
        arg = query.data.split(":")[2:]
        try:
            if action == "home":
                _inputs.pop(uid, None)
                await tb()._edit_or_send(uid, "⚙️ Admin panel", reply_markup=tb()._admin_keyboard("uz"))
            elif action == "inbox":
                await admin_service.ensure_permission(uid, "support.view")
                async with AsyncSessionLocal() as session:
                    rows = (await session.execute(select(SupportMessage).where(
                        SupportMessage.replied.is_(False)
                    ).order_by(SupportMessage.id.desc()).limit(20))).scalars().all()
                if not rows:
                    await tb()._edit_or_send(uid, "Yangi murojaatlar yo‘q.", reply_markup=panel_back())
                else:
                    seen = set()
                    for row in rows:
                        key = (row.user_telegram_id, row.original_text)
                        if key in seen:
                            continue
                        seen.add(key)
                        await tb().get_bot().send_message(uid,
                            f"✉️ {escape(row.user_display_name)} · <code>{row.user_telegram_id}</code>\n\n{escape(row.original_text[:3000])}",
                            reply_markup=support_keyboard(row.id, row.user_telegram_id))
                    await tb()._edit_or_send(uid, "Oxirgi javobsiz murojaatlar.", reply_markup=panel_back())
            elif action in ("reply", "block", "unblock", "channel_add", "ad"):
                permission = {"reply": "support.reply", "block": "users.manage", "unblock": "users.manage",
                              "channel_add": "settings.manage", "ad": "broadcast.send"}[action]
                await admin_service.ensure_permission(uid, permission)
                _inputs[uid] = (action + (":" + arg[0] if arg else ""), monotonic())
                prompts = {"reply": "Javob matnini yuboring.", "block": "Bloklash uchun raqamli Telegram ID yuboring.",
                           "unblock": "Blokdan chiqarish uchun raqamli Telegram ID yuboring.",
                           "channel_add": "Botni kanalga admin qiling. Keyin @kanal yuboring.\nYopiq kanal: -1001234567890 | https://t.me/+taklif",
                           "ad": "Reklama matni, rasm yoki video yuboring. Avval namuna ko‘rsatiladi."}
                await tb()._edit_or_send(uid, prompts[action], reply_markup=panel_back())
            elif action == "ban":
                await set_block(int(arg[0]), uid)
                await tb()._edit_or_send(uid, "🚫 Foydalanuvchi bloklandi.", reply_markup=panel_back())
            elif action == "channels":
                await admin_service.ensure_permission(uid, "settings.manage")
                channels = await required_channels()
                rows = [[Button(text=f"❌ {c.title[:45]}", callback_data=f"ctl:channel_del:{c.chat_id}")] for c in channels]
                rows += [[Button(text="➕ Kanal qo‘shish", callback_data="ctl:channel_add")],
                         [Button(text="⬅️ Admin panel", callback_data="ctl:home")]]
                await tb()._edit_or_send(uid, f"📣 Majburiy kanallar: {len(channels)}\nOlib tashlash uchun kanal tugmasini bosing.",
                                        reply_markup=Keyboard(inline_keyboard=rows))
            elif action == "channel_del":
                await admin_service.ensure_permission(uid, "settings.manage")
                async with AsyncSessionLocal() as session:
                    row = await session.get(RequiredChannel, arg[0])
                    if row:
                        await session.delete(row)
                        await session.commit()
                await tb()._edit_or_send(uid, "Kanal olib tashlandi.", reply_markup=panel_back())
            elif action == "send":
                await admin_service.ensure_permission(uid, "broadcast.send")
                from app.services.bot_broadcasts import enqueue
                count = await enqueue(int(arg[0]), uid, arg[1])
                await tb()._edit_or_send(uid, f"✅ {count} ta chatga yuborish navbatga qo‘yildi. Natija «Reklama tarixi»da.",
                                        reply_markup=panel_back())
            elif action == "cancel":
                await admin_service.ensure_permission(uid, "broadcast.send")
                async with AsyncSessionLocal() as session:
                    await session.execute(update(Broadcast).where(
                        Broadcast.id == int(arg[0]), Broadcast.created_by == uid,
                        Broadcast.status == "pending"
                    ).values(status="cancelled"))
                    await session.commit()
                await tb()._edit_or_send(uid, "Reklama qoralamasi bekor qilindi.", reply_markup=panel_back())
            elif action == "history":
                await admin_service.ensure_permission(uid, "broadcast.view")
                async with AsyncSessionLocal() as session:
                    rows = (await session.execute(select(Broadcast).order_by(Broadcast.id.desc()).limit(10))).scalars().all()
                labels = {"pending":"Qoralama", "queued":"Navbatda", "sending":"Yuborilmoqda",
                          "sent":"Yuborildi", "failed":"Xatolik", "partial":"Qisman yuborildi", "cancelled":"Bekor qilingan"}
                text = "\n".join(f"#{b.id} {labels.get(b.status, b.status)} · ✅ {b.delivered} / ❌ {b.failed} / Jami {b.total}" for b in rows)
                await tb()._edit_or_send(uid, text or "Hali reklama yo‘q.", reply_markup=panel_back())
        except HTTPException as exc:
            await tb().get_bot().send_message(uid, escape(str(exc.detail)))
        except (ValueError, IndexError):
            await tb().get_bot().send_message(uid, "Ma’lumot noto‘g‘ri yoki amal allaqachon bajarilgan. Panelni qayta oching.")
        except TelegramAPIError:
            await tb().get_bot().send_message(uid, "Telegram bilan bog‘lanib bo‘lmadi. Bot huquqlarini tekshiring va qayta urinib ko‘ring.")

    @dp.message(F.chat.type == ChatType.PRIVATE, F.photo | F.video)
    async def media_input(message):
        if not await consume_admin_input(message):
            await message.answer("Reklama uchun Admin panel → Reklama yuborish bo‘limini oching.")


async def consume_admin_input(message):
    uid = message.from_user.id
    pending = _inputs.get(uid)
    if not pending:
        return False
    if monotonic() - pending[1] > 900:
        _inputs.pop(uid, None)
        await message.answer("Kiritish vaqti tugadi. Admin panelni qayta oching.")
        return True
    mode = pending[0]
    try:
        if mode.startswith("reply:"):
            await admin_service.ensure_permission(uid, "support.reply")
            if not message.text:
                raise ValueError("Matnli javob yuboring.")
            if len(message.text) > 3000:
                raise ValueError("Javobni 3000 belgigacha qisqartiring.")
            async with AsyncSessionLocal() as session:
                row = await session.get(SupportMessage, int(mode.split(":")[1]))
                if row is None:
                    raise ValueError("Murojaat topilmadi.")
                await tb().get_bot().send_message(row.user_telegram_id, "✉️ <b>Admin javobi</b>\n\n" + escape(message.text[:3000]))
                row.replied = True
                await session.commit()
            text = "✅ Javob yuborildi."
        elif mode in ("block", "unblock"):
            await set_block(int(message.text), uid, mode == "block")
            text = "✅ Foydalanuvchi bloklandi." if mode == "block" else "✅ Blokdan chiqarildi."
        elif mode == "channel_add":
            title = await add_channel(message.text or "", uid)
            text = f"✅ {escape(title)} qo‘shildi."
        elif mode == "ad":
            await admin_service.ensure_permission(uid, "broadcast.send")
            from app.services.bot_broadcasts import create_draft, audience
            draft = await create_draft(message)
            await tb().get_bot().copy_message(uid, message.chat.id, message.message_id)
            rows = []
            for kind, label in (("all", "Foydalanuvchilar"), ("groups", "Guruhlar"), ("both", "Hammasi")):
                count = len(await audience(kind))
                rows.append([Button(text=f"📤 {label} ({count})", callback_data=f"ctl:send:{draft}:{kind}")])
            rows.append([Button(text="Bekor qilish", callback_data=f"ctl:cancel:{draft}")])
            await message.answer("Namuna tayyor. Yuboriladigan auditoriyani tanlang:", reply_markup=Keyboard(inline_keyboard=rows))
            _inputs.pop(uid, None)
            return True
        else:
            return False
        _inputs.pop(uid, None)
        await message.answer(text, reply_markup=panel_back())
    except (ValueError, TypeError) as exc:
        await message.answer(escape(str(exc)) if isinstance(exc, ValueError) else "Raqamli Telegram ID yuboring.")
    except HTTPException:
        _inputs.pop(uid, None)
        await message.answer("Bu amal uchun ruxsatingiz yo‘q.")
    except TelegramAPIError:
        await message.answer("Yuborilmadi. Bot huquqlari, kanal yoki foydalanuvchi holatini tekshiring.")
    return True
