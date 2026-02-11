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
TOKEN = os.getenv("BOT_TOKEN", "8539913683:AAHx6_ByvA_OWZ1T03xJKwBwtgje-sbsJn8")

DATA_DIR = os.getenv("DATA_DIR", ".")
PLAYERS_FILE = os.path.join(DATA_DIR, "players.xlsx")
PLAYERS_CACHE = os.path.join(DATA_DIR, "players_cache.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
SELECTIONS_FILE = os.path.join(DATA_DIR, "selections.json")

# Your admin (Sergey)
DEFAULT_ADMIN_ID = 199804073

# UI
MIN_PLAYERS = 8
PAGE_SIZE = 24  # fits 25-30 players in 2 pages; safe for Telegram UI sizes

TEAM_EMOJIS = ["ðµ", "ð¢", "ð£", "ð "]

# =========================
# Dummy HTTP server so Render Web Service doesn't hang on "no open ports"
# =========================
def _run_dummy_port_server():
    port = int(os.getenv("PORT", "10000"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, format, *args):
            return  # silence

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


# =========================
# Persistence helpers
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
    # ensure admins are allowed
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
# Ratings & team builder
# =========================
SKILLS = [
    "Ð¢ÐµÑÐ½Ð¸ÐºÐ° Ð²Ð»Ð°Ð´ÐµÐ½Ð¸Ñ Ð¼ÑÑÐ¾Ð¼",
    "Ð¡ÐºÐ¾ÑÐ¾ÑÑÑ Ð¸ ÑÑÐºÐ¾ÑÐµÐ½Ð¸Ðµ",
    "ÐÑÐ½Ð¾ÑÐ»Ð¸Ð²Ð¾ÑÑÑ",
    "Ð¢Ð¾ÑÐ½Ð¾ÑÑÑ ÑÐ´Ð°ÑÐ¾Ð² Ð¸ Ð¿ÐµÑÐµÐ´Ð°Ñ",
    "ÐÑÐ¸Ð½ÑÑÐ¸Ðµ ÑÐµÑÐµÐ½Ð¸Ð¹",
    "ÐÐ°ÑÐ¸ÑÐ°",
    "ÐÐ° Ð²Ð¾ÑÐ¾ÑÐ°Ñ",
]


def calculate_rating(row) -> float:
    return float(row[SKILLS].mean())


def split_into_teams(df: pd.DataFrame, team_count: int) -> Tuple[List[List[str]], List[float]]:
    df = df.sort_values(by="rating", ascending=False)

    teams: List[List[str]] = [[] for _ in range(team_count)]
    sums: List[float] = [0.0 for _ in range(team_count)]

    for _, p in df.iterrows():
        i = min(range(team_count), key=lambda k: sums[k])
        teams[i].append(str(p["ÐÐ³ÑÐ¾Ðº"]))
        sums[i] += float(p["rating"])

    return teams, sums


# =========================
# Access control
# =========================
def is_admin(user_id: int) -> bool:
    users = load_users()
    return user_id in set(users.get("admin_ids", []))


def is_allowed(user_id: int) -> bool:
    users = load_users()
    return user_id in set(users.get("allowed_user_ids", []))


def main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    if is_admin(user_id):
        kb = [
            ["â½ ÐÑÐ±ÑÐ°ÑÑ Ð¸Ð³ÑÐ¾ÐºÐ¾Ð² Ð½Ð° Ð¼Ð°ÑÑ"],
            ["ð¥ ÐÐ°Ð³ÑÑÐ·Ð¸ÑÑ Excel"],
            ["ð¥ ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ð¸"],
        ]
    else:
        kb = [["â½ ÐÑÐ±ÑÐ°ÑÑ Ð¸Ð³ÑÐ¾ÐºÐ¾Ð² Ð½Ð° Ð¼Ð°ÑÑ"]]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


# =========================
# Inline "checkbox" picker
# =========================
def build_players_inline_keyboard(
    players: List[str],
    selected: Set[str],
    page: int,
    team_count: int,
) -> InlineKeyboardMarkup:
    total = len(players)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * PAGE_SIZE
    end = min(total, start + PAGE_SIZE)
    chunk = players[start:end]

    rows: List[List[InlineKeyboardButton]] = []

    # 2 columns
    row: List[InlineKeyboardButton] = []
    for idx, name in enumerate(chunk, start=start):
        checked = "âï¸" if name in selected else "â¬"
        row.append(InlineKeyboardButton(f"{checked} {name}", callback_data=f"tgl|{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(f"ð¢ ÐÐ¾Ð¼Ð°Ð½Ð´: {team_count}", callback_data="noop"),
            InlineKeyboardButton("2", callback_data="teams|2"),
            InlineKeyboardButton("3", callback_data="teams|3"),
            InlineKeyboardButton("4", callback_data="teams|4"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("â Ð¡ÑÐ¾ÑÐ¼Ð¸ÑÐ¾Ð²Ð°ÑÑ ÑÐ¾ÑÑÐ°Ð²Ñ", callback_data="mk"),
            InlineKeyboardButton("ð§¹ ÐÑÐ¸ÑÑÐ¸ÑÑ", callback_data="clr"),
        ]
    )

    if pages > 1:
        nav: List[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton("â¬ï¸", callback_data=f"pg|{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton("â¡ï¸", callback_data=f"pg|{page+1}"))
        rows.append(nav)

    return InlineKeyboardMarkup(rows)


async def render_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, *, reset_page: bool = False):
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
        await update.effective_message.reply_text(
            "Ð¡Ð¿Ð¸ÑÐ¾Ðº Ð¸Ð³ÑÐ¾ÐºÐ¾Ð² Ð¿ÑÑÑ. ÐÐ¾Ð¿ÑÐ¾ÑÐ¸ Ð°Ð´Ð¼Ð¸Ð½Ð° Ð·Ð°Ð³ÑÑÐ·Ð¸ÑÑ Excel (Ð»Ð¸ÑÑ 'ÐÐ³ÑÐ¾ÐºÐ¸')."
        )
        return

    selected = {x for x in selected if x in players}
    selections[chat_key] = {"selected": sorted(selected), "team_count": team_count, "page": page}
    save_selections(selections)

    kb = build_players_inline_keyboard(players, selected, page, team_count)
    await update.effective_message.reply_text(
        "ÐÑÐ±ÐµÑÐ¸ Ð¸Ð³ÑÐ¾ÐºÐ¾Ð² (Ð½Ð°Ð¶Ð¸Ð¼Ð°Ð¹ Ð½Ð° Ð¸Ð¼ÐµÐ½Ð°). ÐÑÐ±Ð¾Ñ ÑÐ¾ÑÑÐ°Ð½ÑÐµÑÑÑ.",
        reply_markup=kb,
    )


# =========================
# Admin: users panel
# =========================
def users_panel_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        ["â ÐÐ¾Ð±Ð°Ð²Ð¸ÑÑ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ", "â Ð£Ð´Ð°Ð»Ð¸ÑÑ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ"],
        ["ð Ð¡Ð¿Ð¸ÑÐ¾Ðº Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»ÐµÐ¹"],
        ["â¬ï¸ ÐÐ°Ð·Ð°Ð´"],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


async def show_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    admins = users.get("admin_ids", [])
    allowed = sorted(set(users.get("allowed_user_ids", [])))

    lines = ["**ð¥ ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ð¸:**", "", "**ÐÐ´Ð¼Ð¸Ð½Ñ:**"]
    for a in admins:
        lines.append(f"- `{a}`")
    lines.append("")
    lines.append("**Ð Ð°Ð·ÑÐµÑÑÐ½Ð½ÑÐµ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ð¸:**")
    for u in allowed:
        tag = " (admin)" if u in set(admins) else ""
        lines.append(f"- `{u}`{tag}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# =========================
# Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    if not is_allowed(uid):
        uname = f"@{user.username}" if user.username else "(Ð±ÐµÐ· username)"
        await update.message.reply_text(
            "â ÐÐ¾ÑÑÑÐ¿ Ð·Ð°ÐºÑÑÑ.\n\n"
            f"Ð¢Ð²Ð¾Ð¹ ID: {uid}\n"
            f"Username: {uname}\n\n"
            "ÐÑÐ¿ÑÐ°Ð²Ñ ÑÑÐ¾ Ð°Ð´Ð¼Ð¸Ð½Ñ, ÑÑÐ¾Ð±Ñ Ð¾Ð½ Ð´Ð¾Ð±Ð°Ð²Ð¸Ð» ÑÐµÐ±Ñ."
        )
        return

    await update.message.reply_text("ÐÐ¾ÑÐ¾Ð² Ðº ÑÐ°Ð±Ð¾ÑÐµ â", reply_markup=main_menu_keyboard(uid))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    text = (update.message.text or "").strip()

    if not is_allowed(uid):
        await update.message.reply_text("â ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°. ÐÐ°Ð¿Ð¸ÑÐ¸ /start ÑÑÐ¾Ð±Ñ ÑÐ²Ð¸Ð´ÐµÑÑ ÑÐ²Ð¾Ð¹ ID.")
        return

    awaiting = context.user_data.get("awaiting")

    # Admin panel
    if text == "ð¥ ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ð¸":
        if not is_admin(uid):
            await update.message.reply_text("Ð¢Ð¾Ð»ÑÐºÐ¾ Ð°Ð´Ð¼Ð¸Ð½.")
            return
        await update.message.reply_text("ÐÐ°Ð½ÐµÐ»Ñ ÑÐ¿ÑÐ°Ð²Ð»ÐµÐ½Ð¸Ñ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»ÑÐ¼Ð¸:", reply_markup=users_panel_keyboard())
        return

    if text == "â¬ï¸ ÐÐ°Ð·Ð°Ð´":
        await update.message.reply_text("ÐÐº.", reply_markup=main_menu_keyboard(uid))
        context.user_data.pop("awaiting", None)
        return

    if text == "â ÐÐ¾Ð±Ð°Ð²Ð¸ÑÑ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ":
        if not is_admin(uid):
            await update.message.reply_text("Ð¢Ð¾Ð»ÑÐºÐ¾ Ð°Ð´Ð¼Ð¸Ð½.")
            return
        context.user_data["awaiting"] = "add_user"
        await update.message.reply_text("ÐÑÐ¸ÑÐ»Ð¸ ID Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ ÑÐ¸ÑÐ»Ð¾Ð¼ (Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ: 123456789).")
        return

    if text == "â Ð£Ð´Ð°Ð»Ð¸ÑÑ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ":
        if not is_admin(uid):
            await update.message.reply_text("Ð¢Ð¾Ð»ÑÐºÐ¾ Ð°Ð´Ð¼Ð¸Ð½.")
            return
        context.user_data["awaiting"] = "remove_user"
        await update.message.reply_text("ÐÑÐ¸ÑÐ»Ð¸ ID Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð´Ð»Ñ ÑÐ´Ð°Ð»ÐµÐ½Ð¸Ñ.")
        return

    if text == "ð Ð¡Ð¿Ð¸ÑÐ¾Ðº Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»ÐµÐ¹":
        if not is_admin(uid):
            await update.message.reply_text("Ð¢Ð¾Ð»ÑÐºÐ¾ Ð°Ð´Ð¼Ð¸Ð½.")
            return
        await show_users_list(update, context)
        return

    if awaiting in {"add_user", "remove_user"}:
        if not is_admin(uid):
            await update.message.reply_text("Ð¢Ð¾Ð»ÑÐºÐ¾ Ð°Ð´Ð¼Ð¸Ð½.")
            return
        if not text.isdigit():
            await update.message.reply_text("ÐÑÐ¶ÐµÐ½ ID ÑÐ¸ÑÐ»Ð¾Ð¼. ÐÑÐ¸Ð¼ÐµÑ: 199804073")
            return
        target = int(text)
        users = load_users()
        allowed = set(users.get("allowed_user_ids", []))
        admins = set(users.get("admin_ids", []))

        if awaiting == "add_user":
            allowed.add(target)
            users["allowed_user_ids"] = sorted(allowed)
            save_users(users)
            context.user_data.pop("awaiting", None)
            await update.message.reply_text(f"â ÐÐ¾Ð±Ð°Ð²Ð¸Ð» Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ `{target}`.", parse_mode=ParseMode.MARKDOWN)
            return

        if awaiting == "remove_user":
            if target in admins:
                await update.message.reply_text("ÐÐµÐ»ÑÐ·Ñ ÑÐ´Ð°Ð»Ð¸ÑÑ Ð°Ð´Ð¼Ð¸Ð½Ð°.")
                return
            allowed.discard(target)
            users["allowed_user_ids"] = sorted(allowed)
            save_users(users)
            context.user_data.pop("awaiting", None)
            await update.message.reply_text(f"â Ð£Ð´Ð°Ð»Ð¸Ð» Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ `{target}`.", parse_mode=ParseMode.MARKDOWN)
            return

    # Excel upload (admin only)
    if text == "ð¥ ÐÐ°Ð³ÑÑÐ·Ð¸ÑÑ Excel":
        if not is_admin(uid):
            await update.message.reply_text("â Ð¢Ð¾Ð»ÑÐºÐ¾ Ð°Ð´Ð¼Ð¸Ð½ Ð¼Ð¾Ð¶ÐµÑ Ð·Ð°Ð³ÑÑÐ¶Ð°ÑÑ Excel.")
            return
        context.user_data["awaiting"] = "upload_excel"
        await update.message.reply_text(
            "ÐÐº, Ð¿ÑÐ¸ÑÐ»Ð¸ Excel-ÑÐ°Ð¹Ð».\n"
            "Ð¢ÑÐµÐ±Ð¾Ð²Ð°Ð½Ð¸Ñ: Ð»Ð¸ÑÑ **ÐÐ³ÑÐ¾ÐºÐ¸**, ÐºÐ¾Ð»Ð¾Ð½ÐºÐ° **ÐÐ³ÑÐ¾Ðº**, ÐºÐ¾Ð»Ð¾Ð½ÐºÐ¸ Ð½Ð°Ð²ÑÐºÐ¾Ð² ÐºÐ°Ðº Ð² ÑÐ°Ð±Ð»Ð¾Ð½Ðµ.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Choose players (everyone allowed)
    if text == "â½ ÐÑÐ±ÑÐ°ÑÑ Ð¸Ð³ÑÐ¾ÐºÐ¾Ð² Ð½Ð° Ð¼Ð°ÑÑ":
        await render_picker(update, context, reset_page=True)
        return

    await update.message.reply_text("ÐÐµ Ð¿Ð¾Ð½ÑÐ». ÐÑÐ¿Ð¾Ð»ÑÐ·ÑÐ¹ ÐºÐ½Ð¾Ð¿ÐºÐ¸ Ð¸Ð»Ð¸ /start.")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    if not is_allowed(uid):
        await update.message.reply_text("â ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°.")
        return

    if not is_admin(uid):
        await update.message.reply_text("â Ð¢Ð¾Ð»ÑÐºÐ¾ Ð°Ð´Ð¼Ð¸Ð½ Ð¼Ð¾Ð¶ÐµÑ Ð¾Ð±Ð½Ð¾Ð²Ð»ÑÑÑ Excel.")
        return

    if context.user_data.get("awaiting") != "upload_excel":
        await update.message.reply_text("Ð§ÑÐ¾Ð±Ñ Ð¾Ð±Ð½Ð¾Ð²Ð¸ÑÑ ÑÐ¿Ð¸ÑÐ¾Ðº, Ð½Ð°Ð¶Ð¼Ð¸ **ð¥ ÐÐ°Ð³ÑÑÐ·Ð¸ÑÑ Excel**.", parse_mode=ParseMode.MARKDOWN)
        return

    doc = update.message.document
    if not doc:
        await update.message.reply_text("ÐÐµ Ð²Ð¸Ð¶Ñ ÑÐ°Ð¹Ð». ÐÑÐ¸ÑÐ»Ð¸ Excel Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ¾Ð¼.")
        return

    tg_file = await doc.get_file()
    await tg_file.download_to_drive(PLAYERS_FILE)

    df = pd.read_excel(PLAYERS_FILE, sheet_name="ÐÐ³ÑÐ¾ÐºÐ¸")
    if "ÐÐ³ÑÐ¾Ðº" not in df.columns:
        await update.message.reply_text("Ð Ð»Ð¸ÑÑÐµ 'ÐÐ³ÑÐ¾ÐºÐ¸' Ð½ÐµÑ ÐºÐ¾Ð»Ð¾Ð½ÐºÐ¸ **ÐÐ³ÑÐ¾Ðº**.", parse_mode=ParseMode.MARKDOWN)
        return

    players = [str(x).strip() for x in df["ÐÐ³ÑÐ¾Ðº"].dropna().tolist() if str(x).strip()]
    save_players_list(players)

    # keep selections but intersect with new list
    selections = load_selections()
    pset = set(players)
    for chat_key, st in selections.items():
        sel = set(st.get("selected", []))
        st["selected"] = sorted(x for x in sel if x in pset)
        selections[chat_key] = st
    save_selections(selections)

    context.user_data.pop("awaiting", None)

    await update.message.reply_text(
        f"â Ð¤Ð°Ð¹Ð» Ð¾Ð±Ð½Ð¾Ð²Ð»ÑÐ½. ÐÐ³ÑÐ¾ÐºÐ¾Ð² Ð² Ð±Ð°Ð·Ðµ: {len(players)}",
        reply_markup=main_menu_keyboard(uid),
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = update.effective_user.id
    if not is_allowed(uid):
        await query.answer("ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°", show_alert=True)
        return

    data = query.data or ""
    chat_key = str(query.message.chat_id)

    selections = load_selections()
    st = selections.get(chat_key, {"selected": [], "team_count": 2, "page": 0})
    selected = set(st.get("selected", []))
    team_count = int(st.get("team_count", 2))
    page = int(st.get("page", 0))

    players = load_players_list()
    if not players:
        await query.edit_message_text("Ð¡Ð¿Ð¸ÑÐ¾Ðº Ð¸Ð³ÑÐ¾ÐºÐ¾Ð² Ð¿ÑÑÑ. ÐÐ¾Ð¿ÑÐ¾ÑÐ¸ Ð°Ð´Ð¼Ð¸Ð½Ð° Ð·Ð°Ð³ÑÑÐ·Ð¸ÑÑ Excel.")
        return

    if data.startswith("tgl|"):
        try:
            idx = int(data.split("|", 1)[1])
            name = players[idx]
        except Exception:
            return
        if name in selected:
            selected.remove(name)
        else:
            selected.add(name)

    elif data.startswith("pg|"):
        try:
            page = int(data.split("|", 1)[1])
        except Exception:
            pass

    elif data.startswith("teams|"):
        try:
            team_count = int(data.split("|", 1)[1])
            if team_count not in (2, 3, 4):
                team_count = 2
        except Exception:
            team_count = 2

    elif data == "clr":
        selected.clear()

    elif data == "mk":
        if len(selected) < MIN_PLAYERS:
            await query.answer(f"ÐÑÐ¶Ð½Ð¾ Ð¼Ð¸Ð½Ð¸Ð¼ÑÐ¼ {MIN_PLAYERS} Ð¸Ð³ÑÐ¾ÐºÐ¾Ð²", show_alert=True)
            return

        df = pd.read_excel(PLAYERS_FILE, sheet_name="ÐÐ³ÑÐ¾ÐºÐ¸")
        df["rating"] = df.apply(calculate_rating, axis=1)
        df = df[df["ÐÐ³ÑÐ¾Ðº"].astype(str).isin(selected)]
        teams, sums = split_into_teams(df, team_count)

        lines = []
        for i, (names, s) in enumerate(zip(teams, sums)):
            emo = TEAM_EMOJIS[i] if i < len(TEAM_EMOJIS) else "âª"
            lines.append(f"{emo} **ÐÐ¾Ð¼Ð°Ð½Ð´Ð° {i+1} (ÑÐµÐ¹ÑÐ¸Ð½Ð³: {round(s,1)})**")
            for n in names:
                lines.append(f"- {n}")
            lines.append("")

        await query.message.reply_text("\n".join(lines).strip(), parse_mode=ParseMode.MARKDOWN)
        return

    # persist + refresh
    pset = set(players)
    selected = {x for x in selected if x in pset}
    selections[chat_key] = {"selected": sorted(selected), "team_count": team_count, "page": page}
    save_selections(selections)

    kb = build_players_inline_keyboard(players, selected, page, team_count)
    try:
        await query.edit_message_reply_markup(reply_markup=kb)
    except Exception:
        await query.message.reply_text("ÐÑÐ¾Ð´Ð¾Ð»Ð¶Ð°ÐµÐ¼ Ð²ÑÐ±Ð¾Ñ:", reply_markup=kb)


# =========================
# Convenience commands
# =========================
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uname = f"@{user.username}" if user.username else "(Ð±ÐµÐ· username)"
    await update.message.reply_text(f"ID: {user.id}\nUsername: {uname}")


async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("Ð¢Ð¾Ð»ÑÐºÐ¾ Ð°Ð´Ð¼Ð¸Ð½.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("ÐÑÐ¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°Ð½Ð¸Ðµ: /allow 123456789")
        return
    target = int(context.args[0])
    users = load_users()
    allowed = set(users.get("allowed_user_ids", []))
    allowed.add(target)
    users["allowed_user_ids"] = sorted(allowed)
    save_users(users)
    await update.message.reply_text(f"â Ð Ð°Ð·ÑÐµÑÑÐ½ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ {target}")


async def deny_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("Ð¢Ð¾Ð»ÑÐºÐ¾ Ð°Ð´Ð¼Ð¸Ð½.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("ÐÑÐ¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°Ð½Ð¸Ðµ: /deny 123456789")
        return
    target = int(context.args[0])
    users = load_users()
    admins = set(users.get("admin_ids", []))
    if target in admins:
        await update.message.reply_text("ÐÐµÐ»ÑÐ·Ñ ÑÐ´Ð°Ð»Ð¸ÑÑ Ð°Ð´Ð¼Ð¸Ð½Ð°.")
        return
    allowed = set(users.get("allowed_user_ids", []))
    allowed.discard(target)
    users["allowed_user_ids"] = sorted(allowed)
    save_users(users)
    await update.message.reply_text(f"â Ð£Ð´Ð°Ð»ÑÐ½ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ {target}")


def main():
    # init files
    load_users()
    if not os.path.exists(PLAYERS_CACHE):
        save_players_list([])
    if not os.path.exists(SELECTIONS_FILE):
        save_selections({})

    # Render Web: open a port
    threading.Thread(target=_run_dummy_port_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("allow", allow_cmd))
    app.add_handler(CommandHandler("deny", deny_cmd))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
