from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, DateTime, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def _utcnow() -> datetime:
    """Current UTC time as a naive datetime.

    Every DateTime column in this file is a plain ``DateTime`` (i.e. maps to
    Postgres' ``TIMESTAMP WITHOUT TIME ZONE``), so the Python-side value has
    to be naive too. ``datetime.now(timezone.utc)`` returns a *timezone-aware*
    value; handing that to asyncpg for a "without time zone" column raises
    ``can't subtract offset-naive and offset-aware datetimes``. Stripping
    tzinfo here (after computing the correct UTC instant) keeps every
    default/onupdate value naive-but-UTC, matching the column type.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """A Telegram user. Created/updated on every verified initData login."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    games_played: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    town_wins: Mapped[int] = mapped_column(Integer, default=0)
    mafia_wins: Mapped[int] = mapped_column(Integer, default=0)
    neutral_wins: Mapped[int] = mapped_column(Integer, default=0)


class Role(Base):
    """Read-only catalog of role metadata, kept in sync with app/game_engine/roles.py
    for querying/statistics purposes (e.g. 'favorite role')."""
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    faction: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(String(512))


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    host_telegram_id: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(16), default="classic")
    phase: Mapped[str] = mapped_column(String(32), default="lobby")
    player_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    winner_faction: Mapped[str | None] = mapped_column(String(16), nullable=True)

    players: Mapped[list["GamePlayer"]] = relationship(back_populates="game")
    settings: Mapped["GameSettings"] = relationship(back_populates="game", uselist=False)


class GamePlayer(Base):
    __tablename__ = "game_players"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_host: Mapped[bool] = mapped_column(Boolean, default=False)
    alive: Mapped[bool] = mapped_column(Boolean, default=True)
    death_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    death_night: Mapped[int | None] = mapped_column(Integer, nullable=True)
    survived_to_end: Mapped[bool] = mapped_column(Boolean, default=False)

    game: Mapped["Game"] = relationship(back_populates="players")


class GameAction(Base):
    """Append-only log of every night action, for debugging and anti-cheat audits."""
    __tablename__ = "game_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    night_number: Mapped[int] = mapped_column(Integer)
    player_id: Mapped[str] = mapped_column(String(64))
    role_name: Mapped[str] = mapped_column(String(32))
    action_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    day_number: Mapped[int] = mapped_column(Integer)
    voter_id: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class GameEvent(Base):
    """Full event log per game — powers reconnection debugging and game history replay."""
    __tablename__ = "game_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class GameSettings(Base):
    __tablename__ = "game_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), unique=True)
    day_duration_s: Mapped[int] = mapped_column(Integer, default=90)
    night_duration_s: Mapped[int] = mapped_column(Integer, default=45)
    voting_duration_s: Mapped[int] = mapped_column(Integer, default=60)
    anonymous_voting: Mapped[bool] = mapped_column(Boolean, default=False)
    reveal_role_on_death: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_self_vote: Mapped[bool] = mapped_column(Boolean, default=False)
    tie_rule: Mapped[str] = mapped_column(String(16), default="revote")
    allow_neutral_roles: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_special_roles: Mapped[bool] = mapped_column(Boolean, default=True)

    game: Mapped["Game"] = relationship(back_populates="settings")


class GameHistory(Base):
    """Denormalized per-player summary of a finished game — fast reads for
    'game history' and 'my stats' screens without joining live tables."""
    __tablename__ = "game_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    played_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    player_count: Mapped[int] = mapped_column(Integer)
    role_name: Mapped[str] = mapped_column(String(32))
    faction: Mapped[str] = mapped_column(String(16))
    won: Mapped[bool] = mapped_column(Boolean)
    survived_nights: Mapped[int] = mapped_column(Integer, default=0)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    successful_investigations: Mapped[int] = mapped_column(Integer, default=0)
    successful_protections: Mapped[int] = mapped_column(Integer, default=0)


