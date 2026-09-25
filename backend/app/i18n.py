"""
Shared language support — one preference, read and written by both the bot
(app/telegram_bot.py) and the webapp (app/api/routes_auth.py hands it to
app/static/app.js on login), so switching language on either side shows up
on the other.

Scope: this covers every message an ordinary PLAYER can see from the bot
(menu, about, stats, roles/group-picker prompts, force-sub gate, the
admin's reply relayed back to them) and the webapp's UI chrome. The bot
owner's own admin panel (app/telegram_bot.py's admin: callbacks) stays
Uzbek-only — it's a tool for whoever runs the bot, not player-facing.
The join message posted into a GROUP chat (post_join_button) also stays
Uzbek-only on purpose: it's a single message shared by everyone in that
group, not tied to any one reader's preference.
"""
from __future__ import annotations
from typing import Optional

from app.database import AsyncSessionLocal
from app.models.models import UserLanguage
from app.services import bot_config

SUPPORTED_LANGUAGES = ("uz", "ru", "en")
DEFAULT_LANGUAGE = "uz"

LANGUAGE_LABELS = {
    "uz": "🇺🇿 O'zbekcha",
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
}

# Always shown the same way regardless of the current language, since it
# already names all three languages — no translation lookup needed for it.
# Defined before BUTTONS so the "language" button's defaults can reuse it.
BTN_LANGUAGE = "🌐 Til / Язык / Language"

# ------------------------------------------------------ persistent state -
async def get_user_language(telegram_user_id: int) -> str:
    async with AsyncSessionLocal() as session:
        row = await session.get(UserLanguage, telegram_user_id)
        return row.language if row and row.language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


async def set_user_language(telegram_user_id: int, language: str) -> None:
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    async with AsyncSessionLocal() as session:
        row = await session.get(UserLanguage, telegram_user_id)
        if row is None:
            session.add(UserLanguage(telegram_user_id=telegram_user_id, language=language))
        else:
            row.language = language
        await session.commit()


# ------------------------------------------------------------- buttons ---
# Persistent reply-keyboard buttons are matched by their literal text, so
# each language's label has to be recognized on its own — see
# button_texts() below, used to build the F.text.in_({...}) filters in
# app/telegram_bot.py instead of a single F.text == ... check.
BUTTONS: dict[str, dict[str, str]] = {
    "start_group_game": {
        "uz": "🎮 Guruhda o'yin boshlash",
        "ru": "🎮 Начать игру в группе",
        "en": "🎮 Start game in a group",
    },
    "roles": {
        "uz": "🎭 Rollar",
        "ru": "🎭 Роли",
        "en": "🎭 Roles",
    },
    "my_stats": {
        "uz": "📊 Statistikam",
        "ru": "📊 Моя статистика",
        "en": "📊 My stats",
    },
    "my_profile": {
        "uz": "👤 Profilim",
        "ru": "👤 Мой профиль",
        "en": "👤 My profile",
    },
    "leaderboard": {
        "uz": "🏆 Top / Reyting",
        "ru": "🏆 Топ / Рейтинг",
        "en": "🏆 Top / Rating",
    },
    "about": {
        "uz": "ℹ️ Bot haqida",
        "ru": "ℹ️ О боте",
        "en": "ℹ️ About the bot",
    },
    "contact_admin": {
        "uz": "👨‍💼 Admin bilan bog'lanish",
        "ru": "👨‍💼 Связаться с админом",
        "en": "👨‍💼 Contact admin",
    },
    "admin_panel": {
        "uz": "🛠 Admin paneli",
        "ru": "🛠 Панель админа",
        "en": "🛠 Admin panel",
    },
    # Every submenu's trailing row — pops back to the previous panel. Shown
    # in the current language like any other panel button, hence three labels.
    "back": {
        "uz": "⬅️ Orqaga",
        "ru": "⬅️ Назад",
        "en": "⬅️ Back",
    },
    # The blue Menu button's launcher (a fixed label inside the Telegram app)
    # and the main-menu "language" button all name every language at once, so
    # their label is the same constant in all three.
    "language": {
        "uz": BTN_LANGUAGE,
        "ru": BTN_LANGUAGE,
        "en": BTN_LANGUAGE,
    },
}

