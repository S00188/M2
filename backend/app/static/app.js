// ============================================================================
// Mafia Mini App — client
// Talks to the FastAPI backend over REST (auth + join) and WebSocket (live
// game state). Every screen render is driven by the server's state push —
// this file never invents game facts the server hasn't sent.
// ============================================================================

const API = ""; // same-origin: this file is served by the FastAPI app itself

let sessionToken = null;
let myTelegramId = null;
let gameId = null;
let myPlayerId = null;
let ws = null;
let wsRetryDelay = 1500;
let currentState = null;   // last "state" payload from the server
let selectedTarget = null; // currently-highlighted player in night/vote lists
let gamePaneFocusedOnce = false; // #17: landed the game screen on O'yin pane once
let winRevealShown = false; // whether the full-screen win-reveal card has already been shown this game
let countdownTimer = null;
let currentGamePhase = null; // the GAME_PHASES id currently shown in the "game" screen, or null when not in a match — read by resolveSyncTheme()

// ------------------------------------------------------- Telegram WebApp --
// One shared reference (several functions below used to do their own local
// `const tg = window.Telegram && window.Telegram.WebApp` — harmless
// duplication, but the BackButton needs a single owner so it isn't wired
// twice). Everything that navigates goes through go() below, which is also
// the only thing that touches BackButton.show()/.hide() — so the two can
// never drift out of sync with each other.
const tg = window.Telegram && window.Telegram.WebApp;
// Whichever screen boot() actually lands on first IS this session's root —
// it is NOT always "home". Opened from a group's join button, the session
// never touches "home" at all and starts straight on "lobby"; opened from
// the bot's Profile/Admin entry points, it starts on "profile"/"admin"
// with no "home" underneath it either. The previous version hardcoded
// "home" as the only root, so BackButton from any of those other three
// entry points would pop to an uninitialized "home" screen instead of
// closing — establishRoot() is what each entry point calls to declare
// itself, instead of that assumption.
let sessionRoot = "home";
let navHistory = [sessionRoot];
function establishRoot(id) {
  sessionRoot = id;
  navHistory = [id];
  if (tg && tg.BackButton) tg.BackButton.hide();
}

// ----------------------------------------------------------------- i18n ---
// Shared with the bot (app/i18n.py) via the language field on
// POST /auth/telegram, and via ?lang= for the bot's "Rollar" kiosk link —
// see applyLanguage() usage in boot() below. Covers the static UI chrome;
// role catalog desc/ability text lives in ROLE_I18N further down, next to
// the ROLES data it overrides.
let currentLang = "uz";
const I18N = {
  uz: {
    home_headline: "Har bir qaror muhim.", home_menu_label: "SHAXSIY KABINET",
    ballot_day: "KUN", ballot_revote: "QAYTA OVOZ",
    ballot_hint: "Nomzodni tanlang va ovozingizni tasdiqlang.",
    ballot_revote_hint: "Teng ovoz olgan nomzodlardan birini tanlang.",
    ballot_received: "Ovozingiz qabul qilindi. Boshqalarni kutamiz.",
    ballot_unavailable: "Bu bosqichda ovoz bera olmaysiz.", ballot_skip: "Betaraf qolish",
    home_intro_kicker: "STRATEGIYA · MULOQOT · MANTIQ",
    home_intro_text: "Do‘stlar davrasida mantiq va strategiya. Guruhingizga qo‘shiling, o‘z rolingizni o‘ynang.",
    chat_wait_discussion: "Chat kunduzgi muhokama vaqtida ochiladi.",
    chat_silenced: "Bugun sukut qilingansiz — xabar yubora olmaysiz",
    home_eyebrow: "Do'stlar davrasi", home_enter: "O'yinga kirish",
    home_rules_roles: "Qoidalar va rollar",
    home_notice: "Botni guruhingizga admin qiling va <b style=\"color:var(--gold)\">/start</b> buyrug'ini yuboring",
    lobby_title: "LOBBY", lobby_players_label: "O'yinchilar", lobby_start_btn: "O'YINNI BOSHLASH",
    lobby_start_hint: "Kamida 4 o'yinchi kerak",
    lobby_empty_slot: "Bo'sh joy", lobby_host_badge: "HOST",
    lobby_wait_host: "Admin boshlashini kuting",
    lobby_ready_hint: "Boshlash uchun tayyor",
    brp_title: "BOT ROLLARI", brp_note: "Har bir botga rol belgilang yoki “Avtomatik” qoldiring. Tanlovlar o'yinning ushbu tarkibi bilan chegaralanadi.", brp_auto: "🎲 Avtomatik", brp_you: "👑 Siz", brp_clear: "tanlovni olib tashlash",
    role_title: "SIZNING ROLINGIZ", role_understood_btn: "Tushundim",
    role_eyebrow: "Rollar taqsimlandi", role_fab: "Rolim",
    role_tap: "Ochish uchun bosing",
    role_tapsub: "Kartani faqat siz ko'rishingiz kerak. Atrofingizdagilar ekranga qaramaganiga ishonch hosil qiling.",
    role_skip: "Hozir emas \u2014 keyinroq ko'raman",
    role_secret: "Rolingizni istalgan vaqt ROLINGIZ paneli (Xabarlar yonidagi oynachalar) orqali qayta ko'rishingiz mumkin.",
    night_title: "TUN", night_action_label: "HARAKATINGIZ", day_title: "KUN",
    vote_title: "OVOZ BERISH", vote_submit_btn: "Ovozimni tasdiqlash",
    outcome_continue_btn: "Davom etish",
    roles_title: "ROLLAR", tab_all: "Hammasi", tab_mafia: "Mafia", tab_town: "Shahar", tab_neutral: "Neytral",
    nav_home: "Home", nav_lobby: "Lobby", nav_roles: "Rollar", nav_admin: "Admin",
    chat_placeholder: "Xabar yozing...", role_ability_label: "Qobiliyati",
    profile_title: "PROFIL", profile_stats_label: "STATISTIKA", profile_factions_label: "FAKSIYA G'ALABALARI",
    profile_active_label: "FAOL O'YINLAR", profile_recent_label: "SO'NGI O'YINLAR", profile_refresh: "YANGILASH",
    profile_joined: "Qo'shilgan", profile_gamesplayed: "O'YINLAR", profile_wins: "G'ALABALAR",
    profile_losses: "MAG'LUBIYATLAR", profile_winrate: "G'ALABA FOIZI", profile_banter: "Qisqa hazil",
    profile_none: "Hozircha o'yin yo'q", profile_noactive: "Faol o'yin yo'q", profile_lobby: "Lobbi",
    profile_playing: "O'yinda", profile_phase_role_assignment: "Rollar",
    profile_town: "Shahar", profile_mafia: "Mafia", profile_neutral: "Neytral",
    home_title: "MAFIA",
    home_btn_profile: "Mening profilim", home_btn_leaderboard: "Top / Reyting",
    home_btn_about: "Bot haqida",
    home_btn_language: "Til", home_btn_admin: "Admin Panel", home_btn_settings: "Mavzu",
    leaderboard_empty: "Hali hech kim o'yin yakunlamagan",
    leaderboard_you: "Siz", language_note: "Yangi til Bot va WebApp uchun ham qo'llaniladi.",
    profile_loading: "Yuklanmoqda...", lb_games: "o'yin",
    settings_title: "SOZLAMALAR", settings_theme_label: "MAVZU",
    theme_light: "Yorug' rejim", theme_light_desc: "Doimiy yorug' dizayn",
    theme_dark: "Qorong'i rejim", theme_dark_desc: "Doimiy qorong'i dizayn",
    theme_sync: "O'yinga moslashgan", theme_sync_desc: "Kunda yorug', tunda qorong'i",
    theme_system: "Telegramga moslashgan", theme_system_desc: "Telegram ilovangiz mavzusiga mos",
    theme_note_light: "Web App doimiy yorug' dizaynda turadi.",
    theme_note_dark: "Web App doimiy qorong'i dizaynda turadi.",
    theme_note_sync: "Kun bosqichida yorug', tun tushganda qorong'i. O'yin bo'lmaganda — yorug'.",
    theme_note_system: "Telegram ilovangiz qaysi mavzuda bo'lsa, shunga moslashadi.",
  },
  ru: {
    home_headline: "Каждое решение важно.", home_menu_label: "ЛИЧНЫЙ КАБИНЕТ",
    ballot_day: "ДЕНЬ", ballot_revote: "ПОВТОРНОЕ ГОЛОСОВАНИЕ",
    ballot_hint: "Выберите кандидата и подтвердите голос.",
    ballot_revote_hint: "Выберите одного из кандидатов с равным числом голосов.",
    ballot_received: "Ваш голос принят. Ожидаем остальных.",
    ballot_unavailable: "Вы не можете голосовать на этом этапе.", ballot_skip: "Воздержаться",
    home_intro_kicker: "СТРАТЕГИЯ · ОБЩЕНИЕ · ЛОГИКА",
    home_intro_text: "Логика и стратегия в кругу друзей. Присоединяйтесь к группе и играйте свою роль.",
    chat_wait_discussion: "Чат доступен во время дневного обсуждения.",
    chat_silenced: "Сегодня вы не можете отправлять сообщения.",
    home_eyebrow: "Круг друзей", home_enter: "Войти в игру",
    home_rules_roles: "Правила и роли",
    home_notice: "Сделайте бота админом группы и отправьте команду <b style=\"color:var(--gold)\">/start</b>",
    lobby_title: "ЛОББИ", lobby_players_label: "Игроки", lobby_start_btn: "НАЧАТЬ ИГРУ",
    lobby_start_hint: "Нужно минимум 4 игрока",
    lobby_empty_slot: "Свободно", lobby_host_badge: "ХОСТ",
    lobby_wait_host: "Ждём хоста",
    lobby_ready_hint: "Можно начинать",
    brp_title: "РОЛИ БОТОВ", brp_note: "Назначьте каждому боту роль или оставьте «Автоматически». Выбор ограничен составом этой игры.", brp_auto: "🎲 Автоматически", brp_you: "👑 Вы", brp_clear: "сбросить выбор",
    role_title: "ВАША РОЛЬ", role_understood_btn: "Понятно",
    role_eyebrow: "Роли распределены", role_fab: "Моя роль",
    role_tap: "Нажмите, чтобы открыть",
    role_tapsub: "Карту должны видеть только вы. Убедитесь, что никто не смотрит в экран.",
    role_skip: "Не сейчас \u2014 посмотрю позже",
    role_secret: "Свою роль можно в любой момент посмотреть в панели «ВАША РОЛЬ» (окно рядом с Сообщениями).",
    night_title: "НОЧЬ", night_action_label: "ВАШЕ ДЕЙСТВИЕ", day_title: "ДЕНЬ",
    vote_title: "ГОЛОСОВАНИЕ", vote_submit_btn: "Подтвердить голос",
    outcome_continue_btn: "Продолжить",
    roles_title: "РОЛИ", tab_all: "Все", tab_mafia: "Мафия", tab_town: "Город", tab_neutral: "Нейтральные",
    nav_home: "Главная", nav_lobby: "Лобби", nav_roles: "Роли", nav_admin: "Админ",
    chat_placeholder: "Напишите сообщение...", role_ability_label: "Способность",
    profile_title: "ПРОФИЛЬ", profile_stats_label: "СТАТИСТИКА", profile_factions_label: "ПОБЕДЫ ПО ФРАКЦИЯМ",
    profile_active_label: "АКТИВНЫЕ ИГРЫ", profile_recent_label: "НЕДАВНИЕ ИГРЫ", profile_refresh: "ОБНОВИТЬ",
    profile_joined: "Зарегистрирован", profile_gamesplayed: "ИГРЫ", profile_wins: "ПОБЕДЫ",
    profile_losses: "ПОРАЖЕНИЯ", profile_winrate: "ПРОЦЕНТ ПОБЕД", profile_banter: "Короткая шутка",
    profile_none: "Пока нет игр", profile_noactive: "Нет активных игр", profile_lobby: "Лобби",
    profile_playing: "Идёт игра", profile_phase_role_assignment: "Роли",
    profile_town: "Город", profile_mafia: "Мафия", profile_neutral: "Нейтральные",
    home_title: "МАФИЯ",
    home_btn_profile: "Мой профиль", home_btn_leaderboard: "Топ / Рейтинг",
    home_btn_about: "О боте",
    home_btn_language: "Язык", home_btn_admin: "Админ-панель", home_btn_settings: "Тема",
    leaderboard_empty: "Пока никто не закончил игру",
    leaderboard_you: "Вы", language_note: "Новый язык применяется и в боте, и в приложении.",
    profile_loading: "Загрузка...", lb_games: "игр",
    settings_title: "НАСТРОЙКИ", settings_theme_label: "ТЕМА",
    theme_light: "Светлый режим", theme_light_desc: "Всегда светлый дизайн",
    theme_dark: "Тёмный режим", theme_dark_desc: "Всегда тёмный дизайн",
    theme_sync: "По ходу игры", theme_sync_desc: "Днём светло, ночью темно",
    theme_system: "По теме Telegram", theme_system_desc: "Подстраивается под тему вашего Telegram",
    theme_note_light: "Web App всегда остаётся в светлом дизайне.",
    theme_note_dark: "Web App всегда остаётся в тёмном дизайне.",
    theme_note_sync: "Днём светло, ночью темно. Вне игры — светлый режим.",
    theme_note_system: "Подстраивается под тему вашего приложения Telegram.",
  },
  en: {
    home_headline: "Every decision matters.", home_menu_label: "YOUR DASHBOARD",
    ballot_day: "DAY", ballot_revote: "REVOTE",
    ballot_hint: "Choose a candidate and confirm your vote.",
    ballot_revote_hint: "Choose one of the tied candidates.",
    ballot_received: "Your vote was accepted. Waiting for the others.",
    ballot_unavailable: "You cannot vote in this phase.", ballot_skip: "Abstain",
    home_intro_kicker: "STRATEGY · CONVERSATION · LOGIC",
    home_intro_text: "Logic and strategy with friends. Join your group and play your part.",
    chat_wait_discussion: "Chat opens during the daytime discussion.",
    chat_silenced: "You cannot send messages today.",
    home_eyebrow: "Circle of Friends", home_enter: "Enter the game",
    home_rules_roles: "Rules and roles",
    home_notice: "Make the bot a group admin and send the <b style=\"color:var(--gold)\">/start</b> command",
    lobby_title: "LOBBY", lobby_players_label: "Players", lobby_start_btn: "START THE GAME",
    lobby_start_hint: "At least 4 players needed",
    lobby_empty_slot: "Empty seat", lobby_host_badge: "HOST",
    lobby_wait_host: "Waiting for the host",
    lobby_ready_hint: "Ready to start",
    brp_title: "BOT ROLES", brp_note: "Assign each bot a role, or leave \"Auto\". Picks are limited to this game's lineup.", brp_auto: "🎲 Auto", brp_you: "👑 You", brp_clear: "clear pick",
    role_title: "YOUR ROLE", role_understood_btn: "Got it",
    role_eyebrow: "Roles have been dealt", role_fab: "My role",
    role_tap: "Tap to reveal",
    role_tapsub: "This card is for your eyes only. Make sure nobody is looking at your screen.",
    role_skip: "Not now \u2014 I'll look later",
    role_secret: "You can reopen your role at any time in the ROLE panel (the window next to Messages).",
    night_title: "NIGHT", night_action_label: "YOUR ACTION", day_title: "DAY",
    vote_title: "VOTING", vote_submit_btn: "Confirm my vote",
    outcome_continue_btn: "Continue",
    roles_title: "ROLES", tab_all: "All", tab_mafia: "Mafia", tab_town: "Town", tab_neutral: "Neutral",
    nav_home: "Home", nav_lobby: "Lobby", nav_roles: "Roles", nav_admin: "Admin",
    chat_placeholder: "Type a message...", role_ability_label: "Ability",
    profile_title: "PROFILE", profile_stats_label: "STATISTICS", profile_factions_label: "FACTION WINS",
    profile_active_label: "ACTIVE GAMES", profile_recent_label: "RECENT GAMES", profile_refresh: "REFRESH",
    profile_joined: "Joined", profile_gamesplayed: "GAMES", profile_wins: "WINS",
    profile_losses: "LOSSES", profile_winrate: "WIN RATE", profile_banter: "Quick roast",
    profile_none: "No games yet", profile_noactive: "No active games", profile_lobby: "Lobby",
    profile_playing: "Playing", profile_phase_role_assignment: "Roles",
    profile_town: "Town", profile_mafia: "Mafia", profile_neutral: "Neutral",
    home_title: "MAFIA",
    home_btn_profile: "My profile", home_btn_leaderboard: "Top / Ratings",
    home_btn_about: "About the bot",
    home_btn_language: "Language", home_btn_admin: "Admin Panel", home_btn_settings: "Theme",
    leaderboard_empty: "Nobody has finished a game yet",
    leaderboard_you: "You", language_note: "The new language applies to both the bot and the app.",
    profile_loading: "Loading...", lb_games: "games",
    settings_title: "SETTINGS", settings_theme_label: "THEME",
    theme_light: "Light mode", theme_light_desc: "Always light design",
    theme_dark: "Dark mode", theme_dark_desc: "Always dark design",
    theme_sync: "Game Sync", theme_sync_desc: "Light by day, dark at night",
    theme_system: "System Auto", theme_system_desc: "Matches your Telegram app's theme",
    theme_note_light: "The Web App always stays in light design.",
    theme_note_dark: "The Web App always stays in dark design.",
    theme_note_sync: "Light during the Day phase, dark once Night falls. Light when no game is running.",
    theme_note_system: "Matches whichever theme your Telegram app is currently using.",
  },
};

function t(key) {
  const dict = I18N[currentLang] || I18N.uz;
  return dict[key] !== undefined ? dict[key] : (I18N.uz[key] || "");
}

// ------------------------------------------------------------- theme -----
// Four modes, picked in Settings and kept in localStorage — a per-device
// display preference only, never sent to the server:
//   light  - always light
//   dark   - always dark
//   sync   - follows the match: "night" -> dark, every other phase (and no
//            active match at all) -> light
//   system - follows Telegram's own client theme (tg.colorScheme), falling
//            back to the OS prefers-color-scheme when opened outside Telegram
// Every mode resolves down to just "light" or "dark", written onto
// <html data-theme="..."> — that's the only thing the CSS in index.html
// actually reads.
const THEME_STORAGE_KEY = "mafia_theme_mode";
const THEME_RESOLVED_CACHE_KEY = "mafia_theme_mode_resolved"; // read by the pre-paint inline script in <head>
const THEME_MODES = ["light", "dark", "sync", "system"];
let themeMode = "system";

function loadThemeMode() {
  let saved = null;
  try { saved = localStorage.getItem(THEME_STORAGE_KEY); } catch (e) {}
  themeMode = THEME_MODES.includes(saved) ? saved : "system";
}

function resolveSystemTheme() {
  if (tg && tg.colorScheme) return tg.colorScheme === "dark" ? "dark" : "light";
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return prefersDark ? "dark" : "light";
}

function resolveSyncTheme() {
  return currentGamePhase === "night" ? "dark" : "light";
}

function resolveTheme() {
  if (themeMode === "light") return "light";
  if (themeMode === "dark") return "dark";
  if (themeMode === "sync") return resolveSyncTheme();
  return resolveSystemTheme(); // "system"
}

function applyTheme() {
  const resolved = resolveTheme();
  document.documentElement.setAttribute("data-theme", resolved);
  try { localStorage.setItem(THEME_RESOLVED_CACHE_KEY, resolved); } catch (e) {}
  if (tg) {
    try {
      tg.setHeaderColor(resolved === "dark" ? "#0e1013" : "#ffffff");
      tg.setBackgroundColor(resolved === "dark" ? "#0e1013" : "#ffffff");
    } catch (e) {}
  }
  markThemeMode();
}

function setThemeMode(mode) {
  if (!THEME_MODES.includes(mode)) return;
  themeMode = mode;
  try { localStorage.setItem(THEME_STORAGE_KEY, mode); } catch (e) {}
  applyTheme();
}

function markThemeMode() {
  document.querySelectorAll("#settings .optbtn[data-theme-mode]").forEach((b) => {
    b.classList.toggle("on", b.dataset.themeMode === themeMode);
    b.setAttribute("aria-pressed", String(b.dataset.themeMode === themeMode));
  });
  const note = document.getElementById("themeModeNote");
  if (note) note.textContent = t("theme_note_" + themeMode);
}

let settingsReturnTo = null; // screen (or GAME_PHASES id) to go back to when Settings closes
function openSettings() {
  const active = document.querySelector(".screen.active");
  settingsReturnTo = active && active.id === "game" ? (currentGamePhase || "home") : (active ? active.id : "home");
  go("settings");
  window.scrollTo(0, 0);
  markThemeMode();
}
function closeSettings() {
  go(settingsReturnTo || "home");
}

