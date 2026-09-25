"""
GameEngine's internal managers. Each class has one job and is fully
unit-testable without any WebSocket/Telegram/HTTP layer involved.

This is the True Mafia 13-role edition: the shared Mafia night kill, the
Commissioner's check/kill, Doctor protection, Mistress blocking, Lawyers
shielding a client from a Commissioner read, the Maniac's independent kill,
the Lucky's survival luck, and the Vagabond's watcher report all resolve in
one deterministic order with a single authority (the server).
"""
from __future__ import annotations
import random
import uuid
from time import time
from typing import Optional
from collections import Counter, defaultdict

from app.game_engine.roles import RoleName, Faction, ActionType, ROLES, MAFIA_KILLING_ROLES
from app.game_engine.compositions import select_composition
from app.game_engine.state import (
    GameState, PlayerState, Phase, NightAction, Vote, WinResult, EngineError, ChatMessage,
)

# Death reason fragments -> the killer's ROLE/team label shown in the public
# chat announcement. These are role / faction labels — never player
# identities — so a death message never leaks WHO performed it, only what
# class of action it was. "mafia" maps to the faction because the whole team
# owns the kill.
DEATH_KILLER_LABELS: dict[str, str] = {
    "mafia": "Mafia",
    "maniac": "Maniac",
    "commissioner": "Commissioner",
    "day_vote": "town_vote",
    "kamikaze": "Kamikaze",
    "removed_by_admin": "Admin",
}


def death_killer_label(reason: str) -> Optional[str]:
    """First '/'-separated fragment wins; simultaneous sources ("mafia/
    maniac") read as a single combined line by the client anyway, so
    returning the first label is exactly the information the announce line
    needs. Unknown reasons return None -> the client falls back to its own
    deathReasonUz()."""
    first = str(reason).split("/")[0]
    return DEATH_KILLER_LABELS.get(first)


def death_announcement(state: GameState, victim_id: str, reason: str) -> ChatMessage:
    """Public "who died" chat entry (spec: stands out, killer role + victim
    role). Respects reveal_role_on_death: the victim's exact role is only
    included when the shared reveal setting allows it, matching the
    players[] reveal rule."""
    p = state.players[victim_id]
    return ChatMessage(
        message_id=f"death-{uuid.uuid4()}",
        player_id=victim_id,
        display_name=p.display_name,
        text="",
        day_number=state.day_number,
        kind="death",
        payload={
            "victim": victim_id,
            "reason": reason,
            "killer_role": death_killer_label(reason),
            "victim_role": (p.role.value if p.role and state.settings.reveal_role_on_death else None),
        },
    )


def last_words_announcement(state: GameState, player_id: str, text: str) -> ChatMessage:
    """A dead player's final message, mirrored into the public chat so it
    shows (and stands out) in the messages window."""
    p = state.players[player_id]
    return ChatMessage(
        message_id=f"lastwords-{uuid.uuid4()}",
        player_id=player_id,
        display_name=p.display_name,
        text=text,
        day_number=state.day_number,
        kind="last_words",
        payload={"victim": player_id},
    )


class TimerManager:
    """Server-authoritative phase timing. Frontend only renders a countdown
    from phase_start/phase_end that this class sets — it never owns time."""

    @staticmethod
    def start_phase(state: GameState, duration_s: int) -> None:
        now = time()
        state.phase_start = now
        state.phase_end = now + duration_s

    @staticmethod
    def remaining_seconds(state: GameState) -> float:
        return max(0.0, state.phase_end - time())

    @staticmethod
    def is_expired(state: GameState) -> bool:
        return time() >= state.phase_end


class EventManager:
    @staticmethod
    def log(state: GameState, event_type: str, **payload) -> None:
        state.log(event_type, **payload)


