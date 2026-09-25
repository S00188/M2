from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.api.dependencies import require_telegram_id
from app.config import settings
from app.database import get_session
from app.i18n import get_user_language, set_user_language
from app.models.models import BlockedUser
from app.services import admin_service
from app.services.telegram_auth import verify_init_data, TelegramAuthError
from app.services.game_service import get_or_create_user
from app.utils.helpers import create_session_token

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramLoginRequest(BaseModel):
    init_data: str


class TelegramLoginResponse(BaseModel):
    session_token: str
    telegram_user_id: int
    display_name: str
    photo_url: str | None = None
    # Lets the WebApp know, right at login and without a second round trip,
    # whether to show the bot-owner-only "Admin" tab. The real gate is on
    # every /admin/* endpoint (require_bot_admin / require_admin_permission)
    # — this flag is a display convenience, not the authorization itself.
    # True for both super admins and AdminUser panel admins.
    is_bot_admin: bool = False
    # True only for the bot owner (settings.admin_telegram_ids) — the few
    # routes still gated by require_bot_admin (live game control) are theirs.
    is_super_admin: bool = False
    # The permissions this admin holds (module-scoped keys), for UI
    # labelling only. Always empty for non-admins; super admins report all.
    permissions: list[str] = []
    # The user's preferred language (see app/i18n.py) — shared with the bot,
    # so switching it from the bot's own menu is reflected here too.
    language: str = "uz"


@router.post("/telegram", response_model=TelegramLoginResponse)
async def login_with_telegram(body: TelegramLoginRequest, session: AsyncSession = Depends(get_session)):
    try:
        tg_user = verify_init_data(body.init_data, settings.telegram_bot_token)
    except TelegramAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # Admins can block a user from the platform entirely (Admin panel
    # "Foydalanuvchilar" module) — a blocked user may not sign in.
    if await session.get(BlockedUser, tg_user.telegram_user_id) is not None:
        raise HTTPException(status_code=403, detail="Siz botdan foydalanishdan bloklangansiz")
    from app.services.access_control import require_subscription
    await require_subscription(tg_user.telegram_user_id)

    user = await get_or_create_user(
        session, tg_user.telegram_user_id, tg_user.first_name,
        tg_user.last_name, tg_user.username, tg_user.photo_url,
    )
    token = create_session_token(tg_user.telegram_user_id, settings.session_secret,
                                  settings.session_ttl_seconds)
    display_name = tg_user.username or f"{tg_user.first_name} {tg_user.last_name or ''}".strip()
    language = await get_user_language(tg_user.telegram_user_id)
    is_bot_admin = await admin_service.is_admin(tg_user.telegram_user_id)
    is_super_admin = admin_service.is_super_admin(tg_user.telegram_user_id)
    permissions = sorted(await admin_service.admin_permissions(tg_user.telegram_user_id)) if is_bot_admin else []
    return TelegramLoginResponse(session_token=token, telegram_user_id=tg_user.telegram_user_id,
                                  display_name=display_name, photo_url=tg_user.photo_url,
                                  is_bot_admin=is_bot_admin, is_super_admin=is_super_admin,
                                  permissions=permissions,
                                  language=language)


class LanguageRequest(BaseModel):
    language: str


@router.post("/language")
async def update_language(body: LanguageRequest,
                          telegram_user_id: int = Depends(require_telegram_id)):
    """Switch the user's interface language from inside the WebApp — the
    other half of the single, shared language setting (the bot's own /til
    menu is the first half). Both surfaces read and write the same row, so
    changing it here is reflected in the bot immediately."""
    await set_user_language(telegram_user_id, body.language)
    return {"ok": True, "language": body.language}
