from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Optional
from app.game_engine.roles import RoleName, Faction, ActionType


class EngineError(ValueError):
    """Raised for any client-caused invalid action. Safe to show to the user.

    Lives here (a leaf module with no dependency on engine.py or
    managers.py) rather than in engine.py, specifically so that
    managers.py — which engine.py already imports from — can raise it too
    without creating an engine.py <-> managers.py import cycle. engine.py
    re-imports and re-exports it from here so `from
    app.game_engine.engine import EngineError` (used throughout the API/
    WebSocket layer) keeps working unchanged."""


class Phase(str, Enum):
    LOBBY = "lobby"
    ROLE_ASSIGNMENT = "role_assignment"
    NIGHT = "night"
    MORNING = "morning"
    DAY_DISCUSSION = "day_discussion"
    VOTING = "voting"
    LYNCH_CONFIRMATION = "lynch_confirmation"
    KAMIKAZE_STRIKE = "kamikaze_strike"
    VOTE_RESULTS = "vote_results"
    GAME_OVER = "game_over"


@dataclass
class GameSettings:
    mode: str = "classic"                 # classic | advanced | custom
    day_duration_s: int = 90
    night_duration_s: int = 45
    voting_duration_s: int = 60
    lobby_duration_s: int = 300
    anonymous_voting: bool = False
    reveal_role_on_death: bool = True
    allow_self_vote: bool = False
    tie_rule: str = "revote"              # no_elimination | revote | random
    allow_neutral_roles: bool = True
    allow_special_roles: bool = True


@dataclass
class PlayerState:
    player_id: str                        # internal uuid
    telegram_user_id: int
    display_name: str
    avatar_url: Optional[str] = None
    role: Optional[RoleName] = None
    alive: bool = True
    is_host: bool = False
    connected: bool = True
    # Filled-in AI player, added only through the bot owner's admin panel so
    # a match can be exercised end to end without gathering six real people.
    # Never set by any player-facing route.
    is_bot: bool = False
    death_reason: Optional[str] = None
    death_night: Optional[int] = None
    # per-night transient effects (cleared every night)
    silenced: bool = False
    protected_by_bodyguard: Optional[str] = None   # the Doctor that healed this player tonight
    # per-game counters
    last_self_heal_night: Optional[int] = None
    vote_weight: int = 1
    # Whether this player has hit "Ready" during the current DAY_DISCUSSION
    # (spec item 1) — cleared every time a fresh discussion phase begins.
    ready_for_vote: bool = False
    # personal stats — spec section 22 "personal statistics" (shown to a
    # player about themself at game end, alongside the shared final role
    # reveal). Deliberately simple counters, bumped at the exact points
    # actions are validated/resolved; see engine.py.
    kills: int = 0
    investigations: int = 0
    protections: int = 0
    votes_cast: int = 0
    # spoken during the VOTE_RESULTS window right after being voted out
    # (spec: 60s to type something before the game moves on)
    last_words: Optional[str] = None
    # Host-chosen role for this player (bot games: "choose the bots' roles
    # yourself"). A RoleName value as a plain string, honored by
    # RoleManager.assign_roles and cleared once consumed. Only the host may
    # set it, only in the lobby, only for bots / the host themself, and only
    # to a role that exists in this size's composition.
    bot_role_pick: Optional[str] = None
    # -- True Mafia additions -------------------------------------------
    # Blocked this night by the Mistress — the player's night ability is
    # skipped (per-night transient, cleared every night with the others).
    blocked: bool = False
    # Protected by the Doctor tonight (per-night transient).
    protected: bool = False
    # Lucky's self-survival luck already resolved is transient by nature; we
    # only need the per-game guarantee that each attack does its own check,
    # so no persistent flag beyond the existing per-night resets is needed.
    # Whether this player survives a specific night's lethal attack because
    # of a Lucky lucksave. Transient (per-night).
    lucky_survived_lethal: bool = False
    # Commissioner's one-shot special kill — consumed exactly once per game.
    commissioner_kills_used: int = 0
    # Set when the Sergeant is promoted to Commissioner (or a Mafia member is
    # promoted to Don) — the server flips `role` and records the promotion.
    promoted: bool = False
    # Lawyer's per-night client (the player shielded from a correct
    # Commissioner read). Cleared every night alongside the other
    # per-night transient effects.
    lawyer_client: Optional[str] = None
    # True while this player is the chronic Suicide who must be lynched to
    # win — surfaced so a Jury/outcome screen can explain the win.
    suicide_lynched: bool = False
    # The Kamikaze's chosen "take-you-with-me" target while the game is in
    # the KAMIKAZE_STRIKE phase (only ever set if role is Kamikaze).
    kamikaze_target: Optional[str] = None