class ActivityFeedManager:
    """The anonymous, phase-scoped "what's happening" feed — separate from
    EventManager.log's internal trace. Every entry carries an i18n message_key
    and an explicit visibility; nothing about *who* did something or *who it
    was done to* is ever accepted as a parameter, so there is no path that
    could leak an identity even by mistake."""

    @staticmethod
    def _phase_number(state: GameState) -> int:
        if state.phase in (Phase.NIGHT, Phase.MORNING):
            return state.night_number
        # DAY_DISCUSSION, VOTING, LYNCH_CONFIRMATION, KAMIKAZE_STRIKE and
        # VOTE_RESULTS all share one human-facing "Day N".
        return state.day_number

    @staticmethod
    def public(state: GameState, message_key: str, **extra) -> None:
        ActivityFeedManager._append(state, message_key, "all", extra)

    @staticmethod
    def _append(state: GameState, message_key: str, visible_to, extra: dict) -> None:
        state._activity_seq += 1
        state.activity_feed.append({
            "seq": state._activity_seq,
            "phase": state.phase.value,
            "phase_number": ActivityFeedManager._phase_number(state),
            "message_key": message_key,
            "visible_to": visible_to,
            **extra,
        })

    @staticmethod
    def for_player(state: GameState, player_id: Optional[str]) -> list[dict]:
        out = []
        for entry in state.activity_feed:
            vis = entry["visible_to"]
            if vis == "all" or (player_id is not None and player_id in vis):
                out.append({k: v for k, v in entry.items() if k != "visible_to"})
        return out


class RoleManager:
    @staticmethod
    def assign_roles(state: GameState, rng: Optional[random.Random] = None) -> None:
        rng = rng or random.Random()
        player_ids = list(state.players.keys())
        n = len(player_ids)
        if not (4 <= n <= 20):
            raise ValueError("Mafia requires 4–20 players to start")
        # NVariant-selection is PURE INDEPENDENT RANDOM and server-side secure
        # (secrets, not the game rng): no history, no anti-repeat, no rotation.
        school = select_composition(n, random.SystemRandom())
        state.selected_variant = school[0]
        pool = school[1]
        state.roles = [r.value for r in pool]
        for pid in player_ids:
            pick = state.players[pid].bot_role_pick
            if not pick:
                continue
            try:
                role = RoleName(pick)
            except ValueError:
                continue
            state.players[pid].bot_role_pick = None
            if role in pool:
                state.players[pid].role = role
                pool.remove(role)
        remaining = [pid for pid in player_ids if state.players[pid].role is None]
        rng.shuffle(pool)
        rng.shuffle(remaining)
        for pid, role in zip(remaining, pool):
            state.players[pid].role = role
        for p in state.players.values():
            p.vote_weight = 1
        EventManager.log(state, "roles_assigned", count=n)

    @staticmethod
    def mafia_teammates(state: GameState, player_id: str) -> list[str]:
        p = state.players[player_id]
        if p.role is None or ROLES[p.role].faction != Faction.MAFIA:
            return []
        return [pid for pid, o in state.players.items()
                if pid != player_id and o.role and ROLES[o.role].faction == Faction.MAFIA]

    @staticmethod
    def promote_sergeant(state: GameState, dead_commissioner_id: str) -> Optional[str]:
        """If the Commissioner dies, the first living Sergeant is promoted to
        Commissioner (True Mafia rule). Returns the promoted player_id, or
        None if there is no living Sergeant. The newly-promoted player's role
        is flipped server-side; their vote_weight and alive status are
        untouched."""
        for pid, p in state.players.items():
            if p.player_id != dead_commissioner_id and p.alive and p.role == RoleName.SERGEANT:
                p.role = RoleName.COMMISSIONER
                p.promoted = True
                EventManager.log(state, "player_promoted", player_id=pid, to="commissioner")
                state.outcome_messages.setdefault(pid, []).append(
                    "\U0001F396\uFE0F Afsuski, Komissar xizmat burchini bajarishda halok "
                    "bo'ldi. Shahar xavfsizligi endi sizning qo'lingizda. Siz yangi "
                    "Komissar bo'ldingiz!")
                return pid
        return None

    @staticmethod
    def current_don(state: GameState) -> Optional[str]:
        """The single living Don — used for the shared Mafia kill tie-break
        and for the 'who knows the team' display. If the Don is dead the
        first living Mafia member is treated as the effective Don."""
        for pid, p in state.players.items():
            if p.alive and p.role == RoleName.DON:
                return pid
        for pid, p in state.players.items():
            if p.alive and p.role == RoleName.MAFIA:
                return pid
        return None

    @staticmethod
    def promote_new_don(state: GameState) -> Optional[str]:
        """When the Don dies (or a promoted Don dies), promote the first
        living Mafia member to Don so the family always has a leader."""
        for pid, p in state.players.items():
            if p.alive and p.role == RoleName.MAFIA:
                p.role = RoleName.DON
                p.promoted = True
                EventManager.log(state, "player_promoted", player_id=pid, to="don")
                return pid
        return None


