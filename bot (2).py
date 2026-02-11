import pandas as pd
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8539913683:AAHx6_ByvA_OWZ1T03xJKwBwtgje-sbsJn8"
PLAYERS_FILE = "players.xlsx"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Update players"],
        ["Create teams"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Bot is ready", reply_markup=reply_markup)

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    file = await document.get_file()
    await file.download_to_drive(PLAYERS_FILE)
    await update.message.reply_text("File saved")

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

async def create_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")
    df["rating"] = df.apply(calculate_rating, axis=1)
    df = df.sort_values(by="rating", ascending=False)

    team1 = []
    team2 = []
    s1 = 0
    s2 = 0

    for _, p in df.iterrows():
        if s1 <= s2:
            team1.append(p["Игрок"])
            s1 += p["rating"]
        else:
            team2.append(p["Игрок"])
            s2 += p["rating"]

    text = "Team 1:\n"
    for p in team1:
        text += "- " + str(p) + "\n"

    text += "\nTeam 2:\n"
    for p in team2:
        text += "- " + str(p) + "\n"

    await update.message.reply_text(text)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "Update players":
        await update.message.reply_text("Send Excel file")

    elif text == "Create teams":
        await create_teams(update, context)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
