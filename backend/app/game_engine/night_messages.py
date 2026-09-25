"""
Builds the exact, human-readable Uzbek narrative texts players see after a
night resolves — one entry per player per thing that happened *to them* or
*because of them* (Doctor saves, Mistress blocks, Commissioner reads,
Mafia/Maniac kills, Lucky saves, Vagabond watch reports, ...).

This is the single source of truth for that copy: the same strings are
shown in the client's Role Cabinet panel (GameState.outcome_messages is
serialized straight into `get_player_view`'s `me.outcome_messages`) and sent
as a personal Telegram DM (app/services/notifications.py). Keeping the text
in exactly one place means the two can never drift apart.

Day-phase narrative lines that don't come from NightResolver — the Sergeant
promotion, the Suicide's lynch win, the Kamikaze's take-you-with-me strike —
are appended directly to `state.outcome_messages` at the point they happen
(RoleManager.promote_sergeant / DeathManager.eliminate in managers.py,
GameEngine.submit_kamikaze_target in engine.py) since they aren't part of a
night resolution at all. This module only covers what NightResolver.resolve
just produced.
"""
from __future__ import annotations
from typing import Optional

from app.game_engine.roles import RoleName, ActionType
from app.game_engine.state import GameState


def _name(state: GameState, player_id: Optional[str]) -> str:
    p = state.players.get(player_id) if player_id else None
    return p.display_name if p else "?"


def _effective(log: list[dict], role: RoleName, action_type: ActionType):
    """Yields this night's non-blocked action-log entries for one role +
    action-type pair, in submission order."""
    for entry in log:
        if entry["blocked"]:
            continue
        if entry["role"] == role.value and entry["action_type"] == action_type.value:
            yield entry


