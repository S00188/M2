"""
Role system for the Mafia game engine.

True Mafia 13-role setup (see the integration prompt). Every role is pure
data + declared capabilities. All *logic* for what a role's action actually
does lives in NightResolver (managers.py) — this module only says WHO can do
WHAT, HOW OFTEN, and WHAT FACTION they belong to.

A quick map of the 13 roles and their place in the game:

  TOWN      Citizen      — no night action; discusses and votes.
            Commissioner — each night either CHECKS a player (learns
                           Mafia or not) or KILLS once per game.
            Sergeant     — no night action; if the Commissioner dies the
                           Sergeant is promoted to Commissioner.
            Doctor       — protects one player each night (self once).
            Lucky        — no night action; may survive a lethal attack by
                           chance (a luck check).
            Kamikaze     — no night action; if lynched by day vote they pick
                           one player to take with them.

  MAFIA     Don          — knows the Mafia team, participates in the shared
                           night kill. If the Don dies a living Mafia takes
                           his place.
            Mafia        — knows the Don and the rest of the team,
                           participates in the shared night kill, and can be
                           promoted to Don.

  NEUTRAL   Maniac       — an independent night killer with his own win goal.
            Mistress     — blocks one player's night action.
            Lawyer       — secretly works with the Mafia but does not know
                           their identities; each night picks a "client"
                           (not self) — a Commissioner check on that client
                           returns "Citizen" regardless of their real role.
            Suicide      — wins if he is eliminated by the day vote (lynch).
            Vagabond     — watches one player at night and learns who
                           visited them.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Faction(str, Enum):
    MAFIA = "mafia"
    TOWN = "town"
    NEUTRAL = "neutral"


class ActionType(str, Enum):
    KILL = "kill"                # shared mafia kill + maniac's own kill
    PROTECT = "protect"          # doctor
    INVESTIGATE = "investigate"  # commissioner's CHECK
    SHOOT = "shoot"              # commissioner's special one-shot KILL
    BLOCK = "block"              # mistress
    WATCH = "watch"              # vagabond (learn who visited the target)
    SHIELD = "shield"            # lawyer (choose who reads as "Citizen" if checked)
    # day-vote constellations handled outside of night actions
    NONE = "none"


class RoleName(str, Enum):
    CITIZEN = "Citizen"
    COMMISSIONER = "Commissioner"
    SERGEANT = "Sergeant"
    DOCTOR = "Doctor"
    LUCKY = "Lucky"
    KAMIKAZE = "Kamikaze"
    DON = "Don"
    MAFIA = "Mafia"
    MANIAC = "Maniac"
    MISTRESS = "Mistress"
    LAWYER = "Lawyer"
    SUICIDE = "Suicide"
    VAGABOND = "Vagabond"


@dataclass(frozen=True)
class RoleDefinition:
    name: RoleName
    faction: Faction
    night_action: Optional[ActionType]
    day_action: Optional[ActionType] = None
    max_charges: Optional[int] = None      # None = unlimited while alive
    can_target_self: bool = False
    unique: bool = True                    # only one copy per game
    description: str = ""


ROLES: dict[RoleName, RoleDefinition] = {
    RoleName.CITIZEN: RoleDefinition(
        RoleName.CITIZEN, Faction.TOWN, None, unique=False,
        description="Maxsus tungi qobiliyati yo'q. Mafiyani topish uchun "
                     "kunduzgi muhokama va ovoz berishdan foydalanadi."),
    RoleName.COMMISSIONER: RoleDefinition(
        RoleName.COMMISSIONER, Faction.TOWN, ActionType.INVESTIGATE,
        description="Har kecha bitta o'yinchini tekshiradi (Mafia yoki yo'q) "
                     "yoki o'yin davomida bir marta o'ldirishi mumkin. "
                     "Tekshiruv natijasida Mafiyani ko'rsatadi, lekin "
                     "Lawyer himoya qilgan o'rinbu 'Citizen' bo'lib ko'rinadi."),
    RoleName.SERGEANT: RoleDefinition(
        RoleName.SERGEANT, Faction.TOWN, None,
        description="Komissar yordamchisi. Inson Komissar vafot etsa, "
                     "Serjant yangi Komissar bo'lib lavozimga ko'tariladi."),
    RoleName.DOCTOR: RoleDefinition(
        RoleName.DOCTOR, Faction.TOWN, ActionType.PROTECT,
        can_target_self=True,
        description="Har kecha bitta o'yinchini himoya qiladi. O'zini "
                     "himoya qilish o'yin davomida faqat bir marta."),
    RoleName.LUCKY: RoleDefinition(
        RoleName.LUCKY, Faction.TOWN, None, unique=False,
        description="Hujum qilinganida tasodifan (omad tufayli) omon "
                     "qolishi mumkin."),
    RoleName.KAMIKAZE: RoleDefinition(
        RoleName.KAMIKAZE, Faction.TOWN, None,
        description="Kunduzgi ovoz berish (osib o'ldirilish) bilan o'lsa, "
                     "o'zi bilan birga yana bir o'yinchini olib ketadi."),
    RoleName.DON: RoleDefinition(
        RoleName.DON, Faction.MAFIA, ActionType.KILL,
        description="Mafia rahbari. Mafia jamoasi bilan birga tungi "
                     "nishonni tanlaydi va Mafia jamoasini taniydi. Inson Don "
                     "vafot etsa, tirik Mafia a'zosi yangi Don bo'ladi."),
    RoleName.MAFIA: RoleDefinition(
        RoleName.MAFIA, Faction.MAFIA, ActionType.KILL, unique=False,
        description="Mafia jamoasi a'zosi. Don va boshqa Mafialarni taniydi, "
                     "jamoaviy tungi o'ldirishda qatnashadi. Don vafot etsa "
                     "yangi Don bo'lishi mumkin."),
    RoleName.MANIAC: RoleDefinition(
        RoleName.MANIAC, Faction.NEUTRAL, ActionType.KILL,
        description="Mustaqil qotil. O'z maqsadi uchun har kecha bitta "
                     "o'yinchini yo'q qiladi."),
    RoleName.MISTRESS: RoleDefinition(
        RoleName.MISTRESS, Faction.NEUTRAL, ActionType.BLOCK,
        description="Har kecha bitta o'yinchining tungi qobiliyatini "
                     "bloklaydi (chalg'itadi)."),
    RoleName.LAWYER: RoleDefinition(
        RoleName.LAWYER, Faction.NEUTRAL, ActionType.SHIELD,
        description="Mafia nomiga yashirin ishlaydi, lekin ularning "
                     "identifikatsiyalarini bilmaydi. Har kecha bitta o'yinchini "
                     "\"mijoz\" qilib tanlaydi (o'zini tanlay olmaydi). Agar "
                     "Komissar aynan shu mijozni tekshirsa, uning haqiqiy "
                     "roli qanday bo'lishidan qat'i nazar natija 'Citizen' "
                     "bo'lib ko'rsatiladi. Tanlov kim ekanligini Lawyer "
                     "bilmagani uchun bu ko'r-ko'rona tanlov — lekin agar "
                     "u tasodifan mafiyaning bir a'zosini tanlasa, o'sha "
                     "kechada uni Komissar tekshiruvidan haqiqatan ham "
                     "yashiradi."),
    RoleName.SUICIDE: RoleDefinition(
        RoleName.SUICIDE, Faction.NEUTRAL, None,
        description="Maqsadi: kunduzgi ovoz berish (osib o'ldirilish) "
                     "orqali yo'q qilinish. Shu tarzda o'lsa g'olib bo'ladi."),
    RoleName.VAGABOND: RoleDefinition(
        RoleName.VAGABOND, Faction.NEUTRAL, ActionType.WATCH,
        description="Kechasi bir o'yinchini kuzatadi va uning oldiga kimlar "
                     "tashrif buyurganini biladi."),
}


def role_def(name: RoleName) -> RoleDefinition:
    return ROLES[name]


# Roles that cast a vote in the shared Mafia night-kill.
MAFIA_KILLING_ROLES = (RoleName.DON, RoleName.MAFIA)

# Roles allowed to repeat within a single game (filler roles).
NON_UNIQUE_ROLES = {name for name, r in ROLES.items() if not r.unique}

# Anonymous activity-feed i18n keys for a just-submitted night action,
# keyed by (role, action_type, has_target) — role- and action-shaped, never
# naming WHO did it or WHO it was done to.
NIGHT_ACTION_ACTIVITY_KEYS: dict[tuple[RoleName, ActionType, bool], str] = {
    (RoleName.DON, ActionType.KILL, True): "night.mafia.kill_target_selected",
    (RoleName.DON, ActionType.KILL, False): "night.mafia.kill_skipped",
    (RoleName.MAFIA, ActionType.KILL, True): "night.mafia.kill_target_selected",
    (RoleName.MAFIA, ActionType.KILL, False): "night.mafia.kill_skipped",
    (RoleName.COMMISSIONER, ActionType.INVESTIGATE, True): "night.commissioner.investigated",
    (RoleName.COMMISSIONER, ActionType.SHOOT, True): "night.commissioner.kill_selected",
    (RoleName.DOCTOR, ActionType.PROTECT, True): "night.doctor.protected",
    (RoleName.MANIAC, ActionType.KILL, True): "night.maniac.kill_target_selected",
    (RoleName.MANIAC, ActionType.KILL, False): "night.maniac.kill_skipped",
    (RoleName.MISTRESS, ActionType.BLOCK, True): "night.mistress.blocked",
    (RoleName.VAGABOND, ActionType.WATCH, True): "night.vagabond.watched",
    (RoleName.LAWYER, ActionType.SHIELD, True): "night.lawyer.shielded",
}


def night_action_activity_key(role: RoleName, action_type: ActionType, has_target: bool) -> str:
    key = NIGHT_ACTION_ACTIVITY_KEYS.get((role, action_type, has_target))
    if key:
        return key
    return "night.generic.action_submitted"