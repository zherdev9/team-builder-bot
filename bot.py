import pandas as pd
import json
import os

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters
)

TOKEN = "8539913683:AAHx6_ByvA_OWZ1T03xJKwBwtgje-sbsJn8"

PLAYERS_FILE = "players.xlsx"
SELECTED_FILE = "selected_players.json"

# ---------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ---------------------------

def load_players():
    if not os.path.exists(PLAYERS_FILE):
        return []
    df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")
    return df["Игрок"].dropna().tolist()

def load_selected():
    if not os.path.exists(SELECTED_FILE):
        return []
    with open(SELECTED_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_selected(players):
    with open(SELECTED_FILE, "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False)

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

# ---------------------------
# СТАРТ
# ---------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["👥 Выбрать игроков на матч"],
        ["📥 Загрузить новый список"]
    ]
    await update.message.reply_text(
        "Готов к работе ⚽",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

# ---------------------------
# ЗАГРУЗКА EXCEL
# ---------------------------

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    file = await document.get_file()
    await file.download_to_drive(PLAYERS_FILE)

    await update.message.reply_text("Список игроков обновлён ✅")

# ---------------------------
# ПОКАЗ ЧЕКБОКСОВ
# ---------------------------

async def show_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    players = load_players()

    if not players:
        await update.message.reply_text(
            "Список игроков не найден. Сначала загрузите Excel."
        )
        return

    selected = load_selected()

    keyboard = []
    for p in players:
        mark = "☑" if p in selected else "☐"
        keyboard.append([
            InlineKeyboardButton(f"{mark} {p}", callback_data=f"toggle|{p}")
        ])

    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="done")])

    await update.message.reply_text(
        "Выбери игроков:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------------------
# ПЕРЕКЛЮЧЕНИЕ ЧЕКБОКСОВ
# ---------------------------

async def toggle_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, player = query.data.split("|")

    selected = load_selected()

    if player in selected:
        selected.remove(player)
    else:
        selected.append(player)

    save_selected(selected)

    # перерисовываем список
    players = load_players()

    keyboard = []
    for p in players:
        mark = "☑" if p in selected else "☐"
        keyboard.append([
            InlineKeyboardButton(f"{mark} {p}", callback_data=f"toggle|{p}")
        ])

    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="done")])

    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------------------
# ГОТОВО → ПОКАЗАТЬ КНОПКУ СОСТАВОВ
# ---------------------------

async def done_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("⚙️ Сформировать составы", callback_data="make_teams")]
    ]

    await query.edit_message_text(
        "Состав сохранён 👌",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------------------
# СПРОСИТЬ КОЛИЧЕСТВО КОМАНД
# ---------------------------

async def ask_team_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("⚽ 2", callback_data="teams|2"),
            InlineKeyboardButton("⚽ 3", callback_data="teams|3"),
            InlineKeyboardButton("⚽ 4", callback_data="teams|4"),
        ]
    ]

    await query.edit_message_text(
        "Сколько команд сделать?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------------------
# ДЕЛЕНИЕ НА КОМАНДЫ
# ---------------------------

async def create_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    team_count = int(query.data.split("|")[1])

    selected = load_selected()
    df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")

    df = df[df["Игрок"].isin(selected)].copy()
    df["rating"] = df.apply(calculate_rating, axis=1)
    df = df.sort_values(by="rating", ascending=False)

    teams = [[] for _ in range(team_count)]
    scores = [0] * team_count

    for _, row in df.iterrows():
        idx = scores.index(min(scores))
        teams[idx].append((row["Игрок"], row["rating"]))
        scores[idx] += row["rating"]

    text = ""
    for i, team in enumerate(teams):
        text += f"\n🔴 Команда {i+1}\n"
        for name, r in team:
            text += f"{name} ({round(r,1)})\n"
        text += f"Сила: {round(scores[i],1)}\n"

    await query.edit_message_text(text)

# ---------------------------
# ОБРАБОТКА ТЕКСТА
# ---------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "👥 Выбрать игроков на матч":
        await show_players(update, context)

    elif text == "📥 Загрузить новый список":
        await update.message.reply_text("Отправь Excel файл")

# ---------------------------
# MAIN
# ---------------------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_handler(CallbackQueryHandler(toggle_player, pattern="^toggle"))
    app.add_handler(CallbackQueryHandler(done_select, pattern="^done$"))
    app.add_handler(CallbackQueryHandler(ask_team_count, pattern="^make_teams$"))
    app.add_handler(CallbackQueryHandler(create_teams, pattern="^teams"))

    app.run_polling()

if __name__ == "__main__":
    main()