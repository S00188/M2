#!/usr/bin/env python3
"""
Monte Carlo balance simulator — drives the REAL MafiaGameEngine from
app.game_engine so win rates reflect the actual implementation (resolver,
win conditions, protection logic, charge caps) rather than hand-waving.

Models three town "skill" levels (how often a no-info lynch hits a Mafia):
  0.0  random town (no deduction)
  0.33 moderate players
  0.5  strong players
Plus Commissioner confirmations feed the lynch every day.

Usage: run from backend/ with PYTHONPATH=. ; change N / GAMES at the bottom.
"""
import random
import statistics

from app.game_engine.engine import GameEngine
from app.game_engine.managers import PhaseManager, WinConditionManager
from app.game_engine.roles import RoleName as R, ROLES, Faction
from app.game_engine.state import Phase
from app.game_engine.compositions import get_composition

MAFIA_KILLERS = (R.DON, R.MAFIOSO)
# Value order for mafia's night kill target (most dangerous town first).
MAFIA_TARGET_PRIORITY = [
    R.DOCTOR, R.COMMISSIONER, R.INVESTIGATOR, R.BODYGUARD, R.VETERAN,
    R.TRACKER, R.WATCHER, R.GUNNER, R.MAYOR, R.MEDIUM,
]
FACTION_OF = lambda role: ROLES[role].faction


def make_engine_from_composition(n, rng):
    roles = get_composition(n)
    rng.shuffle(roles)
    eng = GameEngine(game_id=f"sim-{rng.random()}", host_telegram_id=1, host_name="P0")
    for i in range(1, n):
        eng.add_player(telegram_user_id=100 + i, display_name=f"P{i}")
    for (key, p), role in zip(eng.state.players.items(), roles):
        p.role = role
    PhaseManager.to_night(eng.state)
    return eng


def alive_w(eng):
    return {pid: p for pid, p in eng.state.players.items() if p.alive}


def faction_alive(eng, faction):
    return [pid for pid, p in alive_w(eng).items() if FACTION_OF(p.role) == faction]


def role_token(p):
    """A role name for a killed/shot/voted actor, for mafia priority etc."""
    return p.role