@dataclass
class ChatMessage:
    """One in-app discussion message (spec sections 11/32) — the Telegram
    group never sees this; it exists only inside a single game's state.

    kind/payload turn the same list into system announcements too:
      kind == "player" (default)  -> a player-typed chat line (text only)
      kind == "death"             -> who died, by what role, victim's role
                                     (payload carries structured fields so
                                     the frontend can localize them)
      kind == "last_words"        -> a dead player's final message
      kind == "mafia_result"      -> a mafia-team system note (Consigliere
                                     exact-role findings land in mafia chat)
    Both new fields have defaults, so checkpoints serialized with asdict and
    restored with ChatMessage(**m) stay backward-compatible."""
    message_id: str
    player_id: str
    display_name: str
    text: str
    day_number: int
    ts: float = field(default_factory=time)
    kind: str = "player"
    payload: dict = field(default_factory=dict)


@dataclass
class NightAction:
    player_id: str
    role: RoleName
    action_type: ActionType
    target_id: Optional[str] = None
    submitted_at: float = field(default_factory=time)


@dataclass
class Vote:
    voter_id: str
    target_id: Optional[str]              # None = abstain
    weight: int = 1


@dataclass
class GameEvent:
    ts: float
    event_type: str
    payload: dict = field(default_factory=dict)


@dataclass
class WinResult:
    faction: Optional[Faction]
    winners: list[str]
    reason: str
    # Players who won individually (Jester lynched, Survivor alive at game
    # end) even though the main winner above is a different faction —
    # spec items 10/11's "main_winner / individual_winners[]" model. Never
    # overlaps `winners` for the same win.
    individual_winners: list[str] = field(default_factory=list)