# Fixed duration for ROLE_ASSIGNMENT (spec item 5).
ROLE_ASSIGNMENT_DURATION_S = 15
# A short cinematic window for the morning report before the day's discussion.
MORNING_DURATION_S = 8
# A short window for the YES/NO lynch confirmation vote.
LYNCH_CONFIRMATION_DURATION_S = 15
# A short window for the Kamikaze to choose who they take with them.
KAMIKAZE_STRIKE_DURATION_S = 15


class PhaseManager:
    @staticmethod
    def to_role_assignment(state: GameState) -> None:
        state.phase = Phase.ROLE_ASSIGNMENT
        TimerManager.start_phase(state, ROLE_ASSIGNMENT_DURATION_S)
        EventManager.log(state, "phase_role_assignment")

    @staticmethod
    def to_night(state: GameState) -> None:
        state.phase = Phase.NIGHT
        state.night_number += 1
        state.night_actions.clear()
        for p in state.players.values():
            p.silenced = False
            p.blocked = False
            p.protected = False
            p.protected_by_bodyguard = None
            p.lucky_survived_lethal = False
            p.lawyer_client = None
            p.kamikaze_target = None
        TimerManager.start_phase(state, state.settings.night_duration_s)
        EventManager.log(state, "phase_night", night=state.night_number)
        ActivityFeedManager.public(state, "night.begins", night=state.night_number)

    @staticmethod
    def to_morning(state: GameState) -> None:
        """Short morning-report phase right after the night resolves: the
        frontend shows "nobody died" or "Player X was found dead" here before
        discussion opens."""
        state.phase = Phase.MORNING
        TimerManager.start_phase(state, MORNING_DURATION_S)
        EventManager.log(state, "phase_morning", night=state.night_number)
        ActivityFeedManager.public(state, "morning.begins", night=state.night_number)

    @staticmethod
    def to_day(state: GameState) -> None:
        state.phase = Phase.DAY_DISCUSSION
        state.day_number += 1
        for p in state.players.values():
            p.ready_for_vote = False
        TimerManager.start_phase(state, state.settings.day_duration_s)
        EventManager.log(state, "phase_day", day=state.day_number)
        ActivityFeedManager.public(state, "day.begins", day=state.day_number)

    @staticmethod
    def to_voting(state: GameState) -> None:
        state.phase = Phase.VOTING
        state.votes.clear()
        state.revote_round = 0
        state.revote_candidates = None
        TimerManager.start_phase(state, state.settings.voting_duration_s)
        EventManager.log(state, "phase_voting")
        ActivityFeedManager.public(state, "voting.begins", day=state.day_number)

    @staticmethod
    def to_lynch_confirmation(state: GameState, candidates: list[str]) -> None:
        """After the vote tally picks an eventual victim, everyone alive
        votes YES/NO to actually carry out the lynch (spec: lynch
        confirmation). The ballot is a YES/NO choice, not a player pick."""
        state.phase = Phase.LYNCH_CONFIRMATION
        state.revote_candidates = sorted(candidates)
        state.votes.clear()
        state._confirm_yes = 0
        state._confirm_no = 0
        state._confirm_voters.clear()  # a fresh ballot each time: never carry votes over
        TimerManager.start_phase(state, LYNCH_CONFIRMATION_DURATION_S)
        EventManager.log(state, "phase_lynch_confirmation", candidates=state.revote_candidates)
        ActivityFeedManager.public(state, "lynch.confirmation_begins", day=state.day_number)

    @staticmethod
    def to_kamikaze_strike(state: GameState) -> None:
        """The Kamikaze has been lynched; they now get one short window to
        choose a living player to take with them."""
        state.phase = Phase.KAMIKAZE_STRIKE
        TimerManager.start_phase(state, KAMIKAZE_STRIKE_DURATION_S)
        EventManager.log(state, "phase_kamikaze_strike")
        ActivityFeedManager.public(state, "kamikaze.strike_begins", day=state.day_number)

    @staticmethod
    def to_vote_results(state: GameState) -> None:
        state.phase = Phase.VOTE_RESULTS
        # gives the just-eliminated player a window to type last words
        TimerManager.start_phase(state, 60)
        ActivityFeedManager.public(state, "voting.resolved", day=state.day_number)

    @staticmethod
    def to_game_over(state: GameState, result: WinResult) -> None:
        state.phase = Phase.GAME_OVER
        state.winner = result
        EventManager.log(state, "game_over", faction=result.faction, reason=result.reason)