def build_night_outcome_messages(state: GameState, results: dict) -> dict[str, list[str]]:
    """Returns player_id -> list of new narrative lines for the night that
    was just resolved (state.last_night_deaths / state._night_action_log /
    state._night_attack_targets already reflect it — see NightResolver.resolve).
    Callers append these onto state.outcome_messages themselves."""
    out: dict[str, list[str]] = {}

    def add(player_id: Optional[str], text: str) -> None:
        if not player_id:
            return
        out.setdefault(player_id, []).append(text)

    log = state._night_action_log
    deaths = {d["player_id"]: set(d["reason"].split("/")) for d in state.last_night_deaths}
    attack_targets = state._night_attack_targets  # target_id -> [attacker labels]

    # ---------------------------------------------------------- DOCTOR --
    for e in _effective(log, RoleName.DOCTOR, ActionType.PROTECT):
        doctor_id, target_id = e["player_id"], e["target_id"]
        if not target_id:
            continue
        target_name = _name(state, target_id)
        real_save = results.get(target_id, {}).get("saved_by") == "doctor"
        if real_save:
            if target_id != doctor_id:
                add(target_id, "\U0001F489 Bu kecha sizga suiqasd uyushtirildi, ammo Doktor "
                                "o'z vaqtida kelib hayotingizni saqlab qoldi!")
            add(doctor_id, f"\U0001F525 Siz {target_name}ni o'limdan qutqarib qoldingiz!")
        else:
            if target_id != doctor_id:
                add(target_id, "\U0001F489 Bu kecha sizning xonadoningizga Doktor "
                                "tashrif buyurib, sizni himoyaladi.")
            add(doctor_id, f"\u2705 Siz {target_name}ni muvaffaqiyatli davoladingiz.")

    # -------------------------------------------------------- MISTRESS --
    for e in _effective(log, RoleName.MISTRESS, ActionType.BLOCK):
        mistress_id, target_id = e["player_id"], e["target_id"]
        if not target_id:
            continue
        target_name = _name(state, target_id)
        add(target_id, "\U0001F48B Bu tunda huzuringizga go'zal ayol tashrif buyurdi. Siz "
                        "vasvasaga tushib, tungi vazifangizni bajara olmadingiz!")
        add(mistress_id, f"\u2705 Siz {target_name}ni chalg'itdingiz, u bu tunda hech "
                          f"qanday harakat qila olmadi.")

    # ---------------------------------------------------------- LAWYER --
    for e in _effective(log, RoleName.LAWYER, ActionType.SHIELD):
        lawyer_id, target_id = e["player_id"], e["target_id"]
        if not target_id:
            continue
        target_name = _name(state, target_id)
        add(target_id, "\u2696\uFE0F Bu kecha sizni maxfiy Advokat o'z himoyasiga oldi. "
                        "Agar politsiya sizni tekshirsa, Fuqaro bo'lib ko'rinasiz.")
        add(lawyer_id, f"\u2705 {target_name} sizning yuridik himoyangiz ostida. Tonggacha "
                        f"u Fuqaro sifatida niqoblandi.")

    # ---------------------------------------------------- COMMISSIONER --
    for e in _effective(log, RoleName.COMMISSIONER, ActionType.SHOOT):
        target_id = e["target_id"]
        if target_id and "commissioner" in deaths.get(target_id, set()):
            add(target_id, "\U0001F4A5 Tungi sukunatda o'q ovozi yangradi. Komissar sizni "
                            "xavfli deb topib, otib tashladi!")

    for e in _effective(log, RoleName.COMMISSIONER, ActionType.INVESTIGATE):
        commissioner_id, target_id = e["player_id"], e["target_id"]
        if not target_id:
            continue
        target_name = _name(state, target_id)
        add(target_id, "\U0001F575\uFE0F\u200D\u2642\uFE0F Xonangiz atrofida kimdir "
                        "poylayotganini sezdingiz.")
        verdict = results.get(commissioner_id, {}).get("verdict")
        if verdict == "mafia":
            add(commissioner_id, f"\U0001F50E Qidiruv natijasi: {target_name} \u2014 Mafiya!")
        elif verdict == "not_mafia":
            add(commissioner_id, f"\U0001F50E Qidiruv natijasi: {target_name} \u2014 "
                                  f"Tinch fuqaro.")

    # ----------------------------------------- DON / MAFIA / MANIAC kills --
    living_mafia = [pid for pid, p in state.players.items()
                     if p.alive and p.role in (RoleName.DON, RoleName.MAFIA)]
    living_maniac = [pid for pid, p in state.players.items()
                      if p.alive and p.role == RoleName.MANIAC]

    for target_id, attackers in attack_targets.items():
        target = state.players.get(target_id)
        if not target:
            continue
        died = target_id in deaths
        saved_by = results.get(target_id, {}).get("saved_by")

        if "mafia" in attackers:
            if died and "mafia" in deaths.get(target_id, set()):
                add(target_id, "\U0001F52B Qorong'ulikda Mafiya to'dasi sizga suiqasd "
                                "uyushtirdi. Siz halok bo'ldingiz!")
            elif not died:
                for pid in living_mafia:
                    add(pid, "\u274C Suiqasd barbod bo'ldi! Nishonni Doktor qutqarib qoldi "
                              "yoki uning omadi keldi.")

        if "maniac" in attackers:
            if died and "maniac" in deaths.get(target_id, set()):
                add(target_id, "\U0001F52A Tungi soyadan Maniyak paydo bo'ldi va sizga "
                                "shafqatsizlarcha zarba berdi. Siz halok bo'ldingiz!")

        # -------------------------------------------------------- LUCKY --
        if not died and saved_by == "luck":
            add(target_id, "\U0001F340 Sizga bu tunda xavfli hujum uyushtirildi, ammo "
                            "tug'ma omadingiz sabab mo'jizaviy tarzda omon qoldingiz!")
            recipients = (living_mafia if "mafia" in attackers else []) + \
                         (living_maniac if "maniac" in attackers else [])
            for pid in recipients:
                add(pid, "\u26A0\uFE0F Nishon juda omadli chiqdi, hujum kutilmaganda "
                          "omadsiz yakunlandi!")

    # -------------------------------------------------------- VAGABOND --
    for e in _effective(log, RoleName.VAGABOND, ActionType.WATCH):
        vagabond_id, target_id = e["player_id"], e["target_id"]
        if not target_id:
            continue
        target_name = _name(state, target_id)
        visitors = results.get(vagabond_id, {}).get("visitors") or []
        visitor_names = ", ".join(_name(state, v) for v in visitors) if visitors \
            else "hech kim tashrif buyurmadi"
        add(vagabond_id, f"\U0001F463 Kuzatuv natijasi: Bu kecha {target_name}ning oldiga "
                          f"quyidagilar tashrif buyurdi: {visitor_names}.")
        add(target_id, "\U0001F440 Orqangizdan kimdir kuzatib yurganini sezdingiz.")

    return out
