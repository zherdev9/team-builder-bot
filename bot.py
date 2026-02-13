import os
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Set, Tuple

import pandas as pd
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("8539913683:AAHx6_ByvA_OWZ1T03xJKwBwtgje-sbsJn8")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN env var is not set")

DATA_DIR = os.getenv("DATA_DIR", ".")
PLAYERS_FILE = os.path.join(DATA_DIR, "players.xlsx")
PLAYERS_CACHE = os.path.join(DATA_DIR, "players_cache.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
SELECTIONS_FILE = os.path.join(DATA_DIR, "selections.json")

DEFAULT_ADMIN_ID = 199804073

MIN_PLAYERS = 8
PAGE_SIZE = 24

TEAM_EMOJIS = ["🔵", "🟢", "🟣", "🟠"]

# =========================
# Dummy HTTP server (Render Web only)
# =========================
def _run_dummy_port_server():
    port = int(os.getenv("PORT", "10000"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, format, *args):
            return

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


# =========================
# Persistence
# =========================
def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_users() -> Dict:
    data = _load_json(USERS_FILE, {})
    if not data:
        data = {"admin_ids": [DEFAULT_ADMIN_ID], "allowed_user_ids": [DEFAULT_ADMIN_ID]}
        _save_json(USERS_FILE, data)

    data.setdefault("admin_ids", [DEFAULT_ADMIN_ID])
    data.setdefault("allowed_user_ids", list(set(data["admin_ids"])))

    for aid in data["admin_ids"]:
        if aid not in data["allowed_user_ids"]:
            data["allowed_user_ids"].append(aid)

    _save_json(USERS_FILE, data)
    return data


def save_users(data: Dict) -> None:
    for aid in data.get("admin_ids", []):
        if aid not in data.get("allowed_user_ids", []):
            data.setdefault("allowed_user_ids", []).append(aid)
    _save_json(USERS_FILE, data)


def load_players_list() -> List[str]:
    cache = _load_json(PLAYERS_CACHE, {})
    return cache.get("players", [])


def save_players_list(players: List[str]) -> None:
    _save_json(PLAYERS_CACHE, {"players": players})


def load_selections() -> Dict[str, Dict]:
    return _load_json(SELECTIONS_FILE, {})


def save_selections(data: Dict[str, Dict]) -> None:
    _save_json(SELECTIONS_FILE, data)


def get_chat_key(update: Update) -> str:
    return str(update.effective_chat.id)


# =========================
# Ratings
# =========================
SKILLS = [
    "Техника владения мячом",
    "Скорость и ускорение",
    "Выносливость",
    "Точность ударов и передач",
    "Принятие решений",
    "Защита",
    "На воротах",
]


def calculate_rating(row) -> float:
    return float(row[SKILLS].mean())


def split_into_teams(df: pd.DataFrame, team_count: int) -> Tuple[List[List[str]], List[float]]:
    df = df.sort_values(by="rating", ascending=False)

    teams = [[] for _ in range(team_count)]
    sums = [0.0 for _ in range(team_count)]

    for _, p in df.iterrows():
        i = min(range(team_count), key=lambda k: sums[k])
        teams[i].append(str(p["Игрок"]))
        sums[i] += float(p["rating"])

    return teams, sums


# =========================
# Access
# =========================
def is_admin(user_id: int) -> bool:
    return user_id in set(load_users().get("admin_ids", []))


def is_allowed(user_id: int) -> bool:
    return user_id in set(load_users().get("allowed_user_ids", []))


def main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    if is_admin(user_id):
        kb = [
            ["⚽ Выбрать игроков на матч"],
            ["📥 Загрузить Excel"],
            ["👥 Пользователи"],
        ]
    else:
        kb = [["⚽ Выбрать игроков на матч"]]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


# =========================
# CHECKBOX PICKER
# =========================
def build_players_inline_keyboard(players, selected, page, team_count):
    total = len(players)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * PAGE_SIZE
    end = min(total, start + PAGE_SIZE)
    chunk = players[start:end]

    rows = []
    row = []

    for idx, name in enumerate(chunk, start=start):
        checked = "☑️" if name in selected else "⬜"
        row.append(InlineKeyboardButton(f"{checked} {name}", callback_data=f"tgl|{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(f"🔢 Команд: {team_count}", callback_data="noop"),
        InlineKeyboardButton("2", callback_data="teams|2"),
        InlineKeyboardButton("3", callback_data="teams|3"),
        InlineKeyboardButton("4", callback_data="teams|4"),
    ])

    rows.append([
        InlineKeyboardButton("✅ Сформировать составы", callback_data="mk"),
        InlineKeyboardButton("🧹 Очистить", callback_data="clr"),
    ])

    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"pg|{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton("➡️", callback_data=f"pg|{page+1}"))
        rows.append(nav)

    return InlineKeyboardMarkup(rows)


async def render_picker(update, context, reset_page=False):
    players = load_players_list()
    chat_key = get_chat_key(update)
    selections = load_selections()

    st = selections.get(chat_key, {})
    selected = set(st.get("selected", []))
    team_count = int(st.get("team_count", 2))
    page = int(st.get("page", 0))
    if reset_page:
        page = 0

    if not players:
        await update.effective_message.reply_text("Список игроков пуст.")
        return

    selections[chat_key] = {
        "selected": sorted(selected),
        "team_count": team_count,
        "page": page,
    }
    save_selections(selections)

    kb = build_players_inline_keyboard(players, selected, page, team_count)
    await update.effective_message.reply_text(
        "Выбери игроков (галочки запоминаются):",
        reply_markup=kb,
    )


# =========================
# CALLBACKS
# =========================
async def on_callback(update, context):
    query = update.callback_query
    await query.answer()

    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    data = query.data
    chat_key = str(query.message.chat_id)

    selections = load_selections()
    st = selections.get(chat_key, {"selected": [], "team_count": 2, "page": 0})
    selected = set(st.get("selected", []))
    team_count = int(st.get("team_count", 2))
    page = int(st.get("page", 0))

    players = load_players_list()

    if data.startswith("tgl|"):
        idx = int(data.split("|")[1])
        name = players[idx]
        if name in selected:
            selected.remove(name)
        else:
            selected.add(name)

    elif data.startswith("pg|"):
        page = int(data.split("|")[1])

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
        df = df[df["Игрок"].astype(str).isin(selected)]

        teams, sums = split_into_teams(df, team_count)

        lines = []
        for i, (names, s) in enumerate(zip(teams, sums)):
            lines.append(f"{TEAM_EMOJIS[i]} Команда {i+1} ({round(s,1)})")
            for n in names:
                lines.append(f"- {n}")
            lines.append("")

        await query.message.reply_text("\n".join(lines))
        return

    selections[chat_key] = {
        "selected": sorted(selected),
        "team_count": team_count,
        "page": page,
    }
    save_selections(selections)

    kb = build_players_inline_keyboard(players, selected, page, team_count)
    await query.edit_message_reply_markup(reply_markup=kb)


# =========================
# HANDLERS
# =========================
async def start(update, context):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text(f"Нет доступа.\nID: {uid}")
        return
    await update.message.reply_text("Готов", reply_markup=main_menu_keyboard(uid))


async def handle_text(update, context):
    text = update.message.text

    if text == "⚽ Выбрать игроков на матч":
        await render_picker(update, context, reset_page=True)


# =========================
# MAIN
# =========================
def main():
    load_users()
    if not os.path.exists(PLAYERS_CACHE):
        save_players_list([])
    if not os.path.exists(SELECTIONS_FILE):
        save_selections({})

    if os.getenv("PORT"):
        threading.Thread(target=_run_dummy_port_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling()


if __name__ == "__main__":
    main()