class NightResolver:
    """Resolves an entire night in an explicit deterministic order so effect
    ordering is never dependent on submission order:

      1. Block resolution   (Mistress) — a blocked actor's action is skipped
      1.5. Lawyer shield    (Lawyer's own client choice, sets lawyer_client)
      2. Protection         (Doctor)
      3. Kill attacks       (Mafia team, Maniac, Commissioner's shot)
      4. Survival checks    (Doctor protection, Lucky luck)
      5. Investigations     (Commissioner check, Lawyer-modified)
      6. Watcher reports    (Vagabond)
    """

    # Lucky survives a lethal attack with this probability when attacked.
    LUCKY_SURVIVE_CHANCE = 0.5

    @staticmethod
    def resolve(state: GameState, rng: Optional[random.Random] = None) -> list[dict]:
        rng = rng or random.Random()
        actions = list(state.night_actions.values())
        deaths: dict[str, str] = {}          # player_id -> reason
        results: dict[str, dict] = {}        # player_id -> private result payload
        visits: dict[str, list[str]] = defaultdict(list)   # target_id -> [visitor_id]

        for a in actions:
            if a.target_id:
                visits[a.target_id].append(a.player_id)

        # --- Phase 1: block resolution ---
        blocked: set[str] = set()
        for a in actions:
            if a.action_type == ActionType.BLOCK and a.target_id:
                blocked.add(a.target_id)
                state.players[a.target_id].blocked = True

        effective = [a for a in actions if a.player_id not in blocked]
        state._night_action_log = [{"player_id": a.player_id, "role": a.role.value,
                                    "action_type": a.action_type.value, "target_id": a.target_id,
                                    "blocked": a.player_id in blocked}
                                   for a in actions]

        # --- Phase 1.5: lawyer shield ---
        # The Lawyer picks their own client now (used to be a random
        # server-side assignment at night start) — same blocking rules as
        # any other role: a Mistress-blocked Lawyer shields no one tonight.
        for a in effective:
            if a.action_type == ActionType.SHIELD and a.target_id:
                state.players[a.player_id].lawyer_client = a.target_id

        # --- Phase 2: protection ---
        for a in effective:
            if a.action_type == ActionType.PROTECT and a.target_id:
                if a.player_id == a.target_id:
                    doc = state.players[a.player_id]
                    if doc.last_self_heal_night is not None:
                        continue  # Doctor can self-heal only once per game
                    doc.last_self_heal_night = state.night_number
                state.players[a.target_id].protected = True
                state.players[a.target_id].protected_by_bodyguard = a.player_id

        # --- Phase 3: kill attacks ---
        pending_kills: dict[str, list[str]] = defaultdict(list)  # target -> [attacker labels]

        mafia_votes = [a for a in effective
                       if a.action_type == ActionType.KILL and a.role in MAFIA_KILLING_ROLES]
        if mafia_votes:
            target = NightResolver._resolve_mafia_target(state, mafia_votes, rng)
            if target:
                pending_kills[target].append("mafia")

        for a in effective:
            if a.action_type == ActionType.KILL and a.role == RoleName.MANIAC and a.target_id:
                pending_kills[a.target_id].append("maniac")

        for a in effective:
            if a.action_type == ActionType.SHOOT and a.target_id:
                pending_kills[a.target_id].append("commissioner")

        # Snapshot who-attacked-whom before Phase 4 consumes it into deaths —
        # night_messages.build_night_outcome_messages needs this even for
        # attacks that end up failing (Doctor/Lucky save), which leave no
        # other trace once this method returns.
        state._night_attack_targets = {tid: list(a) for tid, a in pending_kills.items()}

        # --- Phase 4: survival / protection / luck ---
        for target_id, attackers in pending_kills.items():
            target = state.players[target_id]
            if not target.alive:
                continue
            if target.protected:
                results.setdefault(target_id, {})["saved_by"] = "doctor"
                continue
            if target.role == RoleName.LUCKY and rng.random() < NightResolver.LUCKY_SURVIVE_CHANCE:
                target.lucky_survived_lethal = True
                results.setdefault(target_id, {})["saved_by"] = "luck"
                continue
            deaths[target_id] = "/".join(sorted(set(attackers)))

        for pid, reason in deaths.items():
            p = state.players[pid]
            if p.alive:
                p.alive = False
                p.death_reason = reason
                p.death_night = state.night_number

        # --- Phase 5: investigations (after deaths, so results are final) ---
        for a in effective:
            if a.action_type != ActionType.INVESTIGATE or not a.target_id:
                continue
            target = state.players[a.target_id]
            lawyer_source = NightResolver._lawyer_protecting(state, a.target_id)
            if lawyer_source is not None:
                # The Lawyer shields the client: regardless of the target's
                # real role, the read comes back as a Citizen.
                results.setdefault(a.player_id, {})["verdict"] = "not_mafia"
                results[a.player_id]["lawyer_modifier"] = True
                state.mafia_chat_messages.append(ChatMessage(
                    message_id=f"mafia-lawyer-{uuid.uuid4()}",
                    player_id=lawyer_source,
                    display_name=state.players[lawyer_source].display_name,
                    text="",
                    day_number=state.day_number,
                    kind="lawyer_result",
                    payload={"client": a.target_id},
                ))
            elif ROLES[target.role].faction == Faction.MAFIA:
                results.setdefault(a.player_id, {})["verdict"] = "mafia"
            else:
                results.setdefault(a.player_id, {})["verdict"] = "not_mafia"

        # --- Phase 6: watcher reports (Vagabond) ---
        for a in effective:
            if a.action_type == ActionType.WATCH and a.target_id:
                watched = state.players[a.target_id]
                visitors = [v for v in visits.get(a.target_id, []) if v != a.player_id]
                results.setdefault(a.player_id, {})["visitors"] = visitors

        state.last_night_deaths = [
            {"player_id": pid, "reason": reason} for pid, reason in deaths.items()
        ]
        for pid, reason in deaths.items():
            state.chat_messages.append(death_announcement(state, pid, reason))
        EventManager.log(state, "night_resolved", deaths=list(deaths.keys()))
        ActivityFeedManager.public(state, "night.resolved", night=state.night_number)
        return state.last_night_deaths, results

    @staticmethod
    def _lawyer_protecting(state: GameState, target_id: str) -> Optional[str]:
        """Returns the player_id of a living Lawyer whose per-night client
        matches `target_id`, or None. lawyer_client is set once per night,
        in Phase 1.5 above, from the Lawyer's own SHIELD submission — a
        Mistress-blocked Lawyer never reaches that phase, so their client
        stays None (reset every night in PhaseManager.to_night) and this
        naturally returns None for them without any extra check here."""
        for pid, p in state.players.items():
            if p.alive and p.role == RoleName.LAWYER and p.lawyer_client == target_id:
                return pid
        return None

    @staticmethod
    def _resolve_mafia_target(state: GameState, mafia_votes: list[NightAction],
                               rng: Optional[random.Random] = None) -> Optional[str]:
        targets = [a.target_id for a in mafia_votes if a.target_id]
        if not targets:
            return None
        counts = Counter(targets)
        top = max(counts.values())
        tied = [t for t, c in counts.items() if c == top]
        if len(tied) == 1:
            return tied[0]
        don = RoleManager.current_don(state)
        don_vote = next((a for a in mafia_votes if a.player_id == don and a.target_id in tied), None)
        if don_vote:
            return don_vote.target_id
        rng = rng or random.Random()
        return rng.choice(sorted(tied))