// ------------------------------------------------- activity feed i18n ---
// Maps every message_key the backend's ActivityFeedManager can emit (see
// app/game_engine/roles.py NIGHT_ACTION_ACTIVITY_KEYS, and the
// phase-transition keys logged directly in managers.py PhaseManager) to
// a {emoji, uz, ru, en} entry. This is deliberately the ONLY place that
// turns a message_key into user-facing text — the feed never contains a
// literal string from the server, only a key, so translations live here
// exactly the same way ROLE_I18N overrides the static role catalog text
// further down in this file. Every line describes WHAT happened, never
// WHO did it or WHO it was done to (see the docstring on
// ActivityFeedManager in managers.py) — this is a hard product
// requirement, not a style choice, so no entry here may reference a
// player name or target.
const ACTIVITY_I18N = {
  "night.begins": { emoji: "\ud83c\udf19",
    uz: "Tun boshlandi.", ru: "\u041d\u0430\u0447\u0430\u043b\u0430\u0441\u044c \u043d\u043e\u0447\u044c.", en: "Night has begun." },
  "morning.begins": { emoji: "\ud83c\udf05",
    uz: "Ertalab boshlandi — tungi natijalar e'lon qilinadi.", ru: "\u041d\u0430\u0447\u0430\u043b\u043e\u0441\u044c \u0443\u0442\u0440\u043e \u2014 \u043e\u0431\u044a\u044f\u0432\u043b\u044f\u044e\u0442\u0441\u044f \u043d\u043e\u0447\u043d\u044b\u0435 \u0438\u0442\u043e\u0433\u0438.", en: "Morning has begun — the night's results are announced." },
  "day.begins": { emoji: "\u2600\ufe0f",
    uz: "Kun boshlandi.", ru: "\u041d\u0430\u0447\u0430\u043b\u0441\u044f \u0434\u0435\u043d\u044c.", en: "Day has begun." },
  "voting.begins": { emoji: "\u2696\ufe0f",
    uz: "Ovoz berish boshlandi.", ru: "\u041d\u0430\u0447\u0430\u043b\u043e\u0441\u044c \u0433\u043e\u043b\u043e\u0441\u043e\u0432\u0430\u043d\u0438\u0435.", en: "Voting has begun." },
  "voting.revote_begins": { emoji: "\u2696\ufe0f",
    uz: "Qayta ovoz berish: faqat teng ovoz olganlarga ovoz bering.",
    ru: "\u041f\u043e\u0432\u0442\u043e\u0440\u043d\u043e\u0435 \u0433\u043e\u043b\u043e\u0441\u043e\u0432\u0430\u043d\u0438\u0435: \u0433\u043e\u043b\u043e\u0441\u0443\u0439\u0442\u0435 \u0442\u043e\u043b\u044c\u043a\u043e \u0437\u0430 \u043d\u0438\u0447\u0435\u0439\u0448\u0438\u0445 \u043f\u043e\u0440\u043e\u0432\u043d\u0443.",
    en: "Revote: only tied candidates can be voted for." },
  "voting.resolved": { emoji: "\u2696\ufe0f",
    uz: "Ovoz berish yakunlandi.", ru: "\u0413\u043e\u043b\u043e\u0441\u043e\u0432\u0430\u043d\u0438\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e.", en: "Voting has been resolved." },
  "lynch.confirmation_begins": { emoji: "\u2694\ufe0f",
    uz: "Osib o'ldirishni tasdiqlash boshladi.", ru: "\u041d\u0430\u0447\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u0435 \u043a\u0430\u0437\u043d\u0438 \u0447\u0435\u0440\u0435\u0437 \u0433\u043e\u043b\u043e\u0441\u043e\u0432\u0430\u043d\u0438\u0435.", en: "Lynch confirmation has begun." },
  "kamikaze.strike_begins": { emoji: "\ud83d\udca5",
    uz: "Kamikadze zarbasi boshladi.", ru: "\u041d\u0430\u0447\u0430\u043b\u0441\u044f \u0443\u0434\u0430\u0440 \u043a\u0430\u043c\u0438\u043a\u0430\u0434\u0437\u0435.", en: "The kamikaze strike has begun." },
  "lynch.cancelled": { emoji: "\u2694\ufe0f",
    uz: "Shahar jazoni bekor qildi — hech kim osilmadi.", ru: "\u0413\u043e\u0440\u043e\u0434 \u043e\u0442\u043c\u0435\u043d\u0438\u043b \u043a\u0430\u0437\u043d\u044c \u2014 \u043d\u0438\u043a\u0442\u043e \u043d\u0435 \u043f\u043e\u0432\u0435\u0448\u0435\u043d.", en: "The town cancelled the lynch \u2014 nobody was hanged." },
  "night.resolved": { emoji: "\ud83c\udf19",
    uz: "Tungi harakatlar hal qilindi.", ru: "\u041d\u043e\u0447\u043d\u044b\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u044b.", en: "Night actions have been resolved." },
  "night.mafia.kill_target_selected": { emoji: "\ud83d\udd2a",
    uz: "Mafiya nishon tanladi.", ru: "\u041c\u0430\u0444\u0438\u044f \u0432\u044b\u0431\u0440\u0430\u043b\u0430 \u0446\u0435\u043b\u044c.", en: "Mafia chose a target." },
  "night.mafia.kill_skipped": { emoji: "\ud83d\udd2a",
    uz: "Mafiya bu kecha hujum qilmaslikni tanladi.", ru: "\u041c\u0430\u0444\u0438\u044f \u0440\u0435\u0448\u0438\u043b\u0430 \u043d\u0435 \u0430\u0442\u0430\u043a\u043e\u0432\u0430\u0442\u044c \u0441\u0435\u0433\u043e\u0434\u043d\u044f.", en: "Mafia chose not to attack tonight." },
  "night.commissioner.investigated": { emoji: "\ud83d\udd0e",
    uz: "Komissar tekshiruv o'tkazdi.", ru: "\u041a\u043e\u043c\u0438\u0441\u0441\u0430\u0440 \u043f\u0440\u043e\u0432\u0451\u043b \u0440\u0430\u0441\u0441\u043b\u0435\u0434\u043e\u0432\u0430\u043d\u0438\u0435.", en: "An investigation was performed." },
  "night.commissioner.kill_selected": { emoji: "\ud83d\udd2b",
    uz: "Komissar o'qqa tutdi.", ru: "\u041a\u043e\u043c\u0438\u0441\u0441\u0430\u0440 \u043e\u0442\u043a\u0440\u044b\u043b \u043e\u0433\u043e\u043d\u044c.", en: "The commissioner opened fire." },
  "night.doctor.protected": { emoji: "\ud83e\ude7a",
    uz: "Doktor kimnidir himoya qildi.", ru: "\u0414\u043e\u043a\u0442\u043e\u0440 \u043a\u043e\u0433\u043e-\u0442\u043e \u0437\u0430\u0449\u0438\u0442\u0438\u043b.", en: "Doctor went to protect someone." },
  "night.maniac.kill_target_selected": { emoji: "\ud83d\udd2b",
    uz: "Maniyak nishon tanladi.", ru: "\u041c\u0430\u043d\u044c\u044f\u043a \u0432\u044b\u0431\u0440\u0430\u043b \u0446\u0435\u043b\u044c.", en: "The maniac chose a target." },
  "night.maniac.kill_skipped": { emoji: "\ud83d\udd2b",
    uz: "Maniyak bu kecha hujum qilmaslikni tanladi.", ru: "\u041c\u0430\u043d\u044c\u044f\u043a \u0440\u0435\u0448\u0438\u043b \u043d\u0435 \u0430\u0442\u0430\u043a\u043e\u0432\u0430\u0442\u044c.", en: "The maniac chose not to attack tonight." },
  "night.mistress.blocked": { emoji: "\ud83d\udc8b",
    uz: "Bekorchi tun bo'ldi — kimningdir harakati bloklandi.", ru: "\u0411\u044b\u043b\u0430 \u043f\u0443\u0441\u0442\u0430\u044f \u043d\u043e\u0447\u044c \u2014 \u0447\u044c\u0435-\u0442\u043e \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u0431\u044b\u043b\u043e \u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d\u043e.", en: "Someone's action was blocked tonight." },
  "night.vagabond.watched": { emoji: "\ud83d\udc41",
    uz: "Sayyoh kuzaatib turdi.", ru: "\u0421\u0442\u0440\u0430\u043d\u043d\u0438\u043a \u0432\u0451\u043b \u043d\u0430\u0431\u043b\u044e\u0434\u0435\u043d\u0438\u0435.", en: "A watch action was performed." },
  "night.lawyer.shielded": { emoji: "\u2696\ufe0f",
    uz: "Advokat mijozini tanladi.", ru: "\u0410\u0434\u0432\u043e\u043a\u0430\u0442 \u0432\u044b\u0431\u0440\u0430\u043b \u043a\u043b\u0438\u0435\u043d\u0442\u0430.", en: "The lawyer picked a client." },
  "night.generic.action_submitted": { emoji: "\u2694\ufe0f",
    uz: "Bir harakat amalga oshirildi.", ru: "\u0411\u044b\u043b\u043e \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435.", en: "An action was performed." },
};

function activityLine(entry) {
  const meta = ACTIVITY_I18N[entry.message_key];
  if (!meta) return null;
  const text = meta[currentLang] || meta.uz;
  return { emoji: meta.emoji, text };
}

// Renders one phase's segment of the activity feed into a container.
// `feed` is the full activity_feed array from the server (already
// filtered server-side to what this player may see); `phase`/`number`
// pick out just the current phase's own segment (spec item 7 — Night 1's
// events must never mix with Day 1's). Newest entry on top.
function renderActivityFeed(containerId, feed, phase, number) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const segment = (feed || []).filter((e) => e.phase === phase && e.phase_number === number);
  if (segment.length === 0) {
    el.innerHTML = `
      <div class="activityfeed-head"><span class="livedot"></span>JONLI FAOLIYAT</div>
      <div class="activityfeed-empty">Hozircha hech qanday faoliyat yo'q...</div>`;
    return;
  }
  const rows = segment.slice().reverse().map((e) => {
    const line = activityLine(e);
    if (!line) return "";
    return `<div class="activityfeed-row"><span class="activityfeed-emoji">${line.emoji}</span><span>${escapeHtml(line.text)}</span></div>`;
  }).join("");
  el.innerHTML = `
    <div class="activityfeed-head"><span class="livedot"></span>JONLI FAOLIYAT</div>
    <div class="activityfeed-list">${rows}</div>`;
}

function applyLanguage(lang) {
  currentLang = I18N[lang] ? lang : "uz";
  const dict = I18N[currentLang];
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    if (dict[el.getAttribute("data-i18n")] !== undefined) el.textContent = dict[el.getAttribute("data-i18n")];
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    if (dict[el.getAttribute("data-i18n-html")] !== undefined) el.innerHTML = dict[el.getAttribute("data-i18n-html")];
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    if (dict[el.getAttribute("data-i18n-placeholder")] !== undefined) el.placeholder = dict[el.getAttribute("data-i18n-placeholder")];
  });
  if (typeof renderRoles === "function") {
    const activeTab = document.querySelector(".tab.active");
    renderRoles(activeTab ? activeTab.dataset.fac : "all");
  }
}

// ---------------------------------------------------------------- boot ----

document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  // Kiosk mode: the bot's "Rollar" menu button (app/telegram_bot.py) opens
  // this same page with ?view=roles so it lands straight on the role
  // catalog with nothing else navigable — no Telegram session needed for
  // that (it's static reference content), so this skips auth entirely
  // instead of failing on a missing/irrelevant initData.
  const requestedView = new URLSearchParams(location.search).get("view");
  if (requestedView === "roles") {
    document.body.classList.add("kiosk-roles");
    applyLanguage(new URLSearchParams(location.search).get("lang") || "uz");
    go("roles");
    return;
  }

  loadThemeMode();
  applyTheme(); // resolves the real theme (mode + Telegram/OS state) and overwrites the pre-paint guess from <head>

  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.BackButton) tg.BackButton.onClick(goBack);
    // Telegram fires this when the user flips their own client's theme —
    // only matters in "system" mode, everything else ignores it.
    if (tg.onEvent) tg.onEvent("themeChanged", () => { if (themeMode === "system") applyTheme(); });
  }
  // Fallback for "system" mode when opened in a plain browser (no Telegram).
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onSchemeChange = () => { if (themeMode === "system") applyTheme(); };
    if (mq.addEventListener) mq.addEventListener("change", onSchemeChange);
    else if (mq.addListener) mq.addListener(onSchemeChange);
  }

  const initData = tg && tg.initData ? tg.initData : "";
  if (!initData) {
    // Opened outside Telegram (e.g. a plain browser). The rest of the app
    // needs a verified Telegram identity, so it stops here rather than
    // pretending to be a real session.
    toast("Bu ilova faqat Telegram ichida, guruhdagi tugma orqali ochiladi.");
    return;
  }

  // The "Profil" entry (the blue Menu button → ?view=home, the bot's
  // ?startapp=profile/home deep links) must ALWAYS land on the home
  // dashboard with its Til / Mavzu / Profil buttons — even when the auth
  // call below is impossible right now (backend waking from a free-tier
  // cold start, a subscription gate, a transient error). That screen's own
  // menu (language, theme) works without any session, so we never leave
  // the user staring at an empty lobby screen.
  const startParam = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
  const wantedHome = ["home", "profile"].includes(requestedView) ||
                     ["home", "profile"].includes(startParam);

  try {
    const auth = await fetch(API + "/auth/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: initData }),
    }).then(mustOk);
    sessionToken = auth.session_token;
    myTelegramId = auth.telegram_user_id;
    window.__displayName = auth.display_name || "O'yinchi";
    window.__avatarUrl = auth.photo_url || null;
    window.__username = auth.username || null;
    isBotAdmin = !!auth.is_bot_admin;
    isSuperAdmin = !!auth.is_super_admin;
    myPermissions = auth.permissions || [];
    applyLanguage(auth.language || "uz");
  } catch (e) {
    if (e.code !== "subscription_required") toast(e.message || "Ilovani qayta oching.");
    if (wantedHome) {
      establishRoot("home");
      renderHome();
      go("home");
      window.scrollTo(0, 0);
    }
    return;
  }

  // Reconnect scenario (spec item 6): Telegram was closed and reopened, the
  // WebApp was refreshed, or the connection just dropped — in every one of
  // these the page reloads from scratch and this whole file re-runs, so
  // gameId/myPlayerId/ws are all back to null even though the match on the
  // server is still going. As long as the group's chat_id is still in the
  // URL (which it is: Telegram reopens this exact link), there's no reason
  // to make the player tap "Kirish" again — rejoin automatically and let
  // the very next "state" push put them back on whatever screen (night,
  // day, vote, ...) the game is actually on, with their real role, alive
  // status, and timer, exactly where they left off.
  // Opened from the bot's "Admin WebApp" button: a real authenticated
  // session was still required (every /admin/* route checks it), which is
  // why this lands here rather than in the auth-free kiosk branch above.
  // There's no group behind this entry point, so it never joins a lobby.
  if (requestedView === "admin") {
    if (!isBotAdmin) {
      toast("Siz bot admini emassiz.");
      return;
    }
    openAdminPanel({ standalone: true });
    return;
  }

  // Profile entry point: bot's deep-link ?startapp=profile opens this
  // Mini App for each user's personal stats/games screen — no group behind
  // it, just the player's own dashboard.
  if (wantedHome) {
    establishRoot("home");
    renderHome();
    go("home");
    window.scrollTo(0, 0);
    refreshHomeProfile();
    return;
  }

  if (currentChatId()) {
    await enterLobby();
  } else {
    // No group behind this session (opened the bot directly rather than
    // through a group's join button) — land on the personal dashboard.
    establishRoot("home");
    renderHome();
    go("home");
    window.scrollTo(0, 0);
  }
}

function currentChatId() {
  const fromTelegram = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
  if (fromTelegram && !["home", "profile", "roles", "admin"].includes(fromTelegram)) return fromTelegram;
  // Dev convenience only: ?chat_id=... in the URL when testing outside a
  // real bot-issued link. Telegram's own start_param is always preferred.
  return new URLSearchParams(location.search).get("chat_id");
}

// --------------------------------------------------------------- API/WS ---

function api(path, opts) {
  opts = opts || {};
  const headers = Object.assign(
    { "Content-Type": "application/json", "Authorization": "Bearer " + sessionToken },
    opts.headers || {}
  );
  return fetch(API + path, Object.assign({}, opts, { headers })).then(mustOk);
}

async function mustOk(res) {
  if (res.ok) return res.json();
  let detail = "Xatolik yuz berdi";
  try { detail = (await res.json()).detail || detail; } catch (e) {}
  if (detail && detail.code === "subscription_required") showSubscriptionGate(detail);
  const err = new Error(typeof detail === "string" ? detail : (detail.message || "Xatolik yuz berdi"));
  err.code = detail && detail.code;
  err.status = res.status;
  throw err;
}

