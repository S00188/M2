# Mafia Gameplay Balance Revision — Reference Spec

This document was not present in the uploaded project ZIP for the second
audit. It's reconstructed here from the "IMPORTANT EXISTING GAMEPLAY
RULES" section of the second-audit task brief, which is the authoritative
description of what the prior revision session was required to implement
and what this session was required to preserve. It's included as the
reference spec `CHANGES.md` and the final report check against, per the
final deliverable's file list.

For what was actually verified against the code in *this* pass (bugs
found, fixes made, tests run), see `CHANGES.md` — this file is the spec,
not the audit log.

---

## 1. Day Discussion — Ready system

Day discussion must **not** be force-ended by an ordinary player.

Voting starts when:
- 100% of alive players are Ready, **or**
- the discussion timer expires.

Example (6 alive): 5/6 Ready → discussion continues. 6/6 Ready → voting
starts.

The frontend must use a Ready toggle, not an unrestricted "advance to
voting" button.

## 2. Tie → Revote

Default: `tie_rule = "revote"`.

First tie (e.g. A=4, B=4): revote only between A and B. The first-round
votes are cleared.

Second tie (e.g. A=4, B=4 again): no elimination, move to the next phase.

Never use earliest-submitted-vote, request arrival order, or network
latency as a tie-break.

## 3. Persistence

`GameState` has checkpoint persistence. Important game state must
survive a server restart. The project contains
`game_engine/persistence.py`, `services/checkpoint_service.py`, and a
`game_checkpoints` database table. This system must not be removed.

## 4. AFK / Reconnect

Existing AFK/reconnect behavior must never be changed. Hard requirement.

## 5. Role Assignment

Game start must be:

```
LOBBY -> ROLE_ASSIGNMENT (15 seconds, a real phase) -> NIGHT 1
```

## 6. Mafia tie-break

If Mafia kill votes are tied:
- If the Don is alive and participated in the tie, the Don's vote wins.
- Otherwise, seeded engine RNG chooses between the tied targets.

Never use vote submission order.

## 7. Bodyguard

Correct behavior: Mafia attacks Target -> Bodyguard protects Target ->
Target survives, Bodyguard dies, Mafia attacker survives. There is no
attacker trade. If Doctor protection also applies to the same target,
Doctor protection has priority.

## 8. Veteran

Veteran alert only kills hostile visitors. Hostile: Kill, Frame, Silence,
Douse. Non-hostile (must survive simply visiting): Doctor, Investigator,
Commissioner, Tracker, Watcher, Medium.

## 9. Gunner

2 total bullets maximum, 1 shot per day. Day 1 shot: allowed. Day 1
second shot: rejected. Day 2 shot: allowed.

## 10. Jester

Jester wins individually if lynched by Day voting. Jester winning does
not automatically end the entire game.

## 11. Survivor

Survivor wins individually if alive when the game ends.

## 12. Mafia balance

Exact Mafia count by player count:

| Players | Mafia |
|---|---|
| 6 | 2 |
| 7 | 2 |
| 8 | 2 |
| 9 | 3 |
| 10 | 3 |
| 11 | 3 |
| 12 | 3 |
| 13 | 4 |
| 14 | 4 |
| 15 | 4 |
| 16 | 5 |
| 17 | 5 |
| 18 | 5 |
| 19 | 5 |
| 20 | 6 |
| 21 | 6 |
| 22 | 6 |
| 23 | 7 |
| 24 | 7 |
| 25 | 7 |

At 25 players specifically: Don, 4x Mafioso, Consigliere, Silencer. No
Framer.

## 13. Arsonist

Arsonist must remain excluded from Classic compositions.
