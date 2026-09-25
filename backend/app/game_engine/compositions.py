"""
Role compositions per player count, taken VERBATIM as the immutable source of
truth from `mafia_rol_jadvali_FINAL.md` (spec 68). Each player count may have
several variants (A, B, C, ...). On every new game the server:

  1. counts the valid players,
  2. lists the existing variants for that count,
  3. uses PURE INDEPENDENT RANDOM selection to pick ONE variant
     (no history, no anti-repeat, no rotation, no balancing),
  4. expands that variant into a role pool,
  5. securely shuffles and assigns roles to players.

NOTES:
- "Qotil" in the source table maps to the MANIAC role (the independent night
  killer). No composition lists both "Maniac" and "Qotil", and Maniac is the
  only matching card in the fixed 13-role roster.
- The source table intentionally allows duplicate UNIQUE roles (e.g. "Don 2",
  "Komissar 2"). We keep the numbers exactly as given — no de-duplication.
"""
from __future__ import annotations
from typing import Optional
from app.game_engine.roles import RoleName as R

Composition = dict[str, list[R]]  # variant letter -> role pool
VariantMap = dict[int, Composition]

COMPOSITIONS: VariantMap = {
    4: {
        "A": [R.CITIZEN, R.CITIZEN, R.DOCTOR, R.DON],
    },
    5: {
        "A": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.DON, R.DOCTOR],
    },
    6: {
        "A": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.DOCTOR, R.COMMISSIONER, R.DON],
    },
    7: {
        "A": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.COMMISSIONER, R.LUCKY, R.DOCTOR, R.DON],
        "B": [R.CITIZEN, R.CITIZEN, R.COMMISSIONER, R.DOCTOR, R.LUCKY, R.MAFIA, R.DON],
        "C": [R.CITIZEN, R.CITIZEN, R.COMMISSIONER, R.LUCKY, R.DOCTOR, R.DON, R.DON],
    },
    8: {
        "A": [R.CITIZEN, R.CITIZEN, R.DON, R.SUICIDE, R.COMMISSIONER, R.MAFIA, R.LUCKY, R.DOCTOR],
        "B": [R.CITIZEN, R.CITIZEN, R.LUCKY, R.SUICIDE, R.DOCTOR, R.DON, R.DON, R.COMMISSIONER],
    },
    9: {
        "A": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.LUCKY, R.COMMISSIONER, R.SUICIDE, R.DON, R.DON, R.DOCTOR],
        "B": [R.CITIZEN, R.CITIZEN, R.LUCKY, R.DOCTOR, R.COMMISSIONER, R.SUICIDE, R.DON, R.DON, R.MAFIA],
        "C": [R.CITIZEN, R.CITIZEN, R.MAFIA, R.MAFIA, R.DON, R.SUICIDE, R.LUCKY, R.DOCTOR, R.COMMISSIONER],
    },
    10: {
        "A": [R.CITIZEN, R.KAMIKAZE, R.LUCKY, R.COMMISSIONER, R.SUICIDE,
              R.DON, R.DON, R.DON, R.DOCTOR, R.VAGABOND],
        "B": [R.CITIZEN, R.KAMIKAZE, R.VAGABOND, R.DON, R.DON, R.COMMISSIONER,
              R.DOCTOR, R.MAFIA, R.SUICIDE, R.LUCKY],
        "C": [R.CITIZEN, R.CITIZEN, R.VAGABOND, R.LUCKY, R.DOCTOR, R.COMMISSIONER,
              R.SUICIDE, R.KAMIKAZE, R.DON, R.DON],
    },
    11: {
        "A": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MISTRESS, R.KAMIKAZE,
              R.COMMISSIONER, R.LUCKY, R.DON, R.DON, R.DOCTOR, R.VAGABOND],
        "B": [R.VAGABOND, R.CITIZEN, R.CITIZEN, R.LUCKY, R.DOCTOR, R.SUICIDE,
              R.DON, R.DON, R.DON, R.COMMISSIONER, R.KAMIKAZE],
        "C": [R.MAFIA, R.DON, R.COMMISSIONER, R.DOCTOR, R.LUCKY, R.SUICIDE,
              R.KAMIKAZE, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
    },
    12: {
        "A": [R.CITIZEN, R.CITIZEN, R.COMMISSIONER, R.VAGABOND, R.KAMIKAZE, R.MAFIA,
              R.MISTRESS, R.DOCTOR, R.DON, R.DON, R.LUCKY, R.SERGEANT],
        "B": [R.MAFIA, R.MAFIA, R.DON, R.SUICIDE, R.KAMIKAZE, R.CITIZEN, R.CITIZEN,
              R.VAGABOND, R.DOCTOR, R.LUCKY, R.MISTRESS, R.COMMISSIONER],
        "C": [R.MAFIA, R.DON, R.DON, R.COMMISSIONER, R.DOCTOR, R.LUCKY, R.SUICIDE,
              R.KAMIKAZE, R.VAGABOND, R.CITIZEN, R.CITIZEN, R.CITIZEN],
    },
    13: {
        "A": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MISTRESS, R.COMMISSIONER, R.COMMISSIONER,
              R.KAMIKAZE, R.VAGABOND, R.DOCTOR, R.LUCKY, R.DON, R.DON, R.MAFIA],
        "B": [R.COMMISSIONER, R.SERGEANT, R.KAMIKAZE, R.CITIZEN, R.CITIZEN, R.CITIZEN,
              R.DOCTOR, R.LUCKY, R.MAFIA, R.MAFIA, R.VAGABOND, R.DON, R.MISTRESS],
        "C": [R.COMMISSIONER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.LUCKY, R.SERGEANT,
              R.MISTRESS, R.DON, R.DON, R.DON, R.KAMIKAZE, R.DOCTOR, R.VAGABOND],
        "D": [R.DOCTOR, R.LUCKY, R.VAGABOND, R.SUICIDE, R.MISTRESS, R.COMMISSIONER,
              R.CITIZEN, R.CITIZEN, R.MAFIA, R.MAFIA, R.DON, R.DON, R.KAMIKAZE],
        "E": [R.KAMIKAZE, R.CITIZEN, R.CITIZEN, R.COMMISSIONER, R.LUCKY, R.VAGABOND,
              R.DON, R.DON, R.DON, R.DOCTOR, R.SUICIDE, R.MISTRESS, R.MAFIA],
        "F": [R.MAFIA, R.MAFIA, R.DON, R.KAMIKAZE, R.DOCTOR, R.COMMISSIONER, R.SUICIDE,
              R.LUCKY, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.MISTRESS, R.VAGABOND],
        "G": [R.MISTRESS, R.DOCTOR, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.LUCKY, R.VAGABOND,
              R.COMMISSIONER, R.DON, R.DON, R.DON, R.SUICIDE, R.KAMIKAZE],
    },
    14: {
        "A": [R.DON, R.DON, R.LUCKY, R.MAFIA, R.MANIAC, R.MISTRESS, R.COMMISSIONER,
              R.COMMISSIONER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.DOCTOR, R.KAMIKAZE, R.VAGABOND],
        "B": [R.MISTRESS, R.LUCKY, R.COMMISSIONER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.VAGABOND,
              R.SERGEANT, R.DOCTOR, R.KAMIKAZE, R.MAFIA, R.DON, R.DON, R.SUICIDE],
        "C": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.DOCTOR, R.COMMISSIONER, R.COMMISSIONER,
              R.LUCKY, R.SUICIDE, R.KAMIKAZE, R.MISTRESS, R.DON, R.DON, R.MAFIA, R.VAGABOND],
    },
    15: {
        "A": [R.DOCTOR, R.KAMIKAZE, R.MISTRESS, R.VAGABOND, R.LUCKY, R.SUICIDE,
              R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.COMMISSIONER, R.COMMISSIONER,
              R.DON, R.DON, R.MAFIA],
        "B": [R.DOCTOR, R.SERGEANT, R.LUCKY, R.COMMISSIONER, R.KAMIKAZE, R.MAFIA, R.MAFIA,
              R.MAFIA, R.MAFIA, R.SUICIDE, R.VAGABOND, R.CITIZEN, R.CITIZEN, R.MISTRESS, R.DON],
        "C": [R.MAFIA, R.MAFIA, R.DON, R.SUICIDE, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
              R.DOCTOR, R.COMMISSIONER, R.COMMISSIONER, R.LUCKY, R.KAMIKAZE, R.VAGABOND, R.MISTRESS],
    },
    16: {
        "A": [R.MAFIA, R.MAFIA, R.DON, R.DON, R.SERGEANT, R.VAGABOND, R.COMMISSIONER, R.MANIAC,
              R.LAWYER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.KAMIKAZE, R.DOCTOR, R.LUCKY, R.MISTRESS],
        "B": [R.MAFIA, R.MAFIA, R.DON, R.COMMISSIONER, R.COMMISSIONER, R.DOCTOR, R.MANIAC,
              R.MISTRESS, R.KAMIKAZE, R.LUCKY, R.VAGABOND, R.SUICIDE, R.CITIZEN, R.CITIZEN,
              R.CITIZEN, R.CITIZEN],
        "C": [R.MAFIA, R.MAFIA, R.MAFIA, R.DON, R.COMMISSIONER, R.SERGEANT, R.DOCTOR, R.MISTRESS,
              R.KAMIKAZE, R.LUCKY, R.VAGABOND, R.SUICIDE, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
    },
    17: {
        "A": [R.MAFIA, R.MAFIA, R.MAFIA, R.DON, R.COMMISSIONER, R.COMMISSIONER, R.DOCTOR,
              R.LAWYER, R.KAMIKAZE, R.LUCKY, R.VAGABOND, R.MISTRESS, R.SUICIDE, R.CITIZEN,
              R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "B": [R.MAFIA, R.MAFIA, R.DON, R.DON, R.COMMISSIONER, R.SERGEANT, R.DOCTOR, R.MANIAC,
              R.KAMIKAZE, R.LUCKY, R.VAGABOND, R.MISTRESS, R.CITIZEN, R.CITIZEN, R.CITIZEN,
              R.CITIZEN, R.CITIZEN],
        "C": [R.MAFIA, R.MAFIA, R.MAFIA, R.DON, R.COMMISSIONER, R.DOCTOR, R.LAWYER, R.KAMIKAZE,
              R.LUCKY, R.VAGABOND, R.SUICIDE, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
              R.CITIZEN, R.CITIZEN],
    },
    18: {
        "A": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.COMMISSIONER, R.LUCKY,
              R.MAFIA, R.MAFIA, R.KAMIKAZE, R.VAGABOND, R.DOCTOR, R.DON, R.DON, R.SERGEANT,
              R.MANIAC, R.MISTRESS, R.LAWYER],
        "B": [R.MAFIA, R.MAFIA, R.MAFIA, R.DON, R.DON, R.COMMISSIONER, R.COMMISSIONER, R.DOCTOR,
              R.KAMIKAZE, R.LUCKY, R.VAGABOND, R.MISTRESS, R.SUICIDE, R.CITIZEN, R.CITIZEN,
              R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "C": [R.MAFIA, R.MAFIA, R.DON, R.DON, R.COMMISSIONER, R.SERGEANT, R.DOCTOR, R.LAWYER,
              R.MANIAC, R.KAMIKAZE, R.LUCKY, R.VAGABOND, R.SUICIDE, R.CITIZEN, R.CITIZEN,
              R.CITIZEN, R.CITIZEN, R.CITIZEN],
    },
    19: {
        "A": [R.MAFIA, R.MAFIA, R.MAFIA, R.MAFIA, R.DON, R.DON, R.CITIZEN, R.CITIZEN, R.CITIZEN,
              R.MISTRESS, R.KAMIKAZE, R.MANIAC, R.LAWYER, R.LUCKY, R.VAGABOND, R.COMMISSIONER,
              R.COMMISSIONER, R.DOCTOR, R.SUICIDE],
        "B": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.COMMISSIONER, R.SERGEANT,
              R.SUICIDE, R.DON, R.DON, R.MISTRESS, R.LUCKY, R.MAFIA, R.MAFIA, R.MANIAC,
              R.KAMIKAZE, R.DOCTOR, R.LAWYER, R.VAGABOND],
        "C": [R.MAFIA, R.MAFIA, R.MAFIA, R.DON, R.DON, R.COMMISSIONER, R.SERGEANT, R.DOCTOR,
              R.LAWYER, R.MANIAC, R.KAMIKAZE, R.LUCKY, R.VAGABOND, R.SUICIDE, R.CITIZEN,
              R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
    },
    20: {
        "A": [R.MAFIA, R.MAFIA, R.MAFIA, R.MAFIA, R.DON, R.COMMISSIONER, R.COMMISSIONER, R.DOCTOR,
              R.LAWYER, R.MANIAC, R.MISTRESS, R.KAMIKAZE, R.LUCKY, R.VAGABOND, R.SUICIDE,
              R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "B": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.KAMIKAZE, R.VAGABOND,
              R.MISTRESS, R.COMMISSIONER, R.COMMISSIONER, R.SUICIDE, R.LAWYER, R.MAFIA, R.MAFIA,
              R.MANIAC, R.DON, R.DON, R.DON, R.DOCTOR, R.LUCKY],
        "C": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.SUICIDE, R.KAMIKAZE,
              R.LUCKY, R.DON, R.DON, R.MISTRESS, R.DOCTOR, R.MAFIA, R.MAFIA, R.MAFIA, R.VAGABOND,
              R.COMMISSIONER, R.LAWYER, R.MANIAC, R.SERGEANT],
        "D": [R.MANIAC, R.SUICIDE, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.DON,
              R.DON, R.MAFIA, R.MAFIA, R.MAFIA, R.MISTRESS, R.DOCTOR, R.KAMIKAZE, R.LUCKY,
              R.COMMISSIONER, R.COMMISSIONER, R.VAGABOND, R.LAWYER],
        "E": [R.DOCTOR, R.SERGEANT, R.KAMIKAZE, R.COMMISSIONER, R.CITIZEN, R.CITIZEN, R.CITIZEN,
              R.CITIZEN, R.CITIZEN, R.MAFIA, R.MAFIA, R.MAFIA, R.MAFIA, R.SUICIDE, R.DON, R.LUCKY,
              R.MANIAC, R.MISTRESS, R.VAGABOND, R.LAWYER],
        "F": [R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.LUCKY, R.DOCTOR, R.SERGEANT,
              R.COMMISSIONER, R.MISTRESS, R.SUICIDE, R.LAWYER, R.DON, R.DON, R.DON, R.MANIAC,
              R.MAFIA, R.MAFIA, R.KAMIKAZE, R.VAGABOND],
    },
}

