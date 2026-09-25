"""
GameEngine: the single authoritative entry point for one running game.
Nothing outside this class is allowed to mutate GameState directly —
the WebSocket layer and API routes only ever call methods here, which
is what makes "never trust the frontend" actually enforceable.

True Mafia 13-role edition.
"""
from __future__ import annotations
import uuid
import random
from typing import Optional

from app.game_engine.roles import (
    RoleName, Faction, ActionType, ROLES, MAFIA_KILLING_ROLES, night_action_activity_key,
)
from app.game_engine.compositions import all_possible_roles, COMPOSITIONS, MIN_PLAYERS, MAX_PLAYERS
from app.game_engine.night_messages import build_night_outcome_messages
from app.game_engine.state import (
    GameState, PlayerState, GameSettings, Phase, NightAction, ChatMessage, EngineError,
)
from app.game_engine.managers import (
    RoleManager, PhaseManager, NightResolver, VoteManager, DeathManager,
    WinConditionManager, TimerManager, EventManager, ActivityFeedManager,
    death_announcement, last_words_announcement, MORNING_DURATION_S,
    LYNCH_CONFIRMATION_DURATION_S, KAMIKAZE_STRIKE_DURATION_S,
)

CHAT_MAX_LEN = 500
CHAT_HISTORY_LIMIT = 200

ADMIN_SETTINGS_BOUNDS: dict[str, tuple[int, int]] = {
    "night_duration_s": (10, 300),
    "day_duration_s": (30, 600),
    "voting_duration_s": (15, 300),
}
ADMIN_SETTINGS_CHOICES: dict[str, set[str]] = {
    "tie_rule": {"no_elimination", "revote", "random"},
}
ADMIN_SETTINGS_BOOLS: set[str] = {"anonymous_voting", "allow_self_vote", "reveal_role_on_death"}