class VoteManager:
    @staticmethod
    def submit_vote(state: GameState, voter_id: str, target_id: Optional[str]) -> None:
        if voter_id not in state.players:
            raise EngineError("Unknown player")
        voter = state.players[voter_id]
        if not voter.alive:
            raise EngineError("Dead players cannot vote")
        if state.phase != Phase.VOTING:
            raise EngineError("Voting is not open")
        if target_id is not None and target_id not in state.players:
            raise EngineError("Invalid target")
        if target_id and not state.players[target_id].alive:
            raise EngineError("Cannot vote for a dead player")
        if state.revote_candidates is not None and target_id is not None \
                and target_id not in state.revote_candidates:
            raise EngineError("You may only vote for one of the tied candidates in this revote")
        if target_id == voter_id and not state.settings.allow_self_vote:
            raise EngineError("Self-voting is disabled")
        if getattr(voter, "silenced", False):
            raise EngineError("You are silenced today and cannot vote")
        state.votes[voter_id] = Vote(voter_id=voter_id, target_id=target_id, weight=voter.vote_weight)

    @staticmethod
    def tally(state: GameState) -> dict:
        totals: dict[str, int] = defaultdict(int)
        for v in state.votes.values():
            if v.target_id:
                totals[v.target_id] += v.weight
        if not totals:
            result = {"eliminated": None, "totals": {}, "reason": "no_votes", "revote": False}
            state.last_vote_result = result
            return result
        top = max(totals.values())
        leaders = sorted(pid for pid, c in totals.items() if c == top)
        if len(leaders) == 1:
            result = {"eliminated": leaders[0], "totals": dict(totals), "reason": "majority", "revote": False}
            state.last_vote_result = result
            return result
        if state.settings.tie_rule == "random":
            eliminated = random.choice(leaders)
            result = {"eliminated": eliminated, "totals": dict(totals), "reason": "tie_random", "revote": False}
            state.last_vote_result = result
            return result
        if state.settings.tie_rule == "revote" and state.revote_round == 0:
            result = {"eliminated": None, "totals": dict(totals), "reason": "tie_revote",
                      "revote": True, "candidates": leaders}
            state.last_vote_result = result
            return result
        result = {"eliminated": None, "totals": dict(totals), "reason": "tie_no_elimination", "revote": False}
        state.last_vote_result = result
        return result

    @staticmethod
    def submit_lynch_confirm(state: GameState, player_id: str, yes: bool) -> None:
        """The YES/NO lynch-confirmation ballot (spec: lynch confirmation).
        Each alive player votes once. The tally is simply approval totals."""
        if state.phase != Phase.LYNCH_CONFIRMATION:
            raise EngineError("Lynch confirmation is not open")
        voter = state.players.get(player_id)
        if not voter:
            raise EngineError("Unknown player")
        if not voter.alive:
            raise EngineError("Dead players cannot vote")
        if player_id in state._confirm_voters:
            raise EngineError("You already voted in this confirmation")
        if voter.silenced:
            raise EngineError("You are silenced today and cannot vote")
        state._confirm_voters.add(player_id)
        if yes:
            state._confirm_yes += voter.vote_weight
        else:
            state._confirm_no += voter.vote_weight
        state.votes[player_id] = Vote(voter_id=player_id, target_id=None, weight=0)

    @staticmethod
    def lynch_confirmation_total(state: GameState) -> dict:
        yes = getattr(state, "_confirm_yes", 0)
        no = getattr(state, "_confirm_no", 0)
        return {"yes": yes, "no": no, "approved": yes > no}


