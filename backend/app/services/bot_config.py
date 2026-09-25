"""
Unified bot configuration — the single source of truth every surface reads.

Premium re-platform: the Bot and the Admin WebApp must never keep separate,
independent configuration stores (spec: "Hech qachon Bot va WebApp uchun
alohida, bir-biridan mustaqil sozlamalar bazasi yaratma."). This is that one
shared store, backed by the same database both surfaces already use:

  * BotText  — the three admin-editable bot messages (/start, bot-added-to-
               a-group, and the lobby join text), stored per language.
  * BotButton — every main-menu reply-keyboard button: its per-language
                label, whether it is enabled, its order across the keyboard,
                its placement ('main'), whether it only shows for admins,
                and the logical action a tap triggers.

Both are seeded on first startup from the code-level defaults in
app/i18n.py, then every read goes through an in-memory cache so the bot's
handlers (which only ever see plain text labels and must match them against
"all languages' labels") stay fast. An admin save through the WebApp writes
the row and calls reload() to invalidate the cache — the very next menu the
bot renders reflects it (spec: bot ↔ webapp synchronization).

The cache is deliberately process-local: there is exactly one backend
process (single web service, see render.yaml), so cache invalidation on save
is always in-process and always effective. Values fall back to the code
defaults when a row is missing, so a fresh DB (or a deploy that predates a
new key) renders a sensible label instead of breaking.
"""
from __future__ import annotations

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.models import AdminUser, BotButton, BotText

# The three admin-editable bot texts (spec section titled "Bot matnlari").
# Every other bot message deliberately stays code-level.
MANAGED_TEXTS = ("start", "group_added", "lobby")

# Fallback text when a BotText row is missing or a language has no value.
_TEXT_FALLBACKS: dict[str, dict[str, str]] = {
    "start": {
        "uz": "🎭 <b>MAFIA BOT</b>\n"
              "▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
              "Guruh o'yinlari uchun mo'ljallangan Mafia boti.\n\n"
              "👥 Meni biror guruhga qo'shing\n"
              "▶️ O'sha yerda <code>/start</code> yuboring\n"
              "✅ Qo'shilish tugmasi paydo bo'ladi\n\n"
              "Yoki pastdagi menyudan foydalaning 👇",
        "ru": "🎭 <b>MAFIA BOT</b>\n"
              "▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
              "Бот для групповой игры в Мафию.\n\n"
              "👥 Добавьте меня в группу\n"
              "▶️ Отправьте там <code>/start</code>\n"
              "✅ Появится кнопка для присоединения\n\n"
              "Либо используйте меню снизу 👇",
        "en": "🎭 <b>MAFIA BOT</b>\n"
              "▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
              "A Mafia bot built for group games.\n\n"
              "👥 Add me to a group\n"
              "▶️ Send <code>/start</code> there\n"
              "✅ A join button will appear\n\n"
              "Or use the menu below 👇",
    },
    "group_added": {
        "uz": "✅ <b>Bot guruhga qo'shildi!</b>\n"
              "▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
              "O'yinni boshlash uchun:\n"
              "▶️ Shu guruhda <code>/start</code> yuboring\n"
              "✅ A'zolar qo'shiladigan tugma paydo bo'ladi",
        "ru": "✅ <b>Бот добавлен в группу!</b>\n"
              "▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
              "Чтобы начать игру:\n"
              "▶️ Отправьте здесь <code>/start</code>\n"
              "✅ Появится кнопка для присоединения",
        "en": "✅ <b>Bot added to the group!</b>\n"
              "▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
              "To start a game:\n"
              "▶️ Send <code>/start</code> here\n"
              "✅ A join button will appear for members",
    },
    "lobby": {
        "uz": "🌙 <b>MAFIA</b> boshlanmoqda!\n"
              "▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
              "🔘 Qo'shilish uchun quyidagi tugmani bosing\n"
              "👥 Kamida <b>6</b> kishi yig'ilsa — start!",
        "ru": "🌙 <b>МАФИЯ</b> начинается!\n"
              "▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
              "🔘 Нажмите кнопку ниже, чтобы присоединиться\n"
              "👥 Минимум <b>6</b> человек — и можно начинать!",
        "en": "🌙 <b>MAFIA</b> is starting!\n"
              "▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
              "🔘 Tap the button below to join\n"
              "👥 At least <b>6</b> people — and it's on!",
    },
}

