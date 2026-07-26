import logging
import os
import secrets
import sqlite3
import sys

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from bot_key_api import generate_key, generate_key_by_type, block_key
    KEY_API_OK = True
except ImportError:
    KEY_API_OK = False
    def generate_key(*a, **k): return {"ok": False, "error": "bot_key_api not found"}
    def generate_key_by_type(*a, **k): return {"ok": False, "error": "bot_key_api not found"}
    def block_key(*a, **k): return {"ok": False, "error": "bot_key_api not found"}

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_USERNAME = "BlackDLCBot"
if not TELEGRAM_BOT_TOKEN:
    print("Ошибка: не задан TELEGRAM_BOT_TOKEN", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DB_PATH = "data/bot.db"
GAME_VERSION = "0.39.2"
PLANS_PRICES = ["250 RUB", "400 RUB", "590 RUB", "790 RUB"]
PLAN_LABELS = ["7 дней", "30 дней", "60 дней", "Навсегда"]
PAYMENT_METHODS = ["СБП #1", "СБП #2 (запасной)", "Карта РФ", "Карта СНГ", "CryptoBot", "Баланс"]
PRODUCT_NAMES = {
    "apk": "Black APK Android",
    "ios": "Black iPA iOS",
    "pc_ext": "St2 External PC",
    "pc_int": "St2 Internal PC",
    "android_ext": "Black Android External",
    "android_int": "Black Android Internal",
    "root": "Установка ROOT-прав",
}
OWNERS = {8097159122: "DEV_01", 8399842427: "DEV_02"}
TOS_URL = "https://telegra.ph/Lensionnoe-soglashenie-Black-07-21"
PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-Black-07-21"

ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER, ROLE_VIP, ROLE_USER, ROLE_BANNED = (
    "Owner", "admin", "reseller", "vip", "user", "banned"
)
ROLE_HIERARCHY = {ROLE_BANNED: 0, ROLE_USER: 1, ROLE_VIP: 2, ROLE_RESELLER: 3, ROLE_ADMIN: 4, ROLE_OWNER: 5}
ROLE_BADGES = {
    ROLE_OWNER: "👑 Owner", ROLE_ADMIN: "🛡 Admin", ROLE_RESELLER: "🤝 Reseller",
    ROLE_VIP: "⭐️ VIP", ROLE_USER: "👤 User", ROLE_BANNED: "🚫 Banned",
}
user_states: dict[int, str] = {}

def role_gte(role, minimum):
    return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get(minimum, 0)

# ===== DB =====
def init_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        balance INTEGER DEFAULT 0, status TEXT DEFAULT 'user',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item TEXT,
        amount TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER,
        referred_id INTEGER UNIQUE, earned INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS ref_tokens (
        token TEXT PRIMARY KEY, user_id INTEGER UNIQUE)""")
    conn.commit()
    conn.close()

def get_user(uid):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT user_id, username, first_name, balance, status, created_at FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return row

def get_or_create_user(uid, username, first_name):
    if get_user(uid):
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?,?,?)",
                 (uid, username or "", first_name or ""))
    conn.commit()
    conn.close()

def get_role(uid):
    row = get_user(uid)
    return row[4] if row else ROLE_USER

def is_banned(uid):
    return get_role(uid) == ROLE_BANNED

def set_user_role(uid, role):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET status=? WHERE user_id=?", (role, uid))
    conn.commit()
    conn.close()

def get_purchases(uid):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT item, amount, created_at FROM purchases WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    conn.close()
    return rows

def add_balance(uid, amount):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    conn.commit()
    conn.close()

def get_or_create_ref_token(uid):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT token FROM ref_tokens WHERE user_id=?", (uid,)).fetchone()
    if row:
        conn.close()
        return row[0]
    token = secrets.token_hex(4)
    conn.execute("INSERT OR REPLACE INTO ref_tokens (token, user_id) VALUES (?,?)", (token, uid))
    conn.commit()
    conn.close()
    return token

def get_user_id_by_token(token):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT user_id FROM ref_tokens WHERE token=?", (token,)).fetchone()
    conn.close()
    return row[0] if row else None

def add_referral(referrer_id, referred_id):
    if referrer_id == referred_id:
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?,?)", (referrer_id, referred_id))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def get_referral_stats(uid):
    conn = sqlite3.connect(DB_PATH)
    invited = conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (uid,)).fetchone()[0]
    earned = conn.execute("SELECT COALESCE(SUM(earned),0) FROM referrals WHERE referrer_id=?", (uid,)).fetchone()[0]
    conn.close()
    return invited, earned

def credit_referrer(referred_id, purchase_amount_rub):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT referrer_id FROM referrals WHERE referred_id=?", (referred_id,)).fetchone()
    if not row:
        conn.close()
        return
    referrer_id = row[0]
    role_row = conn.execute("SELECT status FROM users WHERE user_id=?", (referrer_id,)).fetchone()
    rate = 0.20 if (role_row and role_row[0] == ROLE_RESELLER) else 0.15
    earned = int(purchase_amount_rub * rate)
    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (earned, referrer_id))
    conn.execute("UPDATE referrals SET earned = earned + ? WHERE referred_id=?", (earned, referred_id))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    vip = conn.execute("SELECT COUNT(*) FROM users WHERE status=?", (ROLE_VIP,)).fetchone()[0]
    resellers = conn.execute("SELECT COUNT(*) FROM users WHERE status=?", (ROLE_RESELLER,)).fetchone()[0]
    admins = conn.execute("SELECT COUNT(*) FROM users WHERE status IN (?,?)", (ROLE_ADMIN, ROLE_OWNER)).fetchone()[0]
    banned = conn.execute("SELECT COUNT(*) FROM users WHERE status=?", (ROLE_BANNED,)).fetchone()[0]
    conn.close()
    return {"total": total, "vip": vip, "resellers": resellers, "admins": admins, "banned": banned}

def get_all_user_ids():
    conn = sqlite3.connect(DB_PATH)
    ids = [r[0] for r in conn.execute("SELECT user_id FROM users").fetchall()]
    conn.close()
    return ids

def get_user_by_username(username):
    username = username.lstrip("@")
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT user_id, username, first_name, balance, status, created_at FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return row

def ensure_dev_credits():
    dev_id = 8097159122
    row = get_user(dev_id)
    if row and row[3] == 0:
        add_balance(dev_id, 1000)

# ===== Keyboards =====
def back_btn(cb="main"):
    return [InlineKeyboardButton("🔙 Вернуться назад", callback_data=cb)]

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗝 Приобрести ключ", callback_data="plans")],
        [InlineKeyboardButton("📱 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("🗂 Отзывы", url="https://t.me/BlackHoli")],
        [InlineKeyboardButton("📝 Полезные ссылки", callback_data="links")],
    ])

def profile_kb(role):
    rows = [
        [InlineKeyboardButton("💰 Вывести средства", callback_data="withdraw")],
        [InlineKeyboardButton("🎁 Реферальная система", callback_data="referral")],
        [InlineKeyboardButton("🛍 Мои покупки", callback_data="purchases")],
        [InlineKeyboardButton("📄 Наш ToS", url=TOS_URL)],
        [InlineKeyboardButton("🔒 Privacy Policy", url=PRIVACY_URL)],
    ]
    if role == ROLE_RESELLER:
        rows.insert(1, [InlineKeyboardButton("🤝 Панель реселлера", callback_data="reseller_panel")])
    if role_gte(role, ROLE_ADMIN):
        rows.insert(0, [InlineKeyboardButton("🛡 Панель администратора", callback_data="admin_panel")])
    rows.append(back_btn())
    return InlineKeyboardMarkup(rows)

def sub_kb(game, back):
    rows = [[InlineKeyboardButton(f"{lab} | {price}", callback_data=f"sub_{game}_{i}")]
            for i, (lab, price) in enumerate(zip(PLAN_LABELS, PLANS_PRICES))]
    rows.append(back_btn(back))
    return InlineKeyboardMarkup(rows)

# ===== Commands =====
async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("id", "Мой Telegram ID"),
    ])
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)
    if is_banned(user.id):
        await update.message.reply_text("🚫 Вы заблокированы.")
        return
    if context.args:
        arg = context.args[0]
        if arg.startswith("reft_"):
            rid = get_user_id_by_token(arg[5:])
            if rid and rid != user.id:
                add_referral(rid, user.id)
        elif arg.startswith("ref_"):
            try:
                rid = int(arg[4:])
                if rid != user.id:
                    add_referral(rid, user.id)
            except ValueError:
                pass
    await update.message.reply_text(
        "📻 Добро пожаловать, путник\n"
        "🪄 Этот бот поможет тебе в приобретении самых лучших DLC от Black!\n"
        "👇 Для управления ботом используйте кнопки в этом сообщении",
        reply_markup=main_menu_kb(),
    )

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Telegram ID: {update.effective_user.id}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Команды:\n/start — меню\n/help — помощь\n/id — мой ID")

async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid):
        await update.message.reply_text("🚫 Вы заблокированы.")
        return
    state = user_states.get(uid)
    text = update.message.text.strip()

    if state == "awaiting_withdrawal":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text("Введите число, например: 1500")
            return
        if amount < 1000:
            await update.message.reply_text("⛔️ Минимум 1000 RUB")
            return
        row = get_user(uid)
        if not row or row[3] < amount:
            await update.message.reply_text("⛔️ Недостаточно средств")
            return
        user_states.pop(uid, None)
        await update.message.reply_text(f"✅ Заявка на вывод {amount} RUB принята.")

    elif state == "awaiting_broadcast":
        if not role_gte(get_role(uid), ROLE_ADMIN):
            user_states.pop(uid, None)
            return
        user_states.pop(uid, None)
        sent = failed = 0
        for tid in get_all_user_ids():
            try:
                await context.bot.send_message(chat_id=tid, text=text)
                sent += 1
            except Exception:
                failed += 1
        await update.message.reply_text(f"✅ Рассылка: {sent} отправлено, ошибок: {failed}")

    elif state == "awaiting_manage_user":
        user_states.pop(uid, None)
        if not role_gte(get_role(uid), ROLE_ADMIN):
            return
        row = None
        if text.lstrip("@").isdigit():
            row = get_user(int(text.lstrip("@")))
        else:
            row = get_user_by_username(text)
        if not row:
            try:
                row = get_user(int(text))
            except ValueError:
                pass
        if not row:
            await update.message.reply_text("Пользователь не найден")
            return
        tid, uname, fname, bal, trole, _ = row
        await update.message.reply_text(
            f"👤 ID: {tid}\n@{uname or '—'}\n{fname or '—'}\nРоль: {ROLE_BADGES.get(trole, trole)}\nБаланс: {bal} RUB",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚫 Ban", callback_data=f"set_role_{tid}_banned")],
                [InlineKeyboardButton("👤 User", callback_data=f"set_role_{tid}_user")],
                [InlineKeyboardButton("⭐️ VIP", callback_data=f"set_role_{tid}_vip")],
                [InlineKeyboardButton("🤝 Reseller", callback_data=f"set_role_{tid}_reseller")],
                back_btn("admin_panel"),
            ]),
        )
    else:
        await update.message.reply_text("Нажми /start для открытия меню.")

# ===== Callbacks =====
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    uid = user.id
    get_or_create_user(uid, user.username, user.first_name)
    if is_banned(uid):
        await query.edit_message_text("🚫 Вы заблокированы.")
        return
    role = get_role(uid)

    try:
        if data == "main":
            await query.edit_message_text(
                "📻 Добро пожаловать, путник\n🪄 Этот бот поможет тебе в приобретении самых лучших DLC от Black!\n👇 Используйте кнопки ниже",
                reply_markup=main_menu_kb(),
            )

        elif data == "profile":
            row = get_user(uid)
            _, username, _, balance, status, _ = row
            badge = ROLE_BADGES.get(status, status)
            display_id = OWNERS.get(uid, str(uid))
            await query.edit_message_text(
                f"🔮 Имя: @{username or '—'}\n📻 Купленных подписок: {len(get_purchases(uid))} шт.\n"
                f"💰 Баланс: {balance} RUB\n🧰 Статус: {badge}\n📑 ID аккаунта: {display_id}",
                reply_markup=profile_kb(status),
            )

        elif data == "plans":
            await query.edit_message_text("На какую игру тебе нужен DLC?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔫 Standoff2", callback_data="game_standoff")],
                [InlineKeyboardButton("🪙 Pubg: Mobile ❌", callback_data="disabled")],
                [InlineKeyboardButton("🔧 Установка ROOT-прав", callback_data="game_root")],
                back_btn(),
            ]))

        elif data == "links":
            await query.edit_message_text(
                "✔️ Официальные каналы Black:\n\n"
                "🔹Новости: @BlackDLCNews\n🔹Бот: @BlackDLCBot\n🔹Отзывы: @BlackHoli",
                reply_markup=InlineKeyboardMarkup([back_btn()]),
            )

        elif data == "referral":
            token = get_or_create_ref_token(uid)
            ref_link = f"https://t.me/{BOT_USERNAME}?start=reft_{token}"
            invited, earned = get_referral_stats(uid)
            await query.edit_message_text(
                f"🧳 Реферальная система:\n\n• 15% с каждой покупки приглашённого\n"
                f"👥 Приглашено: {invited}\n💰 Доход: {earned} RUB\n\n🔗 {ref_link}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤝 Партнёрство", url="https://t.me/luzerminecraft")],
                    back_btn("profile"),
                ]),
            )

        elif data == "purchases":
            rows = get_purchases(uid)
            if rows:
                body = "🛍 Твои покупки:\n\n" + "\n".join(f"• {i} — {a} ({c})" for i, a, c in rows)
            else:
                body = "🛍 У вас еще нету покупок"
            await query.edit_message_text(body, reply_markup=InlineKeyboardMarkup([back_btn("profile")]))

        elif data == "withdraw":
            user_states[uid] = "awaiting_withdrawal"
            await context.bot.send_message(uid, "💎 Отправьте сумму вывода (RUB)")

        # Admin
        elif data == "admin_panel":
            if not role_gte(role, ROLE_ADMIN):
                await query.answer("Нет доступа", show_alert=True)
                return
            await query.edit_message_text("🛡 Панель администратора", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
                [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
                [InlineKeyboardButton("👥 Управление", callback_data="admin_manage")],
                back_btn("profile"),
            ]))

        elif data == "admin_stats":
            if not role_gte(role, ROLE_ADMIN):
                return
            s = get_stats()
            await query.edit_message_text(
                f"📊 Статистика:\n👥 Всего: {s['total']}\n⭐️ VIP: {s['vip']}\n"
                f"🤝 Реселлеров: {s['resellers']}\n🛡 Админов: {s['admins']}\n🚫 Заблокировано: {s['banned']}",
                reply_markup=InlineKeyboardMarkup([back_btn("admin_panel")]),
            )

        elif data == "admin_broadcast":
            if not role_gte(role, ROLE_ADMIN):
                return
            user_states[uid] = "awaiting_broadcast"
            await context.bot.send_message(uid, "📢 Введите текст рассылки:")

        elif data == "admin_manage":
            if not role_gte(role, ROLE_ADMIN):
                return
            user_states[uid] = "awaiting_manage_user"
            await context.bot.send_message(uid, "👤 Введите ID или @username:")

        elif data.startswith("set_role_"):
            if not role_gte(role, ROLE_ADMIN):
                return
            parts = data[len("set_role_"):].rsplit("_", 1)
            if len(parts) != 2:
                return
            try:
                tid = int(parts[0])
            except ValueError:
                return
            new_role = parts[1]
            set_user_role(tid, new_role)
            await query.answer(f"Роль изменена: {ROLE_BADGES.get(new_role, new_role)}", show_alert=True)

        elif data == "reseller_panel":
            if role not in (ROLE_RESELLER, ROLE_ADMIN, ROLE_OWNER):
                return
            token = get_or_create_ref_token(uid)
            ref_link = f"https://t.me/{BOT_USERNAME}?start=reft_{token}"
            invited, earned = get_referral_stats(uid)
            await query.edit_message_text(
                f"🤝 Панель реселлера\n👥 Приглашено: {invited}\n💰 Заработано: {earned} RUB\n🔗 {ref_link}",
                reply_markup=InlineKeyboardMarkup([back_btn("profile")]),
            )

        # Shop
        elif data == "game_standoff":
            await query.edit_message_text("На какое устройство нужен DLC?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 Black APK Android ❌", callback_data="disabled")],
                [InlineKeyboardButton("🍎 Black iPA iOS ❌", callback_data="disabled")],
                [InlineKeyboardButton("💻 Black PC Emulator - БЕЗ рут", callback_data="device_pc")],
                [InlineKeyboardButton("📲 Black Android (рут) ❌", callback_data="disabled")],
                back_btn("plans"),
            ]))

        elif data == "device_pc":
            await query.edit_message_text("На какое устройство нужен DLC?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💻 Black PC External - Без рут", callback_data="device_pc_external")],
                [InlineKeyboardButton("💻 Black PC Internal - Без рут", callback_data="device_pc_internal")],
                back_btn("game_standoff"),
            ]))

        elif data == "device_pc_external":
            await query.edit_message_text(
                f"💻 Black PC External - Без рут\n🔥 Версия игры: {GAME_VERSION}\n🖥 Windows 10/11\n\nВыберите срок ⬇️",
                reply_markup=sub_kb("pc_ext", "device_pc"),
            )

        elif data == "device_pc_internal":
            await query.edit_message_text(
                f"💻 Black PC Internal - Без рут\n🔥 Версия игры: {GAME_VERSION}\n🖥 Windows 10/11\n\nВыберите срок ⬇️",
                reply_markup=sub_kb("pc_int", "device_pc"),
            )

        elif data == "game_root":
            await query.edit_message_text(
                "🔧 Установка ROOT-прав\n📱 Xiaomi, Redmi, Pixel, POCO, Pad\n"
                "Нужен ПК Windows + кабель\n\nВыберите:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Навсегда | 400 RUB", callback_data="sub_root_forever")],
                    back_btn("plans"),
                ]),
            )

        elif data == "sub_root_forever":
            await query.edit_message_text(
                "✅ Вы выбрали: Навсегда | 400 RUB\n\nДля оплаты нажмите «💳 Оплата».",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Оплата", callback_data="payment_root")],
                    back_btn("game_root"),
                ]),
            )

        elif data == "payment_root":
            rows = [[InlineKeyboardButton(m, callback_data=f"pm|{i}|root|0")] for i, m in enumerate(PAYMENT_METHODS)]
            rows.append(back_btn("sub_root_forever"))
            await query.edit_message_text("💳 Выберите удобный вам метод для оплаты:", reply_markup=InlineKeyboardMarkup(rows))

        elif data == "disabled":
            await query.answer("❌ Раздел временно недоступен", show_alert=True)

        elif data.startswith("sub_"):
            last = data.rfind("_")
            idx = int(data[last + 1:])
            game_key = data[4:last]
            back_map = {"pc_ext": "device_pc_external", "pc_int": "device_pc_internal"}
            plan, price = PLAN_LABELS[idx], PLANS_PRICES[idx]
            await query.edit_message_text(
                f"✅ Вы выбрали: {plan} | {price}\n\nДля оплаты нажмите «💳 Оплата».",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Оплата", callback_data=f"pay|{game_key}|{idx}")],
                    back_btn(back_map.get(game_key, "game_standoff")),
                ]),
            )

        elif data.startswith("pay|"):
            _, game_key, sub_idx = data.split("|")
            rows = [[InlineKeyboardButton(m, callback_data=f"pm|{i}|{game_key}|{sub_idx}")] for i, m in enumerate(PAYMENT_METHODS)]
            rows.append(back_btn(f"sub_{game_key}_{sub_idx}"))
            await query.edit_message_text("💳 Выберите удобный вам метод для оплаты:", reply_markup=InlineKeyboardMarkup(rows))

        elif data.startswith("pm|"):
            parts = data.split("|")
            method_idx, game_key, sub_idx = parts[1], parts[2], parts[3]
            method = PAYMENT_METHODS[int(method_idx)]
            product = PRODUCT_NAMES.get(game_key, game_key)
            if game_key == "root":
                plan, price = "Навсегда", "400 RUB"
            else:
                plan = PLAN_LABELS[int(sub_idx)]
                price = PLANS_PRICES[int(sub_idx)]
            order_id = secrets.randbelow(900000) + 100000
            try:
                credit_referrer(uid, int(price.replace(" RUB", "")))
            except Exception:
                pass
            back_cb = "payment_root" if game_key == "root" else f"pay|{game_key}|{sub_idx}"
            await query.edit_message_text(
                f"💳 Информация о заказе:\n\n"
                f"🛒 Товар: {product}\n"
                f"⏳ Срок: {plan}\n"
                f"💵 Метод оплаты: {method}\n"
                f"💰 Сумма: {price}\n"
                f"🏷 ID заказа: {order_id}",
                reply_markup=InlineKeyboardMarkup([back_btn(back_cb)]),
            )

        else:
            await query.edit_message_text(
                "📻 Добро пожаловать\n👇 Используйте кнопки",
                reply_markup=main_menu_kb(),
            )

    except Exception as e:
        logger.error("Ошибка в %s: %s", data, e)
        try:
            await query.edit_message_text("📻 Меню", reply_markup=main_menu_kb())
        except Exception:
            pass

async def error_handler(update, context):
    logger.error("Ошибка: %s", context.error)

async def genkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not role_gte(get_role(uid), ROLE_ADMIN):
        await update.message.reply_text("⛔️ Нет доступа")
        return
    if not KEY_API_OK:
        await update.message.reply_text("❌ bot_key_api.py не найден")
        return
    args = context.args or []
    key_type = (args[0] if args else "7D").upper()
    count = 1
    if len(args) >= 2:
        try:
            count = max(1, min(int(args[1]), 20))
        except ValueError:
            pass
    if key_type not in ("7D", "30D", "60D", "LT"):
        await update.message.reply_text("Использование: /genkey <7D|30D|60D|LT> [кол-во]")
        return
    result = generate_key_by_type(key_type, count)
    if not result.get("ok"):
        await update.message.reply_text(f"❌ {result.get('error')}")
        return
    keys = result.get("keys", [])
    await update.message.reply_text(f"✅ Ключи ({key_type}):\n\n" + "\n".join(f"`{k}`" for k in keys), parse_mode="Markdown")

async def blockkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not role_gte(get_role(update.effective_user.id), ROLE_ADMIN):
        await update.message.reply_text("⛔️ Нет доступа")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("Использование: /blockkey BH-7D-XXXXXX")
        return
    result = block_key(args[0])
    if result.get("ok"):
        await update.message.reply_text(f"🚫 Ключ `{args[0].upper()}` заблокирован.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ {result.get('error')}")

def main():
    init_db()
    ensure_dev_credits()
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(10)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("genkey", genkey_command))
    app.add_handler(CommandHandler("blockkey", blockkey_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))
    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