function showSubscriptionGate(detail) {
  let gate = document.getElementById("subscriptionGate");
  if (!gate) {
    gate = document.createElement("div");
    gate.id = "subscriptionGate";
    gate.className = "subscription-gate";
    gate.setAttribute("role", "dialog");
    gate.setAttribute("aria-modal", "true");
    gate.setAttribute("aria-label", "Majburiy obuna");
    document.body.appendChild(gate);
  }
  gate.replaceChildren();
  const card = document.createElement("div");
  card.className = "card";
  const title = document.createElement("h2");
  title.textContent = "Kanallarga obuna bo‘ling";
  card.appendChild(title);
  const hint = document.createElement("p");
  hint.textContent = "Obunadan so‘ng tekshirish tugmasini bosing.";
  card.appendChild(hint);
  for (const channel of detail.channels || []) {
    if (!/^https:\/\/t\.me\//.test(channel.url)) continue;
    const link = document.createElement("a");
    link.className = "btn ghost";
    link.href = channel.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = channel.title;
    card.appendChild(link);
  }
  const check = document.createElement("button");
  check.className = "btn";
  check.textContent = "Obunani tekshirish";
  check.onclick = () => location.reload();
  card.appendChild(check);
  gate.appendChild(card);
  check.focus();
}

async function enterLobby() {
  const chatId = currentChatId();
  if (!chatId) {
    toast("Guruh aniqlanmadi. Iltimos, botning guruhdagi tugmasi orqali kiring.");
    return;
  }
  if (!sessionToken) { toast("Hali ulanmoqda, biroz kuting..."); return; }
  establishRoot("lobby");
  go("lobby");
  try {
    const res = await api("/games/for-chat", {
      method: "POST",
      body: JSON.stringify({
        chat_id: chatId,
        display_name: window.__displayName || "O'yinchi",
        avatar_url: window.__avatarUrl || null,
      }),
    });
    gameId = res.game_id;
    myPlayerId = res.player_id;
    connectWS();
  } catch (e) {
    toast(e.message);
  }
}

let wsRetryTimer = null;
function connectWS() {
  clearTimeout(wsRetryTimer);
  if (!gameId || !sessionToken) return;
  if (ws) {
    ws.onclose = null;
    ws.onerror = null;
    try { ws.close(); } catch (e) {}
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${proto}://${location.host}/ws/games/${gameId}?token=${encodeURIComponent(sessionToken)}`);
  ws = socket;
  socket.onopen = () => {
    if (ws !== socket) return;
    wsRetryDelay = 1500;
    setConnBanner(false);
  };
  socket.onmessage = (ev) => {
    if (ws !== socket) return;
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type === "state") {
      currentState = msg.state;
      render();
    } else if (msg.type === "error") {
      toast(msg.message);
    } else if (msg.type === "game_stopped") {
      gameId = null;
      currentState = null;
      socket.onclose = null;
      socket.close();
      setConnBanner(false);
      toast("O‘yin to‘xtatildi");
      go("home");
    }
  };
  socket.onclose = (ev) => {
    if (ws !== socket || !gameId) return;
    if ([4000, 4001, 4401, 4403, 4404].includes(ev.code)) {
      setConnBanner(false);
      toast(ev.code === 4001 ? "O‘yin boshqa oynada ochildi" : "O‘yinga qayta kirishingiz kerak");
      return;
    }
    setConnBanner(true);
    wsRetryTimer = setTimeout(connectWS, wsRetryDelay + Math.random() * 400);
    wsRetryDelay = Math.min(wsRetryDelay * 1.6, 15000);
  };
  socket.onerror = () => { try { socket.close(); } catch (e) {} };
}

function send(type, extra) {
  if (!ws || ws.readyState !== WebSocket.OPEN) { toast("Aloqa yo'q — qayta ulanmoqda..."); return; }
  ws.send(JSON.stringify(Object.assign({ type }, extra || {})));
}

function setConnBanner(show) {
  document.getElementById("connBanner").classList.toggle("show", show);
}

// ------------------------------------------------------------- toast/nav --

let toastTimer = null;
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

const screens = () => [...document.querySelectorAll(".screen")];
const GAME_PHASES = ["morning", "night", "day", "vote", "lynch", "kamikaze", "outcome"];

// Every screen change funnels through here, so this is also the only place
// that touches navHistory / BackButton — nothing else needs to know either
// exists.
function _pushHistory(id) {
  if (id === sessionRoot) {
    // Landing back on this session's root always clears the trail — e.g.
    // after a game ends and the player taps "Bosh menyu", there's nothing
    // upstream of that worth going "back" to.
    navHistory.length = 0;
    navHistory.push(sessionRoot);
  } else if (navHistory[navHistory.length - 1] !== id) {
    // Guards against re-renders of the *same* screen piling up duplicate
    // entries — go("game") fires on every websocket state push while a
    // match is live, not just when the player actually navigates.
    navHistory.push(id);
  }
  if (tg && tg.BackButton) {
    if (navHistory.length > 1) tg.BackButton.show(); else tg.BackButton.hide();
  }
}

function goBack() {
  if (navHistory.length <= 1) return;
  navHistory.pop();
  go(navHistory[navHistory.length - 1]);
}

function go(id) {
  const destination = GAME_PHASES.includes(id) ? "game" : id;
  const entering = !document.getElementById(destination)?.classList.contains("active");
  document.body.classList.toggle("lobby-view", id === "lobby" || id === "admin");
  if (GAME_PHASES.includes(id)) {
    currentGamePhase = id; // read by resolveSyncTheme() in Game Sync theme mode
    screens().forEach((s) => s.classList.toggle("active", s.id === "game"));
    document.querySelectorAll("[data-nav]").forEach((b) => b.classList.remove("active"));
    showPhaseGroup(id);
    // The panel must be visible before measuring its width.
    if (entering || !gamePaneFocusedOnce) {
      gamePaneFocusedOnce = true;
      scrollToPane("game", true);
    }
    if (themeMode === "sync") applyTheme();
    if (entering) window.scrollTo(0, 0);
    // Collapsed to one "game" stop (see _pushHistory) — night/day/vote/etc
    // are phases the server drives, not stops the player picked, so Back
    // should leave the match rather than rewind through finished phases.
    _pushHistory("game");
    return;
  }
  currentGamePhase = null; // left the match view — Game Sync theme mode settles back to light
  screens().forEach((s) => s.classList.toggle("active", s.id === id));
  document.querySelectorAll("[data-nav]").forEach((b) => b.classList.toggle("active", b.dataset.nav === id));
  if (themeMode === "sync") applyTheme();
  if (entering) window.scrollTo(0, 0);
  _pushHistory(id);
}
function showPhaseGroup(phase) {
  const container = document.getElementById("gamepanels");
  if (container.dataset.phase === phase) return;
  container.dataset.phase = phase;
  ["pg-morning", "pg-night", "pg-day", "pg-vote", "pg-lynch", "pg-kamikaze", "pg-outcome"].forEach((pg) => {
    const el = document.getElementById(pg);
    if (!el) return;
    if (pg === "pg-" + phase) {
      el.style.display = "";
      el.classList.add("phase-enter");
    } else {
      el.style.display = "none";
      el.classList.remove("phase-enter");
    }
  });
}
let selectedGamePane = "game";
function scrollToPane(pane, immediate = false) {
  const gp = document.getElementById("gamepanels");
  if (!gp) return;
  const idx = pane === "chat" ? 0 : pane === "cabinet" ? 2 : 1;
  selectedGamePane = pane;
  gp.scrollTo({ left: gp.clientWidth * idx, behavior: immediate || window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  // Highlight the active nav button
  document.querySelectorAll("#gameNav button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.pane === pane);
  });
}

// Swipes and button presses share the same navigation state.
const gamePanels = document.getElementById("gamepanels");
let paneScrollFrame = 0;
gamePanels.addEventListener("scroll", () => {
  cancelAnimationFrame(paneScrollFrame);
  paneScrollFrame = requestAnimationFrame(() => {
    if (!gamePanels.clientWidth) return;
    selectedGamePane = ["chat", "game", "cabinet"][Math.round(gamePanels.scrollLeft / gamePanels.clientWidth)] || "game";
    document.querySelectorAll("#gameNav button").forEach(btn =>
      btn.classList.toggle("active", btn.dataset.pane === selectedGamePane));
  });
}, { passive: true });
window.addEventListener("resize", () => {
  if (document.getElementById("game").classList.contains("active")) scrollToPane(selectedGamePane, true);
});

// The lobby's top-right button used to be "share invite", which had no job
// left once the bot became the only way into a match — every player already
// arrives through the group's join button. It now opens the role catalog,
// the one reference players actually reach for while waiting in the lobby.
function openRolesFromLobby() {
  document.getElementById("roleDetail").classList.remove("show");
  go("roles");
}

// ----------------------------------------------------------- profile ----
let profileChats = [];  // active games' chat_ids from /me/profile

function openProfile() {
  establishRoot("profile");
  go("profile");
  loadProfile();
}

function profileExit() {
  // From a chat: return to lobby. From standalone (bot menu) / no-chat: close.
  const chatId = currentChatId();
  if (chatId && chatId !== "profile") { go("lobby"); return; }
  if (tg && tg.close) { tg.close(); } else { go("lobby"); }
}

function profileAvatarStyle(u) {
  if (u.photo_url) return `background-image:url('${u.photo_url}')`;
  const hue = Math.abs(hashStr(u.display_name || "?")) % 360;
  return `background:linear-gradient(160deg, hsl(${hue} 45% 38%), hsl(${hue} 55% 20%));
    display:flex;align-items:center;justify-content:center`;
}
function profileInitial(u) { return (u.display_name || u.username || "?").trim().charAt(0).toUpperCase(); }

async function loadProfile() {
  if (!sessionToken) return;
  try {
    const data = await api("/me/profile");
    renderProfile(data);
  } catch (e) {
    toast(e.message || "Profilni yuklashda xatolik");
  }
}

function renderProfile(data) {
  lastProfileData = data;
  const u = data.user || {};
  const st = data.stats || {};
  // Avatar
  const avatar = document.getElementById("profileAvatar");
  if (avatar) {
    avatar.style.cssText = profileAvatarStyle(u);
    avatar.textContent = profileInitial(u);
    avatar.style.display = "flex";
  }
  const pn = document.getElementById("profileName");
  if (pn) pn.textContent = u.display_name || "—";
  const pu = document.getElementById("profileUsername");
  if (pu) pu.textContent = u.username ? ("@" + u.username) : (u.telegram_user_id ? ("ID: " + u.telegram_user_id) : "");
  const pj = document.getElementById("profileJoined");
  if (pj) pj.textContent = u.created_at ? (t("profile_joined") + ": " + new Date(u.created_at).toLocaleDateString()) : "";
  // Stats
  const statsEl = document.getElementById("profileStats");
  if (statsEl) {
    const rows = [
      [st.games_played || 0, t("profile_gamesplayed")],
      [st.wins || 0, t("profile_wins")],
      [st.losses || 0, t("profile_losses")],
      [st.win_rate != null ? st.win_rate + "%" : "—", t("profile_winrate")],
    ];
    statsEl.innerHTML = rows.map(([val, label]) =>
      `<div class="statbox"><b>${escapeHtml(String(val))}</b><span>${label}</span></div>`).join("");
  }
  // Faction wins
  const fwEl = document.getElementById("profileFactionWins");
  if (fwEl) {
    fwEl.innerHTML = [
      [st.town_wins || 0, t("profile_town"), "var(--town-hi)"],
      [st.mafia_wins || 0, t("profile_mafia"), "var(--red-hi)"],
      [st.neutral_wins || 0, t("profile_neutral"), "var(--neutral-hi)"],
    ].map(([v, label, col]) =>
      `<div class="statbox"><b style="color:${col}">${v}</b><span>${label}</span></div>`).join("");
  }
  // Active games
  profileChats = [];
  const activeEl = document.getElementById("profileActiveGames");
  if (activeEl) {
    const games = (data.active_games || []).slice(0, 5);
    if (games.length === 0) {
      activeEl.innerHTML = `<div class="profile-empty">${t("profile_noactive")}</div>`;
    } else {
      activeEl.innerHTML = games.map((g) => {
        if (g.chat_id) profileChats.push(g.chat_id);
        const phaseLabel = PHASE_LABEL_UZ[g.phase] || g.phase || "—";
        const hue = Math.abs(hashStr(g.game_id || "")) % 360;
        return `<div class="pgame-row">
          <div class="pgame-avatar" style="background:linear-gradient(160deg, hsl(${hue} 45% 38%), hsl(${hue} 55% 20%));color:#fff">${avatarInitial({display_name: g.group_title || "?"})}</div>
          <div class="pgame-body">
            <div class="pgame-title">${escapeHtml(g.group_title || t("profile_lobby"))}</div>
            <div class="pgame-sub">${phaseLabel} &middot; ${g.player_count || 0} o'yinchi</div>
          </div>
          <button class="pgame-tag" onclick="enterLobby('${escapeAttr(g.chat_id || "")}')">${t("home_enter")}</button>
        </div>`;
      }).join("");
    }
  }
  // Recent games
  const recEl = document.getElementById("profileRecentGames");
  if (recEl) {
    const rg = (data.recent_games || []).slice(0, 10);
    if (rg.length === 0) {
      recEl.innerHTML = `<div class="profile-empty">${t("profile_none")}</div>`;
    } else {
      recEl.innerHTML = rg.map((g) => {
        const facColor = g.faction === "mafia" ? "var(--red-hi)" : g.faction === "town" ? "var(--town-hi)" : "var(--neutral-hi)";
        return `<div class="pgame-row">
          <div class="pgame-tag ${g.won ? "win" : "lose"}">${g.won ? "\u2713" : "\u2715"}</div>
          <div class="pgame-body">
            <div class="pgame-title" style="color:${facColor}">${g.role_name || "?"} &middot; ${FAC_LABEL[currentLang][g.faction] || g.faction || "?"}</div>
            <div class="pgame-sub">${g.player_count || 0} o'yinchi &middot; ${g.played_at ? new Date(g.played_at).toLocaleDateString() : ""}</div>
          </div>
        </div>`;
      }).join("");
    }
  }
}


// ------------------------------------------------------ user dashboard --
// Personal dashboard (home screen). Shows the signed-in player's identity
// and the main action buttons; also renders the leaderboard, About and
// Language sub-screens. Kept deliberately REST-driven (same /me* routes the
// bot menu uses) so it works from the bot's menu button, a plain browser
// with ?chat_id, or Telegram's WebApp — no WebSocket needed here.

let lastProfileData = null;

function renderHome() {
  const name = window.__displayName || "O'yinchi";
  const avatar = document.getElementById("homeAvatar");
  if (avatar) {
    avatar.style.cssText = profileAvatarStyle({ photo_url: window.__avatarUrl, display_name: name });
    avatar.textContent = profileInitial({ display_name: name, username: window.__username });
    avatar.style.display = "flex";
  }
  const hn = document.getElementById("homeName");
  if (hn) hn.textContent = name;
  const hu = document.getElementById("homeUsername");
  if (hu) {
    const username = window.__username;
    hu.textContent = username ? ("@" + username) : (myTelegramId ? ("ID: " + myTelegramId) : "");
  }
  const hj = document.getElementById("homeJoined");
  if (hj) {
    const joined = lastProfileData && lastProfileData.user && lastProfileData.user.created_at;
    hj.textContent = joined ? (t("profile_joined") + ": " + new Date(joined).toLocaleDateString()) : "";
  }
  const adminBtn = document.getElementById("homeAdminBtn");
  if (adminBtn) adminBtn.style.display = isBotAdmin ? "" : "none";
}

function dashboardBack() {
  go("home");
  window.scrollTo(0, 0);
}

// The home dashboard (opened by the blue Menu button) shows the signed-in
// player's identity. Its "qo'shilgan sana" line comes from /me/profile —
// fetch it once on the first open so that data isn't empty until the user
// happens to tap the Profile button first. Everything renderProfile fills
// is guarded by "if (el)" so running it here is harmless even though the
// profile screen's DOM isn't mounted yet.
function refreshHomeProfile() {
  if (!sessionToken || lastProfileData) return;
  api("/me/profile")
    .then(renderProfile)
    .then(renderHome)
    .catch(() => {});
}

async function openLeaderboard() {
  go("leaderboard");
  window.scrollTo(0, 0);
  const el = document.getElementById("leaderboardRoot");
  if (!el) return;
  el.innerHTML = `<div class="card"><div class="waitnote"><span class="dotpulse"></span>${escapeHtml(t("profile_loading"))}</div></div>`;
  try {
    const res = await api("/leaderboard");
    const list = res.leaderboard || [];
    if (!list.length) {
      el.innerHTML = `<div class="card"><div class="ap-empty">${escapeHtml(t("leaderboard_empty"))}</div></div>`;
      return;
    }
    el.innerHTML = list.map((row) => {
      const isMe = row.telegram_user_id === myTelegramId;
      const medal = row.place <= 3 ? "top" + row.place : "topN";
      return `<div class="card leader-row"${isMe ? ' style="box-shadow:0 0 0 2px var(--town)"' : ""}>
        <div class="lb-medal ${medal}${isMe ? " me" : ""}">${row.place}</div>
        <div class="lbrow-body">
          <div class="lbrow-name">${escapeHtml(row.display_name)}${isMe ? " <span class=\"lb-you\">" + escapeHtml(t("leaderboard_you")) + "</span>" : ""}</div>
          <div class="lbrow-meta">${row.games_played} ${escapeHtml(t("lb_games"))} &middot; ${row.win_rate}%</div>
        </div>
        <div class="lbrow-wins">${row.wins}<span>${escapeHtml(t("profile_wins"))}</span></div>
      </div>`;
    }).join("");
  } catch (e) {
    el.innerHTML = `<div class="card"><div class="ap-empty">${escapeHtml(e.message || "Xatolik")}</div></div>`;
  }
}

const ABOUT_BODY = {
  uz: `<h3>Mafia guruh boti haqida</h3>
    <p>Bu o'yin Telegram guruhi ichida o'tkaziladi. Guruhga botni qo'shib, <b>/start</b> yuboring — "Anda" tugmasi paydo bo'ladi.</p>
    <p>Rollar faqat o'yin davomida ko'rinadi. Kechaning qorong'usida mafiya o'ldiradi, doktor himoya qiladi, komissar tergov qiladi...</p>
    <p>Botning ko'k <b>Menu</b> tugmasi orqali shaxsiy kabinet ochiladi: statistika, reyting va o'yinlar tarixi.</p>
    <p>Har bir tugagan o'yin umumiy reytingda hisoblanadi. Eng yaxshi o'yinchilar "Top / Reyting" bo'limida ko'rinadi.</p>`,
  ru: `<h3>О боте Mafia</h3>
    <p>Игра проходит прямо внутри Telegram-группы. Добавьте бота в группу и отправьте <b>/start</b> — появится кнопка «Анда».</p>
    <p>Роли видны только во время игры. Ночью мафия убивает, доктор лечит, комиссар расследует...</p>
    <p>Через синюю кнопку <b>Menu</b> бота открывается личный кабинет: статистика, рейтинг и история игр.</p>
    <p>Каждая завершённая игра идёт в общий рейтинг. Лучшие игроки — в разделе «Топ / Рейтинг».</p>`,
  en: `<h3>About the Mafia bot</h3>
    <p>The game is played inside a Telegram group. Add the bot to your group and send <b>/start</b> — the "Anda" button will appear.</p>
    <p>Roles are only visible during a game. At night the mafia kills, the doctor heals, the commissioner investigates...</p>
    <p>The bot's blue <b>Menu</b> button opens your personal dashboard: statistics, ratings and game history.</p>
    <p>Every finished game counts towards the global leaderboard. The best players appear in "Top / Ratings".</p>`,
};

function openAbout() {
  go("about");
  window.scrollTo(0, 0);
  const el = document.getElementById("aboutBody");
  if (el) el.innerHTML = ABOUT_BODY[currentLang] || ABOUT_BODY.uz;
}

function openLanguage() {
  go("language");
  window.scrollTo(0, 0);
  markLanguage();
}

function markLanguage() {
  document.querySelectorAll("#language .langbtn").forEach((b) => {
    b.classList.toggle("on", b.dataset.lang === currentLang);
    b.style.boxShadow = b.dataset.lang === currentLang ? "0 0 0 2px var(--town)" : "";
  });
  const note = document.getElementById("languageNote");
  if (note) note.textContent = t("language_note");
}

async function setLanguage(lang) {
  if (!I18N[lang]) return;
  if (lang === currentLang) { markLanguage(); return; }
  try {
    await api("/auth/language", { method: "POST", body: JSON.stringify({ language: lang }) });
    applyLanguage(lang);
    toast(t("language_note"));
    markLanguage();
  } catch (e) {
    toast(e.message || "Xatolik");
  }
}

// ---------------------------------------------------------- role catalog --
// Static reference data for the Rollar screen AND the lookup table the
// live Role/Night screens use to turn a bare role name from the server
// into an icon + description. Not game state — this never changes at runtime.

const ROLES = [
 {id:'citizen',apiName:'Citizen',fac:'town',name:'Citizen',desc:"Oddiy fuqaro. Lekin haqiqat uchun ovoz beradi.",ability:"Maxsus tungi qobiliyati yo'q. Muhokama va ovoz berish orqali g'alabaga hissa qo'shadi."},
 {id:'commissioner',apiName:'Commissioner',fac:'town',name:'Commissioner',desc:"Shahar tartibini saqlovchi komissar. Mafiyani to'xtatmoqchi.",ability:"Har kecha bitta o'yinchini tekshiradi: Mafia yoki yo'q. Yoki o'yin davomida bir marta o'ldirishi mumkin (bir martalik o'q). Lawyer himoya qilgan mijoz tekshiruvda \u201CCitizen\u201D bo'lib ko'rinadi."},
 {id:'sergeant',apiName:'Sergeant',fac:'town',name:'Sergeant',desc:"Komissarning yordamchisi. Uning vorisi.",ability:"Maxsus tungi qobiliyati yo'q. Agar Komissar halok bo'lsa, Serjant yangi Komissar bo'lib lavozimga ko'tariladi."},
 {id:'doctor',apiName:'Doctor',fac:'town',name:'Doctor',desc:"Hayot saqlovchi doktor. Kechani bir kishini himoya qilish bilan o'tkazadi.",ability:"Har kecha bitta o'yinchini himoya qiladi. O'zini o'yin davomida faqat 1 marta davolay oladi."},
 {id:'lucky',apiName:'Lucky',fac:'town',name:'Lucky',desc:"Omadli odam. O'limga yuz tutganda ham omad unga yarashadi.",ability:"Maxsus tungi qobiliyati yo'q. Halokatli hujum oqibatida har safar 50% ehtimollik bilan omon qolishi mumkin."},
 {id:'kamikaze',apiName:'Kamikaze',fac:'town',name:'Kamikaze',desc:"Bosqinchilarga befarq bo'lmagan jangchi.",ability:"Maxsus tungi qobiliyati yo'q. Agar kunduzgi ovoz berish (osish) orqali yo'q qilinsa, o'zi bilan birga yana bitta o'yinchini olib ketadi."},
 {id:'don',apiName:'Don',fac:'mafia',name:'Don',desc:"Mafiya yetakchisi. Jamoasini biladi va jamoaviy tungi o'ldirishni amalga oshiradi.",ability:"Mafia jamoasini taniydi va jamoaviy tungi o'ldirishni bajaradi. Agar Don halok bo'lsa, tirik Mafia a'zosi yangi Don bo'ladi."},
 {id:'mafia',apiName:'Mafia',fac:'mafia',name:'Mafia',desc:"Mafia jamoasi a'zosi. Don va jamoasini taniydi.",ability:"Mafia jamoasini taniydi va jamoaviy tungi o'ldirishda qatnashadi. Don halok bo'lsa, yangi Don bo'lishi mumkin."},
 {id:'maniac',apiName:'Maniac',fac:'neutral',name:'Maniac',desc:"Mustaqil qotil. Faqat o'z maqsadi uchun yashaydi.",ability:"Har kecha bitta o'yinchini mustaqil ravishda o'ldiradi. G'alaba: Mafia yo'q bo'lganda, Maniac soni shahardan kam bo'lmasa (yoki oxirgi qolgan o'yinchi bo'lsa)."},
 {id:'mistress',apiName:'Mistress',fac:'neutral',name:'Mistress',desc:"O'ziga xos ayol. Boshqalarning rejalarini buzadi.",ability:"Har kecha bitta o'yinchining tungi qobiliyatini bloklaydi (chalg'itadi). Nishonning kuchidan mahrum qiladi."},
 {id:'lawyer',apiName:'Lawyer',fac:'neutral',name:'Lawyer',desc:"Mafiya nomiga yashirin ishlaydi, lekin ularni bilmaydi.",ability:"Har kecha bitta o'yinchini \u201Cmijoz\u201D qilib tanlaysiz (o'zingizni tanlay olmaysiz). Kimni tanlash — ko'r-ko'rona, chunki mafiyaning kimligini bilmaysiz. Komissar aynan shu mijozni tekshirsa, natija \u201CCitizen\u201D bo'lib ko'rinadi."},
 {id:'suicide',apiName:'Suicide',fac:'neutral',name:'Suicide',desc:"O'limni qidiradigan ruhiy ezilgan odam.",ability:"Maxsus tungi qobiliyati yo'q. Maqsad: kunduzgi ovoz berish (osib o'ldirilish) orqali yo'q qilinish. Shu tarzda o'lsa g'olib bo'ladi."},
 {id:'vagabond',apiName:'Vagabond',fac:'neutral',name:'Vagabond',desc:"Darbadar kuzatuvchi. Hammadan xabardor bo'lishni xohlaydi.",ability:"Har kecha bitta o'yinchini kuzatadi va uning oldiga kim tashrif buyurganini biladi."},
];
const FAC_LABEL = {
  uz: { mafia: "Mafia", town: "Shahar", neutral: "Neytral" },
  ru: { mafia: "Мафия", town: "Город", neutral: "Нейтральный" },
  en: { mafia: "Mafia", town: "Town", neutral: "Neutral" },
};
const roleByApiName = Object.fromEntries(ROLES.map((r) => [r.apiName, r]));

// ru/en text for each role's desc+ability, keyed by role id. Uzbek stays
// the base data embedded in ROLES above; role *names* (Don, Doctor, ...)
// are the same established Mafia-game terms in every language, so only
// desc/ability are translated here.
const ROLE_I18N = {
  citizen: { ru: { desc: "Обычный житель. Но голосует за правду.", ability: "Не имеет особых способностей. Вносит вклад в победу через обсуждение и голосование." }, en: { desc: "An ordinary citizen. But votes for the truth.", ability: "Has no special ability. Contributes to victory through discussion and voting." } },
  commissioner: { ru: { desc: "Комиссар, поддерживающий порядок. Хочет остановить мафию.", ability: "Каждую ночь проверяет одного игрока: узнаёт, мафия он или нет. Или раз в игру может убить (одноразовый выстрел). Клиент, защищённый адвокатом, при проверке выглядит как «Гражданин»." }, en: { desc: "A commissioner keeping order. Wants to stop the mafia.", ability: "Each night either checks one player (learns Mafia or not) or uses a one-shot kill. A Lawyer-protected client reads as \u201CCitizen\u201D." } },
  sergeant: { ru: { desc: "Заместитель комиссара. Его наследник.", ability: "Не имеет особых способностей. Если Комиссар погибает, Сержант становится новым Комиссаром." }, en: { desc: "The Commissioner's deputy. His successor.", ability: "Has no special ability. If the Commissioner dies, the Sergeant is promoted to Commissioner." } },
  doctor: { ru: { desc: "Доктор, спасающий жизни. Ночью защищает одного человека.", ability: "Каждую ночь защищает одного игрока. Может лечить себя только один раз за игру." }, en: { desc: "A life-saving doctor. Protects one person each night.", ability: "Protects one player each night. Can heal themselves only once per game." } },
  lucky: { ru: { desc: "Счастливчик. Даже перед лицом смерти удача на его стороне.", ability: "Не имеет особых способностей. При смертельной атаке может выжить с вероятностью 50% каждый раз." }, en: { desc: "A lucky one. Even facing death, luck is on his side.", ability: "Has no special ability. May survive a lethal attack with a 50% chance each time." } },
  kamikaze: { ru: { desc: "Боец, не безразличный к оккупантам.", ability: "Не имеет особых способностей. Если его устранят дневным голосованием (повешением), он заберёт с собой ещё одного игрока." }, en: { desc: "A fighter not indifferent to the occupiers.", ability: "Has no special ability. If eliminated by the day vote (lynch), they take one more player with them." } },
  don: { ru: { desc: "Лидер мафии. Знает свою команду и выполняет совместное ночное убийство.", ability: "Знает команду мафии и выполняет совместное ночное убийство. Если Дон погибает, живой член мафии становится новым Доном." }, en: { desc: "The mafia's leader. Knows his team and performs the shared night kill.", ability: "Knows the mafia team and performs the shared night kill. If the Don dies, a living Mafia member becomes the new Don." } },
  mafia: { ru: { desc: "Член мафии. Знает Дона и свою команду.", ability: "Знает команду мафии и участвует в совместном ночном убийстве. Если Дон погибает, может стать новым Доном." }, en: { desc: "A mafia member. Knows the Don and his team.", ability: "Knows the mafia team and joins the shared night kill. If the Don dies, can be promoted to Don." } },
  maniac: { ru: { desc: "Независимый убийца. Живёт только ради своей цели.", ability: "Каждую ночь независимо убивает одного игрока. Победа: когда мафии не осталось и Маниак численно не уступает городу (или он последний выживший)." }, en: { desc: "An independent killer. Lives only for his own goal.", ability: "Independently kills one player each night. Wins when no Mafia remain and Maniac outnumbers/equals the town (or is the last one standing)." } },
  mistress: { ru: { desc: "Своеобразная женщина. Ломает чужие планы.", ability: "Каждую ночь блокирует ночное действие одного игрока. Лишает цель силы." }, en: { desc: "A peculiar woman. Breaks other people's plans.", ability: "Blocks one player's night action each night. Deprives the target of their power." } },
  lawyer: { ru: { desc: "Тайно помогает мафии, но не знает их.", ability: "Каждую ночь вы выбираете одного игрока как «клиента» (себя выбрать нельзя). Выбор вслепую — вы не знаете, кто мафия. Если Комиссар проверяет именно этого клиента, результат выглядит как «Гражданин»." }, en: { desc: "Secretly helps the Mafia but doesn't know them.", ability: "Each night you pick one player as your \u201Cclient\u201D (can't pick yourself). It's a blind pick — you don't know who the mafia are. A Commissioner check on that exact client reads as \u201CCitizen\u201D." } },
  suicide: { ru: { desc: "Душевно смятённый человек, ищущий смерть.", ability: "Не имеет особых способностей. Цель: быть устранённым дневным голосованием (повешением). Так погибнув, побеждает." }, en: { desc: "A troubled soul seeking death.", ability: "Has no special ability. Goal: be eliminated by the day vote (lynch). Winning thus, they win." } },
  vagabond: { ru: { desc: "Скитающийся наблюдатель. Хочет знать обо всех.", ability: "Каждую ночь наблюдает за одним игроком и узнаёт, кто приходил к нему." }, en: { desc: "A wandering observer. Wants to know everything about everyone.", ability: "Watches one player each night and learns who visited them." } },
};

function roleText(r) {
  const tr = ROLE_I18N[r.id] && ROLE_I18N[r.id][currentLang];
  return tr ? tr : { desc: r.desc, ability: r.ability };
}

// ------------------------------------------------------------------ art ----
// Premium, TEXTLESS role cards. Each role's artwork is an inline string of
// SVG (aspect ~300x450) with its own <style> block carrying CSS @keyframes,
// so the images animate forever once inlined into the DOM. No JPG/PNG files
// are involved — the previous /static/cards images are gone. The role NAME
// is never drawn onto the art; the surrounding UI always supplies it.
/* =================================================================
   CARD ART — real photo cards, served from /static/cards/full/*.webp.
   No SVG art engine; the 13 hand-painted card images do the talking.
   ================================================================= */

// Faction glow kept for the existing --artglow CSS custom property.
const ART_AUX = {
  mafia:  { glow: "#e63b4b" },
  town:   { glow: "#3b82f6" },
  neutral:{ glow: "#a06fd8" },
};

// role id -> card image file (without extension, matches the WebP set).
const CARD_FILES = {
  citizen: "Citizen", commissioner: "Commissioner", sergeant: "Sergeant",
  doctor: "Doctor", lucky: "Lucky", kamikaze: "Kamikaze", don: "Don",
  mafia: "Mafia", maniac: "Maniac", mistress: "Mistress", lawyer: "Lawyer",
  suicide: "Suicide", vagabond: "Vagabond",
};

function cardFileFor(id) { return CARD_FILES[id] || ""; }
function cardSrc(id) {
  const f = cardFileFor(id);
  return f ? "/static/cards/full/" + f + ".webp" : "";
}

// ------------------------------------------------------------------
// Public entry points — the rest of the app is untouched.
// ------------------------------------------------------------------
function cardScene(r) {
  if (!r || !r.id) return "";
  const src = cardSrc(r.id);
  if (!src) return "";
  return `<img class="roleart-img" src="${src}" alt="" draggable="false" loading="lazy">`;
}

function roleArtHtml(r) {
  if (!r || !r.id) return "";
  return `<div class="roleart" style="--artglow:${(ART_AUX[r.fac] || ART_AUX.town).glow}">${cardScene(r)}</div>`;
}

// Fallback used if a catalog cell ever fails to resolve its card.
function roleIconFallback(id, fac) {
  const r = (typeof ROLES !== "undefined" && ROLES.find((x) => x.id === id)) || { id, fac, name: "" };
  return roleArtHtml(r);
}

// ------------------------------------------------------------------
function renderRoles(filter) {
  const root = document.getElementById("rolesRoot");
  const facLabel = FAC_LABEL[currentLang] || FAC_LABEL.uz;
  const facs = filter === "all" ? ["mafia", "town", "neutral"] : [filter];
  root.innerHTML = facs.map((fac) => {
    const items = ROLES.filter((r) => r.fac === fac);
    return `<div class="factiontitle ${fac}">${facLabel[fac]}<span class="n">(${items.length})</span></div>
    <div class="rolegrid">${items.map((r) => `
      <div class="rolecell ${fac}" onclick="showRole('${r.id}')">
        <div class="roleicon">${roleArtHtml(r)}</div>
        <div class="rolename">${r.name}</div>
      </div>`).join("")}</div>`;
  }).join("");
}

function showRole(id) {
  const r = ROLES.find((x) => x.id === id);
  const facVar = r.fac === "mafia" ? "red-hi" : r.fac === "town" ? "town-hi" : "neutral-hi";
  const facLabel = FAC_LABEL[currentLang] || FAC_LABEL.uz;
  const text = roleText(r);
  const abilityLabel = I18N[currentLang]?.role_ability_label || I18N.uz.role_ability_label;
  const el = document.getElementById("roleDetail");
  el.innerHTML = `
    <div class="roledetail-card">${roleArtHtml(r)}</div>
    <div class="roledetail-head">
      <div><div class="roledetail-name">${r.name}</div><div class="roledetail-fac" style="color:var(--${facVar})">${facLabel[r.fac]}</div></div>
    </div>
    <div class="roledetail-desc">${text.desc}</div>
    <div class="roledetail-ability"><b>${abilityLabel}</b>${text.ability}</div>`;
  el.classList.add("show");
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  document.getElementById("roleDetail").classList.remove("show");
  renderRoles(t.dataset.fac);
}));
renderRoles("all");