# Key -> placement/action/admin-only defaults for the DB-managed buttons.
# Seeded once; everything here is editable from the Admin panel afterwards.
BUTTON_SEEDS: list[dict] = [
    {"key": "start_group_game", "order": 10, "placement": "main", "admin_only": False},
    {"key": "admin_panel", "order": 70, "placement": "main", "admin_only": True},
    # Everything below is disabled by default — the reply-keyboard is meant
    # to stay down to the two buttons above. Rows stay defined (not deleted)
    # so an admin can still re-enable any of them from the WebApp's
    # Sozlamalar → Tugmalar module without a code change, and so the
    # handlers underneath keep working the moment one is switched back on.
    {"key": "leaderboard", "order": 20, "placement": "main", "admin_only": False, "enabled": False},
    {"key": "my_stats", "order": 30, "placement": "main", "admin_only": False, "enabled": False},
    {"key": "about", "order": 40, "placement": "main", "admin_only": False, "enabled": False},
    {"key": "contact_admin", "order": 50, "placement": "main", "admin_only": False, "enabled": False},
    {"key": "language", "order": 60, "placement": "main", "admin_only": False, "enabled": False},
    # Roles only make sense inside a game (spec: general "Rollar" section is
    # removed from the main menu), and the profile lives inside the Mini App
    # dashboard (reached via the blue Menu button) — both stay defined so the
    # handlers keep working, but they're disabled on the main keyboard.
    {"key": "roles", "order": 80, "placement": "main", "admin_only": False, "enabled": False},
    {"key": "my_profile", "order": 90, "placement": "main", "admin_only": False, "enabled": False},
]

# ------------------------------------------------ in-memory cache ---------
_texts: dict[str, dict[str, str]] = {}
_buttons: dict[str, dict] = {}
# DB-added admins, in addition to settings.admin_telegram_ids (super admins).
# Refreshed by reload() and whenever the admin panel changes an admin role.
_db_admin_ids: set[int] = set()
_config_loaded = False


def _button_label_fallback(key: str, lang: str) -> str | None:
    from app.i18n import BUTTONS, DEFAULT_LANGUAGE
    if key not in BUTTONS:
        return None
    return BUTTONS[key].get(lang, BUTTONS[key][DEFAULT_LANGUAGE])


# ------------------------------------------------------------- seeding ----
async def load_config() -> None:
    """Idempotently seed any missing default texts/buttons, then load the
    whole config (texts, buttons, extra admins) into the in-memory cache.
    Called from the app lifespan, before any request or bot update arrives."""
    # Idempotent: every call inserts only the rows that are missing, then
    # reloads the cache. This is safe on repeated startup and self-heals when
    # the backing store is empty/fresh while the process cache is already
    # flagged as loaded (e.g. a test session that swapped in a new engine).
    async with AsyncSessionLocal() as session:
        existing_texts = {
            row.key for row in (await session.execute(select(BotText))).scalars().all()
        }
        for key in MANAGED_TEXTS:
            if key not in existing_texts:
                row = BotText(
                    key=key,
                    uz=_TEXT_FALLBACKS[key].get("uz", ""),
                    ru=_TEXT_FALLBACKS[key].get("ru", ""),
                    en=_TEXT_FALLBACKS[key].get("en", ""),
                )
                session.add(row)

        existing_buttons = {
            row.key for row in (await session.execute(select(BotButton))).scalars().all()
        }
        for seed in BUTTON_SEEDS:
            if seed["key"] in existing_buttons:
                continue
            session.add(BotButton(
                key=seed["key"],
                label_uz=_button_label_fallback(seed["key"], "uz") or seed["key"],
                label_ru=_button_label_fallback(seed["key"], "ru") or seed["key"],
                label_en=_button_label_fallback(seed["key"], "en") or seed["key"],
                enabled=seed.get("enabled", True),
                order=seed["order"],
                placement=seed["placement"],
                admin_only=seed.get("admin_only", False),
                action=seed["key"],
            ))
        await session.commit()

    await reload()


async def reload() -> None:
    """Rebuild the whole in-memory config from the database — called after
    every admin write so the bot sees the new texts/buttons immediately."""
    global _texts, _buttons, _db_admin_ids, _config_loaded
    async with AsyncSessionLocal() as session:
        texts = (await session.execute(select(BotText))).scalars().all()
        buttons = (await session.execute(select(BotButton))).scalars().all()
        admin_rows = (await session.execute(select(AdminUser))).scalars().all()
    _texts = {row.key: {"uz": row.uz, "ru": row.ru, "en": row.en} for row in texts}
    _buttons = {
        row.key: {
            "label_uz": row.label_uz, "label_ru": row.label_ru, "label_en": row.label_en,
            "enabled": bool(row.enabled), "order": int(row.order or 0),
            "placement": row.placement, "admin_only": bool(row.admin_only),
            "action": row.action,
        }
        for row in buttons
    }
    _db_admin_ids = {row.telegram_user_id for row in admin_rows}
    _config_loaded = True


