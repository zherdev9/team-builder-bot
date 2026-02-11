import os
import json
from pathlib import Path

import pandas as pd
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Лучше хранить токен в переменной окружения BOT_TOKEN (Render -> Environment).
# Оставлен fallback, чтобы у тебя запускалось "как есть".
TOKEN = os.getenv("BOT_TOKEN", "8539913683:AAHx6_ByvA_OWZ1T03xJKwBwtgje-sbsJn8")

PLAYERS_FILE = "players.xlsx"

# Админы: могут загружать Excel + управлять пользователями
ADMIN_IDS = {199804073}

# JSON-файл со списком разрешённых пользователей
# ВАЖНО: чтобы сохранялось между перезапусками на Render — нужен Persistent Disk.
USERS_DB_FILE = "allowed_users.json"

MIN_PLAYERS_TO_CREATE_TEAMS = 8

# --- runtime ---
selected_players = set()
players_list = []


# ---------- Users storage ----------
def load_allowed_users() -> set[int]:
    """Load allowed users from JSON. Always includes admins."""
    try:
        p = Path(USERS_DB_FILE)
        if not p.exists():
            return set(ADMIN_IDS)

        data = json.loads(p.read_text(encoding="utf-8"))
        ids = set(int(x) for x in data.get("allowed_users", []))
        ids |= set(ADMIN_IDS)
        return ids
    except Exception:
        # fail-safe: только админы
        return set(ADMIN_IDS)


def save_allowed_users(allowed: set[int]) -> None:
    p = Path(USERS_DB_FILE)
    payload = {"allowed_users": sorted(set(allowed) | set(ADMIN_IDS))}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


ALLOWED_USERS = load_allowed_users()


def is_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    return uid in ADMIN_IDS