def simulate(n, town_skill, rng, max_days=30):
    eng = make_engine_from_composition(n, rng)
    state = eng.state
    known_mafia = set()       # commissioner-confirmed mafia
    known_clean = set()       # commissioner "not mafia" reads
    doc_self_used = False
    veteran_used = False
    gunner_used = False
    arsonist_ignite_turn = False   # response

    def alive_list():
        return list(alive_w(eng).values())

    def mafia_alive():
        return [p for p in alive_list() if FACTION_OF(p.role) == Faction.MAFIA]

    def town_alive():
        return [p for p in alive_list() if FACTION_OF(p.role) == Faction.TOWN]

    def non_mafia():
        return [p for p in alive_list() if FACTION_OF(p.role) != Faction.MAFIA]

    def pick_best_mafia_target(exclude_self=False):
        cands = [p for p in non_mafia() if not (exclude_self and p.role == R.MEDIUM)]
        cands = [p for p in cands if p.role != R.MEDIUM]  # medium wasted kill
        for role in MAFIA_TARGET_PRIORITY:
            trop = [p for p in cands if p.role == role]
            if trop:
                return trop[0]
        if cands:
            return rng.choice(cands)
        return None

    # ---------- phase loop ----------
    for day in range(1, max_days + 1):
        if state.phase == Phase.GAME_OVER:
            break

        # ---------- NIGHT ----------
        # (Re)submit night actions.
        killer_id = eng._current_mafia_killer()  # Don, or first Mafioso if Don dead
        for p in alive_list():
            role = p.role
            if role in MAFIA_KILLERS:
                if p.player_id != killer_id:
                    continue  # balance fix: only the designated Mafia killer acts
                tgt = pick_best_mafia_target()
                if tgt:
                    try:
                        eng.submit_night_action(p.player_id, tgt.player_id)
                    except Exception:
                        pass
            elif role == R.SERIAL_KILLER:
                cands = [q for q in alive_list() if q.role != R.SERIAL_KILLER]
                # SK kills town or mafia — prefer town (mafia is the rival killer)
                tgt = rng.choice(cands)
                try:
                    eng.submit_night_action(p.player_id, tgt.player_id)
                except Exception:
                    pass
            elif role == R.CONSIGLIERE:
                cands = non_mafia()
                if cands:
                    try:
                        eng.submit_night_action(p.player_id, rng.choice(cands).player_id)
                    except Exception:
                        pass
            elif role == R.FRAMER:
                cands = [q for q in alive_list() if q.role != R.FRAMER]
                if cands:
                    try:
                        eng.submit_night_action(p.player_id, rng.choice(cands).player_id)
                    except Exception:
                        pass
            elif role == R.SILENCER:
                cands = [q for q in town_alive() if q.role != R.SILENCER]
                if cands:
                    try:
                        eng.submit_night_action(p.player_id, rng.choice(cands).player_id)
                    except Exception:
                        pass
            elif role == R.COMMISSIONER:
                cands = [q for q in alive_list()
                         if q.player_id not in known_mafia and q.player_id not in known_clean]
                if not cands:
                    cands = [q for q in alive_list() if q.player_id not in known_mafia]
                if cands:
                    pick = rng.choice(cands)
                    try:
                        eng.submit_night_action(p.player_id, pick.player_id)
                    except Exception:
                        pass
                    # record truthful result (engine: Don reads clean, framed read mafia)
                    target = state.players[pick.player_id]
                    framed = target.framed
                    if target.role == R.DON and not framed:
                        known_clean.add(pick.player_id)
                    else:
                        is_maf = FACTION_OF(target.role) == Faction.MAFIA and not (target.role == R.DON and not framed)
                        if is_maf or framed:
                            known_mafia.add(pick.player_id)
                        else:
                            known_clean.add(pick.player_id)
            elif role == R.DOCTOR:
                cands = [q for q in town_alive() if q.player_id != p.player_id]
                if cands:
                    # protect Commissioner or random town
                    doc_target = next((q for q in cands if q.role == R.COMMISSIONER), rng.choice(cands))
                    try:
                        eng.submit_night_action(p.player_id, doc_target.player_id)
                    except Exception:
                        pass
            elif role == R.INVESTIGATOR:
                cands = non_mafia()
                if cands:
                    try:
                        eng.submit_night_action(p.player_id, rng.choice(cands).player_id)
                    except Exception:
                        pass
            elif role in (R.TRACKER, R.WATCHER):
                cands = alive_list()
                if cands:
                    try:
                        eng.submit_night_action(p.player_id, rng.choice(cands).player_id)
                    except Exception:
                        pass
            elif role == R.BODYGUARD:
                cands = [q for q in town_alive() if q.player_id != p.player_id]
                if cands:
                    try:
                        eng.submit_night_action(p.player_id, rng.choice(cands).player_id)
                    except Exception:
                        pass
            elif role == R.VETERAN and not veteran_used:
                veteran_used = True
                try:
                    eng.submit_night_action(p.player_id, None)
                except Exception:
                    pass
            elif role == R.MEDIUM:
                deads = [q for q in state.players.values() if not q.alive]
                if deads:
                    try:
                        eng.submit_night_action(p.player_id, rng.choice(deads).player_id)
                    except Exception:
                        pass
            elif role == R.ARSONIST:
                if arsonist_ignite_turn and state.doused_players:
                    try:
                        eng.submit_night_action(p.player_id, None)  # ignite
                    except Exception:
                        pass
                else:
                    cands = [q for q in alive_list() if q.role != R.ARSONIST]
                    if cands:
                        try:
                            eng.submit_night_action(p.player_id, rng.choice(cands).player_id)
                        except Exception:
                            pass

        # resolve night
        eng.resolve_night_if_ready(force=True)
        if state.phase == Phase.GAME_OVER:
            break

        # ---------- DAY ----------
        # Gunner may shoot a known-mafia (1 bullet)
        gunner = next((p for p in alive_list() if p.role == R.GUNNER), None)
        if gunner and not gunner_used and known_mafia:
            cand = [q for q in alive_list() if q.player_id in known_mafia]
            if cand:
                try:
                    eng.gunner_shoot(gunner.player_id, cand[0].player_id)
                except Exception:
                    pass
                gunner_used = True
        # Mayor reveal (1 event, early)
        mayor = next((p for p in alive_list() if p.role == R.MAYOR and not p.mayor_revealed), None)
        if mayor:
            try:
                eng.reveal_mayor(mayor.player_id)
            except Exception:
                pass
        if state.phase == Phase.GAME_OVER:
            break

        # move day -> voting (ignore discussion)
        eng.advance_to_voting_if_ready(force=True)

        # town chooses lynch target
        if state.phase == Phase.VOTING:
            alive = alive_list()
            known = [pid for pid in known_mafia if state.players[pid].alive]
            if known:
                lynch_target = known[0]
            else:
                ma = [p for p in alive if FACTION_OF(p.role) == Faction.MAFIA]
                if rng.random() < town_skill and ma:
                    lynch_target = rng.choice(ma).player_id
                else:
                    innocents = [p for p in alive][:]
                    lynch_target = rng.choice(innocents).player_id
            # votes
            for p in alive:
                # silenced or spectate? engine may still accept; just vote.
                if p.player_id == lynch_target:
                    continue
                # mafia / neutral / town all vote the lynch target (town = lynch; mafia vote lynch to survive; neutrals blend)
                try:
                    eng.submit_vote(p.player_id, lynch_target)
                except Exception:
                    pass
            # target votes for itself (abstain -> submit None)
            try:
                eng.submit_vote(lynch_target, None)
            except Exception:
                pass
            eng.resolve_voting_if_ready(force=True)
            if state.phase == Phase.GAME_OVER:
                break
            # after vote_results, advance to next night
            try:
                eng.start_next_night_if_ready(force=True)
            except Exception:
                pass

    # ---------- outcome ----------
    if state.phase != Phase.GAME_OVER:
        w = WinConditionManager.check(state)
    else:
        w = state.winner
    if w is None:
        return "TIE"
    return w.faction.value if w.faction else "TIE"


def run(n, skill, games, seed=1234):
    rng = random.Random(seed)
    counts = {"mafia": 0, "town": 0, "neutral": 0, "TIE": 0}
    for _ in range(games):
        res = simulate(n, skill, rng)
        counts[res] = counts.get(res, 0) + 1
    total = sum(counts.values())
    return {k: 100.0 * v / total for k, v in counts.items() if v}


if __name__ == "__main__":
    GAMES = 1500
    for skill in (0.0, 0.33, 0.5):
        print(f"\n=== Town skill (random-lynch accuracy) = {skill} ===")
        print(f"{'N':>4} {'Mafia':>7} {'Town':>7} {'Neutral':>9}")
        for n in (6, 8, 10, 12, 14, 15, 17, 20, 23, 25):
            res = run(n, skill, GAMES, seed=999 + (n * 7) + int(skill * 100))
            print(f"{n:>4} {res.get('mafia', 0):>6.1f}%  {res.get('town', 0):>6.1f}%  "
                  f"{res.get('neutral', 0):>7.1f}%")