# ---------------------------------------------------------------- reads ----
def get_text(key: str, lang: str) -> str:
    """The configured text for `key` in `lang`, falling back to the row's
    default language, then to the code default. Never raises."""
    from app.i18n import DEFAULT_LANGUAGE
    row = _texts.get(key)
    if row:
        value = row.get(lang) or row.get(DEFAULT_LANGUAGE) or ""
        if value:
            return value
    fallback = _TEXT_FALLBACKS.get(key, {}).get(lang) or _TEXT_FALLBACKS.get(key, {}).get(DEFAULT_LANGUAGE)
    return fallback or ""


def button_label_or_none(key: str, lang: str) -> str | None:
    """The DB-configured label for this button in `lang`, or None when the
    button isn't DB-managed / hasn't been seeded. Used by app/i18n.py's
    button_text() so renames made in the Admin panel are honored everywhere
    (including the text-matching filters in the bot)."""
    info = _buttons.get(key)
    if not info:
        return None
    from app.i18n import DEFAULT_LANGUAGE
    label = info.get(f"label_{lang}") or info.get(f"label_{DEFAULT_LANGUAGE}") or ""
    return label or None


def button_labels_or_none(key: str) -> set[str]:
    """Every language's configured label for a button, for the bot's
    F.text.in_(...) filters — so a renamed button still triggers its handler
    regardless of the sender's language."""
    info = _buttons.get(key)
    if not info:
        return set()
    return {label for label in (info.get("label_uz"), info.get("label_ru"), info.get("label_en")) if label}


def menu_button_order(user_id: int) -> list[dict]:
    """The enabled main-menu buttons in keyboard order, as small dicts
    {key, label_uz, label_ru, label_en, admin_only, action}. Admin-only
    buttons are included only for admins (super admin ids are read live so
    test monkeypatching and .env changes behave)."""
    from app.config import settings
    is_admin = user_id in settings.admin_telegram_ids or user_id in _db_admin_ids
    items = []
    for key, info in sorted(_buttons.items(), key=lambda kv: kv[1].get("order", 0)):
        if info.get("placement") != "main":
            continue
        if not info.get("enabled", True):
            continue
        if info.get("admin_only") and not is_admin:
            continue
        items.append({
            "key": key,
            "label_uz": info.get("label_uz") or "",
            "label_ru": info.get("label_ru") or "",
            "label_en": info.get("label_en") or "",
            "admin_only": bool(info.get("admin_only")),
            "action": info.get("action") or key,
        })
    return items


def is_known_admin(user_id: int) -> bool:
    from app.config import settings
    return user_id in settings.admin_telegram_ids or user_id in _db_admin_ids


def admin_ids() -> set[int]:
    """Super admins (live) union DB-added admins. Kept small and in-memory;
    routes that add/remove admins call reload() so this is always current."""
    from app.config import settings
    return set(settings.admin_telegram_ids) | _db_admin_ids


# ----------------------------------------------------------------- writes ----
async def save_text(session, key: str, lang: str, value: str) -> None:
    """Persist one managed text's translation and refresh the cache."""
    from app.i18n import SUPPORTED_LANGUAGES
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {lang}")
    row = await session.get(BotText, key)
    if row is None:
        row = BotText(key=key)
        session.add(row)
    setattr(row, lang, (value or "")[:4096])
    await session.commit()
    await reload()


async def save_button(session, key: str, fields: dict) -> None:
    """Persist button config fields (labels, enabled, order, placement,
    admin_only) and refresh the cache."""
    row = await session.get(BotButton, key)
    if row is None:
        row = BotButton(key=key)
        session.add(row)
    allowed = {"label_uz", "label_ru", "label_en", "enabled", "order",
               "placement", "admin_only", "action"}
    for field, value in fields.items():
        if field in allowed:
            setattr(row, field, value)
    await session.commit()
    await reload()


async def reorder_buttons(session, keys: list[str]) -> None:
    """Assign order 10,20,30... in the given key sequence."""
    rows = (await session.execute(select(BotButton))).scalars().all()
    by_key = {row.key: row for row in rows}
    for index, key in enumerate(keys):
        if key in by_key:
            by_key[key].order = (index + 1) * 10
    await session.commit()
    await reload()