class DeathManager:
    @staticmethod
    def eliminate(state: GameState, player_id: str, reason: str) -> None:
        p = state.players[player_id]
        if not p.alive:
            return
        p.alive = False
        p.death_reason = reason
        if p.role == RoleName.SUICIDE and reason == "day_vote":
            p.suicide_lynched = True
            state.outcome_messages.setdefault(player_id, []).append(
                "\U0001F3C6 Tabriklaymiz! Siz o'z maqsadingizga erishdingiz \u2014 shahar "
                "sizni osib o'ldirdi. Siz yagona g'olibsiz!")
        EventManager.log(state, "player_eliminated", player_id=player_id, reason=reason)
        if reason in ("mafia", "maniac", "commissioner"):
            killed_by = "mafia" if reason == "mafia" else reason
        # Promotion on death-by-day-vote, Kamikaze strike, or admin removal.
        # Night deaths take a separate path (NightResolver marks them dead
        # directly, without going through eliminate()) and already call
        # these same two methods from engine.py's resolve_night_if_ready —
        # this covers every death that reaches the engine through here,
        # which used to fall through this comment doing nothing.
        if p.role == RoleName.COMMISSIONER:
            RoleManager.promote_sergeant(state, player_id)
        elif p.role == RoleName.DON:
            RoleManager.promote_new_don(state)

    @staticmethod
    def apply_night_deaths(state: GameState, deaths: dict[str, str]) -> None:
        """Finalize a night's deaths (already marked dead by NightResolver, but
        this centralizes the bookkeeping/announcement in one place)."""
        for pid, reason in deaths.items():
            p = state.players[pid]
            if p.alive:
                p.alive = False
                p.death_reason = reason
                p.death_night = state.night_number
                EventManager.log(state, "player_eliminated", player_id=pid, reason=reason)


