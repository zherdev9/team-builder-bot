import pandas as pd
import threading
import http.server
import socketserver
import os

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8539913683:AAHx6_ByvA_OWZ1T03xJKwBwtgje-sbsJn8"
PLAYERS_FILE = "players.xlsx"

ADMIN_IDS = {199804073}
ALLOWED_USERS = {199804073}

selected_players = set()
players_list = []
waiting_for_user_id = None


def calculate_rating(row):
    skills = [
        "Техника владения мячом",
        "Скорость и ускорение",
        "Выносливость",
        "Точность ударов и передач",
        "Принятие решений",
        "Защита",
        "На воротах"
    ]
    return row[skills].mean()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def is_allowed(user_id):
    return user_id in ALLOWED_USERS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("У тебя нет доступа к боту")
        return

    if is_admin(user_id):
        keyboard = [
            ["Загрузить Excel"],
            ["Выбрать игроков на матч"],
            ["Добавить пользователя", "Удалить пользователя"]
        ]
    else:
        keyboard = [
            ["Выбрать игроков на матч"]
        ]

    await update.message.reply_text(
        "Готов к работе",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players_list, selected_players

    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    document = update.message.document
    file = await document.get_file()
    await file.download_to_drive(PLAYERS_FILE)

    df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")
    players_list = df["Игрок"].tolist()
    selected_players = set()

    keyboard = [["Выбрать игроков на матч"]]

    await update.message.reply_text(
        "Файл обновлён",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


async def choose_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players_list

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

    await update.message.reply_text(
        "Выбери игроков (нажимай по именам):",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


async def create_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")
    df["rating"] = df.apply(calculate_rating, axis=1)

    df = df[df["Игрок"].isin(selected_players)]
    df = df.sort_values(by="rating", ascending=False)

    team1 = []
    team2 = []
    s1 = 0
    s2 = 0

    for _, p in df.iterrows():
        if s1 <= s2:
            team1.append(p)
            s1 += p["rating"]
        else:
            team2.append(p)
            s2 += p["rating"]

    text = f"🔵 Команда 1 (рейтинг: {round(s1,1)})\n"
    for p in team1:
        text += f"- {p['Игрок']}\n"

    text += f"\n🟢 Команда 2 (рейтинг: {round(s2,1)})\n"
    for p in team2:
        text += f"- {p['Игрок']}\n"

    await update.message.reply_text(text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global selected_players, waiting_for_user_id

    user_id = update.effective_user.id
    text = update.message.text

    if not is_allowed(user_id):
        await update.message.reply_text("Нет доступа")
        return

    if text == "Загрузить Excel":
        if not is_admin(user_id):
            return
        await update.message.reply_text("Пришли Excel файл")

    elif text == "Выбрать игроков на матч":
        await choose_players(update, context)

    elif text == "Сформировать составы":
        if len(selected_players) < 8:
            await update.message.reply_text("Нужно минимум 8 игроков")
            return
        await create_teams(update, context)

    elif text == "Добавить пользователя" and is_admin(user_id):
        waiting_for_user_id = "add"
        await update.message.reply_text("Отправь ID пользователя")

    elif text == "Удалить пользователя" and is_admin(user_id):
        waiting_for_user_id = "remove"
        await update.message.reply_text("Отправь ID пользователя")

    elif waiting_for_user_id and is_admin(user_id):
        try:
            uid = int(text)

            if waiting_for_user_id == "add":
                ALLOWED_USERS.add(uid)
                await update.message.reply_text(f"Пользователь {uid} добавлен")

            elif waiting_for_user_id == "remove":
                ALLOWED_USERS.discard(uid)
                await update.message.reply_text(f"Пользователь {uid} удалён")

        except:
            await update.message.reply_text("Это не ID")

        waiting_for_user_id = None

    elif text in players_list:
        if text in selected_players:
            selected_players.remove(text)
        else:
            selected_players.add(text)


def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.serve_forever()


def main():
    threading.Thread(target=run_fake_server).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()


if __name__ == "__main__":
    main()