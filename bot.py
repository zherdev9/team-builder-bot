import logging
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8539913683:AAHx6_ByvA_OWZ1T03xJKwBwtgje-sbsJn8"

PLAYERS_FILE = "players.xlsx"

logging.basicConfig(level=logging.INFO)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📥 Обновить участников"],
        ["⚽ Сформировать составы"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "TeamBuilderBot готов. Выберите действие:",
        reply_markup=reply_markup,
    )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document

    if not document.file_name.endswith(".xlsx"):
        await update.message.reply_text("Пришли Excel файл (.xlsx)")
        return

    file = await document.get_file()
    await file.download_to_drive(PLAYERS_FILE)

    df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")
    await update.message.reply_text(f"Файл обновлён. Игроков загружено: {len(df)}")


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


def build_teams(df, team_count=2):
    df = df.copy()
    df["rating"] = df.apply(calculate_rating, axis=1)
    df = df.sort_values(by="rating", ascending=False)

    teams = [[] for _ in range(team_count)]
    team_scores = [0.0] * team_count

    for _, player in df.iterrows():
        idx = team_scores.index(min(team_scores))
        teams[idx].append(str(player["Игрок"]))
        team_scores[idx] += float(player["rating"])

    return teams, team_scores


async def create_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")
    except Exception:
        await update.message.reply_text("Сначала загрузите файл участников")
        return

    teams, scores = build_teams(df, team_count=2)

    parts = []
    for i, team in enumerate(teams):
        parts.append(f"🏆 Команда {i+1} (сила {round(scores[i], 1)}):")
        parts.extend([f"• {p}" for p in team])
        parts.append("")

    await update.message.reply_text("
".join(parts).strip())


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text == "📥 Обновить участников":
        await update.message.reply_text("Пришлите Excel файл (.xlsx)")

    elif text == "⚽ Сформировать составы":
        await create_teams(update, context)


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()


if __name__ == "__main__":
    main()