def is_allowed(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    return uid in ADMIN_IDS or uid in ALLOWED_USERS


# ---------- Ratings ----------
def calculate_rating(row):
    skills = [
        "Техника владения мячом",
        "Скорость и ускорение",
        "Выносливость",
        "Точность ударов и передач",
        "Принятие решений",
        "Защита",
        "На воротах",
    ]
    return row[skills].mean()


# ---------- UI helpers ----------
def main_keyboard_for(update: Update) -> ReplyKeyboardMarkup:
    if is_admin(update):
        keyboard = [
            ["Загрузить Excel"],
            ["Выбрать игроков на матч"],
            ["Сформировать составы"],
            ["👑 Пользователи: добавить", "👑 Пользователи: удалить"],
            ["👑 Пользователи: список"],
        ]
    else:
        keyboard = [
            ["Выбрать игроков на матч"],
            ["Сформировать составы"],
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def players_keyboard() -> ReplyKeyboardMarkup:
    keyboard = []
    row = []

    for name in players_list:
        row.append(KeyboardButton(name))
        if len(row) == 3:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(["Сформировать составы"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("У тебя нет доступа к этому боту. Напиши администратору.")
        return

    # сброс режимов ввода (если были)
    context.user_data.pop("awaiting_add_user", None)
    context.user_data.pop("awaiting_remove_user", None)

    await update.message.reply_text("Готов к работе ✅", reply_markup=main_keyboard_for(update))


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # только админ может обновлять Excel
    if not is_admin(update):
        await update.message.reply_text("Только админ может обновлять список игроков.")
        return

    global players_list, selected_players

    document = update.message.document
    file = await document.get_file()
    await file.download_to_drive(PLAYERS_FILE)

    df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")
    players_list = df["Игрок"].dropna().astype(str).tolist()
    selected_players = set()

    await update.message.reply_text(
        "Файл обновлён ✅\nТеперь нажми «Выбрать игроков на матч».",
        reply_markup=main_keyboard_for(update),
    )


async def choose_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    if not players_list:
        if is_admin(update):
            await update.message.reply_text(
                "Список игроков ещё не загружен. Нажми «Загрузить Excel» и пришли файл.",
                reply_markup=main_keyboard_for(update),
            )
        else:
            await update.message.reply_text(
                "Список игроков ещё не загружен. Попроси админа загрузить Excel.",
                reply_markup=main_keyboard_for(update),
            )
        return

    await update.message.reply_text(
        "Выбери игроков (нажимай по именам). Повторное нажатие снимает выбор.",
        reply_markup=players_keyboard(),
    )


async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    allowed = sorted(load_allowed_users())
    txt = "👑 Разрешённые пользователи (ID):\n" + "\n".join(str(x) for x in allowed)
    await update.message.reply_text(txt, reply_markup=main_keyboard_for(update))


async def create_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    if len(selected_players) < MIN_PLAYERS_TO_CREATE_TEAMS:
        await update.message.reply_text(f"Нужно минимум {MIN_PLAYERS_TO_CREATE_TEAMS} игроков.")
        return

    df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")
    df["rating"] = df.apply(calculate_rating, axis=1)

    df = df[df["Игрок"].astype(str).isin({str(x) for x in selected_players})]
    df = df.sort_values(by="rating", ascending=False)

    team1 = []
    team2 = []
    s1 = 0.0
    s2 = 0.0

    for _, p in df.iterrows():
        if s1 <= s2:
            team1.append(p)
            s1 += float(p["rating"])
        else:
            team2.append(p)
            s2 += float(p["rating"])

    text = f"🔵 Команда 1 (рейтинг: {round(s1, 1)})\n"
    for p in team1:
        text += f"- {p['Игрок']}\n"

    text += f"\n🟢 Команда 2 (рейтинг: {round(s2, 1)})\n"
    for p in team2:
        text += f"- {p['Игрок']}\n"

    await update.message.reply_text(text, reply_markup=main_keyboard_for(update))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global selected_players, ALLOWED_USERS

    if not update.message:
        return

    text = (update.message.text or "").strip()

    if not is_allowed(update):
        await update.message.reply_text("У тебя нет доступа к этому боту. Напиши администратору.")
        return

    # --- admin add/remove flow (ждём ID как текст) ---
    if is_admin(update) and context.user_data.get("awaiting_add_user"):
        try:
            uid = int(text)
            ALLOWED_USERS = load_allowed_users()
            ALLOWED_USERS.add(uid)
            save_allowed_users(ALLOWED_USERS)
            context.user_data.pop("awaiting_add_user", None)
            await update.message.reply_text(f"✅ Добавил пользователя: {uid}", reply_markup=main_keyboard_for(update))
        except Exception:
            await update.message.reply_text("Не похоже на ID. Пришли число, например: 123456789")
        return

    if is_admin(update) and context.user_data.get("awaiting_remove_user"):
        try:
            uid = int(text)
            if uid in ADMIN_IDS:
                await update.message.reply_text("Админа удалить нельзя 🙂")
                return
            ALLOWED_USERS = load_allowed_users()
            if uid in ALLOWED_USERS:
                ALLOWED_USERS.remove(uid)
                save_allowed_users(ALLOWED_USERS)
                await update.message.reply_text(f"✅ Удалил пользователя: {uid}", reply_markup=main_keyboard_for(update))
            else:
                await update.message.reply_text("Такого ID нет в списке.", reply_markup=main_keyboard_for(update))
            context.user_data.pop("awaiting_remove_user", None)
        except Exception:
            await update.message.reply_text("Не похоже на ID. Пришли число, например: 123456789")
        return

    # --- кнопки ---
    if text == "Загрузить Excel":
        if not is_admin(update):
            await update.message.reply_text("Только админ может обновлять список игроков.")
            return
        await update.message.reply_text("Пришли Excel файл (players.xlsx).")

    elif text == "Выбрать игроков на матч":
        await choose_players(update, context)

    elif text == "Сформировать составы":
        await create_teams(update, context)

    elif text == "👑 Пользователи: список":
        await users_list(update, context)

    elif text == "👑 Пользователи: добавить":
        if not is_admin(update):
            return
        context.user_data["awaiting_add_user"] = True
        context.user_data.pop("awaiting_remove_user", None)
        await update.message.reply_text("Отправь Telegram ID пользователя, которого нужно ДОБАВИТЬ.")

    elif text == "👑 Пользователи: удалить":
        if not is_admin(update):
            return
        context.user_data["awaiting_remove_user"] = True
        context.user_data.pop("awaiting_add_user", None)
        await update.message.reply_text("Отправь Telegram ID пользователя, которого нужно УДАЛИТЬ.")

    # --- выбор игрока ---
    elif text in players_list:
        if text in selected_players:
            selected_players.remove(text)
        else:
            selected_players.add(text)


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()


if __name__ == "__main__":
    main()