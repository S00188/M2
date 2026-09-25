"""Shared FastAPI auth dependencies.

require_telegram_id / require_bot_admin used to live in app/api/routes_auth.py,
but the admin platform service (app/services/admin_service.py) needs the same
session-token dependency for its permission checks, and routes_auth needs the
admin service to answer "is this user an admin" on login — splitting them into
their own module keeps that from becoming an import cycle.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from app.config import settings
from app.utils.helpers import TokenError, verify_session_token


async def require_telegram_id(authorization: str | None = Header(default=None)) -> int:
    """Dependency: pulls 'Bearer <session_token>' from the Authorization header
    and returns the verified telegram_user_id. Never trust a client-sent user_id."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing session token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = verify_session_token(token, settings.session_secret)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
    from app.services.access_control import is_blocked
    if await is_blocked(user_id):
        raise HTTPException(403, "Siz botdan foydalanishdan bloklangansiz")
    return user_id


def require_bot_admin(telegram_user_id: int = Depends(require_telegram_id)) -> int:
    """Dependency for the bot-owner-only live-ops routes in routes_admin.py
    (force-advance, terminate, practice games, ...). Delegates the actual
    "is this a super admin" check to app.services.admin_service so there is
    exactly one place that answers that question — this used to re-check
    settings.admin_telegram_ids independently, which was the same rule
    copy-pasted into a second spot."""
    from app.services import admin_service  # local import: avoids a cycle,
                                             # since admin_service itself
                                             # depends on this module.
    if not admin_service.is_super_admin(telegram_user_id):
        raise HTTPException(status_code=403, detail="Siz bot admini emassiz")
    return telegram_user_id
