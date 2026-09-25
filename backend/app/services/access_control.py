"""Shared bot / Mini App access rules."""
import asyncio
from sqlalchemy import select
from fastapi import HTTPException

from app.database import AsyncSessionLocal
from app.models.models import BlockedUser, RequiredChannel


async def is_blocked(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        return await session.get(BlockedUser, user_id) is not None


async def required_channels():
    async with AsyncSessionLocal() as session:
        return list((await session.execute(select(RequiredChannel).order_by(RequiredChannel.title))).scalars())


async def missing_channels(user_id: int):
    from app.services.admin_service import is_admin
    from app.telegram_bot import get_bot
    if await is_admin(user_id):
        return []
    channels = await required_channels()
    async def check(channel):
        try:
            member = await asyncio.wait_for(get_bot().get_chat_member(channel.chat_id, user_id), timeout=5)
            joined = member.status in ("creator", "administrator", "member") or (
                member.status == "restricted" and member.is_member
            )
        except Exception:
            joined = False
        return None if joined else channel
    return [c for c in await asyncio.gather(*(check(c) for c in channels)) if c is not None]


async def require_subscription(user_id: int) -> None:
    missing = await missing_channels(user_id)
    if missing:
        raise HTTPException(403, detail={
            "code": "subscription_required",
            "message": "Davom etish uchun kanallarga obuna bo‘ling.",
            "channels": [{"title": c.title, "url": c.join_url} for c in missing],
        })