@dataclass
class GameState:
    game_id: str
    chat_id: Optional[str]
    host_id: str
    settings: GameSettings = field(default_factory=GameSettings)
    players: dict[str, PlayerState] = field(default_factory=dict)
    phase: Phase = Phase.LOBBY
    night_number: int = 0
    day_number: int = 0
    phase_start: float = field(default_factory=time)
    phase_end: float = field(default_factory=time)
    night_actions: dict[str, NightAction] = field(default_factory=dict)   # player_id -> action
    votes: dict[str, Vote] = field(default_factory=dict)                  # voter_id -> vote
    # PURE INDEPENDENT RANDOM server-side variant selection (source of truth:
    # mafia_rol_jadvali_FINAL.md). Chosen once at game start; never derived
    # from history and never stored for reuse.
    selected_variant: Optional[str] = None
    # Tie -> revote bookkeeping (spec item 2). revote_round is 0 during the
    # first vote of the day; a tie under tie_rule="revote" bumps it to 1 and
    # restricts votes to revote_candidates. A second tie stops the lynch —
    # there is never more than one revote.
    revote_round: int = 0
    revote_candidates: Optional[list[str]] = None
    events: list[GameEvent] = field(default_factory=list)
    winner: Optional[WinResult] = None
    last_night_deaths: list[dict] = field(default_factory=list)
    last_vote_result: Optional[dict] = None
    chat_messages: list[ChatMessage] = field(default_factory=list)
    # Private mafia-only channel (engine.send_mafia_chat_message) — a
    # separate list from chat_messages so a leak can never happen by
    # accident: get_player_view only attaches this one to a mafia player's
    # own view, the same way roles themselves are only ever visible to
    # their owner.
    mafia_chat_messages: list[ChatMessage] = field(default_factory=list)
    # Set once persist_finished_game() (app/services/game_service.py) has
    # successfully written this game's Game/GamePlayer/GameHistory rows.
    # A finished game's engine stays in the registry and its WebSocket
    # connection can keep receiving messages (last words, a stray retry,
    # a reconnect) — this flag is what stops any of those from re-running
    # persistence and creating duplicate rows. Deliberately not persisted
    # to a checkpoint: GAME_OVER checkpoints are deleted (see
    # checkpoint_service.save_checkpoint), so a finished game is never
    # rebuilt from one, and this flag would have nothing to round-trip.
    finished_persisted: bool = False
    group_start_announced: bool = False
    group_end_announced: bool = False
    # Anonymous, phase-scoped activity feed (feature request items 2/3/11/
    # 16-18): entries never name an actor or a target, only "what kind of
    # thing happened" — e.g. "Doctor went to protect someone" — using an
    # i18n message_key rather than a hard-coded string, exactly the way
    # send_chat_message uses ChatMessage rather than raw strings. Kept as
    # its own list (not reusing `events` above) because `events` already
    # has a different job (internal admin/debug trace with player_ids in
    # the payload — see get_player_view's "admin" section) and mixing the
    # two would risk a real leak by accident. Each entry:
    #   phase: Phase value the event happened in ("night", "day_discussion", "voting")
    #   phase_number: night_number or day_number at the time, so the
    #     frontend can group/segment feeds per spec item 7 ("do not mix
    #     events from different phases") without needing its own counters
    #   message_key: i18n key, e.g. "night.mafia.action_submitted"
    #   visible_to: "all", or a list of specific player_ids (never a faction
    #     name or role name — always resolved to concrete player_ids at
    #     append time, so a later role change/death can't retroactively
    #     change who could already see a past entry)
    #   seq: monotonic counter, since multiple events can share a ts
    activity_feed: list[dict] = field(default_factory=list)
    _activity_seq: int = 0
    # -- lynch-confirmation ballot bookkeeping (Phase.LYNCH_CONFIRMATION) --
    _confirm_yes: int = 0
    _confirm_no: int = 0
    _confirm_voters: set[str] = field(default_factory=set)
    # Debug trace of the last resolved night (what action each player took).
    _night_action_log: list[dict] = field(default_factory=list)
    # target_id -> [attacker labels ("mafia"/"maniac"/"commissioner")] for
    # the night just resolved — lets the outcome-message builder know who
    # was attacked and by whom even when the attack failed (Doctor/Lucky
    # save), since that information doesn't survive anywhere else once
    # NightResolver.resolve returns. See app/game_engine/night_messages.py.
    _night_attack_targets: dict[str, list[str]] = field(default_factory=dict)
    # Personal narrative texts (Uzbek) produced by night and day resolution
    # — "Doctor saved you", "you were shot by the Commissioner", "the
    # Sergeant was promoted", the Suicide's win line, and so on. This is the
    # single source of truth shown both in the client's Role Cabinet panel
    # and as a personal Telegram DM (app/services/notifications.py); never
    # reset, so it's the player's full narrative history for the match.
    outcome_messages: dict[str, list[str]] = field(default_factory=dict)

    def alive_players(self) -> list[PlayerState]:
        return [p for p in self.players.values() if p.alive]

    def get(self, player_id: str) -> PlayerState:
        return self.players[player_id]

    def log(self, event_type: str, **payload) -> None:
        self.events.append(GameEvent(ts=time(), event_type=event_type, payload=payload))
