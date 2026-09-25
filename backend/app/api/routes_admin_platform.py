"""
Premium Admin panel — the seven WebApp modules (spec: "Yagona Admin WebApp'da
faqat shu 7 modul bo'lsin"):

    👥 Foydalanuvchilar        users  (view/manage: search, block, make admin)
    👨‍💼 Adminlar               admins (view/manage: add/remove admin, permissions)
    📝 Bot matnlari            texts  (view/manage: /start, group-added, lobby)
    📢 Xabarlar                broadcasts (view/send: preview, send, history)
    👥 Guruhlar                groups (view/manage: list, enable/disable)
    📊 Umumiy statistika       statistics (view: KPIs, top players, live games)
    ⚙️ Bot sozlamalari         settings (view/manage: buttons + per-admins)

Every route is gated by a server-side permission dependency from
app/services/admin_service.py (a super admin passes any; a panel admin only
passes the checks their AdminUser/AdminPermission rows give them). The
WebApp's is_bot_admin/permissions flags are display-only conveniences.

Deliberately NOT here (removed in the re-platform per the spec): a game-
settings module, timezone/maintenance/logs/security modules, premium, and
force-sub — the existing owner-level game-control REST routes in
routes_admin.py are untouched, but the panel itself is exactly these seven.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.config import settings
from app.services import admin_service, bot_config
from app.services.game_service import registry, BOT_GAME_CHAT_PREFIX
from app.services.telegram_bot_api import send_telegram_message, send_telegram_media
from app.models.models import (
    AdminPermission, AdminUser, BlockedUser, BotButton, BotText, Broadcast,
    Game, GameHistory, KnownGroup, User, _utcnow,
)

router = APIRouter(prefix="/admin", tags=["admin-platform"])

SUPPORTED_LANGS = ("uz", "ru", "en")


def _display_name(user: User) -> str:
    if user.username:
        return user.username
    parts = [user.first_name, user.last_name or ""]
    return " ".join(p for p in parts if p).strip() or "O'yinchi"


def _user_row(user: User, blocked: bool = False, is_admin: bool = False) -> dict:
    played = user.games_played or 0
    return {
        "telegram_user_id": user.telegram_user_id,
        "display_name": _display_name(user),
        "first_name": user.first_name,
        "username": user.username,
        "photo_url": user.photo_url,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "games_played": played,
        "wins": user.wins or 0,
        "losses": user.losses or 0,
        "win_rate": round(100 * user.wins / played) if played else 0,
        "town_wins": user.town_wins or 0,
        "mafia_wins": user.mafia_wins or 0,
        "neutral_wins": user.neutral_wins or 0,
        "blocked": blocked,
        "is_admin": is_admin,
    }


# --------------------------------------------------------------------------- users
@router.get("/users")
async def admin_list_users(
    search: str = Query("", max_length=64),
    only_active: bool = Query(False),
    only_blocked: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    _: int = Depends(admin_service.require_admin_permission("users.view")),
    session: AsyncSession = Depends(get_session),
):
    """Searchable, filterable user list for the panel's "Foydalanuvchilar"
    module. `search` matches first name, username or Telegram id."""
    stmt = select(User)
    if search.strip():
        term = search.strip()
        try:
            numeric = int(term)
        except ValueError:
            numeric = None
        clauses = [
            User.first_name.ilike(f"%{term}%"),
            User.username.ilike(f"%{term}%"),
        ]
        if numeric is not None:
            clauses.append(User.telegram_user_id == numeric)
        stmt = stmt.where(or_(*clauses))
    stmt = stmt.order_by(User.created_at.desc()).limit(limit)
    users = (await session.execute(stmt)).scalars().all()

    blocked_ids = set((await session.execute(
        select(BlockedUser.telegram_user_id)
    )).scalars().all())
    db_admin_ids = set((await session.execute(
        select(AdminUser.telegram_user_id)
    )).scalars().all())

    rows = []
    for u in users:
        blocked = u.telegram_user_id in blocked_ids
        if only_blocked and not blocked:
            continue
        if only_active and blocked:
            continue
        rows.append(_user_row(u, blocked=blocked,
                              is_admin=u.telegram_user_id in db_admin_ids
                              or admin_service.is_super_admin(u.telegram_user_id)))
    return {"users": rows, "total": len(rows)}


@router.get("/users/{user_id}")
async def admin_user_detail(
    user_id: int,
    _: int = Depends(admin_service.require_admin_permission("users.view")),
    session: AsyncSession = Depends(get_session),
):
    user = (await session.execute(
        select(User).where(User.telegram_user_id == user_id)
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    blocked = await session.get(BlockedUser, user_id) is not None
    is_admin = await admin_service.is_admin(user_id)
    recent = (await session.execute(
        select(GameHistory).where(GameHistory.user_id == user.id)
        .order_by(GameHistory.played_at.desc()).limit(20)
    )).scalars().all()
    return {
        **_user_row(user, blocked=blocked, is_admin=is_admin),
        "permissions": sorted(await admin_service.admin_permissions(user_id)) if is_admin else [],
        "recent_games": [{
            "game_id": h.game_id, "played_at": h.played_at.isoformat() if h.played_at else None,
            "role_name": h.role_name, "faction": h.faction, "won": h.won,
            "player_count": h.player_count,
        } for h in recent],
    }


@router.post("/users/{user_id}/block")
async def admin_block_user(
    user_id: int,
    telegram_user_id: int = Depends(admin_service.require_admin_permission("users.manage")),
    session: AsyncSession = Depends(get_session),
):
    user = (await session.execute(select(User).where(User.telegram_user_id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    from app.bot_controls import set_block
    try:
        await set_block(user_id, telegram_user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "blocked": True}


@router.post("/users/{user_id}/unblock")
async def admin_unblock_user(
    user_id: int,
    _: int = Depends(admin_service.require_admin_permission("users.manage")),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(BlockedUser, user_id)
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"ok": True, "blocked": False}


@router.post("/users/{user_id}/make-admin")
async def admin_make_user_admin(
    user_id: int,
    telegram_user_id: int = Depends(admin_service.require_admin_permission("admins.manage")),
    session: AsyncSession = Depends(get_session),
):
    """Promote a user to panel admin (an AdminUser row). Super admins are
    already implicit — a no-op for them. The new admin gets no permissions
    until granted via PUT /admin/admins/{id}/permissions."""
    user = (await session.execute(select(User).where(User.telegram_user_id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    await admin_service.add_admin_account(session, user_id, _display_name(user), telegram_user_id)
    return {"ok": True, "is_admin": True}


@router.post("/users/{user_id}/remove-admin")
async def admin_remove_user_admin(
    user_id: int,
    _: int = Depends(admin_service.require_admin_permission("admins.manage")),
    session: AsyncSession = Depends(get_session),
):
    if admin_service.is_super_admin(user_id):
        raise HTTPException(400, "Bot egasini adminlikdan olib tashlab bo'lmaydi")
    await admin_service.remove_admin_account(session, user_id)
    return {"ok": True, "is_admin": False}


# -------------------------------------------------------------------------- admins
@router.get("/admins")
async def admin_list_admins(
    _: int = Depends(admin_service.require_admin_permission("admins.view")),
    session: AsyncSession = Depends(get_session),
):
    """Every admin that can reach the panel: super admins (implicit, full
    permissions, marked is_super) plus every AdminUser row."""
    db_rows = (await session.execute(
        select(AdminUser).order_by(AdminUser.created_at.asc())
    )).scalars().all()
    rows = []
    for admin in db_rows:
        rows.append({
            "telegram_user_id": admin.telegram_user_id,
            "display_name": admin.display_name,
            "created_by": admin.created_by,
            "created_at": admin.created_at.isoformat() if admin.created_at else None,
            "is_super": False,
            "permissions": sorted(p.permission for p in admin.permissions),
        })
    # Super admins from settings, in front of the panel admins, marked as such.
    super_ids = list(settings.admin_telegram_ids)
    users_by_id = {}
    if super_ids:
        for u in (await session.execute(
            select(User).where(User.telegram_user_id.in_(super_ids))
        )).scalars().all():
            users_by_id[u.telegram_user_id] = u
    for uid in super_ids:
        user = users_by_id.get(uid)
        rows.insert(0, {
            "telegram_user_id": uid,
            "display_name": _display_name(user) if user else f"Admin {uid}",
            "created_by": 0,
            "created_at": None,
            "is_super": True,
            "permissions": sorted(admin_service.ALL_PERMISSIONS),
        })
    return {"admins": rows}


class AddAdminRequest(BaseModel):
    telegram_user_id: int


@router.post("/admins")
async def admin_add_admin(
    body: AddAdminRequest,
    telegram_user_id: int = Depends(admin_service.require_admin_permission("admins.manage")),
    session: AsyncSession = Depends(get_session),
):
    user = (await session.execute(
        select(User).where(User.telegram_user_id == body.telegram_user_id)
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Foydalanuvchi topilmadi. Avval ular botdan kirishi kerak.")
    if admin_service.is_super_admin(user.telegram_user_id):
        raise HTTPException(400, "Bu foydalanuvchi allaqachon bot egasidir (super admin)")
    existing = await session.get(AdminUser, user.telegram_user_id)
    if existing is not None:
        raise HTTPException(400, "Bu foydalanuvchi allaqachon admindir")
    await admin_service.add_admin_account(session, user.telegram_user_id, _display_name(user),
                                          telegram_user_id)
    return {"ok": True}


@router.delete("/admins/{user_id}")
async def admin_remove_admin(
    user_id: int,
    _: int = Depends(admin_service.require_admin_permission("admins.manage")),
    session: AsyncSession = Depends(get_session),
):
    if admin_service.is_super_admin(user_id):
        raise HTTPException(400, "Bot egasini (super adminni) o'chirib bo'lmaydi")
    await admin_service.remove_admin_account(session, user_id)
    return {"ok": True}


class AdminPermissionsRequest(BaseModel):
    permissions: list[str] = []


@router.put("/admins/{user_id}/permissions")
async def admin_set_permissions(
    user_id: int,
    body: AdminPermissionsRequest,
    _: int = Depends(admin_service.require_admin_permission("admins.manage")),
    session: AsyncSession = Depends(get_session),
):
    if admin_service.is_super_admin(user_id):
        raise HTTPException(400, "Bot egasida barcha ruxsatlar mavjud — o'zgartirib bo'lmaydi")
    await admin_service.set_admin_permissions(session, user_id, body.permissions)
    return {"ok": True, "permissions": body.permissions}


# -------------------------------------------------------------------------- permissions
@router.get("/permissions")
async def admin_permission_catalog(
    _: int = Depends(admin_service.require_any_admin()),
):
    """The full permission catalog, grouped by module, so the panel can render
    the checkbox matrix and validate what it sends back."""
    return {"catalog": admin_service.PERMISSION_CATALOG,
            "all": sorted(admin_service.ALL_PERMISSIONS)}


# --------------------------------------------------------------------------- texts
@router.get("/texts")
async def admin_get_texts(
    _: int = Depends(admin_service.require_admin_permission("texts.view")),
    session: AsyncSession = Depends(get_session),
):
    """The three manageable bot texts, in all languages, with the code-level
    fallback shown for anything unset so the edit form has context."""
    rows = (await session.execute(select(BotText))).scalars().all()
    by_key = {row.key: row for row in rows}
    texts = []
    for key in bot_config.MANAGED_TEXTS:
        row = by_key.get(key)
        texts.append({
            "key": key,
            "uz": (row.uz if row else "") or bot_config.get_text(key, "uz"),
            "ru": (row.ru if row else "") or bot_config.get_text(key, "ru"),
            "en": (row.en if row else "") or bot_config.get_text(key, "en"),
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        })
    return {"texts": texts, "languages": list(SUPPORTED_LANGS)}


class AdminTextUpdate(BaseModel):
    value: str = ""


@router.put("/texts/{key}/{lang}")
async def admin_update_text(
    key: str, lang: str, body: AdminTextUpdate,
    _: int = Depends(admin_service.require_admin_permission("texts.manage")),
    session: AsyncSession = Depends(get_session),
):
    if key not in bot_config.MANAGED_TEXTS:
        raise HTTPException(400, "Bu matn tahrirlash uchun ochiq emas")
    if lang not in SUPPORTED_LANGS:
        raise HTTPException(400, "Noma'lum til")
    await bot_config.save_text(session, key, lang, body.value)
    return {"ok": True, "key": key, "lang": lang, "value": body.value}


# ------------------------------------------------------------------------ broadcasts
class BroadcastRequest(BaseModel):
    title: str = ""
    text: str = ""
    kind: str = "all"  # all | users | groups | active_users | new_users
    user_ids: list[int] = []
    chat_ids: list[int] = []
    media_type: str = ""     # "" | photo | video | document
    file_id: str = ""
    button_text: str = ""
    button_url: str = ""


@router.get("/broadcasts")
async def admin_list_broadcasts(
    limit: int = Query(30, ge=1, le=100),
    _: int = Depends(admin_service.require_admin_permission("broadcast.view")),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(
        select(Broadcast).order_by(Broadcast.created_at.desc()).limit(limit)
    )).scalars().all()
    return {"broadcasts": [{
        "id": b.id, "title": b.title, "text": b.text, "spec": b.spec or {},
        "status": b.status, "created_at": b.created_at.isoformat() if b.created_at else None,
        "sent_at": b.sent_at.isoformat() if b.sent_at else None,
        "total": b.total, "delivered": b.delivered, "failed": b.failed,
    } for b in rows]}


async def _resolve_recipients(session: AsyncSession, spec: dict) -> list[int | str]:
    """The concrete list of chat ids (ints for users, str for groups) a
    broadcast is going to touch. Blocked users are excluded from implicit
    recipient sets (never force a message on a blocked account)."""
    kind = spec.get("kind", "all")
    if kind == "groups":
        return [str(cid) for cid in spec.get("chat_ids", [])]
    if kind == "users":
        return list(spec.get("user_ids", []))
    stmt = select(User.telegram_user_id)
    if kind == "active_users":
        stmt = stmt.where(User.games_played > 0)
    elif kind == "new_users":
        stmt = stmt.where(User.created_at >= _utcnow() - timedelta(days=7))
    ids = [rid for rid in (await session.execute(stmt)).scalars().all() if rid]
    blocked = set((await session.execute(select(BlockedUser.telegram_user_id))).scalars().all())
    return [rid for rid in ids if rid not in blocked]


@router.post("/broadcasts")
async def admin_create_broadcast(
    body: BroadcastRequest,
    telegram_user_id: int = Depends(admin_service.require_admin_permission("broadcast.send")),
    session: AsyncSession = Depends(get_session),
):
    if not body.text.strip() and not body.file_id:
        raise HTTPException(400, "Yuboradigan xabar bo'sh bo'lmasligi kerak")
    if body.kind not in ("all", "users", "groups", "active_users", "new_users"):
        raise HTTPException(400, "Noma'lum qabul qiluvchi turi")
    if body.kind in ("users", "groups") and len(body.user_ids or []) + len(body.chat_ids or []) == 0:
        raise HTTPException(400, "Qabul qiluvchilar ro'yxati bo'sh")
    if body.media_type and body.media_type not in ("photo", "video", "document"):
        raise HTTPException(400, "Noma'lum media turi")
    if body.media_type and not body.file_id:
        raise HTTPException(400, "Media fayl identifikatori (file_id) kerak")

    spec = {
        "kind": body.kind,
        "user_ids": body.user_ids or [],
        "chat_ids": body.chat_ids or [],
        "media_type": body.media_type,
        "file_id": body.file_id,
        "button_text": body.button_text,
        "button_url": body.button_url,
    }
    recipients = await _resolve_recipients(session, spec)
    broadcast = Broadcast(
        title=(body.title or "")[:256],
        text=(body.text or "")[:4096],
        spec=spec,
        created_by=telegram_user_id,
        status="pending",
        total=len(recipients),
    )
    session.add(broadcast)
    await session.commit()
    await session.refresh(broadcast)
    return {"ok": True, "id": broadcast.id, "recipients": len(recipients)}


@router.get("/broadcasts/{broadcast_id}/preview")
async def admin_broadcast_preview(
    broadcast_id: int,
    _: int = Depends(admin_service.require_admin_permission("broadcast.view")),
    session: AsyncSession = Depends(get_session),
):
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        raise HTTPException(404, "Xabar topilmadi")
    spec = broadcast.spec or {}
    return {
        "text": broadcast.text,
        "media_type": spec.get("media_type", ""),
        "file_id": spec.get("file_id", ""),
        "button_text": spec.get("button_text", ""),
        "button_url": spec.get("button_url", ""),
        "kind": spec.get("kind", "all"),
        "recipients": await _resolve_recipients(session, spec),
        "recipient_count": len(await _resolve_recipients(session, spec)),
    }


@router.post("/broadcasts/{broadcast_id}/send")
async def admin_send_broadcast(
    broadcast_id: int,
    _: int = Depends(admin_service.require_admin_permission("broadcast.send")),
    session: AsyncSession = Depends(get_session),
):
    """Actually deliver a pending broadcast to its recipients and persist the
    result counters (sent / delivered / failed) for the history view."""
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        raise HTTPException(404, "Xabar topilmadi")
    if (broadcast.spec or {}).get("bot_campaign"):
        raise HTTPException(400, "Bu reklama botning admin panelidan boshqariladi")
    if broadcast.status not in ("pending", "failed"):
        raise HTTPException(400, "Bu xabar allaqachon yuborilgan")
    claimed = await session.execute(update(Broadcast).where(
        Broadcast.id == broadcast_id, Broadcast.status.in_(["pending", "failed"])
    ).values(status="sending"))
    if claimed.rowcount != 1:
        raise HTTPException(409, "Yuborish allaqachon boshlangan")
    await session.commit()

    recipients = await _resolve_recipients(session, broadcast.spec or {})
    text = broadcast.text or ""
    spec = broadcast.spec or {}
    media_type, file_id = spec.get("media_type", ""), spec.get("file_id", "")
    button_text, button_url = spec.get("button_text"), spec.get("button_url")

    delivered = failed = 0
    for chat_id in recipients:
        ok = False
        if media_type and file_id:
            ok = await send_telegram_media(chat_id, media_type, file_id,
                                           caption=text, button_text=button_text,
                                           button_url=button_url)
        elif text:
            ok = await send_telegram_message(chat_id, text, button_text, button_url)
        delivered += 1 if ok else 0
        failed += 1 if not ok else 0

    broadcast.status = "failed" if recipients and delivered == 0 else "sent"
    broadcast.sent_at = _utcnow()
    broadcast.total = len(recipients)
    broadcast.delivered = delivered
    broadcast.failed = failed
    await session.commit()
    return {"ok": True, "total": broadcast.total, "delivered": delivered, "failed": failed}


# --------------------------------------------------------------------------- groups
@router.get("/groups")
async def admin_list_groups(
    search: str = Query("", max_length=96),
    only_active: bool = Query(False),
    _: int = Depends(admin_service.require_admin_permission("groups.view")),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(KnownGroup)
    if search.strip():
        stmt = stmt.where(KnownGroup.title.ilike(f"%{search.strip()}%"))
    stmt = stmt.order_by(KnownGroup.updated_at.desc())
    groups = (await session.execute(stmt)).scalars().all()
    if only_active:
        groups = [g for g in groups if g.is_active]

    game_counts: dict[int, int] = {}
    if groups:
        chat_ids = [g.chat_id for g in groups]
        for row in (await session.execute(
            select(Game.chat_id, func.count().label("c")).where(
                Game.chat_id.in_([str(c) for c in chat_ids])
            ).group_by(Game.chat_id)
        )).all():
            try:
                game_counts[int(row[0])] = row[1]
            except (TypeError, ValueError):
                continue

    rows = []
    for g in groups:
        row = {"chat_id": g.chat_id, "title": g.title or f"Guruh {g.chat_id}",
               "is_active": g.is_active,
               "updated_at": g.updated_at.isoformat() if g.updated_at else None,
               "finished_games": game_counts.get(g.chat_id, 0)}
        engine = registry.get_by_chat(str(g.chat_id))
        row["current_game"] = None
        if engine is not None and engine.state.phase.value != "lobby":
            s = engine.state
            row["current_game"] = {"game_id": s.game_id, "phase": s.phase.value,
                                   "player_count": len(s.players),
                                   "alive_count": len(s.alive_players())}
        rows.append(row)
    return {"groups": rows}


class GroupStatusRequest(BaseModel):
    is_active: bool = True


@router.post("/groups/{chat_id}/status")
async def admin_set_group_status(
    chat_id: int, body: GroupStatusRequest,
    _: int = Depends(admin_service.require_admin_permission("groups.manage")),
    session: AsyncSession = Depends(get_session),
):
    group = await session.get(KnownGroup, chat_id)
    if group is None:
        raise HTTPException(404, "Guruh topilmadi")
    group.is_active = body.is_active
    await session.commit()
    return {"ok": True, "is_active": body.is_active}


# ----------------------------------------------------------------------- statistics
@router.get("/statistics")
async def admin_statistics(
    _: int = Depends(admin_service.require_admin_permission("statistics.view")),
    session: AsyncSession = Depends(get_session),
):
    now = _utcnow()

    async def count(model, *clauses):
        stmt = select(func.count()).select_from(model)
        for clause in clauses:
            stmt = stmt.where(clause)
        return (await session.execute(stmt)).scalar_one()

    engines = registry.all_engines()

    top_users = (await session.execute(
        select(User).where(User.games_played > 0).order_by(User.wins.desc()).limit(10)
    )).scalars().all()

    # Per-day new-user counts for the last 7 days (chart data).
    daily_new = []
    for days_back in range(6, -1, -1):
        day_start = now - timedelta(days=days_back + 1)
        day_end = now - timedelta(days=days_back)
        daily_new.append({
            "date": day_start.date().isoformat(),
            "count": await count(User, User.created_at >= day_start, User.created_at < day_end),
        })

    recent_games = (await session.execute(
        select(Game).where(Game.ended_at.is_not(None))
        .order_by(Game.ended_at.desc()).limit(10)
    )).scalars().all()
    titles = {g.chat_id: g.title for g in (await session.execute(select(KnownGroup))).scalars().all()}

    return {
        "kp": {
            "total_users": await count(User),
            "active_users": await count(User, User.games_played > 0),
            "blocked_users": await count(BlockedUser),
            "new_users_today": await count(User, User.created_at >= now - timedelta(days=1)),
            "new_users_week": await count(User, User.created_at >= now - timedelta(days=7)),
            "total_groups": await count(KnownGroup),
            "active_groups": await count(KnownGroup, KnownGroup.is_active.is_(True)),
            "total_finished_games": await count(Game),
            "games_today": await count(Game, Game.ended_at >= now - timedelta(days=1)),
            "games_week": await count(Game, Game.ended_at >= now - timedelta(days=7)),
            "games_month": await count(Game, Game.ended_at >= now - timedelta(days=30)),
            "active_games": len(engines),
            "players_in_play": sum(len(e.state.players) for e in engines),
        },
        "daily_new_users": daily_new,
        "top_players": [{
            "display_name": _display_name(u), "games_played": u.games_played,
            "wins": u.wins, "win_rate": round(100 * u.wins / u.games_played) if u.games_played else 0,
        } for u in top_users],
        "active_games": [{
            "game_id": s.game_id, "chat_id": s.chat_id, "phase": s.phase.value,
            "player_count": len(s.players), "alive_count": len(s.alive_players()),
        } for e in engines for s in [e.state]],
        "recent_games": [{
            "game_id": g.game_id, "player_count": g.player_count,
            "phase": g.phase, "winner_faction": g.winner_faction,
            "ended_at": g.ended_at.isoformat() if g.ended_at else None,
            "mode": g.mode,
        } for g in recent_games],
    }


# --------------------------------------------------------------------- settings
@router.get("/settings/buttons")
async def admin_list_buttons(
    _: int = Depends(admin_service.require_admin_permission("settings.view")),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(
        select(BotButton).order_by(BotButton.order.asc())
    )).scalars().all()
    return {"buttons": [{
        "key": b.key, "label_uz": b.label_uz, "label_ru": b.label_ru,
        "label_en": b.label_en, "enabled": b.enabled, "order": b.order,
        "placement": b.placement, "admin_only": b.admin_only, "action": b.action,
    } for b in rows]}


class AdminButtonUpdate(BaseModel):
    label_uz: str | None = None
    label_ru: str | None = None
    label_en: str | None = None
    enabled: bool | None = None
    order: int | None = None
    placement: str | None = None
    admin_only: bool | None = None
    action: str | None = None


@router.put("/settings/buttons/{key}")
async def admin_update_button(
    key: str, body: AdminButtonUpdate,
    _: int = Depends(admin_service.require_admin_permission("settings.manage")),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(BotButton, key)
    if row is None:
        raise HTTPException(404, "Tugma topilmadi")
    fields: dict = {}
    for field in ("label_uz", "label_ru", "label_en", "enabled", "order",
                  "placement", "admin_only", "action"):
        value = getattr(body, field)
        if value is not None:
            if field in ("label_uz", "label_ru", "label_en", "action") and len(str(value)) > 128:
                raise HTTPException(400, f"{field}: juda uzun")
            fields[field] = value
    await bot_config.save_button(session, key, fields)
    return {"ok": True}


class ReorderButtonsRequest(BaseModel):
    keys: list[str] = []


@router.post("/settings/buttons/reorder")
async def admin_reorder_buttons(
    body: ReorderButtonsRequest,
    _: int = Depends(admin_service.require_admin_permission("settings.manage")),
    session: AsyncSession = Depends(get_session),
):
    await bot_config.reorder_buttons(session, body.keys)
    return {"ok": True, "order": list(body.keys)}