class GameEngine:
    def __init__(self, game_id: str, host_telegram_id: int, host_name: str,
                 chat_id: Optional[str] = None, settings: Optional[GameSettings] = None,
                 rng: Optional[random.Random] = None,
                 host_avatar_url: Optional[str] = None):
        host_pid = str(uuid.uuid4())
        self.state = GameState(
            game_id=game_id, chat_id=chat_id, host_id=host_pid,
            settings=settings or GameSettings(),
        )
        self.state.players[host_pid] = PlayerState(
            player_id=host_pid, telegram_user_id=host_telegram_id,
            display_name=host_name, is_host=True,
            avatar_url=host_avatar_url,
        )
        self._rng = rng or random.Random()
        self._night_results: dict[str, dict] = {}
        self._lynch_target: Optional[str] = None
        self._lynch_confirmed: Optional[bool] = None

    @classmethod
    def from_state(cls, state: GameState, rng: Optional[random.Random] = None) -> "GameEngine":
        self = cls.__new__(cls)
        self.state = state
        self._rng = rng or random.Random()
        self._night_results = {}
        self._lynch_target = None
        self._lynch_confirmed = None
        if state.phase == Phase.LYNCH_CONFIRMATION:
            candidates = state.revote_candidates or []
            target = candidates[0] if len(candidates) == 1 else (state.last_vote_result or {}).get("eliminated")
            if target in state.players and state.players[target].alive:
                self._lynch_target = target
        return self

    # ----------------------------------------------------------------
    # lobby
    # ----------------------------------------------------------------

    def add_player(self, telegram_user_id: int, display_name: str,
                    avatar_url: Optional[str] = None) -> str:
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Game already started")
        if any(p.telegram_user_id == telegram_user_id for p in self.state.players.values()):
            raise EngineError("You already joined this game")
        if len(self.state.players) >= MAX_PLAYERS:
            raise EngineError(f"Lobby is full ({MAX_PLAYERS} max)")
        pid = str(uuid.uuid4())
        self.state.players[pid] = PlayerState(
            player_id=pid, telegram_user_id=telegram_user_id,
            display_name=display_name, avatar_url=avatar_url,
        )
        EventManager.log(self.state, "player_joined", player_id=pid)
        if len(self.state.players) >= MAX_PLAYERS:
            self._begin(auto=True)
        return pid

    def add_bot_player(self, display_name: str) -> str:
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Game already started")
        if len(self.state.players) >= MAX_PLAYERS:
            raise EngineError(f"Lobby is full ({MAX_PLAYERS} max)")
        pid = str(uuid.uuid4())
        bot_index = sum(1 for p in self.state.players.values() if p.is_bot) + 1
        self.state.players[pid] = PlayerState(
            player_id=pid, telegram_user_id=-(bot_index + 1000),
            display_name=display_name, is_bot=True,
        )
        EventManager.log(self.state, "bot_joined", player_id=pid)
        return pid

    def has_bots(self) -> bool:
        return any(p.is_bot for p in self.state.players.values())

    def set_bot_role(self, host_id: str, target_id: str, role_name: Optional[str]) -> None:
        self._require_host(host_id)
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Roles can be selected only in the lobby")
        target = self.state.players.get(target_id)
        if not target:
            raise EngineError("Unknown player")
        if not target.is_bot and target_id != host_id:
            raise EngineError("You can only choose roles for bots (or yourself)")
        if not role_name:
            target.bot_role_pick = None
            return
        try:
            role = RoleName(role_name)
        except ValueError:
            raise EngineError("Unknown role")
        available = all_possible_roles(len(self.state.players))
        if role not in available:
            raise EngineError("This role is not part of this game's lineup")
        copies = max(
            pool.count(role) for pool in
            COMPOSITIONS.get(len(self.state.players), {}).values()
        )
        picked = [RoleName(q) for q in
                  (pl.bot_role_pick for pl in self.state.players.values() if pl.bot_role_pick)]
        if picked.count(role) >= copies and target.bot_role_pick != role.value:
            raise EngineError("All copies of this role are already assigned")
        target.bot_role_pick = role.value
        return role.value

    def kick_player(self, host_id: Optional[str], target_id: str) -> None:
        self._require_host_or_system(host_id)
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Cannot kick after the game has started")
        if host_id is not None and target_id == host_id:
            raise EngineError("Host cannot kick themselves")
        self.state.players.pop(target_id, None)

    def start_game(self, host_id: str) -> None:
        self._require_host(host_id)
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Game already started")
        n = len(self.state.players)
        if not (MIN_PLAYERS <= n <= MAX_PLAYERS):
            raise EngineError(f"Need {MIN_PLAYERS}–{MAX_PLAYERS} players to start (have {n})")
        self._begin(auto=False)

    def _begin(self, auto: bool) -> None:
        RoleManager.assign_roles(self.state, self._rng)
        EventManager.log(self.state, "game_started",
                          player_count=len(self.state.players), auto=auto)
        PhaseManager.to_role_assignment(self.state)

    def advance_from_role_assignment_if_ready(self, force: bool = False) -> bool:
        if self.state.phase != Phase.ROLE_ASSIGNMENT:
            return False
        if not force and not TimerManager.is_expired(self.state):
            return False
        PhaseManager.to_night(self.state)
        return True

    # ----------------------------------------------------------------
    # night
    # ----------------------------------------------------------------

    def _current_mafia_killer(self) -> Optional[str]:
        for pid, p in self.state.players.items():
            if p.alive and p.role == RoleName.DON:
                return pid
        for pid, p in self.state.players.items():
            if p.alive and p.role == RoleName.MAFIA:
                return pid
        return None

    def _attribute_night_stats(self) -> None:
        """Attribute per-player statistics after a night resolves so the
        game-over stats screen is truthful:
        - kills: the Mafia killer, the Maniac, or the Commissioner's shot
          (only when the attack actually landed — saves/luck don't count)
        - investigations: each Commissioner's completed check
        - protections: each Doctor's (unblocked) heal
        Uses the resolver's action log so attribution matches exactly what
        NightResolver considered effective."""
        deaths = {d["player_id"]: d["reason"] for d in self.state.last_night_deaths}
        mafia_killer = self._current_mafia_killer()
        for entry in self.state._night_action_log:
            if entry["blocked"]:
                continue
            pid = entry["player_id"]
            target = entry["target_id"]
            action_type = ActionType(entry["action_type"])
            role = RoleName(entry["role"])
            if action_type in (ActionType.KILL, ActionType.SHOOT):
                if target in deaths:
                    if action_type == ActionType.SHOOT or role == RoleName.MANIAC:
                        self.state.players[pid].kills += 1
                    elif mafia_killer == pid:
                        self.state.players[pid].kills += 1
            elif action_type == ActionType.INVESTIGATE and target:
                self.state.players[pid].investigations += 1
            elif action_type == ActionType.PROTECT and target:
                self.state.players[pid].protections += 1

    def _eligible_night_actions(self) -> int:
        """How many living players are expected to submit a night action."""
        killer = self._current_mafia_killer()
        count = 0
        for p in self.state.alive_players():
            rdef = ROLES.get(p.role) if p.role else None
            if rdef is None or rdef.night_action is None:
                continue
            if p.role in MAFIA_KILLING_ROLES and p.player_id != killer:
                continue
            count += 1
        return count

    def submit_night_action(self, player_id: str, target_id: Optional[str],
                             action_override: Optional[str] = None) -> None:
        if self.state.phase != Phase.NIGHT:
            raise EngineError("It is not night")
        player = self._require_alive(player_id)
        if player_id in self.state.night_actions:
            raise EngineError("Action already submitted")

        role_def = ROLES.get(player.role)
        if role_def is None:
            raise EngineError("Your role has no night action")

        # Normalise the action: most roles have exactly one night action;
        # the Commissioner may choose between CHECK (investigate) and SHOOT.
        if action_override == "shoot":
            if player.role != RoleName.COMMISSIONER:
                raise EngineError("Only the Commissioner can shoot")
            if player.commissioner_kills_used >= 1:
                raise EngineError("Commissioner kill already used")
            action_type = ActionType.SHOOT
        else:
            action_type = role_def.night_action

        if action_type is None:
            raise EngineError("Your role has no night action")

        # Only the designated Mafia killer actually performs the kill.
        if player.role in MAFIA_KILLING_ROLES and player.player_id != self._current_mafia_killer():
            raise EngineError("Bu kecha o'ldirishni Don (yoki uning merosxo'ri) amalga oshiradi")

        # Charge cap for Commissioner's one-shot kill.
        if action_type == ActionType.SHOOT and player.commissioner_kills_used >= 1:
            raise EngineError("Commissioner kill already used")

        # Target validation
        no_target_actions = (ActionType.SHOOT,)  # SHOOT can target, but KILL/MANIAC can skip
        targetless_kills = (ActionType.KILL,)  # Mafia/Maniac can skip to say "don't attack"

        if target_id is not None:
            if target_id not in self.state.players:
                raise EngineError("Invalid target")
            if not self.state.players[target_id].alive:
                raise EngineError("Target is not alive")
            if target_id == player_id and not role_def.can_target_self:
                raise EngineError("This role cannot target itself")
        elif action_type not in targetless_kills:
            raise EngineError("This action requires a target")

        self.state.night_actions[player_id] = NightAction(
            player_id=player_id, role=player.role, action_type=action_type, target_id=target_id,
        )
        if action_type == ActionType.SHOOT:
            player.commissioner_kills_used += 1

        EventManager.log(self.state, "night_action_submitted", player_id=player_id)
        ActivityFeedManager.public(
            self.state,
            night_action_activity_key(player.role, action_type, target_id is not None),
            night=self.state.night_number,
        )

    def resolve_night_if_ready(self, force: bool = False) -> bool:
        if self.state.phase != Phase.NIGHT:
            return False
        if not force and not TimerManager.is_expired(self.state):
            if len(self.state.night_actions) < self._eligible_night_actions():
                return False
        deaths, results = NightResolver.resolve(self.state, self._rng)
        self._night_results = results
        # Exact narrative texts (Doctor save, Mistress block, Commissioner
        # read, Mafia/Maniac kill, Lucky save, Vagabond report, ...) for
        # everyone this night touched — the single source of truth shown in
        # the client's Role Cabinet panel and sent as a personal Telegram DM.
        new_messages = build_night_outcome_messages(self.state, results)
        for pid, lines in new_messages.items():
            self.state.outcome_messages.setdefault(pid, []).extend(lines)
        # Lucky survival is already handled in the resolver; just record who
        # survived for the morning report.
        for pid, res in results.items():
            if res.get("saved_by") == "luck":
                self.state.players[pid].lucky_survived_lethal = True
        self._attribute_night_stats()
        # Promotions after night deaths.
        for d in deaths:
            pid = d["player_id"]
            p = self.state.players.get(pid)
            if not p:
                continue
            if p.role == RoleName.COMMISSIONER:
                RoleManager.promote_sergeant(self.state, pid)
            elif p.role == RoleName.DON:
                RoleManager.promote_new_don(self.state)
        win = WinConditionManager.check(self.state)
        if win:
            PhaseManager.to_game_over(self.state, win)
        else:
            PhaseManager.to_morning(self.state)
        return True

    def resolve_morning_if_ready(self, force: bool = False) -> bool:
        if self.state.phase != Phase.MORNING:
            return False
        if not force and not TimerManager.is_expired(self.state):
            return False
        PhaseManager.to_day(self.state)
        return True

    # ----------------------------------------------------------------
    # day / discussion
    # ----------------------------------------------------------------

    def set_ready_for_vote(self, player_id: str, ready: bool = True) -> None:
        if self.state.phase != Phase.DAY_DISCUSSION:
            raise EngineError("Not in discussion phase")
        p = self._require_alive(player_id)
        p.ready_for_vote = bool(ready)
        EventManager.log(self.state, "ready_for_vote", player_id=player_id, ready=p.ready_for_vote)

    def submit_vote(self, voter_id: str, target_id: Optional[str]) -> None:
        VoteManager.submit_vote(self.state, voter_id, target_id)
        if target_id is not None:
            self.state.players[voter_id].votes_cast += 1
        EventManager.log(self.state, "vote_submitted", voter_id=voter_id)

    def resolve_voting_if_ready(self, force: bool = False) -> bool:
        if self.state.phase != Phase.VOTING:
            return False
        alive = [p for p in self.state.alive_players() if not p.silenced]
        if not force and not TimerManager.is_expired(self.state) and len(self.state.votes) < len(alive):
            return False
        result = VoteManager.tally(self.state)
        if result.get("revote"):
            PhaseManager.to_voting(self.state)
            self.state.votes.clear()
            self.state.revote_round = 1
            self.state.revote_candidates = sorted(result["candidates"])
            TimerManager.start_phase(self.state, self.state.settings.voting_duration_s)
            EventManager.log(self.state, "phase_revote", round=1, candidates=self.state.revote_candidates)
            return True
        if result["eliminated"]:
            self._lynch_target = result["eliminated"]
            PhaseManager.to_lynch_confirmation(self.state, [result["eliminated"]])
            return True
        PhaseManager.to_vote_results(self.state)
        return True

    def submit_lynch_confirm(self, player_id: str, yes: bool) -> None:
        VoteManager.submit_lynch_confirm(self.state, player_id, yes)

    def resolve_lynch_confirmation_if_ready(self, force: bool = False) -> bool:
        if self.state.phase != Phase.LYNCH_CONFIRMATION:
            return False
        if not force and not TimerManager.is_expired(self.state):
            alive = [p for p in self.state.alive_players() if not p.silenced]
            voters_so_far = getattr(self.state, "_confirm_voters", set())
            if len(voters_so_far) < len(alive):
                return False
        result = VoteManager.lynch_confirmation_total(self.state)
        if result["approved"]:
            pid = self._lynch_target
            if pid and pid in self.state.players:
                DeathManager.eliminate(self.state, pid, "day_vote")
                self.state.chat_messages.append(
                    death_announcement(self.state, pid, "day_vote"))
                # Kamikaze strike: if the lynched player was a Kamikaze, go
                # to KAMIKAZE_STRIKE phase instead of VOTE_RESULTS.
                p = self.state.players[pid]
                if p.role == RoleName.KAMIKAZE:
                    PhaseManager.to_kamikaze_strike(self.state)
                    return True
                # Suicide win: already recorded by DeathManager.eliminate
                win = WinConditionManager.check(self.state)
                if win:
                    PhaseManager.to_game_over(self.state, win)
                    return True
        else:
            self._lynch_confirmed = False
            if self.state.last_vote_result:
                self.state.last_vote_result = {
                    **self.state.last_vote_result,
                    "candidate": self._lynch_target,
                    "eliminated": None,
                    "reason": "confirmation_rejected",
                    "approved": False,
                }
            EventManager.log(self.state, "lynch_cancelled")
            ActivityFeedManager.public(self.state, "lynch.cancelled", day=self.state.day_number)
        PhaseManager.to_vote_results(self.state)
        return True

    def resolve_kamikaze_strike_if_ready(self, force: bool = False) -> bool:
        if self.state.phase != Phase.KAMIKAZE_STRIKE:
            return False
        if not force and not TimerManager.is_expired(self.state):
            return False
        PhaseManager.to_vote_results(self.state)
        return True

    def submit_kamikaze_target(self, player_id: str, target_id: str) -> None:
        """The Kamikaze's post-lynch 'take-you-with-me' pick. Runs while the
        striker is already dead (they were just voted out), so the normal
        alive-guard must NOT apply to the actor — only to their target."""
        if self.state.phase != Phase.KAMIKAZE_STRIKE:
            raise EngineError("Kamikaze strike is not active")
        p = self.state.players.get(player_id)
        if not p:
            raise EngineError("Unknown player")
        if p.role != RoleName.KAMIKAZE:
            raise EngineError("Only the Kamikaze can choose a strike target")
        if player_id in self.state.night_actions:
            raise EngineError("Strike target already chosen")
        self._require_alive(target_id)
        self.state.night_actions[player_id] = NightAction(
            player_id=player_id, role=RoleName.KAMIKAZE, action_type=ActionType.KILL,
            target_id=target_id,
        )
        p.kills += 1  # the Kamikaze's strike counts as their kill
        DeathManager.eliminate(self.state, target_id, "kamikaze")
        self.state.chat_messages.append(
            death_announcement(self.state, target_id, "kamikaze"))
        self.state.outcome_messages.setdefault(target_id, []).append(
            "\U0001F4A3 Kamikaze dor ostida turib sizni o'zi bilan birga qabrga tortdi! "
            "Siz ham halok bo'ldingiz.")

    def start_next_night(self) -> None:
        if self.state.phase != Phase.VOTE_RESULTS:
            raise EngineError("Not ready for the next night")
        PhaseManager.to_night(self.state)

    def submit_last_words(self, player_id: str, text: str) -> None:
        s = self.state
        player = s.players.get(player_id)
        if not player:
            raise EngineError("Unknown player")
        if player.alive:
            raise EngineError("Only dead players can leave last words")
        if player.last_words is not None:
            raise EngineError("Last words already sent")
        eligible = False
        if s.phase == Phase.VOTE_RESULTS:
            result = s.last_vote_result
            eligible = bool(result and result.get("eliminated") == player_id)
        elif s.phase == Phase.DAY_DISCUSSION:
            eligible = player.death_night == s.night_number
        if not eligible:
            raise EngineError("It is not your turn to leave last words right now")
        text = text.strip()
        if not text:
            raise EngineError("Message is empty")
        if len(text) > CHAT_MAX_LEN:
            text = text[:CHAT_MAX_LEN]
        player.last_words = text
        s.chat_messages.append(last_words_announcement(s, player_id, text))
        EventManager.log(self.state, "last_words_submitted", player_id=player_id)

    def advance_to_voting_if_ready(self, force: bool = False) -> bool:
        if self.state.phase != Phase.DAY_DISCUSSION:
            return False
        if not force:
            alive = self.state.alive_players()
            all_ready = bool(alive) and all(p.ready_for_vote for p in alive)
            if not all_ready and not TimerManager.is_expired(self.state):
                return False
        PhaseManager.to_voting(self.state)
        return True

    def start_next_night_if_ready(self, force: bool = False) -> bool:
        if self.state.phase != Phase.VOTE_RESULTS:
            return False
        if not force and not TimerManager.is_expired(self.state):
            return False
        self.start_next_night()
        return True

    # ----------------------------------------------------------------
    # admin
    # ----------------------------------------------------------------

    def update_settings(self, host_id: Optional[str], updates: dict) -> None:
        self._require_host_or_system(host_id)
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Settings can only be changed before the game starts")
        if not isinstance(updates, dict) or not updates:
            raise EngineError("No settings provided")
        for key, value in updates.items():
            if key in ADMIN_SETTINGS_BOUNDS:
                lo, hi = ADMIN_SETTINGS_BOUNDS[key]
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise EngineError(f"Invalid value for {key}")
                if not (lo <= value <= hi):
                    raise EngineError(f"{key} must be between {lo} and {hi} seconds")
                setattr(self.state.settings, key, value)
            elif key in ADMIN_SETTINGS_CHOICES:
                if value not in ADMIN_SETTINGS_CHOICES[key]:
                    raise EngineError(f"Invalid value for {key}")
                setattr(self.state.settings, key, value)
            elif key in ADMIN_SETTINGS_BOOLS:
                setattr(self.state.settings, key, bool(value))
            else:
                raise EngineError(f"Unknown setting: {key}")
        EventManager.log(self.state, "settings_updated", updates=updates)

    def force_advance_phase(self, host_id: Optional[str]) -> bool:
        self._require_host_or_system(host_id)
        if self.state.phase == Phase.ROLE_ASSIGNMENT:
            return self.advance_from_role_assignment_if_ready(force=True)
        if self.state.phase == Phase.NIGHT:
            return self.resolve_night_if_ready(force=True)
        if self.state.phase == Phase.MORNING:
            return self.resolve_morning_if_ready(force=True)
        if self.state.phase == Phase.DAY_DISCUSSION:
            return self.advance_to_voting_if_ready(force=True)
        if self.state.phase == Phase.VOTING:
            return self.resolve_voting_if_ready(force=True)
        if self.state.phase == Phase.LYNCH_CONFIRMATION:
            return self.resolve_lynch_confirmation_if_ready(force=True)
        if self.state.phase == Phase.KAMIKAZE_STRIKE:
            return self.resolve_kamikaze_strike_if_ready(force=True)
        if self.state.phase == Phase.VOTE_RESULTS:
            return self.start_next_night_if_ready(force=True)
        raise EngineError("Nothing to advance right now")

    def extend_current_phase(self, host_id: Optional[str], seconds: int) -> None:
        self._require_host_or_system(host_id)
        timed_phases = (Phase.NIGHT, Phase.DAY_DISCUSSION, Phase.VOTING,
                        Phase.VOTE_RESULTS, Phase.MORNING,
                        Phase.LYNCH_CONFIRMATION, Phase.KAMIKAZE_STRIKE)
        if self.state.phase not in timed_phases:
            raise EngineError("This phase has no timer to extend")
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            raise EngineError("Invalid duration")
        if not (5 <= seconds <= 120):
            raise EngineError("Extension must be between 5 and 120 seconds")
        self.state.phase_end += seconds
        EventManager.log(self.state, "phase_extended", seconds=seconds)

    def admin_remove_player(self, host_id: Optional[str], target_id: str) -> None:
        self._require_host_or_system(host_id)
        if host_id is not None and target_id == host_id:
            raise EngineError("Host cannot remove themselves")
        if self.state.phase == Phase.LOBBY:
            self.kick_player(host_id, target_id)
            return
        target = self.state.players.get(target_id)
        if not target:
            raise EngineError("Unknown player")
        if not target.alive:
            raise EngineError("Player is already out of the game")
        DeathManager.eliminate(self.state, target_id, "removed_by_admin")
        win = WinConditionManager.check(self.state)
        if win:
            PhaseManager.to_game_over(self.state, win)

    # ----------------------------------------------------------------
    # discussion / mafia chat
    # ----------------------------------------------------------------

    def send_chat_message(self, player_id: str, text: str) -> None:
        if self.state.phase != Phase.DAY_DISCUSSION:
            raise EngineError("Discussion is not open right now")
        player = self.state.players.get(player_id)
        if not player:
            raise EngineError("Unknown player")
        if not player.alive:
            raise EngineError("Dead players can only spectate the discussion")
        if player.silenced:
            raise EngineError("You are silenced today and cannot send messages")
        text = text.strip()
        if not text:
            raise EngineError("Message is empty")
        if len(text) > CHAT_MAX_LEN:
            text = text[:CHAT_MAX_LEN]
        self.state.chat_messages.append(ChatMessage(
            message_id=str(uuid.uuid4()), player_id=player_id,
            display_name=player.display_name, text=text, day_number=self.state.day_number,
        ))
        if len(self.state.chat_messages) > CHAT_HISTORY_LIMIT:
            del self.state.chat_messages[: len(self.state.chat_messages) - CHAT_HISTORY_LIMIT]
        EventManager.log(self.state, "chat_message", player_id=player_id)

    def send_mafia_chat_message(self, player_id: str, text: str) -> None:
        if self.state.phase in (Phase.LOBBY, Phase.ROLE_ASSIGNMENT, Phase.GAME_OVER):
            raise EngineError("Mafia chat is not open right now")
        player = self.state.players.get(player_id)
        if not player:
            raise EngineError("Unknown player")
        if not player.role or ROLES[player.role].faction != Faction.MAFIA:
            raise EngineError("Only Mafia members can use this chat")
        if not player.alive:
            raise EngineError("Dead players can only spectate the mafia chat")
        text = text.strip()
        if not text:
            raise EngineError("Message is empty")
        if len(text) > CHAT_MAX_LEN:
            text = text[:CHAT_MAX_LEN]
        self.state.mafia_chat_messages.append(ChatMessage(
            message_id=str(uuid.uuid4()), player_id=player_id,
            display_name=player.display_name, text=text, day_number=self.state.day_number,
        ))
        if len(self.state.mafia_chat_messages) > CHAT_HISTORY_LIMIT:
            del self.state.mafia_chat_messages[: len(self.state.mafia_chat_messages) - CHAT_HISTORY_LIMIT]
        EventManager.log(self.state, "mafia_chat_message", player_id=player_id)

    # ----------------------------------------------------------------
    # reconnection / hidden-info view
    # ----------------------------------------------------------------

    def get_player_view(self, player_id: str) -> dict:
        s = self.state
        me = s.players.get(player_id)
        game_over = s.phase == Phase.GAME_OVER
        view = {
            "game_id": s.game_id,
            "phase": s.phase.value,
            "night_number": s.night_number,
            "day_number": s.day_number,
            "phase_ends_in": TimerManager.remaining_seconds(s),
            "host_id": s.host_id,
            "players": [
                {
                    "player_id": p.player_id,
                    "display_name": p.display_name,
                    "avatar_url": p.avatar_url,
                    "is_bot": p.is_bot,
                    "alive": p.alive,
                    "is_host": p.is_host,
                    "connected": p.connected,
                    "role": (p.role.value if p.role and (game_over or p.player_id == player_id
                             or (not p.alive and s.settings.reveal_role_on_death)) else None),
                    "last_words": p.last_words,
                }
                for p in s.players.values()
            ],
            "activity_feed": ActivityFeedManager.for_player(s, player_id),
            "last_night_deaths": s.last_night_deaths if s.phase != Phase.NIGHT else [],
            "last_vote_result": s.last_vote_result,
            "ready_count": sum(1 for p in s.players.values() if p.alive and p.ready_for_vote),
            "alive_count": len(s.alive_players()),
            "revote_round": s.revote_round,
            "revote_candidates": s.revote_candidates,
            "lynch_target": self._lynch_target,
            "winner": (
                {"faction": s.winner.faction.value if s.winner.faction else None,
                 "winners": s.winner.winners, "individual_winners": s.winner.individual_winners,
                 "reason": s.winner.reason}
                if s.winner else None
            ),
            "chat": [
                {"message_id": m.message_id, "player_id": m.player_id,
                 "display_name": m.display_name, "text": m.text,
                 "day_number": m.day_number, "ts": m.ts,
                 "kind": m.kind, "payload": m.payload}
                for m in s.chat_messages
            ],
        }
        if me:
            role_def = ROLES.get(me.role) if me.role else None
            no_target_actions = ()  # SHOOT needs a target; all new roles either need one or are skip-only
            view["me"] = {
                "player_id": me.player_id,
                "role": me.role.value if me.role else None,
                "faction": role_def.faction.value if role_def else None,
                "role_description": role_def.description if role_def else None,
                "alive": me.alive,
                "can_chat": me.alive and not me.silenced and s.phase == Phase.DAY_DISCUSSION,
                "can_vote": me.alive and not me.silenced and s.phase == Phase.VOTING,
                "can_confirm": me.alive and not me.silenced and s.phase == Phase.LYNCH_CONFIRMATION,
                "allow_self_vote": s.settings.allow_self_vote,
                "has_submitted_night_action": player_id in s.night_actions,
                "has_voted": player_id in s.votes,
                "vote_weight": me.vote_weight,
                "night_result": self._night_results.get(player_id),
                # Full narrative history for this player (Doctor saves,
                # Mistress blocks, Commissioner reads, Sergeant promotion,
                # Suicide's win, ...) — see app/game_engine/night_messages.py.
                # Never trimmed, so the client keys off list length/index to
                # know which lines are new.
                "outcome_messages": s.outcome_messages.get(player_id, []),
                "night_action_type": (
                    None if (me.role in MAFIA_KILLING_ROLES and player_id != self._current_mafia_killer())
                    else role_def.night_action.value if role_def and role_def.night_action
                    else None
                ),
                "is_mafia_killer": bool(
                    me.role in MAFIA_KILLING_ROLES and player_id == self._current_mafia_killer()
                ),
                "night_action_needs_target": bool(
                    (me.role not in MAFIA_KILLING_ROLES or player_id == self._current_mafia_killer())
                    and role_def and role_def.night_action
                    and role_def.night_action not in no_target_actions
                ),
                "night_action_can_skip_target": bool(
                    me.role in MAFIA_KILLING_ROLES and me.role != RoleName.MANIAC
                    and player_id == self._current_mafia_killer()
                ),
                "can_target_self": bool(role_def and role_def.can_target_self
                    and not (me.role == RoleName.DOCTOR and me.last_self_heal_night is not None)),
                "max_charges": role_def.max_charges if role_def else None,
                "charges_used": None,
                "ready_for_vote": me.ready_for_vote,
                "last_words": me.last_words,
                "can_last_words": bool(
                    not me.alive and me.last_words is None
                    and (
                        (s.phase == Phase.VOTE_RESULTS
                         and bool(s.last_vote_result and s.last_vote_result.get("eliminated") == player_id))
                        or (s.phase == Phase.DAY_DISCUSSION and me.death_night == s.night_number)
                    )
                ),
                # Commissioner's one-shot kill UI flag.
                "commissioner_can_shoot": bool(
                    me.role == RoleName.COMMISSIONER and me.commissioner_kills_used < 1
                ),
                # Lynch-confirmation ballot: whether this player has already
                # voted YES/NO this round (survives a reconnect/re-render).
                "has_lynch_confirmed": player_id in s._confirm_voters,
                # Kamikaze strike UI flags: whether this (dead) player is the
                # struck Kamikaze and, if so, whether their pick is already in.
                "kamikaze_striker": bool(
                    s.phase == Phase.KAMIKAZE_STRIKE
                    and me.role == RoleName.KAMIKAZE
                    and self._lynch_target == player_id
                ),
                "has_submitted_kamikaze": any(
                    na.player_id == player_id and na.role == RoleName.KAMIKAZE
                    for na in s.night_actions.values()
                ),
                # Lucky survival shown after night.
                "lucky_survived": me.lucky_survived_lethal if me.role == RoleName.LUCKY else None,
                # Sergeant promotion flag.
                "promoted": me.promoted,
            }
            if me.role and ROLES[me.role].faction == Faction.MAFIA:
                view["me"]["mafia_teammates"] = RoleManager.mafia_teammates(s, player_id)
                view["me"]["can_mafia_chat"] = (
                    me.alive and s.phase not in (Phase.LOBBY, Phase.ROLE_ASSIGNMENT, Phase.GAME_OVER)
                )
                view["mafia_chat"] = [
                    {"message_id": m.message_id, "player_id": m.player_id,
                     "display_name": m.display_name, "text": m.text,
                     "day_number": m.day_number, "ts": m.ts,
                     "kind": m.kind, "payload": m.payload}
                    for m in s.mafia_chat_messages
                ]
            if game_over:
                view["me"]["stats"] = {
                    "role": me.role.value if me.role else None,
                    "won": bool(s.winner and (player_id in s.winner.winners
                                               or player_id in s.winner.individual_winners)),
                    "survived": me.alive,
                    "death_night": me.death_night,
                    "kills": me.kills,
                    "investigations": me.investigations,
                    "protections": me.protections,
                    "votes_cast": me.votes_cast,
                }
        if player_id == s.host_id:
            timed_phases = (Phase.NIGHT, Phase.DAY_DISCUSSION, Phase.VOTING, Phase.VOTE_RESULTS,
                            Phase.MORNING, Phase.LYNCH_CONFIRMATION, Phase.KAMIKAZE_STRIKE)
            view["admin"] = {
                "settings": {
                    "night_duration_s": s.settings.night_duration_s,
                    "day_duration_s": s.settings.day_duration_s,
                    "voting_duration_s": s.settings.voting_duration_s,
                    "tie_rule": s.settings.tie_rule,
                    "anonymous_voting": s.settings.anonymous_voting,
                    "allow_self_vote": s.settings.allow_self_vote,
                    "reveal_role_on_death": s.settings.reveal_role_on_death,
                },
                "night_actions_submitted": len(s.night_actions) if s.phase == Phase.NIGHT else None,
                "night_actions_expected": self._eligible_night_actions() if s.phase == Phase.NIGHT else None,
                "votes_cast": len(s.votes) if s.phase == Phase.VOTING else None,
                "votes_expected": len(s.alive_players()) if s.phase == Phase.VOTING else None,
                "can_force_advance": s.phase in timed_phases,
                "can_extend_timer": s.phase in timed_phases,
            }
            if s.phase == Phase.LOBBY and MIN_PLAYERS <= len(s.players) <= MAX_PLAYERS:
                union = all_possible_roles(len(s.players))
                pools = list(COMPOSITIONS.get(len(s.players), {}).values())
                view["admin"]["available_roles"] = [r.value for r in union]
                view["admin"]["role_variants"] = [
                    {
                        "key": label,
                        "roles": {r.value: pool.count(r) for r in pool},
                    }
                    for label, pool in COMPOSITIONS.get(len(s.players), {}).items()
                ]
                view["admin"]["role_picks"] = {
                    pid: (pl.bot_role_pick or {})
                    for pid, pl in s.players.items()
                    if pl.is_bot or pid == player_id
                }
                # The variant is picked only at start, so the lobby can't know
                # the exact lineup yet. Mirror set_bot_role's rule instead:
                # the max copies a role can hold across the count's variants,
                # so the frontend can still grey out fully-claimed roles.
                view["admin"]["role_count"] = {
                    r.value: max((pool.count(r) for pool in pools), default=0)
                    for r in union
                }
        return view

    def find_player_id(self, telegram_user_id: int) -> Optional[str]:
        for pid, p in self.state.players.items():
            if p.telegram_user_id == telegram_user_id:
                return pid
        return None

    # ----------------------------------------------------------------
    # helpers
    # ----------------------------------------------------------------

    def _require_host(self, player_id: str) -> PlayerState:
        if player_id != self.state.host_id:
            raise EngineError("Only the host can do that")
        return self.state.players[player_id]

    def _require_host_or_system(self, actor_id: Optional[str]) -> None:
        if actor_id is not None and actor_id != self.state.host_id:
            raise EngineError("Only the host can do that")

    def _require_alive(self, player_id: str) -> PlayerState:
        p = self.state.players.get(player_id)
        if not p:
            raise EngineError("Unknown player")
        if not p.alive:
            raise EngineError("You are no longer alive")
        return p