def button_text(key: str, lang: str) -> str:
    """A button's label in `lang`. The admin can rename any main-menu button
    from the Admin panel's "Tugmalar" module; that DB value (app/services/
    bot_config.py) is the source of truth, with the code default below it —
    so a rename is honored everywhere, including webapp and bot, instantly."""
    configured = bot_config.button_label_or_none(key, lang)
    if configured:
        return configured
    labels = BUTTONS.get(key)
    if labels is None:
        return key
    return labels.get(lang, labels[DEFAULT_LANGUAGE])


def button_texts(key: str) -> set[str]:
    """Every language's label for this button, for F.text.in_(...) filters
    that need to recognize the button regardless of the sender's language.
    Unions the admin-configured labels with the code defaults, so a renamed
    button still triggers its handler in every language."""
    configured = bot_config.button_labels_or_none(key)
    defaults = set(BUTTONS.get(key, {}).values())
    return configured | defaults


# ------------------------------------------------------------ messages ---
MESSAGES: dict[str, dict[str, str]] = {
    "start_private_welcome": {
        "uz": "👋 Salom! Bu bot guruh o'yinlari uchun.\n\n"
              "Meni biror guruhga qo'shing va o'sha yerda <code>/start</code> "
              "buyrug'ini yuboring — a'zolar qo'shiladigan tugma paydo bo'ladi. "
              "Yoki pastdagi menyudan foydalaning.",
        "ru": "👋 Привет! Этот бот для групповых игр.\n\n"
              "Добавьте меня в группу и отправьте там команду <code>/start</code> — "
              "появится кнопка для присоединения. Либо используйте меню снизу.",
        "en": "👋 Hi! This bot is for group games.\n\n"
              "Add me to a group and send <code>/start</code> there — a join "
              "button will appear. Or use the menu below.",
    },
    "use_menu_below": {
        "uz": "Quyidagi menyudan foydalaning:",
        "ru": "Используйте меню снизу:",
        "en": "Use the menu below:",
    },
    "command_not_understood": {
        "uz": "Buyruq tushunilmadi. Pastdagi menyudan foydalaning:",
        "ru": "Команда не распознана. Используйте меню снизу:",
        "en": "I didn't understand that. Use the menu below:",
    },
    "about_body": {
        "uz": "🎭 <b>Mafia Mini App</b>\n\n"
              "Guruhlaringizda 6 dan 25 tagacha o'yinchi bilan Mafia o'ynang — "
              "kechasi maxfiy harakatlar, kunduzi muhokama va ovoz berish.\n\n"
              "Boshlash uchun meni istalgan guruhga admin qilib qo'shing va "
              "o'sha yerda <code>/start</code> yuboring.\n\n"
              "👤 Profilingiz va statistika — pastdagi \"Mening profilim\" "
              "tugmasi yoki <code>/profile</code> orqali ochiladigan ilova ichida.\n\n"
              "{start_group_game} — guruhga chiqmasdan, shu yerdan o'yin havolasini yuborish\n"
              "{leaderboard} — eng yaxshi o'yinchilar reytingi\n"
              "{my_stats} — shaxsiy statistikangiz\n"
              "{contact_admin} — bot admini bilan bog'lanish",
        "ru": "🎭 <b>Mafia Mini App</b>\n\n"
              "Играйте в Мафию в своих группах — от 6 до 25 игроков, тайные "
              "ночные действия, дневные обсуждения и голосование.\n\n"
              "Чтобы начать, добавьте меня администратором в любую группу и "
              "отправьте там <code>/start</code>.\n\n"
              "👤 Ваш профиль и статистика — через кнопку «Мой профиль» ниже "
              "или командой <code>/profile</code>.\n\n"
              "{start_group_game} — отправить ссылку на игру прямо отсюда\n"
              "{leaderboard} — рейтинг лучших игроков\n"
              "{my_stats} — ваша личная статистика\n"
              "{contact_admin} — связаться с администратором бота",
        "en": "🎭 <b>Mafia Mini App</b>\n\n"
              "Play Mafia in your groups — 6 to 25 players, secret night "
              "actions, day discussion and voting.\n\n"
              "To start, add me as an admin to any group and send "
              "<code>/start</code> there.\n\n"
              "👤 Your profile and stats — via the \"My profile\" button below "
              "or the <code>/profile</code> command.\n\n"
              "{start_group_game} — send the game link right from here\n"
              "{leaderboard} — ranking of the best players\n"
              "{my_stats} — your personal stats\n"
              "{contact_admin} — contact the bot's admin",
    },
    "rules_body": {
        "uz": "📜 <b>O'yin qoidalari</b>\n\n"
              "Har bir o'yinchi tunda maxfiy rol oladi: <b>Tinch aholi</b>, "
              "<b>Mafiya</b> yoki maxsus rollar (Komissar, Shifokor va h.k.).\n\n"
              "🌙 <b>Kecha</b> — maxsus rollar o'z harakatini yashirincha bajaradi "
              "(mafiya o'ldiradi, shifokor davolaydi, komissar tekshiradi).\n"
              "☀️ <b>Kun</b> — hamma muhokama qiladi va tundagi voqeani aniqlashga harakat qiladi.\n"
              "🗳 <b>Ovoz berish</b> — eng ko'p ovoz olgan o'yinchi o'yindan chiqariladi.\n\n"
              "🏆 <b>G'alaba:</b> Tinch aholi barcha mafiyalarni chiqarib yuborsa — "
              "shahar g'alaba qiladi. Mafiya soni tinch aholiga teng yoki ko'p bo'lsa — "
              "mafiya g'alaba qiladi.\n\n"
              "Har bir rolning batafsil tavsifi o'yin ichida, \"Rollar\" bo'limida.",
        "ru": "📜 <b>Правила игры</b>\n\n"
              "Каждый игрок тайно получает роль: <b>Мирный житель</b>, "
              "<b>Мафия</b> или особая роль (Комиссар, Доктор и т.д.).\n\n"
              "🌙 <b>Ночь</b> — особые роли тайно совершают свои действия.\n"
              "☀️ <b>День</b> — все обсуждают и пытаются вычислить мафию.\n"
              "🗳 <b>Голосование</b> — игрок с наибольшим числом голосов выбывает.\n\n"
              "🏆 <b>Победа:</b> город побеждает, если изгнаны все мафиози; "
              "мафия побеждает, если её число сравнялось с мирными жителями.",
        "en": "📜 <b>Game rules</b>\n\n"
              "Every player secretly gets a role: <b>Townsperson</b>, "
              "<b>Mafia</b>, or a special role (Detective, Doctor, etc.).\n\n"
              "🌙 <b>Night</b> — special roles act in secret.\n"
              "☀️ <b>Day</b> — everyone discusses and tries to find the mafia.\n"
              "🗳 <b>Voting</b> — the player with the most votes is eliminated.\n\n"
              "🏆 <b>Win:</b> the town wins once every mafia member is out; "
              "the mafia wins once their numbers match the town's.",
    },
    "help_body": {
        "uz": "❓ <b>Yordam</b>\n\n"
              "/start — bosh menyu\n"
              "/profile — profilingiz va statistikangiz\n"
              "/leaderboard — top o'yinchilar\n"
              "/rules — o'yin qoidalari\n\n"
              "O'yinni boshlash uchun meni guruhingizga qo'shing va o'sha "
              "yerda <code>/start</code> yuboring. Savol bo'lsa, pastdagi "
              "\"Admin bilan bog'lanish\" tugmasidan foydalaning.",
        "ru": "❓ <b>Помощь</b>\n\n"
              "/start — главное меню\n"
              "/profile — ваш профиль и статистика\n"
              "/leaderboard — топ игроков\n"
              "/rules — правила игры\n\n"
              "Чтобы начать игру, добавьте меня в группу и отправьте там "
              "<code>/start</code>. Если есть вопрос — используйте кнопку "
              "«Связаться с админом» ниже.",
        "en": "❓ <b>Help</b>\n\n"
              "/start — main menu\n"
              "/profile — your profile and stats\n"
              "/leaderboard — top players\n"
              "/rules — game rules\n\n"
              "To start a game, add me to your group and send "
              "<code>/start</code> there. For anything else, use the "
              "\"Contact admin\" button below.",
    },
    "leaderboard_title": {
        "uz": "🏆 <b>Top o'yinchilar</b>\n\nG'alabalar bo'yicha reyting:",
        "ru": "🏆 <b>Топ игроков</b>\n\nРейтинг по победам:",
        "en": "🏆 <b>Top players</b>\n\nRanked by wins:",
    },
    "leaderboard_empty": {
        "uz": "Hali hech kim o'yin yakunlamagan. Birinchi g'alaba sizniki bo'lsin!",
        "ru": "Пока никто не завершил игру. Пусть первая победа будет вашей!",
        "en": "Nobody has finished a game yet. Make the first win yours!",
    },
    "leaderboard_line": {
        "uz": "{place}. {name} — {wins} g'alaba ({games} o'yin)",
        "ru": "{place}. {name} — {wins} побед ({games} игр)",
        "en": "{place}. {name} — {wins} wins ({games} games)",
    },
    "bot_start_message_label": {
        "uz": "/start matni", "ru": "Текст /start", "en": "/start message",
    },
    "bot_group_added_label": {
        "uz": "Guruhga qo'shilgandagi xabar", "ru": "Сообщение при добавлении в группу", "en": "Bot added to group message",
    },
    "bot_lobby_label": {
        "uz": "Lobby xabari", "ru": "Lobby сообщение", "en": "Lobby message",
    },
    "stats_none_yet": {
        "uz": "Siz hali birorta o'yinni yakunlamagansiz. Guruhda o'ynab ko'ring!",
        "ru": "Вы ещё не завершили ни одной игры. Сыграйте в группе!",
        "en": "You haven't finished a game yet. Try playing in a group!",
    },
    "stats_body": {
        "uz": "📊 <b>Statistikangiz</b>\n\n"
              "O'ynagan o'yinlar: <b>{games_played}</b>\n"
              "G'alabalar: <b>{wins}</b> ({win_rate}%)\n"
              "Mag'lubiyatlar: <b>{losses}</b>\n\n"
              "🏙 Shahar g'alabalari: {town_wins}\n"
              "🔫 Mafiya g'alabalari: {mafia_wins}\n"
              "🎭 Neytral g'alabalari: {neutral_wins}",
        "ru": "📊 <b>Ваша статистика</b>\n\n"
              "Сыграно игр: <b>{games_played}</b>\n"
              "Побед: <b>{wins}</b> ({win_rate}%)\n"
              "Поражений: <b>{losses}</b>\n\n"
              "🏙 Побед за Город: {town_wins}\n"
              "🔫 Побед за Мафию: {mafia_wins}\n"
              "🎭 Побед за Нейтралов: {neutral_wins}",
        "en": "📊 <b>Your stats</b>\n\n"
              "Games played: <b>{games_played}</b>\n"
              "Wins: <b>{wins}</b> ({win_rate}%)\n"
              "Losses: <b>{losses}</b>\n\n"
              "🏙 Town wins: {town_wins}\n"
              "🔫 Mafia wins: {mafia_wins}\n"
              "🎭 Neutral wins: {neutral_wins}",
    },
    "roles_prompt": {
        "uz": "Barcha rollar va ularning qobiliyatlari:",
        "ru": "Все роли и их способности:",
        "en": "Every role and its ability:",
    },
    "roles_open_button": {
        "uz": "🎭 Rollarni ko'rish", "ru": "🎭 Смотреть роли", "en": "🎭 View roles",
    },
    "profile_prompt": {
        "uz": "Profilingizni oching:",
        "ru": "Откройте свой профиль:",
        "en": "Open your profile:",
    },
    "profile_open_button": {
        "uz": "👤 Profilim", "ru": "👤 Мой профиль", "en": "👤 My profile",
    },
    "no_groups_known": {
        "uz": "Hali hech qanday guruh topilmadi. Avval meni biror guruhga "
              "admin qilib qo'shing.",
        "ru": "Группы пока не найдены. Сначала добавьте меня администратором "
              "в какую-нибудь группу.",
        "en": "No groups found yet. First add me as an admin to a group.",
    },
    "no_matching_groups": {
        "uz": "Siz a'zo bo'lgan guruhlardan birortasida meni topa olmadim. "
              "Guruhga o'zingiz a'zo ekaningizga ishonch hosil qiling.",
        "ru": "Не нашёл меня ни в одной группе, где состоите вы. Убедитесь, "
              "что вы действительно состоите в этой группе.",
        "en": "I couldn't find myself in any group you're a member of. "
              "Make sure you're actually a member of that group.",
    },
    "pick_a_group": {
        "uz": "Qaysi guruhda o'yin boshlaymiz?",
        "ru": "В какой группе начнём игру?",
        "en": "Which group should we start the game in?",
    },
    "not_a_member_alert": {
        "uz": "Siz bu guruh a'zosi emassiz.",
        "ru": "Вы не состоите в этой группе.",
        "en": "You're not a member of that group.",
    },
    "could_not_post_to_group_alert": {
        "uz": "Guruhga yubora olmadim: {error}",
        "ru": "Не удалось отправить: {error}",
        "en": "Couldn't post: {error}",
    },
    "could_not_post_to_group_details": {
        "uz": "Guruhga xabar yubora olmadim.\nSabab: {error}\n\nTekshiring: bot hali ham guruhda turibdimi va xabar yuborish huquqiga ega adminmi. Bot olib tashlanib qayta qo'shilgan bo'lsa, avval guruhning o'zida /start buyrug'ini yuborib ko'ring.",
        "ru": "Не удалось отправить сообщение в группу.\nПричина: {error}\n\nПроверьте: бот всё ещё состоит в группе и является админом с правом отправки сообщений. Если бота удаляли и добавляли заново, сначала отправьте /start прямо в группе.",
        "en": "Couldn't post to that group.\nReason: {error}\n\nCheck that the bot is still in the group and is an admin with permission to send messages. If the bot was removed and re-added, try sending /start directly in the group first.",
    },
    "sent_confirmation": {
        "uz": "✅ Yuborildi!", "ru": "✅ Отправлено!", "en": "✅ Sent!",
    },
    "group_link_sent": {
        "uz": "✅ Guruhga o'yin havolasi yuborildi.",
        "ru": "✅ Ссылка на игру отправлена в группу.",
        "en": "✅ Game link sent to the group.",
    },
    "open_group_button": {
        "uz": "\U0001F517 Guruhga o'tish",
        "ru": "\U0001F517 Перейти в группу",
        "en": "\U0001F517 Open the group",
    },
    "admin_not_configured": {
        "uz": "Hozircha admin sozlanmagan.",
        "ru": "Администратор пока не настроен.",
        "en": "No admin is configured yet.",
    },
    "ask_admin_message": {
        "uz": "✍️ Xabaringizni yozing — u to'g'ridan-to'g'ri botning adminiga "
              "yuboriladi. Admin javob yozganda, siz uni shu yerda ko'rasiz.",
        "ru": "✍️ Напишите ваше сообщение — оно будет отправлено "
              "администратору бота напрямую. Когда админ ответит, вы "
              "увидите это здесь.",
        "en": "✍️ Type your message — it'll be sent straight to the bot's "
              "admin. When they reply, you'll see it here.",
    },
    "admin_message_sent": {
        "uz": "✅ Xabaringiz adminga yuborildi. Javobni shu yerda kuting.",
        "ru": "✅ Ваше сообщение отправлено администратору. Ждите ответ здесь.",
        "en": "✅ Your message was sent to the admin. Wait for a reply here.",
    },
    "admin_message_failed": {
        "uz": "Adminga yubora olmadim — admin botni hali ishga tushirmagan bo'lishi mumkin.",
        "ru": "Не удалось отправить администратору — возможно, он ещё не "
              "запускал бота.",
        "en": "Couldn't reach the admin — they may not have started the bot yet.",
    },
    "admin_reply_label": {
        "uz": "👨‍💼 <b>Admin javobi:</b>\n\n{text}",
        "ru": "👨‍💼 <b>Ответ администратора:</b>\n\n{text}",
        "en": "👨‍💼 <b>Admin's reply:</b>\n\n{text}",
    },
    "language_prompt": {
        "uz": "Tilni tanlang:", "ru": "Выберите язык:", "en": "Choose your language:",
    },
    "language_set": {
        "uz": "✅ Til o'zbekchaga o'zgartirildi.",
        "ru": "✅ Язык изменён на русский.",
        "en": "✅ Language changed to English.",
    },
}


def t(key: str, lang: str, **kwargs) -> str:
    text = MESSAGES[key].get(lang, MESSAGES[key][DEFAULT_LANGUAGE])
    return text.format(**kwargs) if kwargs else text