class KnownGroup(Base):
    """A Telegram group the bot is currently a member of, tracked via
    my_chat_member updates (see app/telegram_bot.py). The Bot API has no
    "list every group I'm in" call, so the bot has to remember them itself
    as they happen — this is what powers the private-chat "which group?"
    picker for starting a match without typing /start in the group."""
    __tablename__ = "known_groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BotSetting(Base):
    """Small key/value store for admin-configurable bot settings that
    aren't fixed at deploy time — currently just the mandatory-subscription
    channel, set live from the bot's own /admin panel (app/telegram_bot.py)
    rather than an env var, since the bot owner changes it without a
    redeploy."""
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(512))


class SupportMessage(Base):
    """One row per (admin, forwarded copy) pairing for the "Admin bilan
    bog'lanish" relay in app/telegram_bot.py. A user's message is copied to
    every admin; whichever admin replies (a Telegram reply-to on their own
    copy) needs to be routed back to that original user, even across a
    restart — this table is what makes that lookup possible, keyed by
    which admin got which copy of which message."""
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_display_name: Mapped[str] = mapped_column(String(256))
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    admin_copy_message_id: Mapped[int] = mapped_column(Integer)
    original_text: Mapped[str] = mapped_column(String(4096))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    replied: Mapped[bool] = mapped_column(Boolean, default=False)


class GameCheckpoint(Base):
    """A durable snapshot of one still-in-progress GameState (spec item 3:
    'LIVE GAME STATE PERSISTENCE'), refreshed after every significant
    gameplay event — join, role assignment, night action/resolution,
    death, phase change, vote/vote resolution, mayor reveal, gunner shot,
    game over — via app/services/checkpoint_service.py. Never written on a
    fixed timer, just event-based, so a server restart mid-match can
    reconstruct the game instead of losing it.

    Keyed by the engine's own short game_id rather than games.id, because
    a live match doesn't get a `Game` row until it actually finishes (see
    persist_finished_game) — this table is the only durable record of a
    game while it's still running. The row is deleted once the match ends
    (see checkpoint_service.save_checkpoint), since `games`/`game_history`
    become the permanent record from that point on.

    state_json mirrors GameState's own shape (see
    app/game_engine/persistence.py) rather than normalized columns,
    because that shape is exactly what a recovered engine needs and it
    already changes in lockstep with GameState itself."""
    __tablename__ = "game_checkpoints"

    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    phase: Mapped[str] = mapped_column(String(32))
    state_json: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow,
        onupdate=_utcnow,
    )


class UserLanguage(Base):
    """A user's preferred interface language — a new table rather than a
    column on the existing users table, since adding a column there
    wouldn't retroactively appear in an already-deployed database (this
    project has no migration tool; see app/database.py's create_all()).
    Set from the bot's own menu (app/telegram_bot.py) and read by both the
    bot's own messages and the webapp (POST /auth/telegram includes it) —
    one shared preference either surface can update, so changing it in the
    bot is reflected in the webapp too."""
    __tablename__ = "user_languages"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    language: Mapped[str] = mapped_column(String(8), default="uz")


# ---------------------------------------------------------------------------
# Unified configuration model (premium re-platform: one DB, one source of
# truth for Bot + WebApp). Follows the existing "new table, not a new
# column" convention because this project has no migration tool — every
# admin-editable value therefore lives in its own table that create_all()
# can add to an already-deployed database.
# ---------------------------------------------------------------------------


class BotText(Base):
    """Admin-editable bot texts, in every supported language. The three
    manageable texts per the spec are: /start message, the message posted
    when the bot is added to a group, and the lobby message. Values are
    resolved through app/services/bot_config.py which falls back to the
    code-level defaults in app/i18n.py when a row is missing, and the
    fallback defaults are seeded into this table on first startup so the
    admin always has something to edit.

    Managed through the Admin panel's "Bot matnlari" module; every other
    bot message intentionally stays code-level (the spec lists only these
    three as editable).
    """
    __tablename__ = "bot_texts"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    uz: Mapped[str] = mapped_column(String(4096), default="")
    ru: Mapped[str] = mapped_column(String(4096), default="")
    en: Mapped[str] = mapped_column(String(4096), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow,
        onupdate=_utcnow,
    )


