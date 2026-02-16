import os import json import threading from http.server import
BaseHTTPRequestHandler, HTTPServer from typing import List, Tuple

import pandas as pd from telegram import ( Update, ReplyKeyboardMarkup,
InlineKeyboardButton, InlineKeyboardMarkup, ) from telegram.ext import (
ApplicationBuilder, CommandHandler, MessageHandler,
CallbackQueryHandler, filters, )

=========================

CONFIG

=========================

TOKEN = “8539913683:AAHx6_ByvA_OWZ1T03xJKwBwtgje-sbsJn8”

DATA_DIR = “.” PLAYERS_FILE = os.path.join(DATA_DIR, “players.xlsx”)
PLAYERS_CACHE = os.path.join(DATA_DIR, “players_cache.json”)
SELECTIONS_FILE = os.path.join(DATA_DIR, “selections.json”)

DEFAULT_ADMIN_ID = 199804073 MIN_PLAYERS = 8 PAGE_SIZE = 24

TEAM_EMOJIS = [“🔵”, “🟢”, “🟣”, “🟠”]

=========================

Dummy HTTP server (Render)

=========================

def _run_dummy_port_server(): port = int(os.getenv(“PORT”, “10000”))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, format, *args):
            return

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

=========================

JSON helpers

=========================

def _load_json(path: str, default): try: with open(path, “r”,
encoding=“utf-8”) as f: return json.load(f) except: return default

def _save_json(path: str, data): with open(path, “w”, encoding=“utf-8”)
as f: json.dump(data, f, ensure_ascii=False, indent=2)

def load_players_list(): return _load_json(PLAYERS_CACHE,
{}).get(“players”, [])

def save_players_list(players): _save_json(PLAYERS_CACHE, {“players”:
players})

def load_selections(): return _load_json(SELECTIONS_FILE, {})

def save_selections(data): _save_json(SELECTIONS_FILE, data)

=========================

Ratings

=========================

SKILLS = [ “Техника владения мячом”, “Скорость и ускорение”,
“Выносливость”, “Точность ударов и передач”, “Принятие решений”,
“Защита”, “На воротах”,]

def calculate_rating(row): return float(row[SKILLS].mean())

def split_into_teams(df: pd.DataFrame, team_count: int) ->
Tuple[List[List[str]], List[float]]: df = df.sort_values(by=“rating”,
ascending=False) teams = [[] for _ in range(team_count)] sums = [0.0 for
_ in range(team_count)]

    for _, p in df.iterrows():
        i = min(range(team_count), key=lambda k: sums[k])
        teams[i].append(str(p["Игрок"]))
        sums[i] += float(p["rating"])

    return teams, sums

=========================

UI

=========================

def main_menu_keyboard(): kb = [ [“⚽ Выбрать игроков”], [“📥 Загрузить
Excel”], ] return ReplyKeyboardMarkup(kb, resize_keyboard=True)

Игроки в 1 столбец

def build_players_inline_keyboard(players, selected, page, team_count):
total = len(players) pages = max(1, (total + PAGE_SIZE - 1) //
PAGE_SIZE) start = page * PAGE_SIZE chunk = players[start:start +
PAGE_SIZE]

    rows = []

    for idx, name in enumerate(chunk, start=start):
        checked = "☑️" if name in selected else "⬜"
        rows.append([
            InlineKeyboardButton(f"{checked} {name}", callback_data=f"tgl|{idx}")
        ])

    rows.append([
        InlineKeyboardButton("2", callback_data="teams|2"),
        InlineKeyboardButton("3", callback_data="teams|3"),
        InlineKeyboardButton("4", callback_data="teams|4"),
    ])

    rows.append([
        InlineKeyboardButton("✅ Сформировать", callback_data="mk"),
        InlineKeyboardButton("🧹 Очистить", callback_data="clr"),
    ])

    return InlineKeyboardMarkup(rows)

=========================

START

=========================

async def start(update, context): players = load_players_list()

    if not players:
        await update.message.reply_text(
            "⚽ Привет! Я формирую равные команды.\n\n"
            "Сначала загрузите Excel:\n"
            "Лист: Игроки\n"
            "Колонка: Игрок\n"
            "Остальные — навыки 1–10",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.message.reply_text("Готов к работе ⚽", reply_markup=main_menu_keyboard())

=========================

TEXT HANDLER

=========================

async def handle_text(update, context): text = update.message.text

    if text == "⚽ Выбрать игроков":
        players = load_players_list()

        if not players:
            await update.message.reply_text("Сначала загрузите Excel.")
            return

        selections = load_selections()
        chat_key = str(update.effective_chat.id)
        st = selections.get(chat_key, {"selected": [], "team_count": 2, "page": 0})

        kb = build_players_inline_keyboard(players, set(st["selected"]), 0, st["team_count"])

        await update.message.reply_text("Выберите игроков:", reply_markup=kb)

=========================

EXCEL UPLOAD

=========================

async def handle_file(update, context): doc = update.message.document
tg_file = await doc.get_file() await
tg_file.download_to_drive(PLAYERS_FILE)

    df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")

    if "Игрок" not in df.columns:
        await update.message.reply_text("В Excel нужна колонка 'Игрок'")
        return

    players = [str(x).strip() for x in df["Игрок"].dropna()]
    save_players_list(players)

    await update.message.reply_text(f"Загружено игроков: {len(players)}")

=========================

CALLBACK

=========================

async def on_callback(update, context): query = update.callback_query
await query.answer()

    data = query.data
    chat_key = str(query.message.chat_id)

    selections = load_selections()
    st = selections.get(chat_key, {"selected": [], "team_count": 2, "page": 0})

    selected = set(st["selected"])
    team_count = st["team_count"]

    players = load_players_list()

    if data.startswith("tgl|"):
        idx = int(data.split("|")[1])
        name = players[idx]
        if name in selected:
            selected.remove(name)
        else:
            selected.add(name)

    elif data.startswith("teams|"):
        team_count = int(data.split("|")[1])

    elif data == "clr":
        selected.clear()

    elif data == "mk":
        if len(selected) < MIN_PLAYERS:
            await query.answer(f"Минимум {MIN_PLAYERS} игроков", show_alert=True)
            return

        df = pd.read_excel(PLAYERS_FILE, sheet_name="Игроки")
        df["rating"] = df.apply(calculate_rating, axis=1)
        df = df[df["Игрок"].isin(selected)]

        teams, sums = split_into_teams(df, team_count)

        text = ""
        for i, team in enumerate(teams):
            text += f"{TEAM_EMOJIS[i]} Команда {i+1}\n"
            for p in team:
                text += f"- {p}\n"
            text += "\n"

        await query.message.reply_text(text)
        return

    selections[chat_key] = {"selected": list(selected), "team_count": team_count, "page": 0}
    save_selections(selections)

    kb = build_players_inline_keyboard(players, selected, 0, team_count)
    await query.edit_message_reply_markup(reply_markup=kb)

=========================

MAIN

=========================

def main(): if os.getenv(“PORT”):
threading.Thread(target=_run_dummy_port_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling()

if name == “main”: main()
