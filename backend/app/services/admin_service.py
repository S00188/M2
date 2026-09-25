"""Admin identity and permission model for the premium Admin panel.

Two kinds of admin exist:

  * Super admins — settings.admin_telegram_ids (env ADMIN_TELEGRAM_IDS).
    They implicitly hold *every* permission, can never be demoted from the
    panel, and are not stored in the AdminUser table. The bot owner is
    expected to keep themselves here so the panel can never lock itself out
    of installing other admins.
  * Panel admins — an AdminUser row, added by a super admin (or another
    admin with "admins.manage"). They only have the individual permissions
    explicitly granted in AdminPermission.

The enforcement point is server-side, on every /admin/* route, via
require_admin_permission(...) / require_any_admin(). The WebApp only
receives a permission list for UI labelling; it never gates anything.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import select

from app.api.dependencies import require_telegram_id
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.models import AdminPermission, AdminUser
from app.services import bot_config

# Module -> permission keys. Used to validate permission lists from the
# panel, render the checkboxes, and (indirectly) build the login response.
PERMISSION_CATALOG: dict[str, list[str]] = {
    "support": ["support.view", "support.reply"],
    "users": ["users.view", "users.manage"],
    "admins": ["admins.view", "admins.manage"],
    "texts": ["texts.view", "texts.manage"],
    "broadcasts": ["broadcast.view", "broadcast.send"],
    "groups": ["groups.view", "groups.manage"],
    "statistics": ["statistics.view"],
    "settings": ["settings.view", "settings.manage"],
}

ALL_PERMISSIONS = {p for perms in PERMISSION_CATALOG.values() for p in perms}
MANAGED_PERMISSIONS = {p for perms in PERMISSION_CATALOG.values() for p in perms
                       if p != "statistics.view"}


def is_super_admin(telegram_user_id: int) -> bool:
    return telegram_user_id in settings.admin_telegram_ids


async def is_admin(telegram_user_id: int) -> bool:
    """True for a super admin or anyone with an active AdminUser row."""
    if is_super_admin(telegram_user_id):
        return True
    async with AsyncSessionLocal() as session:
        return (await session.get(AdminUser, telegram_user_id)) is not None


async def admin_permissions(telegram_user_id: int) -> set[str]:
    """Every permission this user holds. Super admins implicitly hold all."""
    if is_super_admin(telegram_user_id):
        return set(ALL_PERMISSIONS)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AdminPermission.permission)
            .where(AdminPermission.admin_id == telegram_user_id)
        )).scalars().all()
    return set(rows)


async def ensure_permission(telegram_user_id: int, permission: str) -> None:
    """Raise 403 unless the user holds `permission` (super admins always do)."""
    if is_super_admin(telegram_user_id):
        return
    async with AsyncSessionLocal() as session:
        admin = await session.get(AdminUser, telegram_user_id)
        if admin is None:
            raise HTTPException(status_code=403, detail="Siz admin emassiz")
        granted = (await session.execute(
            select(AdminPermission)
            .where(AdminPermission.admin_id == telegram_user_id,
                   AdminPermission.permission == permission)
        )).scalar_one_or_none()
    if granted is None:
        raise HTTPException(status_code=403, detail="Sizda bu amal uchun ruxsat yo'q")


def require_admin_permission(permission: str):
    """FastAPI dependency factory: require the caller to hold exactly this
    permission (a super admin always passes)."""
    async def dependency(telegram_user_id: int = Depends(require_telegram_id)) -> int:
        await ensure_permission(telegram_user_id, permission)
        return telegram_user_id
    return dependency


def require_any_admin():
    """FastAPI dependency factory: require an authenticated super or panel
    admin, with no particular permission (for catalog/overview views)."""
    async def dependency(telegram_user_id: int = Depends(require_telegram_id)) -> int:
        if not await is_admin(telegram_user_id):
            raise HTTPException(status_code=403, detail="Siz admin emassiz")
        return telegram_user_id
    return dependency


async def add_admin_account(session, telegram_user_id: int, display_name: str, created_by: int) -> None:
    """Create an AdminUser row and refresh the bot_config admin cache. Super
    admins have no row (they're implicit); this is only for panel admins."""
    existing = await session.get(AdminUser, telegram_user_id)
    if existing is None:
        session.add(AdminUser(telegram_user_id=telegram_user_id,
                              display_name=display_name or "",
                              created_by=created_by))
        await session.commit()
        await bot_config.reload()


async def remove_admin_account(session, telegram_user_id: int) -> None:
    row = await session.get(AdminUser, telegram_user_id)
    if row is not None:
        await session.delete(row)
        await session.commit()
        await bot_config.reload()


async def set_admin_permissions(session, telegram_user_id: int, permissions: list[str]) -> None:
    """Replace the granted permission set for a panel admin (validates against
    the catalog; super admins can't have their permissions changed)."""
    row = await session.get(AdminUser, telegram_user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Admin topilmadi")
    invalid = [p for p in permissions if p not in ALL_PERMISSIONS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Noto'g'ri ruxsatlar: {', '.join(invalid)}")
    for perm in list(row.permissions):
        await session.delete(perm)
    for permission in permissions:
        session.add(AdminPermission(admin_id=telegram_user_id, permission=permission))
    await session.commit()