class WinConditionManager:
    @staticmethod
    def _individual_winners(state: GameState, main_winners: list[str],
                            exclude: frozenset[str] = frozenset()) -> list[str]:
        """Survivor-style individuals: the Suicide won if lynched by the day
        vote; a neutral survivor (Mistress / Vagabond / Lawyer) who is still
        alive at game end rides along as an individual winner. Never includes
        anyone already counted in the main winners."""
        winners = []
        for p in state.players.values():
            if p.player_id in exclude or p.player_id in main_winners:
                continue
            if p.role == RoleName.SUICIDE and p.suicide_lynched:
                winners.append(p.player_id)
            elif p.role in (RoleName.MISTRESS, RoleName.VAGABOND) and p.alive:
                winners.append(p.player_id)
        return winners

    @staticmethod
    def check(state: GameState) -> Optional[WinResult]:
        alive = state.alive_players()
        mafia = [p for p in alive if p.role and ROLES[p.role].faction == Faction.MAFIA]
        town = [p for p in alive if p.role and ROLES[p.role].faction == Faction.TOWN]
        maniac = [p for p in alive if p.role == RoleName.MANIAC]

        # Neutral lone survival (a lone Maniac, or a lone neutral survivor).
        if len(alive) <= 1:
            if alive and alive[0].role == RoleName.MANIAC:
                return WinResult(Faction.NEUTRAL, [alive[0].player_id],
                                 "Maniac is the last one standing",
                                 WinConditionManager._individual_winners(state, [alive[0].player_id]))
            if alive:
                sole = alive[0]
                if ROLES[sole.role].faction == Faction.MAFIA:
                    return WinResult(Faction.MAFIA, [sole.player_id], "The last player alive is Mafia",
                                     WinConditionManager._individual_winners(state, [sole.player_id]))
                if ROLES[sole.role].faction == Faction.TOWN:
                    winners = [sole.player_id]
                    return WinResult(Faction.TOWN, winners, "The last player alive is Town",
                                     WinConditionManager._individual_winners(state, winners))
                return WinResult(Faction.NEUTRAL, [sole.player_id], "The last one standing wins",
                                 WinConditionManager._individual_winners(state, [sole.player_id]))

        # Maniac's own win: no Mafia remain AND the Maniac is alive. True Mafia
        # gives the Maniac an independent shot at winning once the family is
        # gone; he still has to outlast / out-kill the town.
        if not mafia and maniac:
            if len(maniac) >= len(alive) - len(maniac):
                winners = [p.player_id for p in maniac]
                return WinResult(Faction.NEUTRAL, winners, "Maniac remains and the Mafia are gone",
                                 WinConditionManager._individual_winners(state, winners))

        if not mafia and not maniac:
            winners = [p.player_id for p in town]
            return WinResult(Faction.TOWN, winners, "All Mafia and the Maniac eliminated",
                             WinConditionManager._individual_winners(state, winners))

        if mafia and len(mafia) >= len(alive) - len(mafia):
            winners = [p.player_id for p in mafia]
            return WinResult(Faction.MAFIA, winners, "Mafia can no longer be outvoted",
                             WinConditionManager._individual_winners(state, winners))

        return None