function escapeAttr(v) { return String(v).replace(/["'<>]/g, ""); }

// -------------------------------------------------------- avatar helper --
// Real players get their Telegram photo when we have one; otherwise a
// stable initial-based placeholder so the grid never looks broken.
function avatarStyle(p) {
  if (p.avatar_url) return `background-image:url('${p.avatar_url}')`;
  const hue = Math.abs(hashStr(p.display_name)) % 360;
  return `background:linear-gradient(160deg, hsl(${hue} 45% 38%), hsl(${hue} 55% 20%));
    display:flex;align-items:center;justify-content:center;color:#ffffff;font:600 15px var(--ui)`;
}
function avatarInitial(p) { return (p.display_name || "?").trim().charAt(0).toUpperCase(); }
function hashStr(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h << 5) - h + s.charCodeAt(i); return h; }

const cabinetResults = [];
function addCabinetResult(phase, label, value, detail, key) {
  if (key && cabinetResults.some((r) => r._key === key)) return;
  cabinetResults.push({ phase, label, value, detail: detail || "", _key: key || null });
}
function renderCabinetHistory() {
  const box = document.getElementById("cabinetHistory");
  if (!box) return;
  if (cabinetResults.length === 0) {
    box.innerHTML = `<div class="cabinet-history-empty">Hali natija yo'q</div>`;
    return;
  }
  box.innerHTML = cabinetResults.map((r) =>
    `<div class="cabinet-histrow">
      <div class="hdr">${escapeHtml(r.phase)}</div>
      <div class="lbl">${escapeHtml(r.label)}</div>
      <div class="val">${escapeHtml(r.value)}${r.detail ? `<div class="small">${escapeHtml(r.detail)}</div>` : ""}</div>
    </div>`
  ).join("");
}
function renderCabinet(s) {
  if (!s || !s.me) return;
  const me = s.me;
  const roleKey = me.role;
  const rInfo = roleByApiName[me.role] || null;
  const card = document.getElementById("cabinetRoleCard");
  const actionBox = document.getElementById("cabinetAction");
  if (!card || !actionBox) return;

  // ---- accumulate investigation / night results ----
  // Consigliere-fix: night_actions persists through the resolved day (cleared
  // only at the next to_night), so has_submitted_night_action would be True
  // all day long and the history would never accumulate. The phase check
  // alone is the right gate — anything already resolved is fair history.
  if (me.night_result && s.phase !== "night") {
    const nightKey = `N${s.night_number}`;
    const nr = me.night_result;
    const targetName = nr.target_id ? nameFor(s, nr.target_id) : "";
    if (nr.verdict === "mafia" || nr.verdict === "not_mafia") {
      addCabinetResult("TUN " + s.night_number, "tekshiruv", `${targetName}: ${nr.verdict === "mafia" ? "MAFIYA" : "TOZA"}`, "", nightKey);
    } else if (nr.possible_roles) {
      addCabinetResult("TUN " + s.night_number, "tekshiruv", `${targetName}: ${nr.possible_roles.join(", ")}`, "", nightKey);
    } else if (nr.visited !== undefined) {
      const visitedName = nr.visited ? nameFor(s, nr.visited) : "hech qayerga bormadi";
      addCabinetResult("TUN " + s.night_number, "kuzatish", `${targetName} → ${visitedName}`, "", nightKey);
    } else if (nr.visitors) {
      const visitorNames = nr.visitors.length ? nr.visitors.map((v) => nameFor(s, v)).join(", ") : "hech kim kelmadi";
      addCabinetResult("TUN " + s.night_number, "kuzatish", `${targetName}: ${visitorNames}`, "", nightKey);
    } else if (nr.exact_role) {
      const exactInfo = roleByApiName[nr.exact_role] || null;
      const exactName = exactInfo ? exactInfo.name : nr.exact_role;
      addCabinetResult("TUN " + s.night_number, "aniqlash", `${targetName}: ${exactName}`, "", nightKey);
    }
  }

  // ---- accumulate personal outcome messages (Doctor save, Mistress
  // block, Commissioner read, Mafia/Maniac kill, Lucky save, Vagabond
  // report, Sergeant promotion, Suicide win, Kamikaze strike, ...) ----
  // The exact text comes straight from the backend (see
  // app/game_engine/night_messages.py) so it can never drift from the
  // personal Telegram DM built from the same list. The list only ever
  // grows, so each entry is deduped by its own index — safe against
  // re-renders and reconnects alike.
  if (me.outcome_messages && me.outcome_messages.length) {
    me.outcome_messages.forEach((text, idx) => {
      addCabinetResult("XABAR", "", text, "", `outcome-${idx}`);
    });
  }

  // ---- accumulate night death info ----
  if (s.last_night_deaths && s.last_night_deaths.length) {
    const deathKey = `deaths_N${s.night_number}`;
    s.last_night_deaths.forEach((d) => {
      addCabinetResult("NATIJA", nameFor(s, d.player_id), deathReasonUz(d.reason), "", deathKey);
    });
  }

  // ---- accumulate vote result ----
  if (s.last_vote_result && s.last_vote_result.eliminated) {
    const vr = s.last_vote_result;
    const voteKey = `vote_${Object.values(vr.totals || {}).reduce((a, b) => a + b, 0)}`;
    addCabinetResult("OVOZ", nameFor(s, vr.eliminated), "shahar tomonidan olib tashlandi", "", voteKey);
  }

  // ---- role card ----
  const sideLabel = rInfo ? (FAC_LABEL.uz[rInfo.fac] || rInfo.fac) : "";
  card.innerHTML = `<div class="cabinet-rolecard">
    ${roleArtHtml(rInfo)}
    <div class="cabinet-body">
      <div class="cabinet-faction">${sideLabel}</div>
      <div class="cabinet-rolename">${rInfo ? rInfo.name : me.role || "?"}</div>
    </div>
    <div class="cabinet-ability">
      <b>QOBILIYAT</b>
      <span>${rInfo ? roleText(rInfo).desc : ""}</span>
    </div>
  </div>`;

  // ---- action box: build the full action UI directly in the cabinet ----
  // Every role's night action is rendered here so players can act entirely
  // from the Role Cabinet panel (right pane). The new engine has no day
  // actions, so only the night picker is built.
  const phase = s.phase;

  if (phase === "night" && me.night_action_type && !me.has_submitted_night_action) {
    actionBox.innerHTML = buildCabinetNightAction(s, me);
  } else if (phase === "night" && me.night_action_type && me.has_submitted_night_action) {
    actionBox.innerHTML = `<div class="cabinet-noaction"><b style="color:var(--town)">✓ Harakat bajarildi</b><span>Boshqalar hali harakat qilmoqda...</span></div>`;
  } else if (phase === "night" && !me.night_action_type) {
    if (me.alive && me.faction === "mafia") {
      actionBox.innerHTML = `<div class="cabinet-noaction"><b>Bu kecha siz o'ldirmaysiz</b><span>O'ldirishni Don (yoki uning merosxo'ri) amalga oshiradi. Siz mafiya chatida muhokama qilasiz.</span></div>`;
    } else if (me.role === "Kamikaze" && me.alive) {
      actionBox.innerHTML = `<div class="cabinet-noaction"><b>Tungi harakat yo'q</b><span>Maxsus tungi qobiliyatingiz yo'q. Agar kunduzgi ovoz berish orqali yo'q qilinsangiz, o'zingiz bilan bitta o'yinchini olib ketasiz.</span></div>`;
    } else {
      actionBox.innerHTML = `<div class="cabinet-noaction"><b>Tungi harakat yo'q</b><span>Sizning rolingiz tungi harakatga ega emas.</span></div>`;
    }
  } else if (phase !== "night") {
    actionBox.innerHTML = `<div class="cabinet-noaction"><b>Maxsus harakat yo'q</b><span>Bu rolda maxsus harakat mavjud emas.</span></div>`;
  } else {
    actionBox.innerHTML = `<div class="cabinet-noaction"><b>Maxsus harakat yo'q</b><span>Bu rolda maxsus harakat mavjud emas.</span></div>`;
  }
  renderCabinetHistory();
}

/** Build night action UI for the Role Cabinet. Reuses the same prompts and
 *  player-card grid as renderNightScreen but generates HTML directly. */
function buildCabinetNightAction(s, me) {
  let html = `<div class="smallcap" style="margin-bottom:10px">TUNGI HARAKAT — ${nightPrompt(me.night_action_type, me)}</div>`;

  // Commissioner special-case: offer a CHECK (investigate) / SHOOT toggle.
  let commissionerToggle = "";
  if (s.phase === "night" && me.role === "Commissioner") {
    if (me.commissioner_can_shoot) {
      commissionerToggle = `
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <button class="btn dark comp-mode" style="min-height:42px;flex:1" id="cabCompCheck" onclick="setCabinetCompMode('check')">🔎 Tekshirish</button>
          <button class="btn town comp-mode" style="min-height:42px;flex:1" id="cabCompShoot" onclick="setCabinetCompMode('shoot')">🔫 O'q otish</button>
        </div>
        <p id="cabCompShootNote" style="display:none;margin:0 0 10px;font-size:12px;color:var(--red-hi);font-weight:600">Bir martalik o'q! Iste'mol qilinsa, endi faqat tekshirishingiz mumkin.</p>`;
    } else {
      commissionerToggle = `<p style="margin:0 0 10px;font-size:12px;color:var(--muted2);font-weight:600">O'q ishlatildi — endi faqat tekshirishingiz mumkin.</p>`;
    }
  }
  html += commissionerToggle;

  const skipBtnHtml = me.night_action_can_skip_target
    ? `<button class="skipbtn" onclick="cabinetNightAction(null)">Bu kecha hujum qilmaslik</button>`
    : "";

  const pool = s.players.filter((p) => p.alive);
  const targets = me.can_target_self ? pool : pool.filter((p) => p.player_id !== myPlayerId);

  if (targets.length === 0) {
    return html + `<div class="waitnote"><span class="dotpulse"></span>Nishon yo'q.</div>${skipBtnHtml}`;
  }

  html += `<div class="pcard-grid" id="cabinetTargetList">
    ${targets.map((p) => buildPlayerCard(p, seatNumberOf(s, p.player_id), {
      isHost: p.player_id === s.host_id, isMe: p.player_id === myPlayerId,
      selectable: true, onSelect: "cabinetSelectTarget",
    })).join("")}
  </div>
  <button class="btn" style="margin-top:14px" id="cabinetConfirmBtn" disabled onclick="cabinetNightAction(cabinetSelectedTarget)">Tasdiqlash</button>
  ${skipBtnHtml}`;
  return html;
}

// ---- Cabinet night action helpers ----
let cabinetSelectedTarget = null;
// Commissioner's CHECK/SHOOT toggle persists across night-screen re-renders.
let cabinetCommissionerMode = "check";
function setCabinetCompMode(mode) {
  cabinetCommissionerMode = mode;
  document.querySelectorAll(".comp-mode").forEach((b) => b.classList.remove("town", "dark"));
  const check = document.getElementById("cabCompCheck");
  const shoot = document.getElementById("cabCompShoot");
  const note = document.getElementById("cabCompShootNote");
  if (check) check.classList.add(mode === "check" ? "town" : "dark");
  if (shoot) shoot.classList.add(mode === "shoot" ? "town" : "dark");
  if (note) note.style.display = mode === "shoot" ? "" : "none";
}
function cabinetSelectTarget(el) {
  document.querySelectorAll("#cabinetTargetList .pcard").forEach((r) => r.classList.remove("selected"));
  el.classList.add("selected");
  cabinetSelectedTarget = el.dataset.pid;
  const btn = document.getElementById("cabinetConfirmBtn");
  if (btn) btn.disabled = false;
}
function cabinetNightAction(targetId) {
  const payload = { target_id: targetId };
  if (cabinetCommissionerMode === "shoot") payload.action_override = "shoot";
  send("night_action", payload);
}

// -------------------------------------------------------- main render() --

function render() {
  if (!currentState) return;
  const s = currentState;
  const phase = s.phase;

  // On entering the live-match panes for the first time (lobby -> role ->
  // night), land on the O'yin (game) pane, not the Chat pane — the panes
  // default to index 0 (= chat) when the game screen first appears.
  const GAME_PANES = ["morning", "night", "day_discussion", "voting", "lynch_confirmation", "kamikaze_strike", "vote_results"];
  const inGamePane = GAME_PANES.includes(phase);
  if (!inGamePane) gamePaneFocusedOnce = false;

  renderLobbyScreen(s);
  renderMafiaChatPanel(s);

  if (phase === "lobby") { go("lobby"); return; }

  if (phase === "role_assignment") {
    renderRoleScreen(s);
    // The 15-second role-assignment window ticks in the phase head above
    // the card (index.html's #roleTimer); it was never wired up before.
    startCountdown(s.phase_ends_in, ["roleTimer"]);
    go("role");
    return;
  }

  if (phase === "morning") {
    renderMorningScreen(s);
    renderChat(s);
    renderCabinet(s);
    go("morning");
    return;
  }

  if (phase === "night") {
    renderNightScreen(s);
    renderChat(s);
    renderCabinet(s);
    go("night");
    return;
  }

  if (phase === "day_discussion") {
    renderDayScreen(s);
    renderChat(s);
    renderCabinet(s);
    go("day");
    return;
  }

  if (phase === "voting") { renderVoteScreen(s); renderChat(s); renderCabinet(s); go("vote"); return; }

  if (phase === "lynch_confirmation") {
    renderLynchScreen(s);
    renderChat(s);
    renderCabinet(s);
    go("lynch");
    return;
  }

  if (phase === "kamikaze_strike") {
    renderKamikazeScreen(s);
    renderChat(s);
    renderCabinet(s);
    go("kamikaze");
    return;
  }

  if (phase === "vote_results") {
    renderOutcomeScreen(s, { kind: "vote" });
    renderChat(s);
    renderCabinet(s);
    go("outcome");
    return;
  }

  if (phase === "game_over") { renderWinScreen(s); return; }
}

// ------------------------------------------------------------- countdown --
// The server is authoritative; phase_ends_in (seconds, from the latest
// state push) just seeds a local ticker so the number moves smoothly
// between pushes instead of only updating once a second from the network.
function startCountdown(seconds, elIds) {
  clearInterval(countdownTimer);
  let remaining = Math.max(0, Math.round(seconds || 0));
  const paint = () => {
    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const sec = String(remaining % 60).padStart(2, "0");
    elIds.forEach((id) => { const el = document.getElementById(id); if (el) el.textContent = `${m}:${sec}`; });
  };
  paint();
  countdownTimer = setInterval(() => { if (remaining > 0) { remaining--; paint(); } }, 1000);
}

// --------------------------------------------------------- lobby screen --

// Names come straight from Telegram, where they can be arbitrarily long
// (and often are — full names, emoji, shop titles). The card only has room
// for a short label, so anything past 10 characters is cut with an
// ellipsis rather than wrapping or overflowing the tile.
const NAME_MAX = 10;
function shortName(name) {
  const n = (name || "").trim();
  return n.length > NAME_MAX ? n.slice(0, NAME_MAX) + "\u2026" : n;
}

// How many seat placeholders to draw after the real players. The lobby caps
// at 20, but painting 16 empty tiles for a 4-player game is just noise —
// this fills out the current row and adds one more, so the grid always
// reads as "there's room for more" without becoming a wall of plus signs.
function emptySlotCount(playerCount) {
  const remaining = 20 - playerCount;
  if (remaining <= 0) return 0;
  const fillCurrentRow = (3 - (playerCount % 3)) % 3;
  return Math.min(remaining, fillCurrentRow + (remaining > fillCurrentRow ? 3 : 0)) || Math.min(remaining, 3);
}

// Shared player card, reused everywhere a screen lists players — the Day
// roster and every target-picker (night action, vote, lynch ballot) build
// on the exact same .pcard markup the lobby grid introduced, just with a
// "select" mode layered on top for the pickers. Keeping one builder means
// all of those screens stay visually identical instead of drifting apart.
function buildPlayerCard(p, seatNumber, opts = {}) {
  const { isHost = false, isMe = false, dead = false, selectable = false, onSelect = "" } = opts;
  const photo = p.avatar_url ? `background-image:url('${escapeAttr(p.avatar_url)}')` : "";
  const classes = ["pcard"];
  if (isHost) classes.push("host");
  if (isMe) classes.push("me");
  if (dead) classes.push("dead");
  if (selectable) classes.push("selectable");
  const attrs = selectable ? ` data-pid="${p.player_id}" onclick="${onSelect}(this)"` : "";
  const indicator = selectable
    ? `<span class="pc-check"></span>`
    : `<span class="pc-dot ${p.connected === false ? "off" : ""}"></span>`;
  return `
    <div class="${classes.join(" ")}"${attrs}>
      ${isHost ? `<div class="pc-ribbon">${t("lobby_host_badge")}</div>` : ""}
      <div class="pc-photo" style="${photo}">${p.avatar_url ? "" : avatarInitial(p)}</div>
      <div class="pc-foot">
        <span class="pc-num">${seatNumber}</span>
        <span class="pc-name">${escapeHtml(shortName(p.display_name))}</span>
        ${indicator}
      </div>
    </div>`;
}
// Target-pickers filter s.players down to who's eligible, but a player's
// seat number should still match the number they wear in the lobby/day
// roster — so look their number up in the full roster rather than using
// their position in the filtered list.
function seatNumberOf(s, playerId) {
  return s.players.findIndex((x) => x.player_id === playerId) + 1;
}

function renderLobbyScreen(s) {
  const iAmHost = myPlayerId === s.host_id;
  const count = s.players.length;

  document.getElementById("lobbyCount").textContent = `${count} / 20`;

  // Segmented progress strip: 12 segments spanning the 4..20 range that the
  // match actually needs, so the first few joins visibly move the bar
  // instead of barely nudging a 20-segment one.
  const SEGMENTS = 12;
  const filled = Math.min(SEGMENTS, Math.round((count / 20) * SEGMENTS));
  document.getElementById("lobbyBar").innerHTML =
    Array.from({ length: SEGMENTS }, (_, i) => `<span class="${i < filled ? "on" : ""}"></span>`).join("");

  const cards = s.players.map((p, i) => {
    const isHost = p.player_id === s.host_id;
    const photo = p.avatar_url
      ? `background-image:url('${escapeAttr(p.avatar_url)}')`
      : "";
    return `
    <div class="pcard ${isHost ? "host" : ""}">
      ${isHost ? `<div class="pc-ribbon">${t("lobby_host_badge")}</div>` : ""}
      <div class="pc-photo" style="${photo}">${p.avatar_url ? "" : avatarInitial(p)}</div>
      <div class="pc-foot">
        <span class="pc-num">${i + 1}</span>
        <span class="pc-name">${escapeHtml(shortName(p.display_name))}</span>
        <span class="pc-dot ${p.connected === false ? "off" : ""}"></span>
      </div>
    </div>`;
  });

  const empties = Array.from({ length: emptySlotCount(count) }, () => `
    <div class="pcard empty">
      <div class="pc-plus"><svg class="icon"><use href="#i-plus"/></svg></div>
      <div class="pc-empty">${t("lobby_empty_slot")}</div>
    </div>`);

  document.getElementById("lobbyPlayers").innerHTML = cards.concat(empties).join("");

  renderBotRolePickers(s);

  const startBtn = document.getElementById("startBtn");
  const main = document.getElementById("startBtnMain");
  const sub = document.getElementById("startBtnSub");
  if (s.phase !== "lobby") { startBtn.style.display = "none"; return; }
  startBtn.style.display = "";

  const enough = count >= 4;
  main.textContent = t("lobby_start_btn");
  if (iAmHost) {
    startBtn.disabled = !enough;
    sub.textContent = enough ? t("lobby_ready_hint") : `${t("lobby_start_hint")} (${count}/4)`;
  } else {
    startBtn.disabled = true;
    sub.textContent = t("lobby_wait_host");
  }
}

// #21: admin chooses the bots' roles (and their own) before Start. Only the
// host sees this; it lists every player with a dropdown of the roles that
// actually exist in this size's lineup (plus an "auto" option), wired to
// set_bot_role on the server so picks survive across state pushes.
function renderBotRolePickers(s) {
  const box = document.getElementById("botRolePickers");
  if (!box) return;
  const admin = s.admin || {};
  const roles = admin.available_roles || [];
  const picks = admin.role_picks || {};
  const roleCount = admin.role_count || {};
  const me = s.me || {};
  const isHost = me.player_id === s.host_id;
  const bots = s.players.filter((p) => p.is_bot || p.player_id === s.host_id);

  const show = isHost && s.phase === "lobby" && bots.length && roles.length;
  box.style.display = show ? "" : "none";
  if (!show) return;

  const rows = bots.map((p) => {
    const cur = picks[p.player_id] || "";
    const opts = `<option value="" ${cur === "" ? "selected" : ""}>${t("brp_auto")}</option>` +
      roles.map((r) => {
        // Copies available = copies in the lineup minus how many OTHER rows
        // already picked this role (the current row's own pick, if any, is
        // already counted in `picks`, so add it back when it's this one).
        const taken = Object.keys(picks).filter((pid) => pid !== p.player_id && picks[pid] === r).length;
        const remaining = (roleCount[r] || 0) - taken;
        const label = roleByApiName[r] ? roleByApiName[r].name : r;
        const disabled = remaining <= 0 && cur !== r ? " disabled" : "";
        return `<option value="${r}" ${cur === r ? "selected" : ""}${disabled}>${label}</option>`;
      }).join("");
    const who = p.player_id === s.host_id ? t("brp_you") : "🤖 " + escapeHtml(shortName(p.display_name));
    return `
    <div class="brp-row">
      <span class="brp-name">${who}</span>
      <button class="brp-clear" onclick="setBotRole('${p.player_id}', null)" title="${t("brp_clear")}">&times;</button>
      <select class="brp-select" data-target="${p.player_id}" onchange="setBotRole(this.dataset.target, this.value || null)">
        ${opts}
      </select>
    </div>`;
  }).join("");

  box.innerHTML = `
    <div class="brp-panel">
      <div class="brp-head">${t("brp_title")}</div>
      <div class="brp-note">${t("brp_note")}</div>
      ${rows}
    </div>`;
}

function setBotRole(targetId, roleName) {
  send("set_bot_role", { target_id: targetId, role: roleName });
}

async function startGame() {
  send("start_game");
}

// ---------------------------------------------------------- role screen --

// A role is revealed once per match and then stays revealed for this
// session. Keyed by game_id so a new match starts face-down again, and
// held only in memory: the server never needs to know whether someone has
// looked at their own card yet.
let roleRevealedFor = null;
// True only while the reveal flip animation is playing, so a second tap
// (or a state push arriving mid-flip) can't restart or short-circuit it.
let roleFlipInProgress = false;

function roleIsRevealed() {
  return currentState && roleRevealedFor === currentState.game_id;
}

function revealRole() {
  if (!currentState) return;
  if (roleIsRevealed()) return;          // already open — nothing to play
  if (roleFlipInProgress) return;        // guard against a double tap
  const s = currentState;
  const r = roleByApiName[(s.me || {}).role] || null;

  // A short haptic tick makes the turn feel like flipping a physical card.
  try { tg.HapticFeedback.impactOccurred("medium"); } catch (e) {}

  const flipper = document.getElementById("rvFlipper");
  const reduced = window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // No flipper on screen (or the player asked for reduced motion): skip
  // straight to the revealed state rather than waiting on an animation
  // that isn't going to run.
  if (!flipper || reduced) {
    roleRevealedFor = s.game_id;
    renderRoleScreen(s);
    return;
  }

  roleFlipInProgress = true;
  // Put the real card art on the (currently hidden) front face, then turn
  // the card. Only after the turn finishes do we swap in the full revealed
  // layout, so the flip and the text stagger read as one continuous move
  // instead of two competing animations.
  const front = flipper.querySelector(".rv-face-front");
  if (front && r) front.innerHTML = roleArtHtml(r);
  flipper.classList.add("flipped");

  setTimeout(() => {
    try { tg.HapticFeedback.notificationOccurred("success"); } catch (e) {}
    roleFlipInProgress = false;
    roleRevealedFor = s.game_id;
    // currentState may have been replaced by a fresh server push while the
    // flip was playing; render whatever is current now, not the snapshot
    // captured when the tap happened.
    renderRoleScreen(currentState || s);
  }, 780);  // matches .rv-flipper's transition duration in index.html
}

/** The role card, faction, description and ability — shared verbatim by the
 *  dedicated reveal screen and the "my role" sheet, so the two can never
 *  drift into showing different text for the same role. */
function roleBodyHtml(s) {
  const me = s.me || {};
  const r = roleByApiName[me.role] || null;
  const facColor = r && r.fac === "mafia" ? "var(--red-hi)"
    : r && r.fac === "town" ? "var(--town-hi)" : "var(--neutral-hi)";
  const facLabel = FAC_LABEL[currentLang] || FAC_LABEL.uz;
  const text = r ? roleText(r) : { desc: "", ability: "" };
  const abilityLabel = I18N[currentLang]?.role_ability_label || I18N.uz.role_ability_label;

  // The server sends a role_description tailored to this player when it has
  // one; the static catalog is the fallback so the screen is never empty.
  const desc = me.role_description || text.desc;

  return `
    <div class="rv-card" style="border-color:${facColor};box-shadow:0 0 44px ${facColor}55">
      ${r ? roleArtHtml(r) : ""}
    </div>
    <div class="rv-fac" style="color:${facColor}">${r ? facLabel[r.fac] : ""}</div>
    <div class="rv-name" style="color:${facColor}">${escapeHtml((me.role || "?").toUpperCase())}</div>
    <p class="rv-desc">${escapeHtml(desc)}</p>
    ${text.ability ? `<div class="rv-ability"><b>${abilityLabel}</b><span>${escapeHtml(text.ability)}</span></div>` : ""}`;
}

function renderRoleScreen(s) {
  const stage = document.getElementById("roleStage");

  if (!roleIsRevealed()) {
    stage.innerHTML = `
      <div class="rv-hidden">
        <div class="rv-flipwrap">
          <div class="rv-flipper" id="rvFlipper">
            <div class="rv-face rv-back" onclick="revealRole()" role="button" tabindex="0"
                 onkeydown="if(event.key==='Enter'||event.key===' ')revealRole()">
              <div class="rv-seal"><svg class="icon"><use href="#i-spade"/></svg></div>
            </div>
            <div class="rv-face rv-face-front"></div>
          </div>
        </div>
        <div>
          <div class="rv-tap">${t("role_tap")}</div>
          <div class="rv-tapsub">${t("role_tapsub")}</div>
        </div>
      </div>
      <div class="rv-actions">
        <button class="btn ghost" onclick="go('night')">${t("role_skip")}</button>
      </div>`;
    return;
  }

  stage.innerHTML = `
    <div class="rv-shown">
      ${roleBodyHtml(s)}
      <p class="rv-secret">${t("role_secret")}</p>
    </div>`;
}

// ------------------------------------------------- mafia private chat ----
// A second, separate channel from the public discussion chat above: the
// server (get_player_view) only ever includes `mafia_chat` and
// `me.mafia_teammates`/`me.can_mafia_chat` in the state a Mafia player
// receives, so simply checking for their presence is what keeps this
// invisible to everyone else — there's no separate "am I mafia" check
// needed here, the isolation already happened server-side.

let lastMafiaChatLen = -1;

function renderMafiaChatPanel(s) {
  const fab = document.getElementById("mafiaChatFab");
  const isMafia = !!(s.me && Array.isArray(s.me.mafia_teammates));
  if (!isMafia || s.phase === "lobby" || s.phase === "role_assignment" || s.phase === "game_over") {
    fab.style.display = "none";
    closeMafiaChatSheet();
    return;
  }
  fab.style.display = "";

  const chat = s.mafia_chat || [];
  const teammatesEl = document.getElementById("mafiaTeammates");
  const names = (s.me.mafia_teammates || []).map((pid) => nameFor(s, pid)).filter(Boolean);
  teammatesEl.textContent = names.length
    ? `Hamkasblaringiz: ${names.join(", ")}`
    : "Boshqa mafiya a'zosi yo'q.";

  const log = document.getElementById("mafiaChatLog");
  log.innerHTML = chat.length
    ? chat.map((m) => chatMessageHtml(s, m)).join("")
    : `<div class="chatempty">Hali xabar yo'q.</div>`;
  if (chat.length !== lastMafiaChatLen) {
    log.scrollTop = log.scrollHeight;
    lastMafiaChatLen = chat.length;
  }

  const badge = document.getElementById("mafiaChatBadge");
  const sheetOpen = document.getElementById("mafiaChatSheet").classList.contains("show");
  const unread = chat.length - mafiaChatSeenCount;
  if (!sheetOpen && unread > 0) {
    badge.style.display = "flex";
    badge.textContent = unread > 9 ? "9+" : String(unread);
  } else {
    badge.style.display = "none";
  }

  const inputArea = document.getElementById("mafiaChatInputArea");
  inputArea.style.display = s.me.can_mafia_chat ? "" : "none";
}

let mafiaChatSeenCount = 0;
function openMafiaChatSheet() {
  document.getElementById("mafiaChatSheet").classList.add("show");
  mafiaChatSeenCount = (currentState && currentState.mafia_chat) ? currentState.mafia_chat.length : 0;
  document.getElementById("mafiaChatBadge").style.display = "none";
}
function closeMafiaChatSheet() {
  document.getElementById("mafiaChatSheet").classList.remove("show");
}
function sendMafiaChatMessage() {
  const input = document.getElementById("mafiaChatInput");
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  send("mafia_chat_message", { text });
  input.value = "";
}

// --------------------------------------------------------- night screen --

function renderNightScreen(s) {
  const me = s.me || {};
  startCountdown(s.phase_ends_in, ["nightTimer"]);

  // Phase header (feature item 6): always NIGHT + number, never bare "Night".
  const titleEl = document.getElementById("nightPhaseTitle");
  if (titleEl) titleEl.textContent = `NIGHT ${s.night_number}`;
  const subEl = document.getElementById("nightPhaseSub");
  if (subEl) subEl.textContent = "Hamma ko'zini yumdi. Rolingizga mos harakatni tanlang.";

  // Live anonymous activity feed (items 2-4/11/16-18): renders regardless
  // of whether this player has already acted, and keeps updating on every
  // subsequent state push — the screen never goes "dead" after acting.
  renderActivityFeed("nightActivityFeed", s.activity_feed, "night", s.night_number);

  const box = document.getElementById("nightAction");
  selectedTarget = null;

  if (me.has_submitted_night_action) {
    document.getElementById("nightActionLabel").textContent = "YUBORILDI";
    box.innerHTML = `
      <div class="actionstatus">
        <svg class="icon"><use href="#i-shield"/></svg>
        <div>
          <div class="actionstatus-title">Harakat yuborildi</div>
          <div class="actionstatus-sub">Boshqalar hali harakat qilmoqda. Tashqi kuzatuv davom etmoqda...</div>
        </div>
      </div>`;
    return;
  }

  if (!me.night_action_type) {
    document.getElementById("nightActionLabel").textContent = "TUNGI HARAKAT";
    if (me.alive && me.faction === "mafia") {
      // Balance fix: only the Don (or his successor) performs the kill.
      box.innerHTML = `<div class="waitnote">Bu kecha siz o'ldirmaysiz — o'ldirishni Don (yoki uning merosxo'ri) amalga oshiradi. Mafiya chatida muhokama qiling.</div>`;
    } else {
      box.innerHTML = `<div class="waitnote"><span class="dotpulse"></span>Sizning rolingiz tungi harakatga ega emas. Tinch uxlang.</div>`;
    }
    return;
  }

  document.getElementById("nightActionLabel").textContent = "TANLANG";

  // Roles whose action can also be explicitly skipped with no target
  // (feature item 8) — Mafia's "I choose not to attack tonight".
  const skipBtnHtml = me.night_action_can_skip_target
    ? `<button class="skipbtn" onclick="confirmNightAction(null)">Bu kecha hujum qilmaslik</button>`
    : "";

  // Every 13-role-set action targets a living player (matches what the
  // server enforces in submit_night_action); every 13-role pick targets a
  // living player only.
  const pool = s.players.filter((p) => p.alive);
  const targets = me.can_target_self ? pool : pool.filter((p) => p.player_id !== myPlayerId);

  if (targets.length === 0) {
    box.innerHTML = `<div class="waitnote"><span class="dotpulse"></span>Hozircha nishon yo'q.</div>${skipBtnHtml}`;
    return;
  }

  box.innerHTML = `
    <p class="subtitle" style="margin:0 0 12px;text-align:left">${nightPrompt(me.night_action_type)}</p>
    <div class="pcard-grid" id="nightTargetList">
      ${targets.map((p) => buildPlayerCard(p, seatNumberOf(s, p.player_id), {
        isHost: p.player_id === s.host_id, isMe: p.player_id === myPlayerId,
        selectable: true, onSelect: "selectNightTarget",
      })).join("")}
    </div>
    <button class="btn" style="margin-top:14px" id="nightConfirmBtn" disabled onclick="confirmNightAction(selectedTarget)">Tanlashni tasdiqlash</button>
    ${skipBtnHtml}`;
}

function nightPrompt(actionType) {
  const prompts = {
    kill: "Kimni yo'q qilasiz?", protect: "Kimni himoya qilasiz?",
    investigate: "Kimni tekshirasiz?", shoot: "Kimni otasiz?",
    block: "Kimning rejasini buzmoqchisiz?", watch: "Kimning oldiga kim kelishini ko'rmoqchisiz?",
    shield: "Kimni mijozingiz qilib tanlaysiz?",
  };
  return prompts[actionType] || "Harakatingizni tanlang";
}

function selectNightTarget(el) {
  document.querySelectorAll("#nightTargetList .pcard").forEach((r) => r.classList.remove("selected"));
  el.classList.add("selected");
  selectedTarget = el.dataset.pid;
  const btn = document.getElementById("nightConfirmBtn");
  if (btn) btn.disabled = false;
}

function confirmNightAction(targetId) {
  send("night_action", { target_id: targetId });
}

// ------------------------------------------------------- morning screen --
// A short report phase right after the night resolves: "Player X died" or
// "nobody died", plus the player's own night result if they had an active
// ability (Commissioner verdict, Vagabond visitors, ...) and any Lucky
// survival note.

function renderMorningScreen(s) {
  startCountdown(s.phase_ends_in, ["morningTimer"]);
  const titleEl = document.getElementById("morningPhaseTitle");
  if (titleEl) titleEl.textContent = `TUN ${s.night_number} — NATIJA`;
  renderActivityFeed("morningActivityFeed", s.activity_feed, "morning", s.night_number);

  const me = s.me || {};
  const deaths = s.last_night_deaths || [];
  const report = document.getElementById("morningReport");

  let cards = "";
  if (deaths.length) {
    cards = deaths.map((d) => {
      const p = s.players.find((x) => x.player_id === d.player_id);
      return `<div class="card" style="display:flex;align-items:center;gap:12px;margin-top:10px">
        <div class="avatar" style="${avatarStyle(p)}">${!p.avatar_url ? avatarInitial(p) : ""}</div>
        <div style="flex:1;min-width:0">
          <div class="result-name" style="font-size:18px">${escapeHtml(nameFor(s, d.player_id))}</div>
          <div class="subtitle" style="text-align:left;margin-top:2px;font-size:12.5px">${deathReasonUz(d.reason)}</div>
        </div>
      </div>`;
    }).join("");
  } else {
    cards = `<div class="card" style="text-align:center;padding:22px;margin-top:10px">
      <div style="font-size:26px">&#127748;</div>
      <div style="font-weight:700;margin-top:6px">Hammasi tinch o'tdi</div>
      <p class="subtitle" style="margin-top:4px">Bu kecha hech kim o'lmadi.</p>
    </div>`;
  }

  // Personal night result (Commissioner verdict / Vagabond report / ...).
  const nr = me.night_result;
  let resultCard = "";
  if (nr) {
    let line = "";
    if (nr.verdict === "mafia" || nr.verdict === "not_mafia") {
      const targetName = nr.target_id ? nameFor(s, nr.target_id) : "";
      line = nr.verdict === "mafia"
        ? `${targetName}: <b style="color:var(--red-hi)">MAFIYA!</b>` : `${targetName}: toza.`;
      resultCard = `<div class="card" style="margin-top:10px;border-left:3px solid var(--town)">
        <div class="smallcap" style="margin-bottom:6px">TEKSHIRUV NATIJASI</div>
        <div style="font-size:14px">${line}</div>
      </div>`;
    } else if (nr.visitors) {
      const targetName = nr.target_id ? nameFor(s, nr.target_id) : "";
      const names = nr.visitors.length ? nr.visitors.map((v) => nameFor(s, v)).join(", ") : "hech kim kelmadi";
      resultCard = `<div class="card" style="margin-top:10px;border-left:3px solid var(--neutral)">
        <div class="smallcap" style="margin-bottom:6px">KUZATUV NATIJASI</div>
        <div style="font-size:14px">${targetName} oldiga: ${names}</div>
      </div>`;
    }
  }
  if (me.lucky_survived) {
    resultCard += `<div class="card" style="margin-top:10px;border-left:3px solid var(--gold-hi);background:var(--town-dim)">
      <div style="font-size:14px;font-weight:700">&#127808; Omad!</div>
      <div style="font-size:13px;color:var(--muted);margin-top:3px">Bugun omad siz tomonda — halokatli hujumdan omon qoldingiz.</div>
    </div>`;
  }

  report.innerHTML = cards + resultCard;
}

// --------------------------------------------------- lynch confirmation --
// After the vote tally picks a victim, every alive player votes YES/NO on
// actually carrying out the lynch. The majority decides; a NO keeps the
// victim alive and the round just rolls on.

function renderLynchScreen(s) {
  startCountdown(s.phase_ends_in, ["lynchTimer"]);
  const titleEl = document.getElementById("lynchPhaseTitle");
  if (titleEl) titleEl.textContent = `DAY ${s.day_number} — OSING YOKI QO'YIB BERING`;
  renderActivityFeed("lynchActivityFeed", s.activity_feed, "lynch_confirmation", s.day_number);

  const me = s.me || {};
  const targetId = s.lynch_target;
  const target = s.players.find((p) => p.player_id === targetId);
  const roleMeta = target && target.role ? roleByApiName[target.role] : null;

  document.getElementById("lynchTargetCard").innerHTML = target
    ? `<div class="card" style="display:flex;align-items:center;gap:12px">
        <div class="avatar" style="${avatarStyle(target)}">${!target.avatar_url ? avatarInitial(target) : ""}</div>
        <div style="flex:1;min-width:0">
          <div class="result-name" style="font-size:19px">${escapeHtml(target.display_name)}</div>
          <div class="subtitle" style="text-align:left;margin-top:2px;font-size:12.5px">Eng ko'p ovozni shu yig'di. Uni o'ldiramizmi?</div>
        </div>
      </div>`
    : `<div class="card" style="text-align:center;padding:20px">Hech kim belgilanmagan.</div>`;

  const yesBtn = document.getElementById("lynchYesBtn");
  const noBtn = document.getElementById("lynchNoBtn");
  const status = document.getElementById("lynchStatus");

  if (!me.can_confirm) {
    if (yesBtn) yesBtn.disabled = true;
    if (noBtn) noBtn.disabled = true;
    if (status) status.textContent = t("ballot_unavailable");
  } else if (me.has_lynch_confirmed) {
    if (yesBtn) yesBtn.disabled = true;
    if (noBtn) noBtn.disabled = true;
    if (status) status.textContent = "Ovozingiz qabul qilindi. Boshqalar ovoz bermoqda...";
  } else {
    if (yesBtn) yesBtn.disabled = false;
    if (noBtn) noBtn.disabled = false;
    if (status) status.textContent = "";
  }
}

function submitLynchConfirm(yes) {
  send("lynch_confirm", { yes });
  const yesBtn = document.getElementById("lynchYesBtn");
  const noBtn = document.getElementById("lynchNoBtn");
  const status = document.getElementById("lynchStatus");
  if (yesBtn) yesBtn.disabled = true;
  if (noBtn) noBtn.disabled = true;
  if (status) status.textContent = "Ovozingiz qabul qilindi. Boshqalar ovoz bermoqda...";
}

// ------------------------------------------------------ kamikaze strike --
// The lynched Kamikaze (already dead) gets one short window to name a living
// player to take with them. Everyone else just watches the countdown.

function renderKamikazeScreen(s) {
  startCountdown(s.phase_ends_in, ["kamikazeTimer"]);
  const titleEl = document.getElementById("kamikazePhaseTitle");
  if (titleEl) titleEl.textContent = `DAY ${s.day_number} — KAMIKADZE ZARBASI`;
  renderActivityFeed("kamikazeActivityFeed", s.activity_feed, "kamikaze_strike", s.day_number);

  const me = s.me || {};
  const box = document.getElementById("kamikazeAction");

  if (!me.kamikaze_striker) {
    box.innerHTML = `
      <div class="card" style="text-align:center;padding:22px">
        <div style="font-size:26px">&#128165;</div>
        <div style="font-weight:700;margin-top:6px">Kamikadze yakuniy tanlov qilmoqda</div>
        <p class="subtitle" style="margin-top:4px">Osilgan Kamikadze o'zi bilan bitta o'yinchini olib ketishi mumkin. Buni kuzatib turing...</p>
      </div>`;
    return;
  }

  if (me.has_submitted_kamikaze) {
    box.innerHTML = `<div class="waitnote"><span class="dotpulse"></span>Zarba nishoni qabul qilindi.</div>`;
    return;
  }

  const targets = s.players.filter((p) => p.alive && p.player_id !== myPlayerId);
  if (targets.length === 0) {
    box.innerHTML = `<div class="waitnote">Olib ketadigan hech kim qolmadi.</div>`;
    return;
  }

  box.innerHTML = `
    <div class="card">
      <div class="smallcap" style="margin-bottom:6px">ZARBA NISHONINI TANLANG</div>
      <p style="font-size:13px;color:var(--muted);line-height:1.5">Siz osildingiz, ammo yakuniy so'zingiz bor: kimni o'zingiz bilan birga olib ketasiz?</p>
    </div>
    <div class="pcard-grid" id="kamikazeTargetList">
      ${targets.map((p) => buildPlayerCard(p, seatNumberOf(s, p.player_id), {
        isHost: p.player_id === s.host_id, isMe: p.player_id === myPlayerId,
        selectable: true, onSelect: "selectKamikazeTarget",
      })).join("")}
    </div>
    <button class="btn gold" style="margin-top:14px" id="kamikazeConfirmBtn" disabled onclick="submitKamikazeTarget()">Zarbani tasdiqlash</button>`;
}

function selectKamikazeTarget(el) {
  document.querySelectorAll("#kamikazeTargetList .pcard").forEach((r) => r.classList.remove("selected"));
  el.classList.add("selected");
  selectedTarget = el.dataset.pid;
  const btn = document.getElementById("kamikazeConfirmBtn");
  if (btn) btn.disabled = false;
}

function submitKamikazeTarget() {
  if (!selectedTarget) return;
  send("kamikaze_target", { target_id: selectedTarget });
  const box = document.getElementById("kamikazeAction");
  if (box) box.innerHTML = `<div class="waitnote"><span class="dotpulse"></span>Zarba nishoni qabul qilindi.</div>`;
}

// ----------------------------------------------------------- day screen --

function renderDayScreen(s) {
  const titleEl = document.getElementById("dayPhaseTitle");
  if (titleEl) titleEl.textContent = `DAY ${s.day_number}`;
  startCountdown(s.phase_ends_in, ["dayTimer"]);
  renderActivityFeed("dayActivityFeed", s.activity_feed, "day_discussion", s.day_number);
  document.getElementById("dayPlayers").innerHTML = s.players.map((p, i) =>
    buildPlayerCard(p, i + 1, {
      isHost: p.player_id === s.host_id, isMe: p.player_id === myPlayerId, dead: !p.alive,
    })).join("");
  const me = s.me || {};
  const btn = document.getElementById("toVoteBtn");
  if (btn) {
    btn.classList.toggle("ready", !!me.ready_for_vote);
    btn.textContent = me.ready_for_vote ? "Kutilmoqda..." : "Tayyor";
  }
  const progress = document.getElementById("readyProgress");
  if (progress) {
    progress.textContent = `${s.ready_count || 0}/${s.alive_count || 0} tayyor`;
  }
}

async function toggleReadyForVote() {
  // Replaces the old one-click "force everyone into voting" button (spec
  // item 1): this only ever toggles the current player's own Ready flag.
  // Voting only actually starts once every alive player is ready, or the
  // discussion timer runs out on its own — never from a single tap.
  const me = (currentState && currentState.me) || {};
  send("ready_for_vote", { ready: !me.ready_for_vote });
}

// -------------------------------------------------- discussion chat -----
// Spec sections 11 & 32: discussion happens ONLY here, inside the WebApp —
// never in the Telegram group. Server is authoritative on every rule
// (alive-only, silenced-block, phase-gated); this just renders what the
// last state push already told us and forwards what the player types.

let lastChatLen = -1;

/** Turns one serialized chat message into HTML. Plain player messages keep
 *  the classic bubble; system messages (death / last words / mafia result)
 *  render as full-width highlighted cards so they stand out in the feed. */
function chatMessageHtml(s, m) {
  const kind = m.kind || "player";
  if (kind === "death") {
    const p = m.payload || {};
    const victimName = escapeHtml(nameFor(s, p.victim) || m.display_name);
    const reasonText = deathReasonUz(p.reason);
    const victimRoleMeta = p.victim_role ? (roleByApiName[p.victim_role] || null) : null;
    const roleLine = victimRoleMeta
      ? `<div class="cd-line"><span class="cd-lbl">Roli</span><span>${escapeHtml(victimRoleMeta.name)}</span></div>`
      : "";
    return `<div class="chatmsg chat-system chat-death">
      <div class="chatname">☠ O'LIM</div>
      <div class="chattext">
        <div class="cd-title">${victimName}</div>
        <div class="cd-line">${reasonText}</div>
        ${roleLine}
      </div>
    </div>`;
  }
  if (kind === "last_words") {
    return `<div class="chatmsg chat-system chat-lastwords">
      <div class="chatname">💬 SO'NGGI SO'Z — ${escapeHtml(m.display_name)} †</div>
      <div class="chattext">“${escapeHtml(m.text)}”</div>
    </div>`;
  }
  const sender = s.players.find((p) => p.player_id === m.player_id);
  const isDead = sender && !sender.alive;
  const isMe = m.player_id === myPlayerId;
  return `<div class="chatmsg ${isMe ? "me" : ""} ${isDead ? "dead" : ""}">
    <div class="chatname">${escapeHtml(m.display_name)}${isDead ? " †" : ""}</div>
    <div class="chattext">${escapeHtml(m.text)}</div>
  </div>`;
}

function renderChat(s) {
  const me = s.me || {};
  const log = document.getElementById("chatLog");
  const chat = s.chat || [];

  if (chat.length === 0) {
    log.innerHTML = `<div class="chatempty">Hali xabar yo'q. Muhokamani boshlang.</div>`;
  } else {
    log.innerHTML = chat.map((m) => chatMessageHtml(s, m)).join("");
  }
  if (chat.length !== lastChatLen) {
    log.scrollTop = log.scrollHeight;
    lastChatLen = chat.length;
  }

  const inputArea = document.getElementById("chatInputArea");
  if (me.can_last_words) {
    // A dead player's final message (night kill aftermath / post-hang 60s
    // window) leaves its input right here in the messages panel.
    inputArea.innerHTML = `
      <div class="lastwords-box">
        <div class="smallcap">SO'NGGI SO'Z</div>
        <textarea id="chatLastWordsInput" maxlength="200" rows="2"
          placeholder="Oxirgi so'zingizni yozing..."></textarea>
        <button class="btn gold" onclick="submitChatLastWords()">Yuborish</button>
      </div>`;
  } else if (me.can_chat) {
    inputArea.innerHTML = `
      <div class="chatinputrow">
        <input class="chatinput" id="chatInput" maxlength="500" placeholder="Xabar yozing..."
          onkeydown="if(event.key==='Enter')sendChatMessage()">
        <button class="chatsend" onclick="sendChatMessage()"><svg class="icon" style="width:17px;height:17px;stroke:#fff"><use href="#i-send"/></svg></button>
      </div>`;
  } else if (!me.alive) {
    inputArea.innerHTML = `<div class="chatspectate">Siz kuzatuvchisiz — spectator sifatida ko'rasiz, yoza olmaysiz</div>`;
  } else {
    const reason = s.phase === "day_discussion" ? t("chat_silenced") : t("chat_wait_discussion");
    inputArea.innerHTML = `<div class="chatspectate">${escapeHtml(reason)}</div>`;
  }
}

function sendChatMessage() {
  const input = document.getElementById("chatInput");
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  send("chat_message", { text });
  input.value = "";
}

function submitChatLastWords() {
  const el = document.getElementById("chatLastWordsInput");
  if (!el) return;
  const text = el.value.trim();
  if (!text) return;
  send("last_words", { text });
  el.disabled = true;
  el.value = "Yuborildi ✓";
  const btn = el.nextElementSibling;
  if (btn) btn.disabled = true;
}

// ---------------------------------------------------------- vote screen --

let voteSelectionRound = null;
function renderVoteScreen(s) {
  const isRevote = !!s.revote_candidates;
  const titleEl = document.getElementById("votePhaseTitle");
  if (titleEl) titleEl.textContent = isRevote
    ? `${t("ballot_day")} ${s.day_number} · ${t("ballot_revote")}` : `${t("ballot_day")} ${s.day_number} · ${t("vote_title")}`;
  const subEl = document.getElementById("votePhaseSub");
  if (subEl) subEl.textContent = isRevote
    ? t("ballot_revote_hint") : t("ballot_hint");
  startCountdown(s.phase_ends_in, ["voteTimer"]);
  renderActivityFeed("voteActivityFeed", s.activity_feed, "voting", s.day_number);
  const me = s.me || {};
  const round = `${s.game_id}:${s.day_number}:${s.revote_round}`;
  if (voteSelectionRound !== round) selectedTarget = null;
  voteSelectionRound = round;
  const alive = s.players.filter((p) => p.alive);
  const skipBtn = document.getElementById("voteSkipBtn");
  if (skipBtn) skipBtn.disabled = false;
  if (skipBtn) skipBtn.style.display = me.can_vote && !me.has_voted ? "" : "none";

  if (me.has_voted) {
    document.getElementById("voteList").innerHTML = `<div class="waitnote"><span class="dotpulse"></span>${t("ballot_received")}</div>`;
    document.getElementById("voteBtn").style.display = "none";
    return;
  }
  if (!me.can_vote) {
    document.getElementById("voteList").innerHTML = `<div class="waitnote">${t("ballot_unavailable")}</div>`;
    document.getElementById("voteBtn").style.display = "none";
    return;
  }
  document.getElementById("voteBtn").style.display = "";
  document.getElementById("voteBtn").disabled = true;

  // During a revote (spec item 2), only the tied candidates from the
  // first round can be voted for — everyone else is filtered out here
  // to match what the server will actually accept.
  const candidates = s.revote_candidates;
  const votable = (candidates ? alive.filter((p) => candidates.includes(p.player_id)) : alive)
    .filter((p) => me.allow_self_vote || p.player_id !== me.player_id);
  if (!votable.some((p) => p.player_id === selectedTarget)) selectedTarget = null;

  document.getElementById("voteList").innerHTML = votable.map((p) => `
    <button type="button" class="pcard vote-row ${p.player_id === selectedTarget ? "selected" : ""}"
      data-pid="${escapeAttr(p.player_id)}" aria-pressed="${p.player_id === selectedTarget}" onclick="selectVoteTarget(this)">
      <span class="vote-avatar">${escapeHtml(avatarInitial(p))}</span>
      <span class="vote-person"><span class="vote-name">${escapeHtml(p.display_name)}</span>
      <span class="vote-seat">#${seatNumberOf(s, p.player_id)}${p.player_id === s.host_id ? " · " + t("lobby_host_badge") : ""}</span></span>
      <span class="vote-choice" aria-hidden="true"></span>
    </button>`).join("");
  document.getElementById("voteBtn").disabled = !selectedTarget;
}

function selectVoteTarget(el) {
  document.querySelectorAll("#voteList .pcard").forEach((r) => { r.classList.remove("selected"); r.setAttribute("aria-pressed", "false"); });
  el.classList.add("selected");
  el.setAttribute("aria-pressed", "true");
  selectedTarget = el.dataset.pid;
  document.getElementById("voteBtn").disabled = false;
}

function submitVote() {
  if (!selectedTarget) return;
  send("vote", { target_id: selectedTarget });
  document.getElementById("voteBtn").disabled = true;
}

// ------------------------------------------------------- outcome screen --

function nameFor(s, playerId) {
  const p = s.players.find((x) => x.player_id === playerId);
  return p ? p.display_name : "Noma'lum";
}
// engine.py joins simultaneous attackers with "/" (e.g. "mafia/maniac"
// when two sources hit the same target the same night), so these are
// per-attacker fragments, translated and then joined below — NOT full
// sentences on their own like the old dict assumed.
const DEATH_REASON_ACTORS_UZ = {
  mafia: "mafiya", maniac: "manik", commissioner: "komissar", kamikaze: "kamikadze",
};
// A handful of reasons are always their own complete, un-joinable string
// (engine.py never combines these with "/") — matched verbatim first.
const DEATH_REASON_FULL_UZ = {
  day_vote: "shahar tomonidan osib qo'yildi",
  removed_by_admin: "admin tomonidan o'yindan olib tashlandi",
};
function deathReasonUz(reason) {
  if (DEATH_REASON_FULL_UZ[reason]) return DEATH_REASON_FULL_UZ[reason];
  const parts = String(reason).split("/").map((r) => DEATH_REASON_ACTORS_UZ[r] || r);
  return `${parts.join(" va ")} tomonidan o'ldirildi`;
}

function renderOutcomeScreen(s, opts) {
  const heroEl = document.getElementById("outcomeHero");
  const extraEl = document.getElementById("outcomeExtra");
  const titleEl = document.getElementById("outcomeTitle");
  const introEl = document.getElementById("outcomeIntro");
  const continueBtn = document.getElementById("outcomeContinueBtn");
  continueBtn.disabled = false;
  extraEl.innerHTML = "";
  heroEl.style.display = "";

  function roleCardFor(playerId) {
    const p = s.players.find((x) => x.player_id === playerId);
    return p && p.role ? roleByApiName[p.role] : null;
  }

  if (opts.kind === "night") {
    const deaths = s.last_night_deaths || [];
    titleEl.textContent = "TUN NATIJASI";
    introEl.textContent = deaths.length ? "Shahar kimnidir yo'qotdi..." : "Bu kecha hech kim o'lmadi.";
    if (deaths.length === 0) {
      heroEl.style.backgroundImage = "";
      heroEl.style.aspectRatio = "auto";
      heroEl.innerHTML = `<div class="card" style="text-align:center;padding:28px">Hammasi tinch o'tdi.</div>`;
    } else {
      const first = deaths[0];
      const roleMeta = roleCardFor(first.player_id);
      heroEl.style.backgroundImage = "";
      heroEl.style.aspectRatio = "";
      heroEl.innerHTML = `
        ${roleMeta ? `<div style="position:absolute;inset:0">${roleArtHtml(roleMeta)}</div>` : ""}
        <div class="death-content"><div class="big-name" style="color:#fff;text-shadow:0 2px 14px rgba(0,0,0,.6)">${escapeHtml(nameFor(s, first.player_id))}</div>
        <div class="subtitle" style="color:var(--red-hi);font-weight:700;letter-spacing:.06em">O'LDIRILDI</div></div>`;
      if (deaths.length > 1) {
        extraEl.innerHTML = `<div class="card" style="margin-top:14px">` +
          deaths.slice(1).map((d) => `<div class="deathrow"><b>${escapeHtml(nameFor(s, d.player_id))}</b> — ${deathReasonUz(d.reason)}</div>`).join("") +
          `</div>`;
      }
    }
    continueBtn.onclick = () => { go("day"); };
    continueBtn.textContent = "Davom etish";
    return;
  }

  // day-vote outcome
  heroEl.style.display = "none";
  const result = s.last_vote_result;
  titleEl.textContent = "OVOZ NATIJASI";
  const totals = (result && result.totals) || {};

  const rosterHtml = s.players.map((p, i) => {
    const isOut = !!(result && result.eliminated === p.player_id);
    const dead = !p.alive;
    return `<div class="ocard ${isOut ? "out" : ""}${dead && !isOut ? " dead" : ""}">
      <div class="ocard-num">${i + 1}</div>
      ${isOut ? `<svg class="icon ocard-crown"><use href="#i-crown"/></svg>` : ""}
      <div class="avatar" style="${avatarStyle(p)}">${!p.avatar_url ? avatarInitial(p) : ""}</div>
      <div class="ocard-name">${escapeHtml(p.display_name)}${p.player_id === myPlayerId ? " (siz)" : ""}</div>
      <div class="ocard-dot ${p.alive ? "alive" : ""}"></div>
    </div>`;
  }).join("");

  const ranked = s.players.slice().sort((a, b) => (totals[b.player_id] || 0) - (totals[a.player_id] || 0));
  const maxVotes = Math.max(1, ...ranked.map((p) => totals[p.player_id] || 0));
  const resultsHtml = ranked.map((p, i) => {
    const v = totals[p.player_id] || 0;
    const isTop = !!(result && result.eliminated === p.player_id);
    return `<div class="ores-row ${isTop ? "top" : ""}">
      <div class="ores-rank">${i + 1}</div>
      <div class="ores-avatar" style="${avatarStyle(p)}">${!p.avatar_url ? avatarInitial(p) : ""}</div>
      <div class="ores-body">
        <div class="ores-name">${escapeHtml(p.display_name)}${p.player_id === myPlayerId ? " (siz)" : ""}${isTop ? `<svg class="icon" style="width:13px;height:13px;color:var(--gold)"><use href="#i-crown"/></svg>` : ""}</div>
        <div class="ores-bar-track"><div class="ores-bar-fill" style="width:${(v / maxVotes) * 100}%"></div></div>
      </div>
      <div class="ores-count">${v} <span>ovoz</span></div>
    </div>`;
  }).join("");

  let heroHtml = "";
  let wordsHtml = "";
  if (!result || !result.eliminated) {
    introEl.textContent = "Ovozlar taqsimlandi — hech kim osilmadi.";
    heroHtml = `<div class="card" style="text-align:center;padding:22px;margin-top:14px">Shahar qaror qila olmadi.</div>`;
  } else {
    introEl.textContent = "Shahar hukmini chiqardi.";
    const victim = s.players.find((p) => p.player_id === result.eliminated);
    const roleMeta = roleCardFor(result.eliminated);
    const photoHtml = roleMeta
      ? roleArtHtml(roleMeta)
      : `<div class="avatar" style="${avatarStyle(victim)};width:100%;height:100%;margin:0;border-radius:8px"></div>`;
    heroHtml = `<div class="result-hero">
      <div class="result-photo">${photoHtml}</div>
      <div class="result-info">
        <div class="result-name">${escapeHtml(victim.display_name)}</div>
        <div class="result-desc">eng ko'p ovoz oldi va afsuski, o'yinni tark etdi.</div>
        ${roleMeta ? `<div class="result-rolebox"><span class="lbl">Uning roli:</span><span class="val">${roleMeta.name}</span></div>` : ""}
      </div>
    </div>`;

    // The eliminated player gets a 60s window (see PhaseManager.to_vote_results)
    // to leave a final message; everyone else just sees it once submitted.
    if (victim.last_words) {
      wordsHtml = `<div class="card" style="margin-top:14px">
        <div class="smallcap">SO'NGGI SO'Z</div>
        <div style="margin-top:8px;font-style:italic;color:var(--text);line-height:1.5">\u201C${escapeHtml(victim.last_words)}\u201D</div>
        <div style="margin-top:5px;color:var(--muted2);font:600 12px var(--ui)">\u2014 ${escapeHtml(victim.display_name)}</div>
      </div>`;
    } else if (s.me && s.me.player_id === result.eliminated) {
      wordsHtml = `<div class="card" style="margin-top:14px">
        <div class="smallcap">SO'NGGI SO'Z <span id="lastWordsTimer" style="float:right;color:var(--red-hi)"></span></div>
        <textarea id="lastWordsInput" maxlength="200" rows="2" placeholder="Oxirgi so'zingizni yozing..."
          style="width:100%;margin-top:8px;background:var(--panel2);border:1px solid var(--line-soft);
          border-radius:10px;color:var(--text);padding:10px;font:13px var(--body);resize:none"></textarea>
        <button class="btn gold" style="margin-top:8px" onclick="submitLastWords()">Yuborish</button>
      </div>`;
    }
  }

  extraEl.innerHTML = `<div class="orow">${rosterHtml}</div><div class="card oresults" style="margin-top:10px">${resultsHtml}</div>${heroHtml}${wordsHtml}`;
  if (document.getElementById("lastWordsTimer")) startCountdown(s.phase_ends_in, ["lastWordsTimer"]);
  continueBtn.textContent = "Keyingi tun avtomatik boshlanadi";
  continueBtn.disabled = true;
  continueBtn.onclick = null;
}

function submitLastWords() {
  const el = document.getElementById("lastWordsInput");
  if (!el) return;
  const text = el.value.trim();
  if (!text) return;
  send("last_words", { text });
  el.disabled = true;
  const btn = el.nextElementSibling;
  if (btn) btn.disabled = true;
}

function dismissOutcome() {
  // Fallback for the generic button binding; renderOutcomeScreen always
  // overrides onclick with the correct behavior for what's on screen.
  go("day");
}

// ------------------------------------------------------------ win screen --

function renderWinScreen(s) {
  const w = s.winner || {};
  const winners = (w.winners || []).map((pid) => nameFor(s, pid)).filter(Boolean);
  const list = winners.length ? winners.join(", ") : "";
  // Spec items 10/11 + bug 6: a Jester lynched by the day vote, or a
  // Survivor alive at game end, wins individually alongside whatever the
  // main winner above turns out to be (Town, Mafia, or nobody at all —
  // see WinConditionManager.check's "no faction remains" case). This is
  // never folded into `winners`/`list` above: individual wins are called
  // out on their own line so e.g. "Town won, and the Jester also won" is
  // never misread as "the Jester was part of Town's win".
  const individualWinners = (w.individual_winners || []).map((pid) => nameFor(s, pid)).filter(Boolean);
  const individualList = individualWinners.length ? individualWinners.join(", ") : "";
  const targetScreen = w.faction === "town" ? "town_win" : "mafia_win";

  if (w.faction === "town") {
    document.getElementById("winNotice").textContent = "Barcha mafiya yo'q qilindi. Shahar tinch." + (list ? ` G'oliblar: ${list}.` : "");
  } else if (w.faction === "mafia") {
    document.getElementById("winBoxM").classList.remove("neutral");
    document.getElementById("winBoxM").classList.add("red");
    document.getElementById("winTitleM").textContent = "MAFIYA G'ALABA QOZONDI!";
    document.getElementById("winNoticeM").textContent = "Shahar mafiyaning qo'liga o'tdi." + (list ? ` G'oliblar: ${list}.` : "");
  } else {
    // Neutral win, or no main winner at all (only individual neutral
    // winner(s) left standing, e.g. a lone Survivor) — no unique art yet,
    // so we reuse the mafia_win banner recolored purple.
    document.getElementById("winBoxM").classList.remove("red");
    document.getElementById("winBoxM").classList.add("neutral");
    document.getElementById("winTitleM").textContent = "MUSTAQIL G'OLIB!";
    document.getElementById("winNoticeM").textContent = (w.reason || "") + (list ? ` G'olib: ${list}.` : "");
  }

  // Individual winners get their own line, shown only when there are any
  // — an empty "Mustaqil g'oliblar:" line would be a misleading result
  // for the common case (no Jester/Survivor in this match at all).
  const indivEl = document.getElementById(targetScreen === "town_win" ? "winIndividual" : "winIndividualM");
  if (indivEl) {
    if (individualList) {
      indivEl.textContent = `Mustaqil g'oliblar: ${individualList}`;
      indivEl.style.display = "";
    } else {
      indivEl.textContent = "";
      indivEl.style.display = "none";
    }
  }

  renderFinalStats(s, targetScreen === "town_win" ? "myStats" : "myStatsM");
  renderFinalRoster(s, targetScreen === "town_win" ? "finalRosterWin" : "finalRosterWinM", targetScreen === "town_win" ? "finalRosterLose" : "finalRosterLoseM");
  go(targetScreen);

  // Show the big cinematic card reveal exactly once per game. The
  // stats/roster screen above is already rendered underneath it, so
  // tapping "Ma'lumotlar" just has to dismiss the overlay.
  if (!winRevealShown) {
    winRevealShown = true;
    showWinReveal(w.faction);
  }
}

function showWinReveal(faction) {
  const overlay = document.getElementById("winReveal");
  const cardwrap = document.getElementById("winRevealCardwrap");
  const art = document.getElementById("winRevealArt");
  art.innerHTML = winPosterHtml(faction);
  cardwrap.classList.toggle("red", faction === "mafia");
  overlay.classList.remove("closing");
  overlay.classList.add("show");
}

// Cinematic victory poster — the winning faction's representative card,
// full-bleed, tinted by the faction glow.
function winPosterHtml(faction) {
  const a = ART_AUX[faction] || ART_AUX.town;
  const rep = faction === "mafia" ? "Mafia" : faction === "neutral" ? "Maniac" : "Commissioner";
  return `<div class="winposter" style="--artglow:${a.glow}">
    <img class="winposter-img" src="/static/cards/full/${rep}.webp" alt="" draggable="false">
  </div>`;
}

function closeWinReveal() {
  const overlay = document.getElementById("winReveal");
  if (!overlay.classList.contains("show")) return;
  overlay.classList.add("closing");
  setTimeout(() => { overlay.classList.remove("show", "closing"); }, 340);
}

function renderFinalStats(s, elId) {
  const st = (s.me && s.me.stats) || {};
  const rows = [
    [st.won ? "G'ALABA" : "MAG'LUBIYAT", "NATIJA"],
    [st.role || "—", "ROLINGIZ"],
    [st.kills != null ? st.kills : 0, "O'LDIRISH"],
    [st.investigations != null ? st.investigations : 0, "TEKSHIRUV"],
    [st.protections != null ? st.protections : 0, "HIMOYA"],
    [st.votes_cast != null ? st.votes_cast : 0, "OVOZ"],
  ];
  document.getElementById(elId).innerHTML = rows.map(([val, label]) =>
    `<div class="statbox"><b>${escapeHtml(String(val))}</b><span>${label}</span></div>`).join("");
}

function renderFinalRoster(s, winElId, loseElId) {
  // Individual winners (Jester lynched, Survivor alive at the end) belong
  // in the winners column too, same as `me.stats.won` already counts them
  // server-side (see GameEngine.get_player_view) — otherwise a Jester who
  // won individually would show up in MAG'LUBLAR (losers) on everyone
  // else's screen while their own stat card says they won.
  const winners = new Set([
    ...((s.winner && s.winner.winners) || []),
    ...((s.winner && s.winner.individual_winners) || []),
  ]);
  const rowHtml = (p) => {
    const r = roleByApiName[p.role];
    const facColor = r ? (r.fac === "mafia" ? "var(--red-hi)" : r.fac === "town" ? "var(--town-hi)" : "var(--neutral-hi)") : "var(--muted)";
    return `<div class="rosterrow">
      <div class="avatar" style="${avatarStyle(p)}">${!p.avatar_url ? avatarInitial(p) : ""}</div>
      <span class="rname">${escapeHtml(p.display_name)}${!p.alive ? " †" : ""}</span>
      <span class="smallcap" style="color:${facColor}">${p.role || "?"}</span>
    </div>`;
  };
  const winList = s.players.filter((p) => winners.has(p.player_id));
  const loseList = s.players.filter((p) => !winners.has(p.player_id));
  const winBox = document.getElementById(winElId).closest(".rostergroup");
  const loseBox = document.getElementById(loseElId).closest(".rostergroup");
  document.getElementById(winElId).innerHTML = winList.map(rowHtml).join("");
  document.getElementById(loseElId).innerHTML = loseList.map(rowHtml).join("");
  if (winBox) winBox.style.display = winList.length ? "" : "none";
  if (loseBox) loseBox.style.display = loseList.length ? "" : "none";
}

// ------------------------------------------------------------- utilities --

function escapeHtml(str) {
  return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ----------------------------------------------------------- admin panel --
// Level 1 — "Boshqaruv": the seven-module panel (users, admins, texts,
// broadcasts, groups, statistics, settings). Each module is gated by the
// server-side permission in admin_service; the WebApp's is_bot_admin /
// permissions flags are display conveniences only.
// Level 2 — "O'yin nazorati": the inherited bot-owner game-control routes
// (routes_admin.py, super-admin-only) for live matches and bot test games.
// Both are deliberately independent of currentState/ws — the admin sees
// every match across every group without ever joining one as a player.
// Driven entirely by REST calls, not the per-game WebSocket this file
// otherwise uses.

let isBotAdmin = false;
let isSuperAdmin = false;
let myPermissions = [];

let adminMode = "panel";           // "panel" (7 modules) | "control" (live games/bots)
let adminTabActive = "users";      // panel module tab
let adminCtrlTab = "ctrlgames";    // control sub-tab

// ---- panel module state
let adminUserFilter = "";
let adminUsersOnlyBlocked = false;
let adminSelectedUser = null;
let adminAdmins = [];
let adminAddAdminId = "";
let adminPermCatalog = null;
let adminTexts = null;
let adminTextKey = "start";
let adminTextLang = "uz";
let adminGroups = [];
let adminGroupSearch = "";
let adminGroupsOnlyActive = false;
let adminStats = null;
let adminButtons = null;

// ---- control-mode state
let adminGamesList = [];
let adminSelectedGameId = null;
let adminSelectedGameDetail = null;
// True when the panel was opened straight from the bot's "Admin WebApp"
// button (?view=admin) rather than from inside a game. In that mode there
// is no lobby to fall back to, so the back arrow closes the Mini App.
let adminStandalone = false;
// Bots tab: how many AI seats the owner has dialed in for their next
// practice match. Kept separate from adminGamesList so the stepper
// doesn't reset every adminRefresh() poll.
let adminBotCount = 4;
// Mirrors the backend's BOT_GAME_CHAT_PREFIX (app/services/game_service.py) —
// how a practice match's synthetic chat_id is recognised in adminGamesList.
const BOT_GAME_CHAT_PREFIX = "botlab:";

const PHASE_LABEL_UZ = {
  lobby: "Lobbi", role_assignment: "Rol taqsimoti", night: "Tun",
  morning: "Tun natijasi", day_discussion: "Kunduz — muhokama", voting: "Ovoz berish",
  lynch_confirmation: "Osib o'ldirish tasdig'i", kamikaze_strike: "Kamikadze zarbasi",
  vote_results: "Ovoz natijasi", game_over: "O'yin tugadi",
};
const PHASE_PILL = {
  lobby: "lobby", role_assignment: "live", night: "live",
  morning: "live", day_discussion: "live", voting: "live",
  lynch_confirmation: "live", kamikaze_strike: "live",
  vote_results: "live", game_over: "over",
};

// Panel module (data-apmod) → required server-side permission.
const PERMISSION_BY_TAB = {
  users: "users.view", admins: "admins.view", texts: "texts.view",
  groups: "groups.view",
  stats: "statistics.view", settings: "settings.view",
};
const MODULE_ORDER = ["users", "admins", "texts", "groups", "stats", "settings"];
const MODULE_LABELS = {
  support: "Murojaatlar",
  users: "Foydalanuvchilar", admins: "Adminlar", texts: "Bot matnlari",
  groups: "Guruhlar", stats: "Statistika", settings: "Sozlamalar",
};

function hasPermission(perm) {
  return isSuperAdmin || (myPermissions || []).includes(perm);
}

function openAdminPanel(opts) {
  adminStandalone = !!(opts && opts.standalone);
  if (adminStandalone) establishRoot("admin");
  const modeSwitch = document.getElementById("adminModeSwitch");
  if (modeSwitch) modeSwitch.style.display = isSuperAdmin ? "" : "none";
  if (!isSuperAdmin && adminMode === "control") adminMode = "panel";
  applyAdminCapabilities();
  go("admin");
  adminTab(adminMode === "control"
    ? (adminCtrlTab === "ctrlgames" ? "ctrlgames" : "ctrlbots")
    : adminTabActive);
}

function applyAdminCapabilities() {
  document.querySelectorAll("#adminModuleTabs .ap-tab").forEach((btn) => {
    const perm = PERMISSION_BY_TAB[btn.dataset.apmod];
    btn.style.display = hasPermission(perm) ? "" : "none";
  });
  if (!hasPermission(PERMISSION_BY_TAB[adminTabActive])) {
    const first = MODULE_ORDER.find((m) => hasPermission(PERMISSION_BY_TAB[m]));
    if (first) adminTabActive = first;
  }
}

function adminExit() {
  if (adminStandalone) {
    if (tg && tg.close) { tg.close(); return; }
  }
  adminSelectedGameId = null;
  adminSelectedGameDetail = null;
  go("home");
}

function adminSetMode(mode) {
  adminMode = mode;
  adminTab(adminMode === "control"
    ? (adminCtrlTab === "ctrlgames" ? "ctrlgames" : "ctrlbots")
    : adminTabActive);
}

function adminTab(tab) {
  if (Object.prototype.hasOwnProperty.call(PERMISSION_BY_TAB, tab)) {
    adminMode = "panel";
    adminTabActive = tab;
  } else if (tab === "ctrlgames" || tab === "ctrlbots") {
    adminCtrlTab = tab;
    if (tab === "ctrlgames") { adminSelectedGameId = null; adminSelectedGameDetail = null; }
  }
  document.getElementById("adminModuleTabs").style.display = adminMode === "panel" ? "" : "none";
  document.getElementById("adminControlTabs").style.display = adminMode === "control" ? "" : "none";
  document.getElementById("apModePanel").classList.toggle("active", adminMode === "panel");
  document.getElementById("apModeControl").classList.toggle("active", adminMode === "control");
  document.querySelectorAll("#adminModuleTabs .ap-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.apmod === adminTabActive));
  document.querySelectorAll("#adminControlTabs .ap-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.actrl === adminCtrlTab));
  document.querySelectorAll(".ap-pane").forEach((p) => (p.style.display = "none"));
  const panelPanes = {
    users: "apUsers", admins: "apAdmins", texts: "apTexts",
    groups: "apGroups", stats: "apStats", settings: "apSettings",
  };
  const paneId = adminMode === "panel"
    ? (panelPanes[adminTabActive] || "apUsers")
    : (adminCtrlTab === "ctrlgames" ? "apControlGames" : "apControlBots");
  const pane = document.getElementById(paneId);
  if (pane) pane.style.display = "";
  renderAdminScreen();
  window.scrollTo(0, 0);
  // The actual data fetch — this used to be missing here entirely, so
  // switching tabs only ever re-rendered whatever was already in memory.
  // The tab shown on first open worked (openAdminPanel called adminRefresh
  // once, separately) but every other tab stayed on its "Yuklanmoqda..."
  // placeholder forever, since nothing ever fetched for it.
  adminRefresh();
}

// One fetch per visible concern, all tolerant of failure: a single dead
// endpoint shouldn't blank the whole panel, so each result falls back to
// its empty shape and the UI renders what it has.
async function adminRefresh() {
  if (adminMode === "control") {
    adminGamesList = await api("/admin/games").then((r) => r.games).catch(() => []);
    if (adminSelectedGameId) {
      adminSelectedGameDetail =
        await api(`/admin/games/${adminSelectedGameId}`).catch(() => null);
      if (!adminSelectedGameDetail) adminSelectedGameId = null;
    }
    renderAdminScreen();
    return;
  }
  const tab = adminTabActive;
  if (tab === "users") await refreshUsers();
  else if (tab === "admins") await refreshAdmins();
  else if (tab === "texts") await refreshTexts();
  else if (tab === "groups") await refreshGroups();
  else if (tab === "stats") await refreshStats();
  else if (tab === "settings") { await refreshButtons(); await loadPermCatalog(); }
  renderAdminScreen();
}

async function adminOpenGame(gameId) {
  try {
    adminSelectedGameDetail = await api(`/admin/games/${gameId}`);
    adminSelectedGameId = gameId;
  } catch (e) {
    toast(e.message);
    adminSelectedGameId = null;
    adminSelectedGameDetail = null;
  }
  renderAdminScreen();
}

function adminBackToGamesList() {
  adminSelectedGameId = null;
  adminSelectedGameDetail = null;
  renderAdminScreen();
  adminRefresh();
}

function renderAdminScreen() {
  if (adminMode === "control") {
    if (adminCtrlTab === "ctrlgames") {
      if (adminSelectedGameDetail) renderAdminGameDetail(adminSelectedGameDetail);
      else renderAdminGamesList();
    } else renderAdminBots();
    return;
  }
  const tab = adminTabActive;
  if (tab === "users") { if (adminSelectedUser) renderUsersDetail(); else renderUsers(); }
  else if (tab === "admins") renderAdmins();
  else if (tab === "texts") renderTexts();
  else if (tab === "groups") renderGroups();
  else if (tab === "stats") renderStats();
  else if (tab === "settings") renderSettings();
}

// ------------------------------------------------------ users module ------
// Foydalanuvchilar: search / block / make-admin from the user detail.
// Permission: users.view (list+detail), users.manage (block/unblock).

let adminUsersAll = [];

async function refreshUsers() {
  const q = new URLSearchParams();
  if (adminUserFilter) q.set("search", adminUserFilter);
  if (adminUsersOnlyBlocked) q.set("only_blocked", "1");
  q.set("limit", "100");
  adminUsersAll = await api(`/admin/users?${q.toString()}`).then((r) => r.users || []).catch(() => []);
}

function renderUsers() {
  const el = document.getElementById("apUsers");
  el.innerHTML = `
    <div class="ap-card">
      <div class="ap-h"><span>Qidiruv</span></div>
      <div class="ap-search">
        <input class="ap-input" id="usersSearchInput" placeholder="Ism, username yoki ID..." value="${escapeAttr(adminUserFilter)}"
          onkeydown="if(event.key==='Enter')adminUserApplySearch()">
        <button class="ap-searchbtn" onclick="adminUserApplySearch()">Qidirish</button>
      </div>
      <div class="ap-filterrow">
        <button class="ap-chip ${adminUsersOnlyBlocked ? "on" : ""}" onclick="adminUsersToggleBlocked()">Bloklanganlar</button>
        ${adminUserFilter || adminUsersOnlyBlocked ? `<button class="ap-chip" onclick="adminUserClearSearch()">Tozalash</button>` : ""}
      </div>
      <div class="ap-hint">${adminUsersAll.length} ta natija</div>
    </div>
    ${adminUsersAll.length ? adminUsersAll.map((u) => `
      <div class="ap-card">
        <div class="ap-row" style="cursor:pointer" onclick="adminUserDetail(${u.telegram_user_id})">
          <span class="avatar" style="width:38px;height:38px;flex:0 0 38px;${profileAvatarStyle(u)}">${u.photo_url ? "" : profileInitial(u)}</span>
          <span class="grow" style="min-width:0">
            <span class="rname">${escapeHtml(u.display_name)}${u.is_admin ? ' <span class="ap-tag admin">Admin</span>' : ""}${u.blocked ? ' <span class="ap-tag blocked">Blok</span>' : ""}</span>
            <span class="rmeta">${u.games_played} o'yin &middot; ${u.wins} g'alaba &middot; ${u.win_rate}%</span>
          </span>
          <svg class="icon ap-chevron" style="transform:rotate(180deg)"><use href="#i-chevleft"/></svg>
        </div>
      </div>`).join("") : `<div class="ap-card"><div class="ap-empty">Foydalanuvchi topilmadi</div></div>`}`;
}

function adminUserApplySearch() {
  const inp = document.getElementById("usersSearchInput");
  adminUserFilter = inp ? inp.value.trim() : "";
  adminSelectedUser = null;
  adminRefresh();
}

function adminUsersToggleBlocked() {
  adminUsersOnlyBlocked = !adminUsersOnlyBlocked;
  adminSelectedUser = null;
  adminRefresh();
}

function adminUserClearSearch() {
  adminUserFilter = "";
  adminUsersOnlyBlocked = false;
  adminSelectedUser = null;
  adminRefresh();
}

async function adminUserDetail(userId) {
  try {
    adminSelectedUser = await api(`/admin/users/${userId}`);
  } catch (e) {
    toast(e.message);
    adminSelectedUser = null;
    return;
  }
  renderAdminScreen();
}

function adminUserBack() { adminSelectedUser = null; renderAdminScreen(); }

function renderUsersDetail() {
  const u = adminSelectedUser;
  const canManageUsers = hasPermission("users.manage");
  const canManageAdmins = hasPermission("admins.manage");
  const el = document.getElementById("apUsers");
  el.innerHTML = `
    <button class="ap-btn dark" style="margin:0 0 12px" onclick="adminUserBack()">&larr; Ro'yxatga</button>
    <div class="ap-card">
      <div class="ap-h">
        <span class="avatar" style="width:40px;height:40px;flex:0 0 40px;${profileAvatarStyle(u)}">${u.photo_url ? "" : profileInitial(u)}</span>
        <span style="min-width:0">
          <span class="rname">${escapeHtml(u.display_name)}${u.blocked ? ' <span class="ap-tag blocked">Blok</span>' : ""}${u.is_admin ? ' <span class="ap-tag admin">Admin</span>' : ""}</span>
        </span>
      </div>
      <div class="ap-kv"><span class="kv-lbl">Telegram ID</span><b>${u.telegram_user_id}</b></div>
      <div class="ap-kv"><span class="kv-lbl">Username</span><b>${escapeHtml(u.username ? ("@" + u.username) : "—")}</b></div>
      <div class="ap-kv"><span class="kv-lbl">O'yinlar</span><b>${u.games_played}</b></div>
      <div class="ap-kv"><span class="kv-lbl">G'alabalar</span><b>${u.wins}</b></div>
      <div class="ap-kv"><span class="kv-lbl">Mag'lubiyatlar</span><b>${u.losses}</b></div>
      <div class="ap-kv"><span class="kv-lbl">G'alaba foizi</span><b>${u.win_rate}%</b></div>
      ${u.is_admin ? `<div class="ap-kv"><span class="kv-lbl">Ruxsatlar</span><b style="font-size:11.5px">${u.permissions.length ? escapeHtml(u.permissions.join(", ")) : "yo'q"}</b></div>` : ""}
    </div>
    ${u.recent_games && u.recent_games.length ? `
    <div class="ap-card">
      <div class="ap-h"><span>So'nggi o'yinlar</span><span>${u.recent_games.length}</span></div>
      ${u.recent_games.slice(0, 8).map((g) => `
        <div class="ap-kv">
          <span class="kv-lbl"><b class="${g.won ? "history-win" : "history-lose"}">${g.won ? "G'alaba" : "Mag'lubiyat"}</b> &middot; ${escapeHtml(g.role_name || "?")}</span>
          <b>${g.player_count || 0} o'yinchi</b>
        </div>`).join("")}
    </div>` : ""}
    <div class="ap-card">
      <div class="ap-h"><span>Amallar</span></div>
      <div class="ap-btnrow" style="margin-top:12px">
        ${canManageUsers && !u.blocked ? `<button class="ap-btn danger" onclick="adminBlockUser(${u.telegram_user_id})">Bloklash</button>` : ""}
        ${canManageUsers && u.blocked ? `<button class="ap-btn gold" onclick="adminUnblockUser(${u.telegram_user_id})">Blokdan chiqarish</button>` : ""}
        ${canManageAdmins && !u.is_admin ? `<button class="ap-btn dark" onclick="adminMakeAdmin(${u.telegram_user_id})">Admin qilish</button>` : ""}
        ${canManageAdmins && u.is_admin ? `<button class="ap-btn dark" onclick="adminRemoveUserAdmin(${u.telegram_user_id})">Adminlikni olib tashlash</button>` : ""}
      </div>
    </div>`;
}

function adminBlockUser(userId) {
  askConfirm("Bu foydalanuvchini bloklaymizmi? U bot va WebApp'dan foydalana olmaydi.", async () => {
    try { await api(`/admin/users/${userId}/block`, { method: "POST" }); toast("Foydalanuvchi bloklandi"); adminUserBack(); await refreshUsers(); }
    catch (e) { toast(e.message); }
  });
}

function adminUnblockUser(userId) {
  askConfirm("Blokdan chiqaramizmi?", async () => {
    try { await api(`/admin/users/${userId}/unblock`, { method: "POST" }); toast("Blokdan chiqarildi"); adminUserBack(); await refreshUsers(); }
    catch (e) { toast(e.message); }
  });
}

function adminMakeAdmin(userId) {
  askConfirm("Bu foydalanuvchini panel admini qilamizmi? Ruxsatlar keyin 'Adminlar' bo'limida beriladi.", async () => {
    try { await api(`/admin/users/${userId}/make-admin`, { method: "POST" }); toast("Admin qilindi"); adminUserBack(); await refreshUsers(); }
    catch (e) { toast(e.message); }
  });
}

function adminRemoveUserAdmin(userId) {
  askConfirm("Adminlikni olib tashlaymizmi?", async () => {
    try { await api(`/admin/users/${userId}/remove-admin`, { method: "POST" }); toast("Adminlik olib tashlandi"); adminUserBack(); await refreshUsers(); }
    catch (e) { toast(e.message); }
  });
}

// ----------------------------------------------------- admins module ------
// Adminlar: add/remove panel admins and edit their per-module permissions.
// Permission: admins.view (list) + admins.manage (mutation).

async function refreshAdmins() {
  const [admins, catalog] = await Promise.all([
    api("/admin/admins").then((r) => r.admins).catch(() => []),
    api("/admin/permissions").then((r) => r).catch(() => ({ catalog: {} })),
  ]);
  adminAdmins = admins;
  adminPermCatalog = catalog;
}

function renderAdmins() {
  const el = document.getElementById("apAdmins");
  const canManage = hasPermission("admins.manage");
  const catalog = (adminPermCatalog && adminPermCatalog.catalog) || {};
  el.innerHTML = `
    <div class="ap-card">
      <div class="ap-h"><span>Admin qo'shish</span></div>
      ${canManage ? `
      <div class="ap-search">
        <input class="ap-input" id="adminAddAdminId" placeholder="Telegram ID" value="${escapeAttr(adminAddAdminId)}"
          onkeydown="if(event.key==='Enter')adminAddAdmin()">
        <button class="ap-searchbtn" onclick="adminAddAdmin()">Qo'shish</button>
      </div>
      <div class="ap-quicknote">Foydalanuvchi allaqachon botdan kirgan bo'lishi kerak. Qo'shilgach, quyidagi ro'yxatda ruxsatlarni belgilang.</div>`
      : `<div class="ap-empty">Adminlarni boshqarish uchun ruxsat yo'q</div>`}
    </div>
    ${adminAdmins.length ? adminAdmins.map((a) => `
      <div class="ap-card">
        <div class="ap-h"><span>${escapeHtml(a.display_name)}</span>${a.is_super ? ' <span class="ap-tag super">Super Admin</span>' : ""}</div>
        ${a.is_super
          ? `<div class="ap-quicknote">Bot egasi — barcha ruxsatlarga ega, o'zgartirib bo'lmaydi.</div>`
          : (canManage ? `
            <div class="ap-perms" style="margin-top:10px">
              ${Object.keys(catalog).map((mod) => `
                <div style="margin-bottom:10px">
                  <div class="ap-kv" style="margin-bottom:6px"><span class="kv-lbl">${MODULE_LABELS[mod] || mod}</span></div>
                  <div style="display:flex;flex-wrap:wrap;gap:8px">
                    ${catalog[mod].map((perm) => `
                      <label class="ap-ck" style="display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted);cursor:pointer">
                        <input type="checkbox" class="ap-check" value="${perm}" id="perm_${a.telegram_user_id}_${perm}" ${a.permissions.includes(perm) ? "checked" : ""}>
                        ${perm.split(".")[1]}
                      </label>`).join("")}
                  </div>
                </div>`).join("")}
              <button class="ap-btn gold" style="margin-top:4px" onclick="adminSavePermissions(${a.telegram_user_id})">Ruxsatlarni saqlash</button>
              <button class="ap-btn danger" style="margin-top:8px" onclick="adminRemoveAdmin(${a.telegram_user_id})">Adminlikni olib tashlash</button>
            </div>`
          : `<div class="ap-quicknote">Ruxsatlar: ${escapeHtml((a.permissions || []).join(", ") || "yo'q")}</div>`)}
      </div>`).join("") : `<div class="ap-card"><div class="ap-empty">Adminlar yo'q</div></div>`}`;
}

function adminAddAdmin() {
  const id = parseInt(adminAddAdminId.trim(), 10);
  if (!id) { toast("Telegram ID kiriting"); return; }
  (async () => {
    try { await api("/admin/admins", { method: "POST", body: JSON.stringify({ telegram_user_id: id }) }); toast("Admin qo'shildi"); adminAddAdminId = ""; await refreshAdmins(); renderAdminScreen(); }
    catch (e) { toast(e.message); }
  })();
}

function adminRemoveAdmin(userId) {
  askConfirm("Bu foydalanuvchini adminlikdan olib tashlaymizmi?", async () => {
    try { await api(`/admin/admins/${userId}`, { method: "DELETE" }); toast("Adminlik olib tashlandi"); await refreshAdmins(); renderAdminScreen(); }
    catch (e) { toast(e.message); }
  });
}

function adminSavePermissions(userId) {
  const perms = [];
  document.querySelectorAll(`#apAdmins .ap-check`).forEach((c) => { if (c.checked) perms.push(c.value); });
  (async () => {
    try { await api(`/admin/admins/${userId}/permissions`, { method: "PUT", body: JSON.stringify({ permissions: perms }) }); toast("Ruxsatlar saqlandi"); await refreshAdmins(); renderAdminScreen(); }
    catch (e) { toast(e.message); }
  })();
}

// ------------------------------------------------- control: games ------

function renderAdminGamesList() {
  document.getElementById("apControlGames").innerHTML = `
    <div class="ap-card">
      <div class="ap-h"><span>Faol o'yinlar</span><span>${adminGamesList.length}</span></div>
      <div class="ap-hint">Boshqa guruhlardagi jonli o'yinlar. Batafsil nazorat uchun biron o'yinga kiring.</div>
      ${adminGamesList.length ? adminGamesList.map((g) => `
        <div class="ap-row" style="cursor:pointer" onclick="adminOpenGame('${g.game_id}')">
          <span class="grow">
            <span class="rname">${escapeHtml(g.chat_id || g.game_id)}</span>
            <span class="rmeta">${escapeHtml(g.host_display_name || "?")} · ${g.alive_count}/${g.player_count} tirik</span>
          </span>
          <span class="ap-pill ${PHASE_PILL[g.phase] || "over"}">${PHASE_LABEL_UZ[g.phase] || g.phase}</span>
          <svg class="icon ap-chevron" style="transform:rotate(180deg)"><use href="#i-chevleft"/></svg>
        </div>`).join("") : `<div class="ap-empty">Hozircha faol o'yin yo'q</div>`}
    </div>`;
}

function renderAdminGameDetail(g) {
  const inLobby = g.phase === "lobby";
  document.getElementById("apControlGames").innerHTML = `
    <div class="ap-card">
      <button class="ap-btn dark" style="margin:0 0 14px" onclick="adminBackToGamesList()">← Barcha o'yinlar</button>
      <div class="ap-h"><span>${escapeHtml(g.chat_id || g.game_id)}</span>
        <span class="ap-pill ${PHASE_PILL[g.phase] || "over"}">${PHASE_LABEL_UZ[g.phase] || g.phase}</span></div>
      <div class="ap-stats" style="margin-top:12px">
        <div class="ap-stat"><b>${g.night_number}</b><span>Kecha</span></div>
        <div class="ap-stat"><b>${g.day_number}</b><span>Kun</span></div>
      </div>
      <div class="ap-btnrow" style="margin-top:14px">
        <button class="ap-btn dark" ${inLobby ? "disabled" : ""} onclick="adminForceAdvance('${g.game_id}')">Keyingi bosqich</button>
        <button class="ap-btn dark" ${inLobby ? "disabled" : ""} onclick="adminExtendTimer('${g.game_id}')">+30 soniya</button>
      </div>
      <button class="ap-btn danger" onclick="adminTerminateGame('${g.game_id}')">O'yinni tugatish</button>
    </div>

    <div class="ap-card">
      <div class="ap-h"><span>O'yinchilar</span><span>${g.players.length}</span></div>
      ${g.players.map((p) => `
        <div class="ap-row">
          <span class="grow">
            <span class="rname">${escapeHtml(p.display_name)}${p.is_host ? " 👑" : ""}${!p.alive ? " †" : ""}</span>
            <span class="rmeta">${escapeHtml(p.role || "rol berilmagan")}${p.connected ? "" : " · oflayn"}</span>
          </span>
          <button class="ap-btn danger ap-mini" onclick="adminRemovePlayer('${g.game_id}','${p.player_id}')">Chiqarish</button>
        </div>`).join("")}
    </div>`;
}

// ------------------------------------------------------ texts module -----
// Bot matnlari: edit the three bot texts bot_config exposes, per language.
// Permission: texts.view (list+edit form) + texts.manage (save).

const ADMIN_TEXT_LABELS = {
  start: "Start matni", group_added: "Guruhga qo'shilish", lobby: "Lobbi matni",
};

async function refreshTexts() {
  adminTexts = await api("/admin/texts").then((r) => r.texts || null).catch(() => null);
}

function renderTexts() {
  const el = document.getElementById("apTexts");
  if (!adminTexts) {
    el.innerHTML = `<div class="ap-card"><div class="waitnote"><span class="dotpulse"></span>Yuklanmoqda...</div></div>`;
    return;
  }
  const canManage = hasPermission("texts.manage");
  const item = adminTexts.find((x) => x.key === adminTextKey) || { key: adminTextKey, uz: "", ru: "", en: "" };
  el.innerHTML = `
    <div class="ap-card">
      <div class="ap-h"><span>Bot matnlari</span></div>
      <div class="ap-quick" style="margin-top:12px">
        ${adminTexts.map((x) => `
          <button class="ap-chip ${x.key === adminTextKey ? "on" : ""}" onclick="adminTextSelectKey('${x.key}')">${ADMIN_TEXT_LABELS[x.key] || x.key}</button>`).join("")}
      </div>
    </div>
    <div class="ap-card">
      <div class="ap-h"><span>${ADMIN_TEXT_LABELS[item.key] || item.key}</span></div>
      <div class="ap-quick" style="margin-top:10px">
        ${["uz", "ru", "en"].map((l) => `
          <button class="ap-chip ${l === adminTextLang ? "on" : ""}" onclick="adminTextSelectLang('${l}')">${l.toUpperCase()}</button>`).join("")}
      </div>
      <div class="ap-field" style="margin-top:12px">
        <label>Matn (${adminTextLang})</label>
        <textarea class="ap-input textarea" id="adminTextValue">${escapeHtml(item[adminTextLang] || "")}</textarea>
      </div>
      ${canManage
        ? `<button class="ap-btn gold" style="margin:14px 0 0" onclick="adminSaveText('${item.key}','${adminTextLang}')">Saqlash</button>`
        : `<div class="ap-quicknote">Faqat ko'rish — tahrirlash ruxsati yo'q.</div>`}
    </div>`;
}

function adminTextSelectKey(key) { adminTextKey = key; renderTexts(); }
function adminTextSelectLang(lang) { adminTextLang = lang; renderTexts(); }

function adminSaveText(key, lang) {
  const val = document.getElementById("adminTextValue");
  const value = val ? val.value : "";
  (async () => {
    try {
      await api(`/admin/texts/${key}/${lang}`, { method: "PUT", body: JSON.stringify({ value }) });
      toast("Matn saqlandi");
      await refreshTexts();
      renderTexts();
    } catch (e) { toast(e.message); }
  })();
}

// ------------------------------------------------------ groups module -----
// Guruhlar: list groups with activity, enable/disable them.
// Permission: groups.view (list) + groups.manage (status toggle).

async function refreshGroups() {
  const q = new URLSearchParams();
  if (adminGroupSearch) q.set("search", adminGroupSearch);
  if (adminGroupsOnlyActive) q.set("only_active", "1");
  adminGroups = await api(`/admin/groups?${q.toString()}`).then((r) => r.groups || []).catch(() => []);
}

function renderGroups() {
  const el = document.getElementById("apGroups");
  const canManage = hasPermission("groups.manage");
  el.innerHTML = `
    <div class="ap-card">
      <div class="ap-h"><span>Qidiruv</span></div>
      <div class="ap-search">
        <input class="ap-input" id="groupSearchInput" placeholder="Guruh nomi..." value="${escapeAttr(adminGroupSearch)}"
          onkeydown="if(event.key==='Enter')adminGroupsApplySearch()">
        <button class="ap-searchbtn" onclick="adminGroupsApplySearch()">Qidirish</button>
      </div>
      <div class="ap-filterrow">
        <button class="ap-chip ${adminGroupsOnlyActive ? "on" : ""}" onclick="adminGroupsToggleActive()">Faqat faollar</button>
        ${adminGroupSearch || adminGroupsOnlyActive ? `<button class="ap-chip" onclick="adminGroupsClear()">Tozalash</button>` : ""}
      </div>
    </div>
    ${adminGroups.length ? adminGroups.map((g) => `
      <div class="ap-card">
        <div class="ap-row">
          <span class="grow">
            <span class="rname">${escapeHtml(g.title)}</span>
            <span class="rmeta">Chat ID ${g.chat_id} &middot; ${g.finished_games} o'yin${g.current_game ? " &middot; jonli · " + (PHASE_LABEL_UZ[g.current_game.phase] || g.current_game.phase) : ""}</span>
          </span>
          <span class="ap-tag ${g.is_active ? "done" : "over"}">${g.is_active ? "Faol" : "O'chiq"}</span>
          ${canManage ? `
          <button class="ap-chip" style="margin-left:4px" onclick="adminToggleGroup('${g.chat_id}', ${!g.is_active})">
            ${g.is_active ? "O'chirish" : "Yoqish"}</button>` : ""}
        </div>
      </div>`).join("") : `<div class="ap-card"><div class="ap-empty">Guruhlar yo'q</div></div>`}`;
}

function adminGroupsApplySearch() {
  const inp = document.getElementById("groupSearchInput");
  adminGroupSearch = inp ? inp.value.trim() : "";
  adminRefresh();
}
function adminGroupsToggleActive() { adminGroupsOnlyActive = !adminGroupsOnlyActive; adminRefresh(); }
function adminGroupsClear() { adminGroupSearch = ""; adminGroupsOnlyActive = false; adminRefresh(); }

function adminToggleGroup(chatId, isActive) {
  askConfirm(`Guruhni ${isActive ? "yoqamizmi" : "o'chiramizmi"}: ${chatId}?`, async () => {
    try {
      await api(`/admin/groups/${chatId}/status`, { method: "POST", body: JSON.stringify({ is_active: isActive }) });
      toast("Holat yangilandi");
      await refreshGroups();
      renderAdminScreen();
    } catch (e) { toast(e.message); }
  });
}

// ------------------------------------------------------- stats module -----
// Umumiy statistika: KPIs, 7-day new-user chart, top players, recent games.
// Permission: statistics.view.

async function refreshStats() {
  adminStats = await api("/admin/statistics").catch(() => null);
}

function renderStats() {
  const el = document.getElementById("apStats");
  if (!adminStats) {
    el.innerHTML = `<div class="ap-card"><div class="waitnote"><span class="dotpulse"></span>Yuklanmoqda...</div></div>`;
    return;
  }
  const kp = adminStats.kp || {};
  const daily = adminStats.daily_new_users || [];
  const maxDay = Math.max(1, ...daily.map((d) => d.count));
  el.innerHTML = `
    <div class="ap-card">
      <div class="ap-h"><span>Foydalanuvchilar</span></div>
      <div class="ap-stats" style="margin-top:12px">
        <div class="ap-stat"><b>${kp.total_users}</b><span>Jami</span></div>
        <div class="ap-stat"><b>${kp.active_users}</b><span>Faol</span></div>
        <div class="ap-stat accent"><b>${kp.blocked_users}</b><span>Bloklangan</span></div>
        <div class="ap-stat"><b>${kp.new_users_today}</b><span>24 soat</span></div>
        <div class="ap-stat"><b>${kp.new_users_week}</b><span>7 kun</span></div>
        <div class="ap-stat"><b>${kp.players_in_play}</b><span>O'yindagilar</span></div>
      </div>
    </div>
    <div class="ap-card">
      <div class="ap-h"><span>O'yinlar</span></div>
      <div class="ap-stats" style="margin-top:12px">
        <div class="ap-stat accent"><b>${kp.active_games}</b><span>Jonli o'yinlar</span></div>
        <div class="ap-stat"><b>${kp.total_finished_games}</b><span>Jami tugagan</span></div>
        <div class="ap-stat"><b>${kp.games_today}</b><span>24 soat</span></div>
        <div class="ap-stat"><b>${kp.games_week}</b><span>7 kun</span></div>
        <div class="ap-stat"><b>${kp.games_month}</b><span>30 kun</span></div>
      </div>
    </div>
    <div class="ap-card">
      <div class="ap-h"><span>Guruhlar</span></div>
      <div class="ap-stats" style="margin-top:12px">
        <div class="ap-stat"><b>${kp.total_groups}</b><span>Jami</span></div>
        <div class="ap-stat"><b>${kp.active_groups}</b><span>Faol</span></div>
      </div>
    </div>
    <div class="ap-card">
      <div class="ap-h"><span>Yangi foydalanuvchilar (7 kun)</span></div>
      <div style="display:flex;align-items:flex-end;gap:6px;height:96px;margin-top:12px">
        ${daily.map((d) => `
          <div style="flex:1;display:flex;flex-direction:column;gap:5px;align-items:center">
            <div style="width:100%;background:var(--town);border-radius:5px 5px 0 0;height:${Math.max(2, Math.round((d.count / maxDay) * 68))}px"></div>
            <div style="font:600 8.5px var(--ui);color:var(--muted2)">${d.date ? d.date.slice(5) : ""}</div>
          </div>`).join("")}
      </div>
    </div>
    ${adminStats.top_players && adminStats.top_players.length ? `
    <div class="ap-card">
      <div class="ap-h"><span>Top o'yinchilar</span></div>
      ${adminStats.top_players.map((p, i) => `
        <div class="ap-row">
          <span class="pc-num">${i + 1}</span>
          <span class="grow">
            <span class="rname">${escapeHtml(p.display_name)}</span>
            <span class="rmeta">${p.games_played} o'yin &middot; ${p.win_rate}%</span>
          </span>
          <span class="ap-pill lobby">${p.wins}</span>
        </div>`).join("")}
    </div>` : ""}
    ${adminStats.recent_games && adminStats.recent_games.length ? `
    <div class="ap-card">
      <div class="ap-h"><span>So'nggi tugagan o'yinlar</span></div>
      ${adminStats.recent_games.slice(0, 6).map((g) => `
        <div class="ap-kv">
          <span class="kv-lbl">${escapeHtml(g.winner_faction || "?")} yutdi &middot; ${g.player_count || 0} o'yinchi</span>
          <b>${g.ended_at ? g.ended_at.slice(0, 10) : ""}</b>
        </div>`).join("")}
    </div>` : ""}`;
}

// ---------------------------------------------------- settings module -----
// Bot sozlamalari: bot menu buttons (labels/enabled/order) + the permission
// catalog reference. Permission: settings.view + settings.manage. Note this
// is NOT a game-settings editor — global match settings were deliberately
// dropped from the panel (spec section 13), only bot texts/buttons render.

async function loadPermCatalog() {
  adminPermCatalog = await api("/admin/permissions").then((r) => r).catch(() => ({ catalog: {} }));
}

async function refreshButtons() {
  adminButtons = await api("/admin/settings/buttons").then((r) => r.buttons || []).catch(() => []);
}

function renderSettings() {
  const el = document.getElementById("apSettings");
  const canManage = hasPermission("settings.manage");
  if (!adminButtons) {
    el.innerHTML = `<div class="ap-card"><div class="waitnote"><span class="dotpulse"></span>Yuklanmoqda...</div></div>`;
    return;
  }
  const order = adminButtons.slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  el.innerHTML = `
    <div class="ap-card">
      <div class="ap-h"><span>Bot menyu tugmalari</span><span>${order.length}</span></div>
      <div class="ap-quicknote">Botning asosiy menyusidagi tugmalar. "Admin panel" kabi tugmalar faqat adminlarga ko'rinadi. Qoidalardagi global o'yin sozlamalari panelga kiritilmagan (spec §13).</div>
      ${order.map((b) => `
        <div class="ap-card" style="margin-top:12px">
          <div class="ap-h">
            <span>${escapeHtml(b.key)}${b.admin_only ? ' <span class="ap-tag super">admin</span>' : ""}</span>
            <span class="ap-tag ${b.enabled ? "done" : "over"}">${b.enabled ? "Yoniq" : "O'chiq"}</span>
          </div>
          ${canManage ? `
          <div class="ap-field" style="margin-top:10px"><label>O'zbekcha</label>
            <input class="ap-input" id="btn_${b.key}_uz" value="${escapeAttr(b.label_uz)}"></div>
          <div class="ap-field"><label>Русский</label>
            <input class="ap-input" id="btn_${b.key}_ru" value="${escapeAttr(b.label_ru)}"></div>
          <div class="ap-field"><label>English</label>
            <input class="ap-input" id="btn_${b.key}_en" value="${escapeAttr(b.label_en)}"></div>
          <label class="ap-toggle" style="margin-top:10px">
            <span class="grow"><span class="tname">Menyuda ko'rsatish</span><span class="tsub">O'chirilsa, bot tugmani ko'rsatmaydi</span></span>
            <span class="ap-switch"><input type="checkbox" id="btn_${b.key}_enabled" ${b.enabled ? "checked" : ""}><i></i></span>
          </label>
          ${b.admin_only ? `
          <label class="ap-toggle">
            <span class="grow"><span class="tname">Faqat adminlar</span></span>
            <span class="ap-switch"><input type="checkbox" id="btn_${b.key}_adminonly" ${b.admin_only ? "checked" : ""}><i></i></span>
          </label>` : ""}
          <div class="ap-btnrow" style="margin-top:12px">
            <button class="ap-btn gold ap-mini" onclick="adminSaveButton('${b.key}')">Saqlash</button>
            <button class="ap-btn dark ap-mini" onclick="adminMoveButton('${b.key}', -1)">&uarr; Yuqori</button>
            <button class="ap-btn dark ap-mini" onclick="adminMoveButton('${b.key}', 1)">&darr; Past</button>
          </div>`
          : `<div class="ap-quicknote">Sozlamalarni tahrirlash uchun ruxsat yo'q.</div>`}
        </div>`).join("")}
    </div>
    <div class="ap-card">
      <div class="ap-h"><span>Admin ruxsatlari katalogi</span></div>
      <div class="ap-quicknote">Har bir modul bo'yicha mavjud ruxsatlar — panel adminlariga "Adminlar" bo'limida beriladi.</div>
      ${Object.keys((adminPermCatalog && adminPermCatalog.catalog) || {}).map((mod) => `
        <div class="ap-kv">
          <span class="kv-lbl">${MODULE_LABELS[mod] || mod}</span>
          <b style="font-weight:600;font-size:11px">${adminPermCatalog.catalog[mod].map((p) => escapeHtml(p.replace(".", " · "))).join("&nbsp;&nbsp;")}</b>
        </div>`).join("")}
    </div>`;
}

function adminSaveButton(key) {
  const v = (id) => { const el = document.getElementById(id); return el ? el.value : ""; };
  const fields = {
    label_uz: v("btn_" + key + "_uz").trim(),
    label_ru: v("btn_" + key + "_ru").trim(),
    label_en: v("btn_" + key + "_en").trim(),
    enabled: document.getElementById("btn_" + key + "_enabled").checked,
  };
  const adminOnly = document.getElementById("btn_" + key + "_adminonly");
  if (adminOnly) fields.admin_only = adminOnly.checked;
  (async () => {
    try {
      await api(`/admin/settings/buttons/${key}`, { method: "PUT", body: JSON.stringify(fields) });
      toast("Saqlandi");
      await refreshButtons();
      renderSettings();
    } catch (e) { toast(e.message); }
  })();
}

function adminMoveButton(key, dir) {
  const order = adminButtons.slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  const i = order.findIndex((b) => b.key === key);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= order.length) return;
  const tmp = order[i]; order[i] = order[j]; order[j] = tmp;
  const keys = order.map((b) => b.key);
  (async () => {
    try {
      await api("/admin/settings/buttons/reorder", { method: "POST", body: JSON.stringify({ keys }) });
      await refreshButtons();
      renderSettings();
    } catch (e) { toast(e.message); }
  })();
}

// --------------------------------------------------------- bots tab ------
// Lets the bot owner spin up a practice match seated with AI players
// (POST /admin/bot-game) and drop straight into its lobby as the host,
// without needing five other humans or the bot's own deep-link message.

const BOT_COUNT_CHIPS = [4, 6, 8, 10, 12, 15, 18];

function renderAdminBots() {
  const el = document.getElementById("apControlBots");
  const myChatId = myTelegramId ? (BOT_GAME_CHAT_PREFIX + myTelegramId) : null;
  const existing = myChatId ? adminGamesList.find((g) => g.chat_id === myChatId) : null;

  el.innerHTML = `
    ${existing ? `
    <div class="ap-card">
      <div class="ap-h"><span>Sizning sinov o'yiningiz</span>
        <span class="ap-pill ${PHASE_PILL[existing.phase] || "over"}">${PHASE_LABEL_UZ[existing.phase] || existing.phase}</span></div>
      <div class="ap-stats" style="margin-top:12px">
        <div class="ap-stat accent"><b>${existing.player_count}</b><span>Jami o'yinchilar</span></div>
        <div class="ap-stat accent"><b>${existing.alive_count}</b><span>Tirik</span></div>
      </div>
      <div class="ap-btnrow" style="margin-top:14px">
        <button class="ap-btn gold" onclick="adminEnterBotGame('${existing.chat_id}')">O'yinga kirish</button>
        <button class="ap-btn danger" onclick="adminTerminateBotGame('${existing.game_id}')">Bekor qilish</button>
      </div>
    </div>` : ""}

    <div class="ap-card">
      <div class="ap-h"><span>Botlar bilan sinov o'yini</span></div>
      <div class="ap-hint">Siz — yagona jonli o'yinchi, qolganlarini AI botlar to'ldiradi. Kamida 3 ta bot kerak (jami 4 o'yinchi), eng ko'pi 19 ta (jami 20).${existing ? " Yangi o'yin yaratsangiz, hozirgisi almashtiriladi." : ""}</div>
      <div class="ap-counter">
        <button class="ap-step" onclick="adminBotStep(-1)">&minus;</button>
        <div class="ap-countval"><b id="botCountVal">${adminBotCount}</b><span>Botlar</span></div>
        <button class="ap-step" onclick="adminBotStep(1)">&plus;</button>
      </div>
      <div class="ap-quick">
        ${BOT_COUNT_CHIPS.map((n) => `
          <button class="ap-chip ${n === adminBotCount ? "on" : ""}" onclick="adminBotSetCount(${n})">${n}</button>`).join("")}
      </div>
      <button class="ap-btn gold" id="botCreateBtn" onclick="adminCreateBotGame()">
        O'yin yaratish va kirish (${adminBotCount + 1} o'yinchi)
      </button>
    </div>`;
}

function adminBotStep(delta) {
  adminBotCount = Math.max(3, Math.min(19, adminBotCount + delta));
  renderAdminBots();
}

function adminBotSetCount(n) {
  adminBotCount = Math.max(3, Math.min(19, n));
  renderAdminBots();
}

async function adminCreateBotGame() {
  const btn = document.getElementById("botCreateBtn");
  btn.disabled = true;
  btn.textContent = "Yaratilmoqda...";
  try {
    const res = await api("/admin/bot-game", {
      method: "POST", body: JSON.stringify({ bot_count: adminBotCount }),
    });
    await adminEnterBotGame(res.chat_id);
  } catch (e) {
    toast(e.message);
    btn.disabled = false;
    renderAdminBots();
  }
}

async function adminEnterBotGame(chatId) {
  try {
    const res = await api("/games/for-chat", {
      method: "POST",
      body: JSON.stringify({
        chat_id: chatId,
        display_name: window.__displayName || "Admin",
        avatar_url: window.__avatarUrl || null,
      }),
    });
    gameId = res.game_id;
    myPlayerId = res.player_id;
    connectWS();
    go("lobby");
  } catch (e) {
    toast(e.message);
    await adminRefresh();
  }
}

function adminTerminateBotGame(gameId_) {
  askConfirm("Bu sinov o'yinini tugatamizmi?", async () => {
    try {
      await api(`/admin/games/${gameId_}/terminate`, { method: "POST" });
      toast("O'yin bekor qilindi");
      await adminRefresh();
    } catch (e) { toast(e.message); }
  });
}

// ------------------------------------------------------- match actions ---

async function adminForceAdvance(gameId) {
  try {
    await api(`/admin/games/${gameId}/force-advance`, { method: "POST" });
    toast("Bosqich o'tkazildi");
    await adminOpenGame(gameId);
  } catch (e) { toast(e.message); }
}

async function adminExtendTimer(gameId) {
  try {
    await api(`/admin/games/${gameId}/extend-timer`, { method: "POST", body: JSON.stringify({ seconds: 30 }) });
    toast("+30 soniya qo'shildi");
    await adminOpenGame(gameId);
  } catch (e) { toast(e.message); }
}

function adminTerminateGame(gameId) {
  askConfirm("O'yinni butunlay tugatamizmi? Bu amalni qaytarib bo'lmaydi.", async () => {
    try {
      await api(`/admin/games/${gameId}/terminate`, { method: "POST" });
      toast("O'yin tugatildi");
      adminBackToGamesList();
    } catch (e) { toast(e.message); }
  });
}

function adminRemovePlayer(gameId, targetId) {
  askConfirm("O'yinchini o'yindan chiqaramizmi?", async () => {
    try {
      await api(`/admin/games/${gameId}/remove/${targetId}`, { method: "POST" });
      toast("O'yinchi olib tashlandi");
      await adminOpenGame(gameId);
    } catch (e) { toast(e.message); }
  });
}

// ------------------------------------------------------ confirm sheet -----
// Small shared confirmation sheet (index.html #confirmSheet) for any action
// that cannot be undone: terminate, block, remove, broadcast send...

let confirmFn = null;

function askConfirm(text, fn) {
  confirmFn = fn;
  const sheet = document.getElementById("confirmSheet");
  const tx = document.getElementById("confirmText");
  if (sheet && tx) {
    tx.innerHTML = escapeHtml(text);
    sheet.classList.add("show");
  }
}

function runConfirm() {
  const fn = confirmFn;
  closeConfirm();
  if (typeof fn === "function") fn();
}

function closeConfirm() {
  confirmFn = null;
  const sheet = document.getElementById("confirmSheet");
  if (sheet) sheet.classList.remove("show");
}
