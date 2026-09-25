"""Durable, single-worker Telegram campaigns initiated from the bot panel."""
import asyncio
import logging
from datetime import datetime, timezone

from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from sqlalchemy import select, update, func
from app.database import AsyncSessionLocal
from app.models.models import BlockedUser, Broadcast, BroadcastDelivery, KnownGroup, User, _utcnow
from app.services.access_control import is_blocked

logger = logging.getLogger("mafia.broadcast")


async def audience(kind):
    if kind not in ("all", "groups", "both"):
        raise ValueError("Noma’lum auditoriya")
    async with AsyncSessionLocal() as session:
        ids = []
        if kind in ("all", "both"):
            blocked = select(BlockedUser.telegram_user_id)
            ids += [str(i) for i in (await session.execute(select(User.telegram_user_id).where(
                User.telegram_user_id.not_in(blocked)
            ))).scalars() if i > 0]
        if kind in ("groups", "both"):
            ids += [str(i) for i in (await session.execute(select(KnownGroup.chat_id).where(
                KnownGroup.is_active.is_(True)
            ))).scalars()]
        return sorted(set(ids))


async def create_draft(message):
    media_type, file_id = "", ""
    if message.photo:
        media_type, file_id = "photo", message.photo[-1].file_id
    elif message.video:
        media_type, file_id = "video", message.video.file_id
    text = message.html_text or message.html_caption or ""
    if len(text) > 4096:
        raise ValueError("Reklama matni yoki formatini qisqartiring (4096 belgigacha).")
    if not text and not file_id:
        raise ValueError("Matn, rasm yoki video yuboring.")
    async with AsyncSessionLocal() as session:
        row = Broadcast(title="Bot reklamasi", text=text, created_by=message.from_user.id,
                        spec={"bot_campaign": True, "media_type": media_type, "file_id": file_id})
        session.add(row)
        await session.commit()
        return row.id


async def enqueue(campaign_id, actor, kind):
    recipients = await audience(kind)
    if not recipients:
        raise ValueError("Auditoriya bo‘sh")
    async with AsyncSessionLocal() as session:
        row = await session.get(Broadcast, campaign_id)
        if not row or row.created_by != actor or not row.spec.get("bot_campaign"):
            raise ValueError("Reklama topilmadi")
        result = await session.execute(update(Broadcast).where(
            Broadcast.id == campaign_id, Broadcast.status == "pending"
        ).values(status="queued", total=len(recipients), spec={**row.spec, "kind": kind}))
        if result.rowcount != 1:
            raise ValueError("Bu reklama allaqachon navbatga qo‘yilgan")
        session.add_all([BroadcastDelivery(campaign_id=campaign_id, chat_id=cid) for cid in recipients])
        await session.commit()
    return len(recipients)


async def process_next(bot):
    async with AsyncSessionLocal() as session:
        # The worker is the sole consumer; deployment uses one process.
        row = (await session.execute(select(Broadcast).where(
            Broadcast.status.in_(["queued", "sending"]),
            Broadcast.spec["bot_campaign"].as_boolean().is_(True),
        ).order_by(Broadcast.id))).scalars().first()
        if not row or not row.spec.get("bot_campaign"):
            return False
        row.status = "sending"
        delivery = (await session.execute(select(BroadcastDelivery).where(
            BroadcastDelivery.campaign_id == row.id, BroadcastDelivery.status == "pending"
        ).order_by(BroadcastDelivery.chat_id).limit(1))).scalar_one_or_none()
        if delivery is None:
            counts = dict((await session.execute(select(BroadcastDelivery.status, func.count()).where(
                BroadcastDelivery.campaign_id == row.id
            ).group_by(BroadcastDelivery.status))).all())
            row.delivered = counts.get("sent", 0)
            row.failed = sum(v for k, v in counts.items() if k != "sent")
            row.status = "sent" if row.failed == 0 else ("partial" if row.delivered else "failed")
            row.sent_at = _utcnow()
            await session.commit()
            return True
        delivery.status = "sending"
        campaign_id, cid, text, spec = row.id, delivery.chat_id, row.text, row.spec
        await session.commit()
    status = "failed"
    try:
        if int(cid) > 0 and await is_blocked(int(cid)):
            status = "skipped"
        else:
            if spec.get("media_type") == "photo":
                await bot.send_photo(int(cid), spec["file_id"], caption=text, parse_mode="HTML")
            elif spec.get("media_type") == "video":
                await bot.send_video(int(cid), spec["file_id"], caption=text, parse_mode="HTML")
            else:
                await bot.send_message(int(cid), text, parse_mode="HTML")
            status = "sent"
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
        status = "pending"
    except TelegramAPIError:
        pass
    async with AsyncSessionLocal() as session:
        delivery = await session.get(BroadcastDelivery, (campaign_id, cid))
        delivery.status = status
        row = await session.get(Broadcast, campaign_id)
        if status == "sent":
            row.delivered += 1
        elif status not in ("pending",):
            row.failed += 1
        await session.commit()
    await asyncio.sleep(.08)
    return True


async def worker():
    from app.telegram_bot import get_bot
    # A crash after Telegram accepted a message has an unknown outcome.
    # Do not blindly resend that recipient; finish remaining pending rows.
    async with AsyncSessionLocal() as session:
        await session.execute(update(BroadcastDelivery).where(
            BroadcastDelivery.status == "sending").values(status="unknown"))
        await session.commit()
    while True:
        try:
            if await process_next(get_bot()):
                continue
        except Exception:
            logger.exception("Broadcast worker failed; retrying")
        await asyncio.sleep(2)