MIN_PLAYERS = 4
MAX_PLAYERS = 20

_RNG = None  # module-level shared random source (seeded by the engine callers)


def variants_for(player_count: int) -> list[str]:
    """Existing variant letters for a player count (e.g. ['A', 'B', 'C'])."""
    if player_count not in COMPOSITIONS:
        raise ValueError(f"Unsupported player count: {player_count} ({MIN_PLAYERS}–{MAX_PLAYERS} only)")
    return list(COMPOSITIONS[player_count].keys())


def get_composition(player_count: int, variant: Optional[str] = None) -> list[R]:
    """Return the role pool for `player_count`.

    If `variant` is given, return that exact variant. Otherwise return the
    pool of the FIRST variant (alphabetical) — callers that must pick randomly
    should use `select_composition` instead so the choice is server-side and
    independent each game.
    """
    if player_count not in COMPOSITIONS:
        raise ValueError(f"Unsupported player count: {player_count} ({MIN_PLAYERS}–{MAX_PLAYERS} only)")
    comp = COMPOSITIONS[player_count]
    if variant is not None:
        if variant not in comp:
            raise ValueError(f"No variant {variant} for {player_count} players")
        return list(comp[variant])
    first = sorted(comp)[0]
    return list(comp[first])


def all_possible_roles(player_count: int) -> list[R]:
    """Every role that can appear in ANY variant of a player count (union).
    Used only for lobby-time UI and bot-role-pick validation, since the
    concrete variant is chosen at game start, server-side."""
    if player_count not in COMPOSITIONS:
        raise ValueError(f"Unsupported player count: {player_count} ({MIN_PLAYERS}–{MAX_PLAYERS} only)")
    seen: set[R] = set()
    for pool in COMPOSITIONS[player_count].values():
        seen.update(pool)
    return sorted(seen, key=lambda r: r.value)