class BotButton(Base):
    """One reply-keyboard button on the bot's main menu, fully configured
    from the Admin panel's "Tugmalar" module: its per-language label, whether
    it's enabled at all, its order across the whole keyboard, which
    placement it belongs to ('main' = the private-chat menu), and whether it
    only appears for admins. The keyboard is rebuilt from the *enabled*
    rows sorted by `order`, so reordering/renaming/enabling here is
    instantly reflected on the bot — the two surfaces share this table as
    their single source of truth (spec: Bot ↔ WebApp synchronization).

    `action` is the logical hook a tap triggers (e.g. "start_group_game",
    "my_stats", "leaderboard", "about", "contact_admin", "language",
    "admin_panel") and never changes with the label.
    """
    __tablename__ = "bot_buttons"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label_uz: Mapped[str] = mapped_column(String(128), default="")
    label_ru: Mapped[str] = mapped_column(String(128), default="")
    label_en: Mapped[str] = mapped_column(String(128), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    placement: Mapped[str] = mapped_column(String(32), default="main")
    admin_only: Mapped[bool] = mapped_column(Boolean, default=False)
    action: Mapped[str] = mapped_column(String(64), default="")


class AdminUser(Base):
    """An admin for the premium Admin panel, beyond the fixed
    settings.admin_telegram_ids super-admins. Super admins (from
    ADMIN_TELEGRAM_IDS env / render.yaml) always hold every permission and
    can never be demoted from the panel; everyone else must be added here
    explicitly by the owner and is granted permissions per-module via the
    AdminPermission table. Server-side permission checks (not the UI) are the
    enforcement point for every /admin/* endpoint.
    """
    __tablename__ = "admin_users"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    created_by: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    permissions: Mapped[list["AdminPermission"]] = relationship(
        back_populates="admin", cascade="all, delete-orphan", lazy="selectin")


class AdminPermission(Base):
    """One granted permission per admin (module-scoped keys like
    'users.view', 'broadcast.send' — see app/api/routes_admin_platform.py's
    PERMISSION_CATALOG). Super admins are not listed here: they implicitly
    hold everything. Ordinary admins are allowed an action only when this
    table has the matching granted row, checked server-side on every route.
    """
    __tablename__ = "admin_permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("admin_users.telegram_user_id", ondelete="CASCADE"))
    permission: Mapped[str] = mapped_column(String(64))

    admin: Mapped["AdminUser"] = relationship(back_populates="permissions")


class BlockedUser(Base):
    """Users the admin has blocked from the platform. Kept in its own table
    (not a column on users — no migration tool) so create_all() can add it
    to a deployed database. A blocked user cannot log in to the WebApp
    (POST /auth/telegram rejects them) and their games are not reachable via
    the profile APIs. Blocking/unblocking lives in the Admin panel's
    "Foydalanuvchilar" module.
    """
    __tablename__ = "blocked_users"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    blocked_by: Mapped[int] = mapped_column(BigInteger, default=0)
    blocked_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RequiredChannel(Base):
    __tablename__ = "required_channels"
    chat_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    join_url: Mapped[str] = mapped_column(String(512))
    created_by: Mapped[int] = mapped_column(BigInteger)


class BroadcastDelivery(Base):
    __tablename__ = "broadcast_deliveries"
    campaign_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")


class Broadcast(Base):
    """One broadcast campaign sent from the Admin panel's "Xabarlar" module.
    `spec` is a JSON dict describing the recipient set (kind: all / users /
    groups / active_users, plus explicit ids when kind is users/groups) and
    the optional inline button(s). The counters record the run result —
    how many were sent, delivered and failed — and the history view lists
    every campaign with those numbers.
    """
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    text: Mapped[str] = mapped_column(String(4096), default="")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/sent/failed
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    delivered: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
