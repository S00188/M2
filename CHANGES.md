# CHANGES — Eighth Pass: Premium Admin Panel + User Dashboard

Implements the "premium admin" feature end to end: a permission-based
multi-module **Admin panel** inside the Mini App (not the classic
web-style dashboard at `/admin-panel-classic`), a user-facing **Home /**
**Leaderboard** / **Language** dashboard, and the `/leaderboard` and
`/auth/language` API halves those screens talk to.

## Two-tier admin model, enforced server-side

- `backend/app/services/admin_service.py` — NEW. Super admins come from
  `ADMIN_TELEGRAM_IDS` (all permissions, listed with `is_super=true`,
  never demotable/blockable). Panel admins are `AdminUser` +
  `AdminPermission` rows. `PERMISSION_CATALOG` defines the 13 permissions
  across 7 modules; `require_admin_permission("module.action")` is an
  injected FastAPI dependency so **every** `/admin/*` route re-validates
  each request, and `is_admin`/`permissions` in the `/auth/telegram`
  response are display conveniences only.
- `backend/app/api/routes_admin_platform.py` — NEW. The 7 modules the
  panel needs: users (search/paging, detail with recent games, block/
  unblock, promote/demote), admins (add/remove, per-module permissions),
  texts (`start`/`group_added`/`lobby` × uz/ru/en live-edited),
  broadcasts (draft by audience → preview → send, one-shot),
  groups (enable/disable), statistics (7-day KPIs, top players, recent
  games) and settings (menu-button labels/visibility/reorder).
- `backend/app/api/routes_me.py` — public `GET /leaderboard` (top players
  by wins, `?limit=` 1–50, places/win-rates; active players only).
- `backend/app/api/routes_auth.py` — `POST /auth/language` so the WebApp's
  language switch shares the bot's single per-user language row
  (`i18n.set_user_language`); unsupported codes are coerced to the default,
  never raised.

## The Mini App becomes the dashboard

- `backend/app/static/index.html` — Home screen with avatar/name cards
  and buttons for their **Profile**, **Leaderboard**, **About** and
  **Language**; a Leaderboard screen; a Language chooser; and the full
  7-module Admin screen (9 panes, "Boshqaruv" / "O'yin nazorati" mode
  switch, permission-aware module tabs, `#confirmSheet` for destructive
  actions).
- `backend/app/static/app.js` — `renderHome`/`openLeaderboard`/
  `openAbout`/`openLanguage`/`markLanguage`/`setLanguage`; `boot()` now
  captures `is_bot_admin`/`is_super_admin`/`permissions` and routes a
  logged-in user with no group to the new Home instead of an empty lobby.
  The admin state machine (`adminMode` panel/control, `adminTabActive`,
  `adminCtrlTab`) hides module tabs the caller lacks permissions for, and
  every module drives its real REST routes end to end (users CRUD with
  confirm sheets, broadcasts create→preview→send, buttons reorder, texts
  save, statistics grids). The legacy super-admin game controls now render
  under "O'yin nazorati" with the same panel shell; the previously dead
  global toggle/list screens were removed.
- New dashboard/leaderboard/language I18N keys added to all three
  languages (`home_*`, `leaderboard_*`, `language_note`, `profile_loading`,
  `lb_games`).

## Bug fixes along the way

- `backend/app/api/routes_auth.py` — removed a stray `await` in front of
  `admin_service.is_super_admin(...)` (would've crashed every login once
  the admin service landed).

## Tests

- `backend/tests/test_admin_platform.py` — NEW, 19 tests covering the
  whole platform surface: plain users get 403 on every module; the
  login response carries `is_super_admin` and the *real* permission list;
  admin add/remove (duplicate rejected, demotion revokes access);
  permissions validated against the catalog; block → login 403 →
  unblock → login 200; super admins unbockable; texts list/edit and the
  change reflected in the bot's cache; texts/settings writes gated on
  `*.manage`; broadcast create/preview/send (Telegram delivery stubbed
  with a counting fake) including one-shot enforcement and empty-draft
  rejection; groups list/toggle by known chat and the 404 on unknown
  chats; statistics KPI shape; settings buttons labels/visibility/reorder
  and the matching `menu_button_order` change; `/auth/language` persists;
  `/leaderboard` ranks by wins and enforces its limit.

Full suite: **322 passed, 2 warnings** (303 prior + 19 new).
`node --check app/static/app.js` passes.

## Files changed

- `backend/app/services/admin_service.py` — new admin/permission service.
- `backend/app/api/routes_admin_platform.py` — new 7-module admin router.
- `backend/app/api/dependencies.py` — shared auth dependency.
- `backend/app/api/routes_me.py` — public `/leaderboard`.
- `backend/app/api/routes_auth.py` — super-admin flag in login, `await`
  fix, `POST /auth/language`.
- `backend/app/main.py` — router wiring.
- `backend/app/services/bot_config.py` — idempotent menu/text seeding.
- `backend/app/models/models.py`, `backend/app/i18n.py`,
  `backend/app/telegram_bot.py`, `backend/app/services/telegram_bot_api.py`,
  `backend/app/api/routes_admin.py` — panel support / admin menus.
- `backend/app/static/index.html`, `backend/app/static/app.js` — Home,
  Leaderboard, Language, About, and the 7-module Admin panel.
- `backend/tests/test_admin_platform.py` — new; `test_i18n.py`,
  `test_admin_bot_owner.py`, `tests/conftest.py` — extended.

---

# CHANGES — Seventh Pass: Player Profile + Bot Strengthening

## Personal profile dashboard

Every player now has their own profile screen in the Mini App, per
"har bir foydalanuvchining personal ma'lumotlari, o'yinlar tarixi va
statistikasini ko'ra oladigan shaxsiy paneli".

- `backend/app/api/routes_me.py` — NEW. `GET /me/profile` returns the
  logged-in user's `User` stats (games_played/wins/losses/winrate,
  town/mafia/neutral wins), their currently-active game (lobby phase,
  to-start count, room id) if they're in one, and their 5 most recent
  finished `GameHistory` rows (phase won, faction, host name, chat title
  via `KnownGroup`, timestamp). `GET /me/games?limit=` pages more history
  (default 20, max 50). Wired into `app/main.py` under the same
  `require_auth`-guarded router as the rest of the API. Data is scoped to
  the requesting user only — no other player's profile is reachable.
- `backend/app/static/index.html` — new `#profile` screen: header with
  back + refresh buttons, avatar/name/username/registration date card,
  a 3×2 stats grid (games, wins, losses, winrate + per-faction wins),
  the current-active-game card, and the recent-games list. Lobby top bar
  now has a profile button, and both win screens' "Bosh menu" button
  navigates to the profile instead of the dead end it used to hit.
- `backend/app/static/app.js` — `openProfile()`, `loadProfile()`,
  `renderProfile()` and friends; full uz/ru/en I18N coverage; `boot()`
  now routes `?view=profile` and Telegram's `startapp=profile` deep link
  straight into the profile, and a logged-in user with no `chat_id` in
  the URL lands on their profile instead of an erroring empty lobby.
- `backend/app/telegram_bot.py` + `backend/app/i18n.py` — new "👤
  Profilim" main-menu button whose inline `web_app` button opens the Mini
  App at `/?view=profile&lang=<lang>` (same auto-auth pattern as the
  Admin panel button). About text updated to mention it.

## One active game per group

`for-chat` now returns the group's existing match when one is live
(`app/api/routes_game.py` now reuses the cached `GameRegistry` lookup
instead of only checking at creation time), so a group can't be split
across two overlapping games. A fresh match is only created once the
previous one has been removed from the registry — after `GAME_OVER` the
finish/prune path frees the group for a replay.

## Group announcements + finished-game pruning

- `backend/app/services/notifications.py` — NEW. `notify_group_if_phase_changed`
  remembers each engine's phase and posts one public Telegram message per
  transition: "started" when Lobby → Role assignment, and "game over"
  with the winning faction and winners when the match ends. Group
  messages are language-neutral/public on purpose (single shared message,
  no per-reader preference), skip `botlab:` rooms and games with no chat,
  and are strictly best-effort — a failed send is logged, never raised.
  `notify_group_on_restart` posts a "game recovered after restart" line
  from `app/main.py`'s lifespan. All sends go through the new generic
  `send_telegram_message` in `app/services/telegram_bot_api.py`.
- `backend/app/websocket/handlers.py` — `FINISHED_GAME_GRACE_S` (10 min)
  plus `_finished_at`/`prune_finished_games`: a finished game is removed
  from the registry after the grace period (players still online can keep
  viewing the result meanwhile), only if it was persisted, and its
  announcement phase is forgotten so a restarted engine can't announce
  again. Removed a dead no-op loop that walked the registry each tick.

## Tests

- `tests/test_me_profile.py` (6) — profile zero-state, active-game
  listing, group-title resolution, `/me/games` paging, data-leak
  isolation, and a full-stack finished game reflected in the profile.
- `tests/test_notifications.py` (8) — start announcement, once-only,
  game-over faction/winners, botlab/chatless skip, restart recovery
  seeding, prune-after-grace, no-prune for unfinished/unpersisted games,
  and forget-after-prune.
- `tests/test_api_smoke.py` — two regressions: a finished game frees the
  group for a fresh match, and `for-chat` / the registry always agree on
  the single active match.
- `tests/test_i18n.py` — menu includes the new Profilim button and the
  about text renders it.
- `tests/conftest.py` — autouse `_no_group_notifications` patch keeps all
  Telegram sends off the network during the suite.

Full suite: **303 passed, 2 warnings** (verified green across repeated
runs). `node --check app/static/app.js` passes.

## Files changed

- `backend/app/api/routes_me.py` — new `/me` router.
- `backend/app/services/notifications.py` — new announcement module.
- `backend/app/main.py` — `me_router`, `notify_group_on_restart` on
  checkpoint recovery.
- `backend/app/services/telegram_bot_api.py` — generic
  `send_telegram_message`.
- `backend/app/websocket/handlers.py` — prune + notifications, dead code
  removed.
- `backend/app/static/index.html`, `backend/app/static/app.js` — profile
  screen, I18N, routing, lobby/win-screen entry points.
- `backend/app/telegram_bot.py`, `backend/app/i18n.py` — Profilim button.
- `backend/tests/test_me_profile.py`, `tests/test_notifications.py` —
  new; `tests/test_api_smoke.py`, `tests/test_i18n.py`,
  `tests/conftest.py` — extended; `README.md` — updated.

---

# CHANGES — Sixth Pass: Premium Role Reveal Animation

## Real 3D card flip replaces the fade-in

The reveal was previously a plain 0.5s `cardIn` fade with a slight
rotate, and the face-down→face-up swap was an instant `innerHTML`
replacement, so nothing actually "turned over". Rebuilt as a genuine
two-sided card:

- `index.html` — new `.rv-flipwrap` / `.rv-flipper` / `.rv-face`
  structure with `perspective:1400px`, `transform-style:preserve-3d` and
  `backface-visibility:hidden`. The back face (`.rv-back`, restyled to
  drop its own sizing since the flipper now owns dimensions) and the
  front face (`.rv-face-front`, pre-rotated 180°) turn together on one
  `rotateY` transition — a single transform, not a cross-fade, which is
  what makes it read as a physical card.
- A one-shot gold sheen (`rvSheen`) sweeps across the card as it lands,
  and the card gets its own weightier entrance curve (`rvCardLand`).
- The text below now arrives in a 6-step stagger (`rvRise`, nth-child
  delays) instead of appearing all at once with the card.
- Full `prefers-reduced-motion: reduce` branch disables the flip, the
  stagger and the sheen.

`app.js` — `revealRole()` now plays the flip first (putting the real
card art on the hidden front face), then renders the revealed layout on
completion, so the turn and the text stagger read as one continuous
move. Added a `roleFlipInProgress` guard so a double tap can't restart
or short-circuit the animation, a reduced-motion/no-flipper fast path,
a second success haptic on landing, and a re-read of `currentState`
after the timeout in case a fresh server push arrived mid-flip.

## Testing

Verified in a real headless Chromium (Playwright) by driving the actual
screen: face-down state renders with the flipper present, `revealRole()`
adds `.flipped` mid-animation, and the revealed `.rv-shown` layout is in
the DOM after it completes — with zero page errors. Also re-rendered the
Night, Day and Voting screens after the CSS change to confirm none of
them regressed (all three render clean, no console/page errors).

Backend suite: 199 passed, 1 pre-existing unrelated failure (same one
documented in earlier sections). `compileall`, `node --check` and the
HTML well-formedness check all pass.

## Files changed

- `backend/app/static/index.html` — flip structure + reveal animation CSS.
- `backend/app/static/app.js` — `revealRole()` flip sequencing,
  `roleFlipInProgress`, two-sided face-down markup.

---

# CHANGES — Fifth Pass: Activity Feed Placement

One-line layout fix requested after the fourth pass.

## Activity feed moved above the action panel

On Night, Day, and Voting screens, the "JONLI FAOLIYAT" (live activity)
panel was rendering *after* the action panel / player grid / chat, i.e.
below the fold of what the player actually needs to act on. Reordered the
HTML in `index.html` so all three screens now follow the same layout:
phase header → activity feed → action panel (night targets / day player
grid + chat / vote candidate list). No element IDs changed and no JS was
touched — `renderNightScreen`/`renderDayScreen`/`renderVoteScreen` and
`renderActivityFeed` all just fill the same containers in their new
positions, so this is a pure HTML reorder.

## Testing

Full suite: 199 passed, 1 pre-existing unrelated failure (same one
documented in earlier sections). HTML well-formedness check passes.

## Files changed

- `backend/app/static/index.html` — reordered `#night`, `#day`, `#vote`
  sections.

---

# CHANGES — Fourth Pass: Role Icons, Reveal Timer, Bot Chat

Small, targeted follow-ups requested after the third pass — no rework of
anything already shipped.

## Role icon fallback

Audited every one of the 20 role thumbnail/full images
(`app/static/cards/thumb/*.jpg`, `.../full/*.jpg`): all 20 exist, are
valid, uniquely-hashed JPEGs, and are served correctly over HTTP (`200
image/jpeg`, verified with a real request through the FastAPI test
client) — the static mount and the data are both fine. Since the cause
couldn't be reproduced from the code/server side, added a defensive
`onerror` fallback on every role `<img>` in `app.js` (`roleIconFallback()`)
so that if a thumbnail ever does fail to load in some deployment, it's
replaced with the existing SVG faction icon instead of a browser's
broken-image glyph — which is what "the icon disappeared" would actually
look like to a player. This can't make things worse and directly guards
against the reported symptom either way.

## Role-reveal 15s timer surfaced

The role_assignment phase already runs for 15 seconds server-side
(`ROLE_ASSIGNMENT_DURATION_S` in `managers.py`, unchanged) and the
face-down-card-tap-to-reveal flip animation already existed (`revealRole()`,
`.rv-back`/`.rv-shown`, `cardIn` keyframe) — neither needed building.
What was missing: the countdown itself was never shown on this screen, so
a player had no idea a window was closing. Added a `#roleTimer` element
reusing the existing `startCountdown()` helper, wired in wherever the
client enters `role_assignment`. No backend change.

## Bots now send simple day-discussion chat

`bot_players.py` already drove night actions and votes through the real
engine methods (`submit_night_action`, `submit_vote`) — the same public
API any player's WebSocket message goes through — so the new
`activity_feed` from the previous pass already covers bots automatically
with no extra work. The one gap: bots never spoke during
`DAY_DISCUSSION`. Added `_act_chat()`, following the exact same
call-the-real-engine-method pattern (`engine.send_chat_message`), staggered
per-bot the same way night actions are, sending exactly one line from a
short fixed list of bland, non-informational sentences (`BOT_CHAT_LINES`)
— deliberately not "smart" per the existing design note at the top of the
file about keeping bot play simple and legible.

The frontend already draws bot players identically to real ones (no
`is_bot` branch anywhere in `app.js`'s rendering), so this — together with
the activity feed already reaching bots — means bot games now look and
behave the same as real-player games throughout, without any frontend
change needed for that specific ask.

## Testing

- `test_bot_players.py::test_bots_send_exactly_one_simple_chat_message_per_day`
  — new; forces bot think-delays to elapse, drives the engine, and
  asserts every living bot sends exactly one message from the fixed line
  list, no more.
- Full suite: 199 passed, 1 pre-existing unrelated failure (same one
  documented in the prior section).
- `node --check app.js`, `python3 -m compileall`, HTML well-formedness —
  all pass.

## Files changed

- `backend/app/static/app.js` — `roleIconFallback()`; role_assignment
  countdown wiring.
- `backend/app/static/index.html` — `#roleTimer` element.
- `backend/app/game_engine/bot_players.py` — `BOT_CHAT_LINES`, `_act_chat()`.
- `backend/tests/test_bot_players.py` — new test.

---

# CHANGES — Third Pass: Phase UI + Anonymous Live Activity System

This pass implements the "complete phase UI + anonymous live activity
system" feature request on top of the previous two audits' baseline. It
does not re-describe or re-verify earlier fixes (see the sections below
this one).

## Role/action audit

Confirmed against the actual code (`roles.py`, `managers.py`,
`engine.py`) rather than assumed from `rollar-toliq.md` — that reference
doc turned out to be slightly *behind* the code in two places: the
Survivor lone-survivor win check and Jester's `individual_winners`
surfacing are both already correctly implemented (`WinConditionManager`
in `managers.py`), contrary to the doc's "unfixed inconsistencies"
section. Full 20-role matrix (faction/phase/action/optional/visibility)
is unchanged from `rollar-toliq.md` otherwise; no role behavior was
modified.

## New: anonymous, phase-scoped activity feed

- `app/game_engine/state.py` — new `GameState.activity_feed` list and
  `_activity_seq` counter. Each entry: `phase`, `phase_number`,
  `message_key`, plus a `visible_to` field (`"all"` or a list of
  player_ids) that is stripped before ever reaching a client.
- `app/game_engine/managers.py` — new `ActivityFeedManager`
  (`public()`, `to_players()`, `for_player()`). `PhaseManager.to_night/
  to_day/to_voting/to_revote/to_vote_results` and
  `NightResolver.resolve` now each emit a public transition or action
  event. Nothing here ever accepts an actor or target identity as a
  parameter — there is no code path that could leak one by accident.
- `app/game_engine/roles.py` — new `NIGHT_ACTION_ACTIVITY_KEYS` table
  mapping `(role, action_type, has_target)` to an i18n message key
  (e.g. `night.mafia.kill_target_selected`), plus a safe generic
  fallback for any future role/action combination not yet listed.
- `app/game_engine/engine.py` — `submit_night_action` now emits the
  corresponding anonymous feed entry the instant an action is recorded.
  `get_player_view()` exposes the pre-filtered `activity_feed` for the
  requesting player.

## New: Mafia/Serial Killer "choose not to attack"

- `submit_night_action` now accepts `target_id=None` for `KILL`
  specifically (previously only `IGNITE`/`ALERT` could omit a target).
  Verified this needed no resolver change: `_resolve_mafia_target`
  already filters out `None` targets, and the Serial Killer's kill
  check already guards on `a.target_id`.
- `get_player_view()` exposes a new `night_action_can_skip_target` flag
  so the frontend knows which roles get a "don't attack" button,
  without hardcoding role names client-side.

## Frontend: Night/Day/Voting UI rebuilt

- Removed the two large embedded base64 JPEG background images from the
  Night and Day screens (`index.html` dropped from ~176KB to ~68KB).
  Replaced with a card/panel layout reusing CSS that was already staged
  in the stylesheet (`.phasehead`, `.activityfeed`, `.actionstatus`,
  `.skipbtn`) but not yet wired to any HTML or JS.
- Phase header now always shows phase + number (`NIGHT 2`, `DAY 3`,
  `DAY 3 — VOTING`, `DAY 3 — REVOTE`) — never a bare "Night"/"Day".
- Live activity feed renders under the action panel on Night, Day, and
  Voting screens, segmented by `(phase, phase_number)` so Night 1's
  events never mix with Day 1's or Night 2's, and keeps updating after
  the player has already acted — the screen no longer goes static.
- Night action panel shows a "Bu kecha hujum qilmaslik" (don't attack
  tonight) button when `night_action_can_skip_target` is true.
- New `ACTIVITY_I18N` dictionary (uz/ru/en) in `app.js` mapping every
  message_key the backend can emit to `{emoji, text}` — the only place
  a message_key becomes user-facing text.

## Testing

- `backend/tests/test_activity_feed.py` — 13 new unit tests against
  `GameEngine` directly: proves (via `json.dumps` + substring search on
  the whole serialized feed, not just spot checks) that no player_id or
  target_id ever appears in any player's feed view, that investigation
  results stay private, that Night 1/Day 1/Night 2 segments don't mix,
  and that Mafia/Serial Killer's explicit no-attack is recorded and
  visible anonymously.
- `backend/tests/test_activity_feed_e2e.py` — 1 new full-stack test
  through the real `/ws/games/{id}` WebSocket endpoint (not just the
  bare engine), confirming the JSON actually serialized over the wire
  contains `activity_feed` and never a player_id, in the same shape
  `app.js` expects.
- Fixed a test-isolation bug discovered while writing the e2e test:
  an earlier draft used 6 concurrent WebSocket connections and closed
  them all against a still-live (non-`GAME_OVER`) game right as
  `TestClient`'s own lifespan was tearing down the shared DB engine,
  intermittently racing an in-flight `save_checkpoint()` write and
  crashing the entire test session (not just that one test) with
  "Cannot operate on a closed database". Fixed by scoping the test to a
  single socket (matching the existing reliable pattern already in
  `test_api_smoke.py`) and explicitly removing the game from the
  registry before the test function returns. Verified stable across 5
  repeated full-suite runs in both forward and reverse file order.

## Test execution

Real `pytest` (not a stdlib shim, unlike the prior two passes, which
found no installable dependencies) — `fastapi`, `sqlalchemy`,
`aiosqlite`, `pydantic`, `httpx`, `pytest-asyncio` all installed from
PyPI without issue in this environment. Full suite:

```
198 passed, 1 failed in ~8-9s
```

The 1 failure (`test_api_smoke.py::test_full_lobby_flow_create_join_start`)
is **pre-existing and unrelated to this pass** — confirmed by running the
suite before making any changes. The test asserts `phase == "night"`
immediately after `/start`, but the engine correctly enters the 15-second
`ROLE_ASSIGNMENT` phase first (a deliberate, pre-existing, documented
feature — see `PhaseManager.to_role_assignment` and its own docstring;
another test in the very same file, `test_websocket_delivers_lobby_state_
then_starts_the_game`, already asserts the correct `role_assignment`
phase here). Not fixed in this pass since it is outside this feature's
scope; the one-line fix is `body["phase"] == "role_assignment"`.

Also run: `python3 -m compileall app tests` (pass, all backend files),
`node --check app/static/app.js` (pass), and a Python `html.parser`
well-formedness check on `index.html` (pass).

## Files changed

- `backend/app/game_engine/state.py` — `activity_feed`, `_activity_seq`.
- `backend/app/game_engine/managers.py` — `ActivityFeedManager`; phase
  transition and night-resolution activity emission.
- `backend/app/game_engine/roles.py` — `NIGHT_ACTION_ACTIVITY_KEYS`,
  `night_action_activity_key()`.
- `backend/app/game_engine/engine.py` — no-target `KILL` submission;
  activity emission in `submit_night_action`; `activity_feed` and
  `night_action_can_skip_target` in `get_player_view()`.
- `backend/app/static/index.html` — Night/Day/Voting screens rebuilt;
  removed embedded base64 hero images.
- `backend/app/static/app.js` — `ACTIVITY_I18N`, `renderActivityFeed()`,
  `activityLine()`; `renderNightScreen`/`renderDayScreen`/
  `renderVoteScreen` updated for phase headers, feed, and the skip
  button.
- `backend/tests/test_activity_feed.py` — new, 13 tests.
- `backend/tests/test_activity_feed_e2e.py` — new, 1 test.

---

# CHANGES — Second Audit Bug Fixes

This document covers only the work done in this pass: fixing the 7 bugs
found during the second audit, plus the tests and full regression check
that audit required. It assumes the prior 13-point gameplay-balance
revision (see `Mafia_Gameplay_Balance_Revision_Prompt.md`) as a baseline
and does not re-describe that work.

Every fix below was verified against the actual code in this ZIP, not
assumed correct from the audit description — in two cases (Bug 2, Bug 5)
the real root cause was narrower or different from how the audit
described the symptom, and the fix targets the actual cause.

---

## Bug 1 — Invalid votes crashed the WebSocket connection

**Root cause confirmed.** `VoteManager.submit_vote()` in
`app/game_engine/managers.py` raised a plain `ValueError` for every
expected rejection (dead voter, dead target, wrong phase, wrong revote
candidate, self-vote, silenced voter). `app/websocket/handlers.py` only
catches `EngineError`. A `ValueError` is not an `EngineError`, so it
escaped the handler's `try/except` entirely and would take the whole
WebSocket connection down.

There was also a second, worse case the audit didn't name explicitly: an
**invalid `target_id`** (one that isn't a real player at all) hit
`state.players[target_id].alive` directly and raised a bare `KeyError` —
not even the old `ValueError`. Same crash, one line earlier.

**Fix — where `EngineError` lives.** `EngineError` was defined in
`engine.py`, which imports from `managers.py`. Importing it back into
`managers.py` would create `engine.py <-> managers.py` circular import.
Moved the class to `app/game_engine/state.py` — a leaf module both
already depend on with no back-reference — and re-imported it into
`engine.py` so every existing caller (`routes_game.py`, `routes_admin.py`,
which do `from app.game_engine.engine import EngineError`) keeps working
unchanged. Verified directly: `EngineError` imported from `engine` and
from `state` are the same class object, and there's no import cycle.

**Fix — the checks themselves.** All six `raise ValueError(...)` calls in
`VoteManager.submit_vote` are now `raise EngineError(...)`. Added an
explicit "Unknown player" / "Invalid target" check before the
`state.players[target_id]` lookup so a bogus ID gets a clean `EngineError`
instead of a `KeyError`.

**Tests:** `tests/test_second_audit_fixes.py` —
`test_invalid_target_id_raises_engine_error_not_crash`,
`test_dead_voter_raises_engine_error`,
`test_dead_target_raises_engine_error`,
`test_vote_outside_voting_phase_raises_engine_error`,
`test_wrong_revote_candidate_raises_engine_error`,
`test_self_vote_raises_engine_error_when_disabled`,
`test_silenced_voter_raises_engine_error`,
`test_valid_vote_after_a_rejected_one_still_works` (proves the connection/
player isn't taken down by the earlier rejection).

---

## Bug 2 — Game-over persistence could run more than once

**Root cause confirmed, and narrower than the symptom description.**
`app/websocket/handlers.py`'s per-connection message loop runs
`if engine.state.phase == Phase.GAME_OVER: persist_finished_game(...)`
after **every** message received, with no guard — so any message at all
sent after the game ends (a stray retry, a reconnect handshake, anything
that reaches that point in the loop) re-runs persistence, regardless of
what that message actually was or whether it was itself rejected.

The background `phase_ticker` (also in `handlers.py`) turned out to
**already be safe**: it only calls `persist_finished_game` when `changed`
is `True`, which is only ever true on the exact tick where the game
transitions into `GAME_OVER` — never on a later tick while already in
that phase. So the bug is specific to the per-connection message loop,
not a general architectural gap.

**Fix.** Added `finished_persisted: bool = False` to `GameState`
(`app/game_engine/state.py`). `persist_finished_game()`
(`app/services/game_service.py`) now:
1. Returns immediately if `state.finished_persisted` is already `True`
   (cheap, no DB round trip — handles the common case, including the
   exact bug reported).
2. Otherwise checks whether a `Game` row with this `game_id` already
   exists in the DB before inserting, and if so just sets the flag and
   returns. This is a second, independent layer — it also covers the
   theoretical case of the checkpoint/persist race on server restart (see
   note below), not just repeated calls within one process.
3. Sets `state.finished_persisted = True` only after `session.commit()`
   succeeds.

**Why not just remove the game from the registry?** That was one of the
suggested options, but it would have been the wrong fix here: players can
still be connected via WebSocket after `GAME_OVER` to see the final
result screen and last words, and other code (`registry.get(game_id)` in
`routes_game.py`, `routes_admin.py`) expects to look the game up by ID
after it ends. Removing it from the registry immediately would break that
legitimate post-game viewing. The flag-based guard fixes the actual bug
without that side effect.

**Known pre-existing edge case, out of scope for this fix:** if the
server crashes between `persist_finished_game()` succeeding and the
checkpoint delete that follows it in the same handler, a `GAME_OVER`
checkpoint could theoretically be reloaded on restart. This was true
before this fix too and isn't one of the 7 audited bugs; the DB-existence
check above happens to also protect against it, but a full fix (e.g.
never checkpointing `GAME_OVER` states, or deleting the checkpoint
*before* persisting) would be a separate, deliberate change.

**Test:** `tests/test_second_audit_fixes.py` —
`test_finished_persisted_flag_blocks_second_persist_call`. This is a
**mock/behavioral test, not a real database test** — see "Test execution"
below for why, and "Persistence verification" for what this does and
doesn't prove.

---

## Bug 3 & 7 — Stale Bodyguard "trade" text and dead death-reason string

**Root cause confirmed.** The actual mechanic in `managers.py` is
already correct (no trade — Bodyguard dies, target survives, attacker
survives, Doctor priority over Bodyguard). The bug was purely in
player-facing text that still described the old mechanic:

- `app/game_engine/roles.py` — Bodyguard's `description` said "a lone
  attacker dies with them."
- `app/static/app.js` — the Bodyguard `ability` text in **all three**
  languages (`uz` in the base `ROLES` array, `ru`/`en` in `ROLE_I18N`)
  described the attacker dying too.
- `app/static/app.js` — `DEATH_REASON_FULL_UZ` still had an entry for
  `"killed intercepting a Bodyguard"`, a death reason the engine never
  actually produces anymore (it only ever emits `"died protecting a
  teammate"` for the Bodyguard's own death — checked directly against
  `DeathManager`/`NightResolver` in `managers.py`).

**Bonus find, same class of bug:** the Mafioso's `ability` text (`uz`,
`ru`, `en`) still said ties are settled by "whichever vote was submitted
first" when the Don is dead — directly contradicting the actual,
already-correct RNG tie-break (spec item 6) and the explicit "never
submission order" requirement. Fixed alongside the Bodyguard text since
it's the identical failure mode (correct code, stale description).

Also updated the equivalent Uzbek passages in `rollar-toliq.md` (the
design reference doc bundled in this ZIP) for consistency, though that
file isn't served to players at runtime.

**Fix.** Rewrote all of the above to describe the actual behavior:
Bodyguard dies, guarded player survives, attacker survives, no trade,
Doctor priority noted; Mafioso tie-break described as Don's-vote-wins-if-
he-participated, otherwise random. Removed the dead
`"killed intercepting a Bodyguard"` key entirely.

**Verification:** grepped the entire project (`.py`, `.js`, `.html`,
`.md`) for `trade`, `dies with`, `intercepting`, `birinchi yuborilgan`
("submitted first"), and equivalent Russian phrasing after the fix — no
remaining stale matches outside of comments correctly describing what was
removed, and test names/assertions that correctly enforce the *no-trade*
and *no-submission-order* rules going forward.

---

## Bug 4 — Dead, unrestricted `advance_to_voting()`

**Root cause confirmed.** `engine.py` still had an
`advance_to_voting()` method with no ready check and no host/admin check
— call it and voting starts immediately, full stop. Traced every caller:
it was not wired to any WebSocket message type or HTTP route. The only
live path from a player action to starting voting is
`advance_to_voting_if_ready()`, called either by the `ready_for_vote`
message handler (checks 100% ready) or by `force_advance_phase()` (checks
`_require_host_or_system` before calling `advance_to_voting_if_ready(force=True)`).
The two `tests/*.py` references were direct calls in test setup code, not
exercises of a real caller.

**Verdict: genuinely obsolete.** Removed the method entirely per the
audit's instruction. Updated the two test call sites
(`test_discussion_chat_and_stats.py`, a docstring in
`test_phase_automation.py`) to use `advance_to_voting_if_ready(force=True)`,
which is the legitimate host/admin-gated equivalent.

---

## Bug 5 — Unreachable branch in `WinConditionManager.check()`

**Root cause confirmed, and the actual bug is more than "dead code."**
The branch `if len(alive) == 1 and alive[0].role == SURVIVOR: ...` sat
**after** `if not mafia and not killing_neutrals: <Town wins>`. A lone
surviving Survivor makes `mafia`, `killing_neutrals`, **and** `town` all
empty (Survivor is a neutral role, counted in none of the three lists) —
so the Town-wins branch always matched first, and the dead branch below
it could never run.

This wasn't just unreachable code sitting harmlessly unused: it meant a
game that ends with a lone Survivor was **actively misreported** as
`WinResult(Faction.TOWN, winners=[], ...)` — Town declared the winner
with an empty winners list, while the Survivor's actual individual win
was silently dropped.

**Fix.** Moved the Survivor-alone check to run *first*, before the
Town-wins branch. This is the minimal correct fix: when this condition is
true, `mafia`/`killing_neutrals`/`town` are necessarily already empty (by
construction, since only one player is alive), so reordering doesn't
change the outcome of any other existing case — verified by running the
full pre-existing `test_win_conditions.py` suite unchanged and confirming
all cases still pass, plus new tests for the specific scenario.

**Tests:** `tests/test_second_audit_fixes.py` —
`test_lone_survivor_is_not_misreported_as_town_win`,
`test_town_win_with_survivor_also_alive_is_unaffected` (regression guard
for the ordinary "Town wins, Survivor also happens to be alive" case,
which must NOT be affected by this reordering).

---

## Bug 6 — Frontend didn't render `individual_winners`

**Root cause confirmed.** The backend has fully supported
`main_winner`/`individual_winners` since the original revision (`WinResult`
in `state.py`). But `renderWinScreen()` in `app.js` only ever read
`w.winners` — `w.individual_winners` was never referenced anywhere in the
rendering code. A Jester who won by being lynched, or a Survivor who made
it to the end, could be computed correctly server-side and still be
completely invisible on the shared game-over screen.

A second, related problem in the same area: `renderFinalRoster()` built
its winners/losers split from `w.winners` alone too, so an individual
winner would show up in the **losers** column on everyone's screen — even
though that same player's own stat card (`me.stats.won`, computed
server-side in `GameEngine.get_player_view`) already correctly counted
them as having won.

**Fix.**
- `app/static/index.html` — added a new `<p>` line (`#winIndividual` /
  `#winIndividualM`) to both win screens, next to the existing main-winner
  notice.
- `app/static/app.js` `renderWinScreen()` — computes
  `individual_winners` names the same way `winners` names are computed,
  and shows them on the new line **only when non-empty** — per the audit's
  explicit requirement not to show a misleading empty result when there
  are no individual winners.
- `app/static/app.js` `renderFinalRoster()` — the winners `Set` now
  includes both `w.winners` and `w.individual_winners`, so an individual
  winner correctly appears in the "G'OLIBLAR" (winners) roster group
  everywhere, matching what their own stats already said.

**Tests:** `tests/test_second_audit_fixes.py` —
`test_town_win_plus_jester_individual_winner`,
`test_mafia_win_plus_survivor_individual_winner`,
`test_town_win_plus_jester_and_survivor_both_individual_winners`,
`test_no_individual_winners_is_an_empty_list_not_omitted` (backend side —
confirms the data these frontend changes render is always a real `[]`,
never `None` or a missing field, which is what makes the frontend's
"hide when empty" logic safe). The frontend logic itself is plain
DOM/string code with no test harness in this project (no jsdom-style
frontend test infra exists here); verified by code review and by
`node --check app.js` for syntax, and by manually tracing both the
`individualList` truthy/falsy branches against the four example scenarios
in the bug report (Town+Jester, Mafia+Survivor, Town+Jester+Survivor,
no individual winners).

---

## Missing tests added

All added in `backend/tests/test_second_audit_fixes.py` (29 tests):

- **Mafia Don tie-break**: Don alive + participating in a tie wins it
  deterministically (checked across 10 RNG seeds); Don dead/abstained
  falls back to RNG and is verified to pick **both** tied targets across
  30 seeds (proof it isn't secretly "earliest vote wins," which would
  always pick the same one).
- **Jester + Survivor**: Town+Jester, Mafia+Survivor, and
  Town+Jester+Survivor combinations, plus a no-individual-winners case.
- **Mafia composition**: every single count from 6 to 25 checked
  individually against the exact table (not a sample), plus a dedicated
  check of the 25-player case (no Framer, exact role counts).
- **Ready**: 5/6 ready does not start voting, 6/6 does, and ready state
  resets on the next discussion phase.
- **Invalid vote**: all six rejection cases raise `EngineError`, plus a
  test proving a rejected vote doesn't stop the player from voting
  validly afterward.
- **Game-over persistence**: idempotency guard test (mock-only, see
  "Persistence verification" below).
- **Gunner** (added beyond the audit's explicit list, for full item #9
  regression confidence): Day 1 shot allowed → Day 1 second shot
  rejected → Day 2 shot allowed, and the exact out-of-bullets-after-two-
  shots case.
- **Two extra security-checklist tests**: a non-Gunner cannot shoot; the
  existing `test_citizen_has_no_night_action` pattern was already
  covered in `test_anticheat_and_views.py`.

---

## Full regression audit — summary

All 13 original items were re-verified against the actual code (not
assumed from the prior revision), either by tracing the code directly or
via the pre-existing/new test suite. See the final report for the
PASS/FAIL/PARTIAL/NOT RUN table. Headline findings from re-verification:

- **#4 AFK/Reconnect**: confirmed untouched — `git diff` against the
  original ZIP shows zero changes to `routes_game.py`, and
  `GameEngine.get_player_view` (the reconnection/hidden-info method) was
  not modified.
- **#12 Mafia balance**: hand-verified all 20 rows (6–25) against the
  spec table before writing any code — every single row in
  `compositions.py` already matched exactly, including the 25-player
  no-Framer case. No bug found here; only test coverage was missing
  (now added).
- **#13 Arsonist**: confirmed programmatically that `R.ARSONIST` appears
  in zero entries of `COMPOSITIONS`.
- **#3 Persistence**: confirmed the new `finished_persisted` field
  round-trips safely through `state_to_dict`/`state_from_dict` (it's
  simply never included, which is correct — checkpoints are only ever
  saved for non-`GAME_OVER` states, so the flag would never need to
  survive a checkpoint anyway).

---

## Test execution — what actually ran and why

**Environment constraints (verified, not assumed):** `pytest`, `fastapi`,
`sqlalchemy`, `aiosqlite`, and `pydantic` are all **not installed**, and
there is **no network access** in this environment (`pip install` and
`pip download` both fail with no matching distribution — confirmed by
running them, not inferred). This matches what the audit prompt itself
anticipated.

**What was done about it:** `app/game_engine/*` is pure Python/stdlib —
confirmed by grepping every import in that package. To actually execute
those tests (rather than just review them), I wrote a small pytest-shim
(`backend/tools/pytest_shim/`) implementing exactly the pieces the pure
tests use — `pytest.raises`, `pytest.approx`, `pytest.fixture` (accepted,
not auto-invoked), `pytest.mark` — plus a runner
(`backend/tools/run_pure_engine_tests_offline.py`) that imports each pure
test module and calls every `test_*` function directly. This is **not** a
pytest replacement and is clearly documented as such in its own
docstring; the moment real dependencies are available, `pytest -q` is the
right way to run this suite and this tooling becomes unnecessary (but
harmless to leave in place).

**Result:** `129 passed, 0 failed, 0 errored` — 100 pre-existing tests
across `test_voting.py`, `test_discussion_chat_and_stats.py`,
`test_mayor_gunner_phase_guard.py`, `test_mafia_chat.py`,
`test_compositions_and_roles.py`, `test_win_conditions.py`,
`test_night_resolution.py`, `test_phase_automation.py`,
`test_anticheat_and_views.py`, `test_admin_controls.py`, plus 29 new
tests in `test_second_audit_fixes.py`.

**What was NOT run, and why:** `test_admin_bot_owner.py`,
`test_api_smoke.py`, `test_bot_features.py`, `test_bot_players.py`
(imports `app.services.game_service`, which imports `sqlalchemy` at
module level), `test_chat_membership.py`, `test_i18n.py`,
`test_telegram_auth.py`, `test_telegram_webhook.py` — all of these
import FastAPI routes, SQLAlchemy models, or both, at module level or via
`conftest.py`'s autouse fixture. These were **not executed**, and no
result is claimed for them beyond `python3 -m py_compile` syntax
verification (all pass) and manual code review of the specific lines
relevant to each bug.

**Also run:** `python3 -m py_compile` against all 52 backend `.py` files
(pass), `node --check app.js` (pass — Node 22 is available in this
environment), and a basic HTML well-formedness parse of `index.html`
(pass).

---

## Persistence verification

**CODE REVIEW / MOCK TEST ONLY.**

The real `persist_finished_game()` function needs a live (or at least
importable) SQLAlchemy `AsyncSession` and the actual `Game`/`GamePlayer`/
`GameHistory`/`User` models, none of which can be imported in this
environment (`sqlalchemy` is not installed, no network to install it).

What was actually verified:
1. **Code review** of the real function in `app/services/game_service.py`
   after the fix — confirmed the guard structure (in-memory flag checked
   first, DB-existence check second, flag set only after a successful
   `commit()`) is what's actually in the file, not just described.
2. **Behavioral proxy test** (`test_finished_persisted_flag_blocks_second_persist_call`)
   against the real `GameState.finished_persisted` field (which needs no
   database) with a hand-written fake persist function mirroring the real
   one's guard logic, confirming the flag itself behaves correctly across
   repeated calls.
3. **Checkpoint round-trip check** confirming the new field doesn't break
   `state_to_dict`/`state_from_dict` (run directly, output captured: "round
   trip OK... finished_persisted default on restored: False").

This is **not** a substitute for running the real function against a real
(even in-memory SQLite) database and asserting on actual row counts in
`Game`/`GamePlayer`/`GameHistory` after a simulated stray post-game
message. That test should be added and run in an environment with
`sqlalchemy`/`aiosqlite` installed before treating this bug as fully
closed in production — the mock test here only proves the guard
mechanism itself is sound, not that it's wired correctly into every real
code path (e.g. the interaction with `save_checkpoint`'s own DB session).

---

## Files changed

- `backend/app/game_engine/state.py` — added `EngineError`, added
  `GameState.finished_persisted`.
- `backend/app/game_engine/engine.py` — import `EngineError` from
  `state.py` instead of defining it; removed `advance_to_voting()`.
- `backend/app/game_engine/managers.py` — `VoteManager.submit_vote` raises
  `EngineError` (not `ValueError`/`KeyError`); reordered the lone-Survivor
  win-condition branch.
- `backend/app/game_engine/roles.py` — corrected Bodyguard description.
- `backend/app/services/game_service.py` — idempotency guard in
  `persist_finished_game()`.
- `backend/app/static/app.js` — corrected Bodyguard + Mafioso i18n text
  (uz/ru/en), removed dead death-reason string, render
  `individual_winners` on the win screen and in the final roster.
- `backend/app/static/index.html` — added the individual-winners notice
  line to both win screens.
- `backend/tests/test_discussion_chat_and_stats.py`,
  `backend/tests/test_phase_automation.py` — updated the two call sites
  that used the removed `advance_to_voting()`.
- `backend/tests/test_second_audit_fixes.py` — new, 29 tests.
- `backend/tools/run_pure_engine_tests_offline.py`,
  `backend/tools/pytest_shim/` — new, offline test-running tool (see
  "Test execution" above).
- `rollar-toliq.md` — corrected the same stale Don-tie-break/Bodyguard-
  trade wording as `app.js`, in the design reference doc.