def select_composition(player_count: int, rng) -> tuple[str, list[R]]:
    """PURE INDEPENDENT RANDOM selection of one variant for this game.

    `rng` must be a random.SystemRandom (or a Random seeded fresh each game).
    No history, no anti-repeat, no rotation — repetition is fully allowed.
    Returns (variant_label, role_pool).
    """
    if player_count not in COMPOSITIONS:
        raise ValueError(f"Unsupported player count: {player_count} ({MIN_PLAYERS}–{MAX_PLAYERS} only)")
    comp = COMPOSITIONS[player_count]
    label = rng.choice(sorted(comp))
    return label, list(comp[label])


def validate_all_compositions() -> None:
    """Structural sanity checks — NOT a rebalance.

    Every declared count is present, every variant's pool size equals the
    player count, and no variant references an unknown role. The source table
    intentionally allows duplicate unique roles, so we do NOT enforce
    uniqueness here.
    """
    for n in range(MIN_PLAYERS, MAX_PLAYERS + 1):
        assert n in COMPOSITIONS, f"{n}: missing from COMPOSITIONS"
    for n, comp in COMPOSITIONS.items():
        for label, pool in comp.items():
            assert len(pool) == n, f"{n}{label}: wrong role count ({len(pool)})"
            for r in pool:
                assert r in R, f"{n}{label}: unknown role {r}"
