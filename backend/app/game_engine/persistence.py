"""Round-trips a GameState to/from a plain, JSON-safe dict.

This exists solely for crash recovery (spec item 3: "LIVE GAME STATE
PERSISTENCE") — app/services/checkpoint_service.py stores the dict this
module produces, and rebuilds a GameState from it on startup via
GameEngine.from_state(). It is deliberately NOT a generic serializer: it
knows exactly which fields are enums (RoleName, ActionType, Faction, Phase)
and converts only those; everything else is copied as-is because it's
already a JSON-safe primitive, list, or dict.

The event log (GameState.events) is intentionally left out of the
checkpoint blob — the append-only `game_events` DB table is already the
durable copy of that, and re-embedding it here would just make every
checkpoint grow for the life of the match.
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Optional

from app.game_engine.roles import RoleName, ActionType, Faction
from app.game_engine.state import (
    GameState, GameSettings, PlayerState, ChatMessage, NightAction, Vote,
    WinResult, Phase,
)


def state_to_dict(state: GameState) -> dict:
    return {
        "game_id": state.game_id,
        "group_start_announced": state.group_start_announced,
        "group_end_announced": state.group_end_announced,
        "chat_id": state.chat_id,
        "host_id": state.host_id,
        "phase": state.phase.value,
        "night_number": state.night_number,
        "day_number": state.day_number,
        "phase_start": state.phase_start,
        "phase_end": state.phase_end,
        "settings": asdict(state.settings),
        "players": {pid: _player_to_dict(p) for pid, p in state.players.items()},
        "night_actions": {pid: _night_action_to_dict(a) for pid, a in state.night_actions.items()},
        "votes": {pid: asdict(v) for pid, v in state.votes.items()},
        "revote_round": state.revote_round,
        "revote_candidates": state.revote_candidates,
        "winner": _winner_to_dict(state.winner) if state.winner else None,
        "last_night_deaths": state.last_night_deaths,
        "last_vote_result": state.last_vote_result,
        "chat_messages": [asdict(m) for m in state.chat_messages],
        "mafia_chat_messages": [asdict(m) for m in state.mafia_chat_messages],
        "confirm_yes": state._confirm_yes,
        "confirm_no": state._confirm_no,
        "confirm_voters": sorted(state._confirm_voters),
        "night_action_log": state._night_action_log,
        "night_attack_targets": state._night_attack_targets,
        "outcome_messages": state.outcome_messages,
    }


def _player_to_dict(p: PlayerState) -> dict:
    d = asdict(p)
    d["role"] = p.role.value if p.role else None
    return d


def _night_action_to_dict(a: NightAction) -> dict:
    return {
        "player_id": a.player_id,
        "role": a.role.value,
        "action_type": a.action_type.value,
        "target_id": a.target_id,
        "submitted_at": a.submitted_at,
    }


def _winner_to_dict(w: WinResult) -> dict:
    return {
        "faction": w.faction.value if w.faction else None,
        "winners": w.winners,
        "reason": w.reason,
        "individual_winners": w.individual_winners,
    }


def state_from_dict(data: dict) -> GameState:
    settings = GameSettings(**data["settings"])
    state = GameState(
        game_id=data["game_id"], chat_id=data.get("chat_id"), host_id=data["host_id"],
        settings=settings,
    )
    state.phase = Phase(data["phase"])
    state.group_start_announced = data.get("group_start_announced", state.phase != Phase.LOBBY)
    state.group_end_announced = data.get("group_end_announced", False)
    state.night_number = data["night_number"]
    state.day_number = data["day_number"]
    state.phase_start = data["phase_start"]
    state.phase_end = data["phase_end"]
    state.players = {pid: _player_from_dict(pd) for pid, pd in data["players"].items()}
    state.night_actions = {
        pid: _night_action_from_dict(ad) for pid, ad in data.get("night_actions", {}).items()
    }
    state.votes = {pid: Vote(**vd) for pid, vd in data.get("votes", {}).items()}
    state.revote_round = data.get("revote_round", 0)
    state.revote_candidates = data.get("revote_candidates")
    state.winner = _winner_from_dict(data["winner"]) if data.get("winner") else None
    state.last_night_deaths = data.get("last_night_deaths", [])
    state.last_vote_result = data.get("last_vote_result")
    state.chat_messages = [ChatMessage(**m) for m in data.get("chat_messages", [])]
    state.mafia_chat_messages = [ChatMessage(**m) for m in data.get("mafia_chat_messages", [])]
    state._confirm_yes = data.get("confirm_yes", 0)
    state._confirm_no = data.get("confirm_no", 0)
    state._confirm_voters = set(data.get("confirm_voters", []))
    state._night_action_log = data.get("night_action_log", [])
    state._night_attack_targets = data.get("night_attack_targets", {})
    state.outcome_messages = data.get("outcome_messages", {})
    return state


def _player_from_dict(d: dict) -> PlayerState:
    d = dict(d)
    role = d.get("role")
    d["role"] = RoleName(role) if role else None
    return PlayerState(**d)


def _night_action_from_dict(d: dict) -> NightAction:
    return NightAction(
        player_id=d["player_id"],
        role=RoleName(d["role"]),
        action_type=ActionType(d["action_type"]),
        target_id=d.get("target_id"),
        submitted_at=d.get("submitted_at", 0.0),
    )


def _winner_from_dict(d: dict) -> WinResult:
    return WinResult(
        faction=Faction(d["faction"]) if d.get("faction") else None,
        winners=d.get("winners", []),
        reason=d.get("reason", ""),
        individual_winners=d.get("individual_winners", []),
    )
