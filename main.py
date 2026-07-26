import asyncio
import logging
import os
import secrets
import sqlite3
import sys

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Key Server integration
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
    print(
        "Ошибка: не задан секрет TELEGRAM_BOT_TOKEN. "
        "Добавь его в Replit Secrets и перезапусти workflow.",
        file=sys.stderr,
    )
    sys.exit(1)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DB_PATH = "data/bot.db"

# ===== НАСТРОЙКИ БОТА =====
GAME_VERSION = "0.39.2"

PLANS_PRICES = ["250 RUB", "400 RUB", "590 RUB", "790 RUB"]

PAYMENT_METHODS = [
    "СБП #1",
    "СБП #2 (запасной)",
    "Карта РФ",
    "Карта СНГ",
    "CryptoBot",
    "Баланс",
]

CHANNELS = [
    ("news_channel", "@BlackDLCNews"),
    ("bot_channel", "@BlackDLCBot"),
    ("reviews_channel", "@BlackHoli"),
    ("feedback_channel", ""),
]

OWNERS: dict[int, str] = {
    8097159122: "DEV_01",
    8399842427: "DEV_02",
}

TOS_URL = "https://telegra.ph/Lensionnoe-soglashenie-Black-07-21"
PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-Black-07-21"

# ===== РОЛИ =====
ROLE_OWNER    = "Owner"
ROLE_ADMIN    = "admin"
ROLE_RESELLER = "reseller"
ROLE_VIP      = "vip"
ROLE_USER     = "user"
ROLE_BANNED   = "banned"

ROLE_HIERARCHY = {
    ROLE_BANNED: 0,
    ROLE_USER: 1,
    ROLE_VIP: 2,
    ROLE_RESELLER: 3,
    ROLE_ADMIN: 4,
    ROLE_OWNER: 5,
}

ROLE_BADGES = {
    ROLE_OWNER:    "👑 Owner",
    ROLE_ADMIN:    "🛡 Admin",
    ROLE_RESELLER: "🤝 Reseller",
    ROLE_VIP:      "⭐️ VIP",
    ROLE_USER:     "👤 User",
    ROLE_BANNED:   "🚫 Banned",
}

# Состояния / язык
user_states: dict[int, str] = {}
user_langs:  dict[int, str] = {}


def role_gte(role: str, minimum: str) -> bool:
    return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get(minimum, 0)


# ===== ПЕРЕВОДЫ =====
TRANSLATIONS: dict[str, dict[str, str]] = {
    "welcome": {
        "ru": "📻 Добро пожаловать, путник\n🪄 Этот бот поможет тебе в приобретении самых лучших DLC от Black!\n👇 Для управления ботом используйте кнопки в этом сообщении",
        "en": "📻 Welcome, traveler\n🪄 This bot will help you get the best DLC from Black!\n👇 Use the buttons in this message to navigate",
        "uk": "📻 Ласкаво просимо, мандрівнику\n🪄 Цей бот допоможе тобі придбати найкращі DLC від Black!\n👇 Для керування ботом використовуйте кнопки в цьому повідомленні",
        "pt": "📻 Bem-vindo, viajante\n🪄 Este bot vai te ajudar a adquirir os melhores DLCs da Black!\n👇 Use os botões nesta mensagem para navegar",
    },
    "banned_msg": {
        "ru": "🚫 Вы заблокированы и не можете пользоваться ботом.\nЕсли вы считаете это ошибкой — обратитесь в поддержку.",
        "en": "🚫 You are banned and cannot use this bot.\nIf you think this is a mistake — contact support.",
        "uk": "🚫 Вас заблоковано. Зверніться до підтримки.",
        "pt": "🚫 Você foi banido. Entre em contato com o suporte.",
    },
    "btn_buy_key":      {"ru": "🗝 Приобрести ключ",   "en": "🗝 Buy a key",         "uk": "🗝 Придбати ключ",    "pt": "🗝 Comprar chave"},
    "btn_my_profile":   {"ru": "📱 Мой профиль",       "en": "📱 My profile",        "uk": "📱 Мій профіль",     "pt": "📱 Meu perfil"},
    "btn_reviews":      {"ru": "🗂 Отзывы",             "en": "🗂 Reviews",           "uk": "🗂 Відгуки",         "pt": "🗂 Avaliações"},
    "btn_useful_links": {"ru": "📝 Полезные ссылки",   "en": "📝 Useful links",      "uk": "📝 Корисні посилання","pt": "📝 Links úteis"},
    "btn_back":         {"ru": "🔙 Вернуться назад",   "en": "🔙 Go back",           "uk": "🔙 Повернутися",     "pt": "🔙 Voltar"},
    "profile_text": {
        "ru": "🔮 Имя: @{username}\n📻 Купленных подписок: {purchases} шт.\n💰 Баланс: {balance} RUB\n🧰 Статус: {badge}\n📑 ID аккаунта: {account_id}",
        "en": "🔮 Name: @{username}\n📻 Subscriptions: {purchases}\n💰 Balance: {balance} RUB\n🧰 Status: {badge}\n📑 Account ID: {account_id}",
        "uk": "🔮 Ім'я: @{username}\n📻 Підписок: {purchases}\n💰 Баланс: {balance} RUB\n🧰 Статус: {badge}\n📑 ID: {account_id}",
        "pt": "🔮 Nome: @{username}\n📻 Assinaturas: {purchases}\n💰 Saldo: {balance} RUB\n🧰 Status: {badge}\n📑 ID: {account_id}",
    },
    "btn_withdraw":    {"ru": "💰 Вывести средства",    "en": "💰 Withdraw",          "uk": "💰 Вивести кошти",   "pt": "💰 Sacar"},
    "btn_referral":    {"ru": "🎁 Реферальная система", "en": "🎁 Referral system",   "uk": "🎁 Реферальна система","pt": "🎁 Indicações"},
    "btn_purchases":   {"ru": "🛍 Мои покупки",         "en": "🛍 My purchases",      "uk": "🛍 Мої покупки",     "pt": "🛍 Minhas compras"},
    "btn_tos":         {"ru": "📄 Наш ToS",              "en": "📄 Our ToS",           "uk": "📄 Наш ToS",         "pt": "📄 Nosso ToS"},
    "btn_privacy":     {"ru": "🔒 Privacy Policy",       "en": "🔒 Privacy Policy",   "uk": "🔒 Privacy Policy",  "pt": "🔒 Privacidade"},
    "btn_change_lang": {"ru": "🌍 Поменять язык",        "en": "🌍 Change language",  "uk": "🌍 Змінити мову",    "pt": "🌍 Idioma"},
    "btn_admin_panel": {"ru": "🛡 Панель администратора","en": "🛡 Admin panel",      "uk": "🛡 Панель адміна",   "pt": "🛡 Painel admin"},
    "btn_reseller_panel":{"ru":"🤝 Панель реселлера",   "en": "🤝 Reseller panel",   "uk": "🤝 Панель реселера", "pt": "🤝 Painel revendedor"},
    "purchases_title": {"ru": "🛍 Твои покупки:\n\n",   "en": "🛍 Your purchases:\n\n","uk": "🛍 Твої покупки:\n\n","pt": "🛍 Suas compras:\n\n"},
    "no_purchases":    {"ru": "🛍 У вас еще нету покупок","en": "🛍 No purchases yet","uk": "🛍 Покупок ще немає", "pt": "🛍 Sem compras ainda"},
    "choose_language": {"ru": "🌍 Поменять язык:",       "en": "🌍 Change language:", "uk": "🌍 Змінити мову:",   "pt": "🌍 Mudar idioma:"},
    "lang_set": {
        "ru": "✅ Язык изменён на Русский",
        "en": "✅ Language changed to English",
        "uk": "✅ Мову змінено на Українську",
        "pt": "✅ Idioma alterado para Português",
    },
    "withdraw_prompt":       {"ru": "💎 Отправьте сумму вывода (RUB)",         "en": "💎 Enter withdrawal amount (RUB)",     "uk": "💎 Введіть суму (RUB)",        "pt": "💎 Digite o valor (RUB)"},
    "withdraw_not_a_number": {"ru": "Введите число, например: 1500",           "en": "Enter a number, e.g.: 1500",          "uk": "Введіть число: 1500",         "pt": "Digite um número, ex.: 1500"},
    "withdraw_min":          {"ru": "⛔️ Минимум 1000 RUB",                    "en": "⛔️ Minimum 1000 RUB",                "uk": "⛔️ Мінімум 1000 RUB",        "pt": "⛔️ Mínimo 1000 RUB"},
    "withdraw_no_balance":   {"ru": "⛔️ Недостаточно средств на балансе",     "en": "⛔️ Insufficient balance",            "uk": "⛔️ Недостатньо коштів",      "pt": "⛔️ Saldo insuficiente"},
    "withdraw_ok":           {"ru": "✅ Заявка на вывод {amount} RUB принята.","en": "✅ Withdrawal of {amount} RUB accepted.","uk": "✅ Заявку {amount} RUB прийнято.","pt": "✅ Saque de {amount} RUB aceito."},
    "unknown_message":       {"ru": "Нажми /start для открытия меню.",         "en": "Press /start to open the menu.",      "uk": "Натисни /start.",             "pt": "Pressione /start."},
    "choose_game":     {"ru": "На какую игру тебе нужен DLC?",     "en": "Which game?",          "uk": "Для якої гри?",      "pt": "Qual jogo?"},
    "btn_standoff":    {"ru": "🔫 Standoff2",                        "en": "🔫 Standoff2",         "uk": "🔫 Standoff2",       "pt": "🔫 Standoff2"},
    "btn_pubg_disabled":{"ru":"🪙 Pubg: Mobile ❌",                  "en": "🪙 Pubg: Mobile ❌",   "uk": "🪙 Pubg: Mobile ❌", "pt": "🪙 Pubg: Mobile ❌"},
    "btn_root":        {"ru": "🔧 Установка ROOT-прав",              "en": "🔧 ROOT installation", "uk": "🔧 Встановлення ROOT","pt": "🔧 Instalação ROOT"},
    "pubg_disabled_alert":{"ru":"❌ Раздел временно недоступен",    "en": "❌ Temporarily unavailable","uk":"❌ Тимчасово недоступно","pt":"❌ Temporariamente indisponível"},
    "choose_device":   {"ru": "На какое устройство нужен DLC?",     "en": "Which device?",        "uk": "Для якого пристрою?","pt": "Qual dispositivo?"},
    "btn_apk":         {"ru": "📱 Black APK Android - БЕЗ рут",     "en": "📱 Black APK Android - NO root","uk":"📱 Black APK Android","pt":"📱 Black APK Android"},
    "btn_apk_disabled":{"ru": "📱 Black APK Android ❌",             "en": "📱 Black APK Android ❌",         "uk":"📱 Black APK Android ❌",        "pt":"📱 Black APK Android ❌"},
    "btn_ios":                  {"ru": "🍎 Black iPA iOS - на все iOS",       "en": "🍎 Black iPA iOS - all versions","uk":"🍎 Black iPA iOS","pt":"🍎 Black iPA iOS"},
    "btn_ios_disabled":         {"ru": "🍎 Black iPA iOS ❌",                  "en": "🍎 Black iPA iOS ❌",              "uk":"🍎 Black iPA iOS ❌",             "pt":"🍎 Black iPA iOS ❌"},
    "btn_pc_emulator":          {"ru": "💻 Black PC Emulator - БЕЗ рут",     "en": "💻 Black PC Emulator - NO root","uk":"💻 Black PC Emulator","pt":"💻 Black PC Emulator"},
    "btn_android_root":         {"ru": "📲 Black Android - Нужны рут права", "en": "📲 Black Android - ROOT required","uk":"📲 Black Android - ROOT","pt":"📲 Black Android - ROOT"},
    "btn_android_root_disabled":{"ru": "📲 Black Android (рут) ❌",           "en": "📲 Black Android (root) ❌",       "uk":"📲 Black Android (рут) ❌",       "pt":"📲 Black Android (root) ❌"},
    "section_disabled_alert":   {"ru": "❌ Раздел временно закрыт",           "en": "❌ Section temporarily closed",   "uk":"❌ Розділ тимчасово закрито",     "pt":"❌ Seção temporariamente fechada"},
    "choose_pc_version":{"ru":"На какое устройство нужен DLC?",     "en": "Which device?",        "uk": "Для якого пристрою?","pt": "Qual dispositivo?"},
    "btn_pc_external": {"ru": "💻 Black PC External - Без рут",      "en": "💻 Black PC External","uk": "💻 Black PC External","pt": "💻 Black PC External"},
    "btn_pc_internal": {"ru": "💻 Black PC Internal - Без рут",      "en": "💻 Black PC Internal","uk": "💻 Black PC Internal","pt": "💻 Black PC Internal"},
    "choose_android_version":{"ru":"📱 Выберите версию Black Android:","en":"📱 Choose Black Android:","uk":"📱 Оберіть версію:","pt":"📱 Escolha a versão:"},
    "btn_android_external":{"ru":"📱 Black Android External - Нужны рут","en":"📱 Black Android External","uk":"📱 Black Android External","pt":"📱 Black Android External"},
    "btn_android_internal":{"ru":"📱 Black Android Internal - Нужны рут","en":"📱 Black Android Internal","uk":"📱 Black Android Internal","pt":"📱 Black Android Internal"},
    "btn_payment":     {"ru": "💳 Оплата",                           "en": "💳 Payment",          "uk": "💳 Оплата",          "pt": "💳 Pagamento"},
    "choose_payment":  {"ru": "💳 Выберите метод оплаты:",           "en": "💳 Choose payment method:","uk":"💳 Оберіть метод:","pt":"💳 Método de pagamento:"},
    "sub_selected": {
        "ru": "✅ Вы выбрали: {plan} | {price}\n\nДля оплаты нажмите «💳 Оплата».",
        "en": "✅ Selected: {plan} | {price}\n\nClick «💳 Payment» to pay.",
        "uk": "✅ Ви обрали: {plan} | {price}\n\nНатисніть «💳 Оплата».",
        "pt": "✅ Selecionado: {plan} | {price}\n\nClique em «💳 Pagamento».",
    },
    "payment_selected": {
        "ru": "✅ Метод: {method}\nПодписка: {plan} | {price}\n\nСвяжитесь с поддержкой для реквизитов.",
        "en": "✅ Method: {method}\nSubscription: {plan} | {price}\n\nContact support for details.",
        "uk": "✅ Метод: {method}\nПідписка: {plan} | {price}\n\nЗверніться до підтримки.",
        "pt": "✅ Método: {method}\nAssinatura: {plan} | {price}\n\nContate o suporte.",
    },
    "root_selected": {
        "ru": "✅ Вы выбрали: Навсегда | 400 RUB\n\nДля оплаты нажмите «💳 Оплата».",
        "en": "✅ Selected: Forever | 400 RUB\n\nClick «💳 Payment».",
        "uk": "✅ Ви обрали: Назавжди | 400 RUB\n\nНатисніть «💳 Оплата».",
        "pt": "✅ Para sempre | 400 RUB\n\nClique em «💳 Pagamento».",
    },
    "btn_root_forever":{"ru":"Навсегда | 400 RUB","en":"Forever | 400 RUB","uk":"Назавжди | 400 RUB","pt":"Para sempre | 400 RUB"},
    "referral_text": {
        "ru": (
            "🧳 Реферальная система:\n\n"
            "Время — деньги. Делитесь ссылкой — и зарабатывайте на рекомендациях.\n\n"
            "👔 Условия:\n"
            "• 15% с каждой покупки приглашённого\n"
            "• Доход на полном пассиве без ограничений\n\n"
            "📊 Ваша статистика:\n"
            "👥 Приглашено: {invited}\n"
            "💰 Общий доход: {total_earned} RUB\n"
            "💳 Доступно к выводу: {total_earned} RUB\n\n"
            "🔗 Ваша реферальная ссылка: {ref_link}\n\n"
            "📌 Хочешь зарабатывать? Расскажи друзьям и начни прямо сейчас!"
        ),
        "en": (
            "🧳 Referral system:\n\n"
            "Time is money. Share your link — and earn on referrals.\n\n"
            "👔 Terms:\n"
            "• 15% from every referred purchase\n"
            "• Passive income with no limits\n\n"
            "📊 Your stats:\n"
            "👥 Invited: {invited}\n"
            "💰 Total earned: {total_earned} RUB\n"
            "💳 Available to withdraw: {total_earned} RUB\n\n"
            "🔗 Your referral link: {ref_link}\n\n"
            "📌 Want to earn? Tell your friends and start right now!"
        ),
        "uk": (
            "🧳 Реферальна система:\n\n"
            "Час — гроші. Діліться посиланням — і заробляйте на рекомендаціях.\n\n"
            "👔 Умови:\n"
            "• 15% з кожної покупки запрошеного\n"
            "• Дохід на повному пасиві без обмежень\n\n"
            "📊 Ваша статистика:\n"
            "👥 Запрошено: {invited}\n"
            "💰 Загальний дохід: {total_earned} RUB\n"
            "💳 Доступно до виводу: {total_earned} RUB\n\n"
            "🔗 Ваше реферальне посилання: {ref_link}\n\n"
            "📌 Хочеш заробляти? Розкажи друзям і почни прямо зараз!"
        ),
        "pt": (
            "🧳 Sistema de indicação:\n\n"
            "Tempo é dinheiro. Compartilhe seu link — e ganhe com indicações.\n\n"
            "👔 Condições:\n"
            "• 15% de cada compra do indicado\n"
            "• Renda passiva sem limites\n\n"
            "📊 Suas estatísticas:\n"
            "👥 Indicados: {invited}\n"
            "💰 Total ganho: {total_earned} RUB\n"
            "💳 Disponível para saque: {total_earned} RUB\n\n"
            "🔗 Seu link de indicação: {ref_link}\n\n"
            "📌 Quer ganhar? Conte para seus amigos e comece agora!"
        ),
    },
    "btn_copy_ref":   {"ru":"🔗 Скопировать реферальную ссылку","en":"🔗 Copy referral link","uk":"🔗 Копіювати посилання","pt":"🔗 Copiar link"},
    "btn_partnership":{"ru":"🤝 Партнёрство","en":"🤝 Partnership","uk":"🤝 Партнерство","pt":"🤝 Parceria"},
    "ref_link_msg":   {"ru":"🔗 Твоя реферальная ссылка:\n{ref_link}","en":"🔗 Your referral link:\n{ref_link}","uk":"🔗 Твоє реферальне посилання:\n{ref_link}","pt":"🔗 Seu link:\n{ref_link}"},
    "links_header":   {"ru":"✔️ Официальные каналы Black:\n\n","en":"✔️ Official Black channels:\n\n","uk":"✔️ Офіційні канали Black:\n\n","pt":"✔️ Canais oficiais Black:\n\n"},
    "news_channel":   {"ru":"Новости","en":"News","uk":"Новини","pt":"Notícias"},
    "bot_channel":    {"ru":"Бот","en":"Bot","uk":"Бот","pt":"Bot"},
    "reviews_channel":{"ru":"Отзывы","en":"Reviews","uk":"Відгуки","pt":"Avaliações"},
    "feedback_channel":{"ru":"Обратная связь","en":"Feedback","uk":"Зворотній зв'язок","pt":"Feedback"},
    "help_text": {
        "ru": "Команды:\n/start — меню\n/help — помощь\n/id — мой ID",
        "en": "Commands:\n/start — menu\n/help — help\n/id — my ID",
        "uk": "Команди:\n/start — меню\n/help — допомога\n/id — мій ID",
        "pt": "Comandos:\n/start — menu\n/help — ajuda\n/id — meu ID",
    },
    # ===== Описания продуктов (оригинал из файла) =====
    "apk_desc": {
        "ru": (
            "📱 Black APK Android - БЕЗ рут прав\n\n"
            "🔥 Поддержка последней версии игры ({ver})\n\n"
            "📲 Данный продукт поддерживает Android устройства версий 8-16\n\n"
            "🗽 Не требует рут прав!\n\n"
            "🔍 Функционал APK версии: посмотреть\n\n"
            "✅ Поддерживаются такие способы входа: Vk, Facebook, Google — выбирай любой удобный!\n\n"
            "Выберите срок подписки ниже ⬇️"
        ),
        "en": (
            "📱 Black APK Android - NO root required\n\n"
            "🔥 Supports latest game version ({ver})\n\n"
            "📲 Supports Android devices version 8-16\n\n"
            "🗽 No root required!\n\n"
            "🔍 APK version features: view\n\n"
            "✅ Supported logins: Vk, Facebook, Google — choose any!\n\n"
            "Choose subscription period below ⬇️"
        ),
        "uk": (
            "📱 Black APK Android - БЕЗ рут прав\n\n"
            "🔥 Підтримка останньої версії гри ({ver})\n\n"
            "📲 Продукт підтримує Android пристрої версій 8-16\n\n"
            "🗽 Не потребує рут прав!\n\n"
            "🔍 Функціонал APK версії: переглянути\n\n"
            "✅ Підтримувані способи входу: Vk, Facebook, Google — обирай будь-який!\n\n"
            "Оберіть термін підписки нижче ⬇️"
        ),
        "pt": (
            "📱 Black APK Android - SEM root\n\n"
            "🔥 Suporte à versão mais recente do jogo ({ver})\n\n"
            "📲 Suporta dispositivos Android versões 8-16\n\n"
            "🗽 Não requer root!\n\n"
            "🔍 Funcionalidades da versão APK: ver\n\n"
            "✅ Logins suportados: Vk, Facebook, Google — escolha qualquer um!\n\n"
            "Escolha o período de assinatura abaixo ⬇️"
        ),
    },
    "ios_desc": {
        "ru": (
            "🍎 Black iPA iOS - на все iOS\n\n"
            "🔥 Поддержка последней версии игры ({ver})\n\n"
            "📲 Данный продукт поддерживает все версии iOS, даже iOS 26!\n\n"
            "🗽 Не требует Jailbreak/TrollStore\n\n"
            "🔍 Функционал iPA версии: посмотреть\n\n"
            "✅ Поддерживаются такие способы входа: Google, Vk, Facebook — выбирай любой удобный!\n\n"
            "Выберите срок подписки ниже ⬇️"
        ),
        "en": (
            "🍎 Black iPA iOS - all iOS versions\n\n"
            "🔥 Supports latest game version ({ver})\n\n"
            "📲 Supports all iOS versions, even iOS 26!\n\n"
            "🗽 No Jailbreak/TrollStore required\n\n"
            "🔍 iPA version features: view\n\n"
            "✅ Supported logins: Google, Vk, Facebook — choose any!\n\n"
            "Choose subscription period below ⬇️"
        ),
        "uk": (
            "🍎 Black iPA iOS - на всі iOS\n\n"
            "🔥 Підтримка останньої версії гри ({ver})\n\n"
            "📲 Підтримує всі версії iOS, навіть iOS 26!\n\n"
            "🗽 Не потребує Jailbreak/TrollStore\n\n"
            "🔍 Функціонал iPA версії: переглянути\n\n"
            "✅ Підтримувані способи входу: Google, Vk, Facebook — обирай будь-який!\n\n"
            "Оберіть термін підписки нижче ⬇️"
        ),
        "pt": (
            "🍎 Black iPA iOS - todos os iOS\n\n"
            "🔥 Suporte à versão mais recente do jogo ({ver})\n\n"
            "📲 Suporta todas as versões iOS, até iOS 26!\n\n"
            "🗽 Sem Jailbreak/TrollStore\n\n"
            "🔍 Funcionalidades da versão iPA: ver\n\n"
            "✅ Logins suportados: Google, Vk, Facebook — escolha qualquer um!\n\n"
            "Escolha o período de assinatura abaixo ⬇️"
        ),
    },
    "pc_ext_desc": {
        "ru": (
            "💻 Black PC External - Без рут прав\n\n"
            "🔥 Поддержка последней версии игры ({ver})\n\n"
            "🖥 Данный продукт поддерживает Windows 10/11\n\n"
            "🗽 Не требует рут прав!\n\n"
            "🔍 Функционал External версии: посмотреть\n\n"
            "✅ Поддерживаются такие способы входа: Vk, Facebook, Google — выбирай любой удобный!\n\n"
            "Выберите срок подписки ниже ⬇️"
        ),
        "en": (
            "💻 Black PC External - No root required\n\n"
            "🔥 Supports latest game version ({ver})\n\n"
            "🖥 Supports Windows 10/11\n\n"
            "🗽 No root required!\n\n"
            "🔍 External version features: view\n\n"
            "✅ Supported logins: Vk, Facebook, Google — choose any!\n\n"
            "Choose subscription period below ⬇️"
        ),
        "uk": (
            "💻 Black PC External - Без рут прав\n\n"
            "🔥 Підтримка останньої версії гри ({ver})\n\n"
            "🖥 Продукт підтримує Windows 10/11\n\n"
            "🗽 Не потребує рут прав!\n\n"
            "🔍 Функціонал External версії: переглянути\n\n"
            "✅ Підтримувані способи входу: Vk, Facebook, Google — обирай будь-який!\n\n"
            "Оберіть термін підписки нижче ⬇️"
        ),
        "pt": (
            "💻 Black PC External - Sem root\n\n"
            "🔥 Suporte à versão mais recente do jogo ({ver})\n\n"
            "🖥 Suporta Windows 10/11\n\n"
            "🗽 Sem root necessário!\n\n"
            "🔍 Funcionalidades da versão External: ver\n\n"
            "✅ Logins suportados: Vk, Facebook, Google — escolha qualquer um!\n\n"
            "Escolha o período de assinatura abaixo ⬇️"
        ),
    },
    "pc_int_desc": {
        "ru": (
            "💻 Black PC Internal - Без рут прав\n\n"
            "🔥 Поддержка последней версии игры ({ver})\n\n"
            "🖥 Данный продукт поддерживает Windows 10/11\n\n"
            "🗽 Не требует рут прав!\n\n"
            "🔍 Функционал Internal версии: посмотреть\n\n"
            "✅ Поддерживаются такие способы входа: Vk, Facebook, Google — выбирай любой удобный!\n\n"
            "Выберите срок подписки ниже ⬇️"
        ),
        "en": (
            "💻 Black PC Internal - No root required\n\n"
            "🔥 Supports latest game version ({ver})\n\n"
            "🖥 Supports Windows 10/11\n\n"
            "🗽 No root required!\n\n"
            "🔍 Internal version features: view\n\n"
            "✅ Supported logins: Vk, Facebook, Google — choose any!\n\n"
            "Choose subscription period below ⬇️"
        ),
        "uk": (
            "💻 Black PC Internal - Без рут прав\n\n"
            "🔥 Підтримка останньої версії гри ({ver})\n\n"
            "🖥 Продукт підтримує Windows 10/11\n\n"
            "🗽 Не потребує рут прав!\n\n"
            "🔍 Функціонал Internal версії: переглянути\n\n"
            "✅ Підтримувані способи входу: Vk, Facebook, Google — обирай будь-який!\n\n"
            "Оберіть термін підписки нижче ⬇️"
        ),
        "pt": (
            "💻 Black PC Internal - Sem root\n\n"
            "🔥 Suporte à versão mais recente do jogo ({ver})\n\n"
            "🖥 Suporta Windows 10/11\n\n"
            "🗽 Sem root necessário!\n\n"
            "🔍 Funcionalidades da versão Internal: ver\n\n"
            "✅ Logins suportados: Vk, Facebook, Google — escolha qualquer um!\n\n"
            "Escolha o período de assinatura abaixo ⬇️"
        ),
    },
    "android_ext_desc": {
        "ru": (
            "📱 Black Android External — Нужны рут права\n\n"
            "🔥 Поддержка последней версии игры ({ver})\n\n"
            "📲 Данный продукт поддерживает Android устройства версий 8-16\n\n"
            "⚠️ Нужны рут права!\n\n"
            "🔍 Функционал External версии: посмотреть\n\n"
            "✅ Поддерживаются такие способы входа: Vk, Facebook, Google — выбирай любой удобный!\n\n"
            "Выберите срок подписки ниже ⬇️"
        ),
        "en": (
            "📱 Black Android External — ROOT required\n\n"
            "🔥 Supports latest game version ({ver})\n\n"
            "📲 Supports Android devices version 8-16\n\n"
            "⚠️ ROOT access required!\n\n"
            "🔍 External version features: view\n\n"
            "✅ Supported logins: Vk, Facebook, Google — choose any!\n\n"
            "Choose subscription period below ⬇️"
        ),
        "uk": (
            "📱 Black Android External — Потрібні рут права\n\n"
            "🔥 Підтримка останньої версії гри ({ver})\n\n"
            "📲 Продукт підтримує Android пристрої версій 8-16\n\n"
            "⚠️ Потрібні рут права!\n\n"
            "🔍 Функціонал External версії: переглянути\n\n"
            "✅ Підтримувані способи входу: Vk, Facebook, Google — обирай будь-який!\n\n"
            "Оберіть термін підписки нижче ⬇️"
        ),
        "pt": (
            "📱 Black Android External — ROOT necessário\n\n"
            "🔥 Suporte à versão mais recente do jogo ({ver})\n\n"
            "📲 Suporta dispositivos Android versões 8-16\n\n"
            "⚠️ Acesso ROOT necessário!\n\n"
            "🔍 Funcionalidades da versão External: ver\n\n"
            "✅ Logins suportados: Vk, Facebook, Google — escolha qualquer um!\n\n"
            "Escolha o período de assinatura abaixo ⬇️"
        ),
    },
    "android_int_desc": {
        "ru": (
            "📱 Black Android Internal — Нужны рут права\n\n"
            "🔥 Поддержка последней версии игры ({ver})\n\n"
            "📲 Данный продукт поддерживает Android устройства версий 8-16\n\n"
            "⚠️ Нужны рут права!\n\n"
            "🔍 Функционал Internal версии: посмотреть\n\n"
            "✅ Поддерживаются такие способы входа: Vk, Facebook, Google — выбирай любой удобный!\n\n"
            "Выберите срок подписки ниже ⬇️"
        ),
        "en": (
            "📱 Black Android Internal — ROOT required\n\n"
            "🔥 Supports latest game version ({ver})\n\n"
            "📲 Supports Android devices version 8-16\n\n"
            "⚠️ ROOT access required!\n\n"
            "🔍 Internal version features: view\n\n"
            "✅ Supported logins: Vk, Facebook, Google — choose any!\n\n"
            "Choose subscription period below ⬇️"
        ),
        "uk": (
            "📱 Black Android Internal — Потрібні рут права\n\n"
            "🔥 Підтримка останньої версії гри ({ver})\n\n"
            "📲 Продукт підтримує Android пристрої версій 8-16\n\n"
            "⚠️ Потрібні рут права!\n\n"
            "🔍 Функціонал Internal версії: переглянути\n\n"
            "✅ Підтримувані способи входу: Vk, Facebook, Google — обирай будь-який!\n\n"
            "Оберіть термін підписки нижче ⬇️"
        ),
        "pt": (
            "📱 Black Android Internal — ROOT necessário\n\n"
            "🔥 Suporte à versão mais recente do jogo ({ver})\n\n"
            "📲 Suporta dispositivos Android versões 8-16\n\n"
            "⚠️ Acesso ROOT necessário!\n\n"
            "🔍 Funcionalidades da versão Internal: ver\n\n"
            "✅ Logins suportados: Vk, Facebook, Google — escolha qualquer um!\n\n"
            "Escolha o período de assinatura abaixo ⬇️"
        ),
    },
    "root_desc": {
        "ru": (
            "🔧 Установка ROOT-прав\n\n"
            "📱 Устанавливаем ROOT-права на устройства:\n"
            "Xiaomi, Redmi, Google Pixel, Redmi Pad, Xiaomi Pad, POCO\n\n"
            "Для установки рута нужен:\n"
            "• Компьютер или ноутбук на Windows 7–11\n"
            "• Кабель для подключения телефона к компьютеру\n\n"
            "Что такое ROOT права?"
        ),
        "en": (
            "🔧 ROOT installation\n\n"
            "📱 We install ROOT on devices:\n"
            "Xiaomi, Redmi, Google Pixel, Redmi Pad, Xiaomi Pad, POCO\n\n"
            "For ROOT installation you need:\n"
            "• Windows 7–11 PC or laptop\n"
            "• Cable to connect phone to PC\n\n"
            "What is ROOT access?"
        ),
        "uk": (
            "🔧 Встановлення ROOT-прав\n\n"
            "📱 Встановлюємо ROOT-права на пристрої:\n"
            "Xiaomi, Redmi, Google Pixel, Redmi Pad, Xiaomi Pad, POCO\n\n"
            "Для встановлення рута потрібен:\n"
            "• Комп'ютер або ноутбук на Windows 7–11\n"
            "• Кабель для підключення телефону до комп'ютера\n\n"
            "Що таке ROOT права?"
        ),
        "pt": (
            "🔧 Instalação de ROOT\n\n"
            "📱 Instalamos ROOT nos dispositivos:\n"
            "Xiaomi, Redmi, Google Pixel, Redmi Pad, Xiaomi Pad, POCO\n\n"
            "Para instalar ROOT você precisa:\n"
            "• PC ou notebook com Windows 7–11\n"
            "• Cabo para conectar o celular ao PC\n\n"
            "O que é acesso ROOT?"
        ),
    },
    # ===== Адмін панель =====
    "admin_panel_title": {
        "ru": "🛡 Панель администратора",
        "en": "🛡 Admin panel",
        "uk": "🛡 Панель адміністратора",
        "pt": "🛡 Painel admin",
    },
    "btn_stats":        {"ru":"📊 Статистика","en":"📊 Statistics","uk":"📊 Статистика","pt":"📊 Estatísticas"},
    "btn_broadcast":    {"ru":"📢 Рассылка","en":"📢 Broadcast","uk":"📢 Розсилка","pt":"📢 Transmissão"},
    "btn_manage_users": {"ru":"👥 Управление пользователями","en":"👥 Manage users","uk":"👥 Управління користувачами","pt":"👥 Gerenciar usuários"},
    "stats_text": {
        "ru": "📊 Статистика бота:\n\n👥 Всего пользователей: {total}\n⭐️ VIP: {vip}\n🤝 Реселлеров: {resellers}\n🛡 Админов: {admins}\n🚫 Заблокировано: {banned}",
        "en": "📊 Bot statistics:\n\n👥 Total users: {total}\n⭐️ VIP: {vip}\n🤝 Resellers: {resellers}\n🛡 Admins: {admins}\n🚫 Banned: {banned}",
        "uk": "📊 Статистика бота:\n\n👥 Всього: {total}\n⭐️ VIP: {vip}\n🤝 Реселерів: {resellers}\n🛡 Адмінів: {admins}\n🚫 Заблокованих: {banned}",
        "pt": "📊 Estatísticas:\n\n👥 Total: {total}\n⭐️ VIP: {vip}\n🤝 Revendedores: {resellers}\n🛡 Admins: {admins}\n🚫 Banidos: {banned}",
    },
    "broadcast_prompt": {
        "ru": "📢 Введите текст рассылки. Он будет отправлен всем пользователям:",
        "en": "📢 Enter broadcast message to send to all users:",
        "uk": "📢 Введіть текст розсилки для всіх користувачів:",
        "pt": "📢 Digite a mensagem para transmitir a todos:",
    },
    "broadcast_sent": {
        "ru": "✅ Рассылка отправлена {sent} пользователям. Ошибок: {failed}.",
        "en": "✅ Broadcast sent to {sent} users. Errors: {failed}.",
        "uk": "✅ Розсилка надіслана {sent} користувачам. Помилок: {failed}.",
        "pt": "✅ Enviado para {sent} usuários. Erros: {failed}.",
    },
    "manage_prompt": {
        "ru": "👤 Введите ID пользователя или @username:",
        "en": "👤 Enter user ID or @username:",
        "uk": "👤 Введіть ID або @username:",
        "pt": "👤 Digite o ID ou @username:",
    },
    "user_info": {
        "ru": "👤 Пользователь:\nID: {uid}\nUsername: @{username}\nИмя: {name}\nРоль: {badge}\nБаланс: {balance} RUB",
        "en": "👤 User:\nID: {uid}\nUsername: @{username}\nName: {name}\nRole: {badge}\nBalance: {balance} RUB",
        "uk": "👤 Користувач:\nID: {uid}\nUsername: @{username}\nІм'я: {name}\nРоль: {badge}\nБаланс: {balance} RUB",
        "pt": "👤 Usuário:\nID: {uid}\nUsername: @{username}\nNome: {name}\nFunção: {badge}\nSaldo: {balance} RUB",
    },
    "user_not_found": {
        "ru": "❌ Пользователь не найден. Проверьте ID или @username.",
        "en": "❌ User not found. Check the ID or @username.",
        "uk": "❌ Користувача не знайдено.",
        "pt": "❌ Usuário não encontrado.",
    },
    "role_set": {
        "ru": "✅ Роль изменена на {role}.",
        "en": "✅ Role changed to {role}.",
        "uk": "✅ Роль змінено на {role}.",
        "pt": "✅ Função alterada para {role}.",
    },
    "no_permission": {
        "ru": "⛔️ У вас нет прав для этого действия.",
        "en": "⛔️ You don't have permission for this action.",
        "uk": "⛔️ У вас немає прав.",
        "pt": "⛔️ Sem permissão.",
    },
    # ===== Reseller panel =====
    "reseller_panel": {
        "ru": (
            "🤝 Панель реселлера\n\n"
            "💼 Ваша комиссия: 20% с каждой продажи\n\n"
            "📊 Статистика:\n"
            "👥 Приглашено: {invited}\n"
            "💰 Заработано: {earned} RUB\n"
            "💳 Доступно к выводу: {earned} RUB\n\n"
            "🔗 Ваша ссылка:\n{ref_link}"
        ),
        "en": (
            "🤝 Reseller panel\n\n"
            "💼 Your commission: 20% per sale\n\n"
            "📊 Stats:\n"
            "👥 Referred: {invited}\n"
            "💰 Earned: {earned} RUB\n"
            "💳 Available: {earned} RUB\n\n"
            "🔗 Your link:\n{ref_link}"
        ),
        "uk": (
            "🤝 Панель реселера\n\n"
            "💼 Комісія: 20% з кожного продажу\n\n"
            "📊 Статистика:\n"
            "👥 Запрошено: {invited}\n"
            "💰 Зароблено: {earned} RUB\n"
            "💳 Доступно: {earned} RUB\n\n"
            "🔗 Посилання:\n{ref_link}"
        ),
        "pt": (
            "🤝 Painel revendedor\n\n"
            "💼 Comissão: 20% por venda\n\n"
            "📊 Estatísticas:\n"
            "👥 Indicados: {invited}\n"
            "💰 Ganho: {earned} RUB\n"
            "💳 Disponível: {earned} RUB\n\n"
            "🔗 Seu link:\n{ref_link}"
        ),
    },
}


def t(user_id: int, key: str, **kwargs) -> str:
    lang = user_langs.get(user_id, "ru")
    entry = TRANSLATIONS.get(key, {})
    text = entry.get(lang) or entry.get("ru", f"[{key}]")
    if kwargs:
        text = text.format(**kwargs)
    return text


# ===== БД =====
def init_db() -> None:
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0,
            status TEXT DEFAULT 'user',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item TEXT,
            amount TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            earned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ref_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER UNIQUE
        )
    """)
    conn.commit()
    conn.close()


def get_or_create_user(user_id: int, username: str | None, first_name: str | None) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        status = ROLE_OWNER if user_id in OWNERS else ROLE_USER
        cur.execute(
            "INSERT INTO users (user_id, username, first_name, status) VALUES (?, ?, ?, ?)",
            (user_id, username or "", first_name or "", status),
        )
    else:
        if user_id in OWNERS:
            cur.execute("UPDATE users SET status = ? WHERE user_id = ?", (ROLE_OWNER, user_id))
    conn.commit()
    conn.close()


def get_user(user_id: int) -> tuple | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, username, first_name, balance, status, created_at FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_user_by_username(username: str) -> tuple | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    clean = username.lstrip("@")
    cur.execute(
        "SELECT user_id, username, first_name, balance, status, created_at FROM users WHERE username = ?",
        (clean,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def set_user_role(target_id: int, role: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET status = ? WHERE user_id = ?", (role, target_id))
    conn.commit()
    conn.close()


def get_all_user_ids() -> list[int]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE status != ?", (ROLE_BANNED,))
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE status = ?", (ROLE_VIP,))
    vip = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE status = ?", (ROLE_RESELLER,))
    resellers = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE status = ?", (ROLE_ADMIN,))
    admins = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE status = ?", (ROLE_BANNED,))
    banned = cur.fetchone()[0]
    conn.close()
    return {"total": total, "vip": vip, "resellers": resellers, "admins": admins, "banned": banned}


def get_referral_stats(user_id: int) -> tuple[int, int]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COALESCE(SUM(earned), 0) FROM referrals WHERE referrer_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return (row[0], row[1]) if row else (0, 0)


def get_or_create_ref_token(user_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT token FROM ref_tokens WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]
    # Генерируем уникальный токен
    while True:
        token = secrets.token_urlsafe(6)  # ~8 chars, URL-safe
        cur.execute("SELECT 1 FROM ref_tokens WHERE token = ?", (token,))
        if not cur.fetchone():
            break
    cur.execute("INSERT INTO ref_tokens (token, user_id) VALUES (?, ?)", (token, user_id))
    conn.commit()
    conn.close()
    return token


def get_user_id_by_token(token: str) -> int | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM ref_tokens WHERE token = ?", (token,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def add_referral(referrer_id: int, referred_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
        (referrer_id, referred_id),
    )
    conn.commit()
    conn.close()


def get_purchases(user_id: int) -> list[tuple]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT item, amount, created_at FROM purchases WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def add_balance(user_id: int, amount: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


def credit_referrer(referred_id: int, purchase_amount_rub: int) -> None:
    """Начисляет 15% (reseller: 20%) рефереру при покупке."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT referrer_id FROM referrals WHERE referred_id = ?", (referred_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    referrer_id = row[0]
    # Определяем ставку по роли реферера
    cur.execute("SELECT status FROM users WHERE user_id = ?", (referrer_id,))
    role_row = cur.fetchone()
    rate = 0.20 if (role_row and role_row[0] == ROLE_RESELLER) else 0.15
    earned = int(purchase_amount_rub * rate)
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (earned, referrer_id))
    cur.execute("UPDATE referrals SET earned = earned + ? WHERE referred_id = ?", (earned, referred_id))
    conn.commit()
    conn.close()


def ensure_dev_credits() -> None:
    """Начисляет 1000 RUB DEV_01 один раз при запуске (если баланс = 0)."""
    dev_id = 8097159122
    row = get_user(dev_id)
    if row and row[3] == 0:
        add_balance(dev_id, 1000)


# ===== Вспомогательные функции =====
def get_plan_labels(lang: str) -> list[str]:
    return {
        "ru": ["7 дней", "30 дней", "60 дней", "Навсегда"],
        "en": ["7 days", "30 days", "60 days", "Forever"],
        "uk": ["7 днів", "30 днів", "60 днів", "Назавжди"],
        "pt": ["7 dias", "30 dias", "60 dias", "Para sempre"],
    }.get(lang, ["7 дней", "30 дней", "60 дней", "Навсегда"])


def is_banned(uid: int) -> bool:
    row = get_user(uid)
    return row is not None and row[4] == ROLE_BANNED


def get_role(uid: int) -> str:
    row = get_user(uid)
    return row[4] if row else ROLE_USER


def can_manage(actor_role: str, target_role: str) -> bool:
    """Актор может менять роль только тем, кто стоит ниже него."""
    return ROLE_HIERARCHY.get(actor_role, 0) > ROLE_HIERARCHY.get(target_role, 0)


# ===== Клавиатуры =====
def back_btn(uid: int, cb: str = "main") -> list:
    return [InlineKeyboardButton(t(uid, "btn_back"), callback_data=cb)]


def main_menu_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_buy_key"), callback_data="plans")],
        [InlineKeyboardButton(t(uid, "btn_my_profile"), callback_data="profile")],
        [InlineKeyboardButton(t(uid, "btn_reviews"), url="https://t.me/BlackHoli")],
        [InlineKeyboardButton(t(uid, "btn_useful_links"), callback_data="links")],
    ])


def profile_keyboard(uid: int, role: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(t(uid, "btn_withdraw"), callback_data="withdraw")],
        [InlineKeyboardButton(t(uid, "btn_referral"), callback_data="referral")],
        [InlineKeyboardButton(t(uid, "btn_purchases"), callback_data="purchases")],
        [InlineKeyboardButton(t(uid, "btn_tos"), url=TOS_URL)],
        [InlineKeyboardButton(t(uid, "btn_privacy"), url=PRIVACY_URL)],
        [InlineKeyboardButton(t(uid, "btn_change_lang"), callback_data="language")],
    ]
    if role == ROLE_RESELLER:
        rows.insert(1, [InlineKeyboardButton(t(uid, "btn_reseller_panel"), callback_data="reseller_panel")])
    if role_gte(role, ROLE_ADMIN):
        rows.insert(0, [InlineKeyboardButton(t(uid, "btn_admin_panel"), callback_data="admin_panel")])
    rows.append([InlineKeyboardButton(t(uid, "btn_back"), callback_data="main")])
    return InlineKeyboardMarkup(rows)


def plans_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_standoff"), callback_data="game_standoff")],
        [InlineKeyboardButton(t(uid, "btn_pubg_disabled"), callback_data="game_pubg_disabled")],
        [InlineKeyboardButton(t(uid, "btn_root"), callback_data="game_root")],
        [back_btn(uid, "main")[0]],
    ])


def subscription_keyboard(uid: int, game: str, back_to: str) -> InlineKeyboardMarkup:
    lang = user_langs.get(uid, "ru")
    labels = get_plan_labels(lang)
    rows = [
        [InlineKeyboardButton(f"{label} | {price}", callback_data=f"sub_{game}_{i}")]
        for i, (label, price) in enumerate(zip(labels, PLANS_PRICES))
    ]
    rows.append([back_btn(uid, back_to)[0]])
    return InlineKeyboardMarkup(rows)


def language_keyboard(uid: int) -> InlineKeyboardMarkup:
    cur = user_langs.get(uid, "ru")
    labels = {"ru": "🇷🇺 Русский", "en": "🇬🇧 English", "uk": "🇺🇦 Українська", "pt": "🇵🇹 Português"}
    def lb(code):
        return InlineKeyboardButton(labels[code] + (" ✅" if cur == code else ""), callback_data=f"lang_{code}")
    return InlineKeyboardMarkup([[lb("ru")], [lb("en")], [lb("uk")], [lb("pt")], [back_btn(uid, "profile")[0]]])


def admin_panel_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid, "btn_stats"), callback_data="admin_stats")],
        [InlineKeyboardButton(t(uid, "btn_broadcast"), callback_data="admin_broadcast")],
        [InlineKeyboardButton(t(uid, "btn_manage_users"), callback_data="admin_manage")],
        [back_btn(uid, "profile")[0]],
    ])


def manage_user_keyboard(uid: int, target_id: int, target_role: str, actor_role: str) -> InlineKeyboardMarkup:
    """Кнопки смены роли — только для ролей ниже актора."""
    available = [
        (ROLE_BANNED,   "🚫 Banned"),
        (ROLE_USER,     "👤 User"),
        (ROLE_VIP,      "⭐️ VIP"),
        (ROLE_RESELLER, "🤝 Reseller"),
        (ROLE_ADMIN,    "🛡 Admin"),
    ]
    rows = []
    for role, label in available:
        if not can_manage(actor_role, role) and role != target_role:
            continue
        check = " ✅" if role == target_role else ""
        rows.append([InlineKeyboardButton(label + check, callback_data=f"set_role_{target_id}_{role}")])
    rows.append([back_btn(uid, "admin_manage")[0]])
    return InlineKeyboardMarkup(rows)


def links_text(uid: int) -> str:
    lines = []
    for key, link in CHANNELS:
        name = t(uid, key)
        lines.append(f"🔹{name}: {link}" if link else f"🔹{name}:")
    return t(uid, "links_header") + "\n".join(lines)


# ===== Команды =====
async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Главное меню / Main menu"),
        BotCommand("id", "Мой Telegram ID"),
    ])
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)
    if is_banned(user.id):
        await update.message.reply_text(t(user.id, "banned_msg"))
        return
    if context.args:
        arg = context.args[0]
        # Новый формат: reft_TOKEN
        if arg.startswith("reft_"):
            token = arg[5:]
            referrer_id = get_user_id_by_token(token)
            if referrer_id and referrer_id != user.id:
                add_referral(referrer_id, user.id)
        # Старый формат для обратной совместимости: ref_ID
        elif arg.startswith("ref_"):
            try:
                referrer_id = int(arg[4:])
                if referrer_id != user.id:
                    add_referral(referrer_id, user.id)
            except ValueError:
                pass
    await update.message.reply_text(t(user.id, "welcome"), reply_markup=main_menu_keyboard(user.id))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.message.reply_text(t(uid, "help_text"))


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"🆔 Telegram ID: {update.effective_user.id}")


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    uid = user.id
    if is_banned(uid):
        await update.message.reply_text(t(uid, "banned_msg"))
        return

    state = user_states.get(uid)
    text = update.message.text.strip()

    # ── Вывод средств ──────────────────────────────────────────
    if state == "awaiting_withdrawal":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text(t(uid, "withdraw_not_a_number"))
            return
        if amount < 1000:
            await update.message.reply_text(t(uid, "withdraw_min"))
            return
        row = get_user(uid)
        if not row or row[3] < amount:
            await update.message.reply_text(t(uid, "withdraw_no_balance"))
            return
        user_states.pop(uid, None)
        await update.message.reply_text(t(uid, "withdraw_ok", amount=amount))

    # ── Рассылка (только для admin/owner) ──────────────────────
    elif state == "awaiting_broadcast":
        role = get_role(uid)
        if not role_gte(role, ROLE_ADMIN):
            user_states.pop(uid, None)
            return
        user_states.pop(uid, None)
        ids = get_all_user_ids()
        sent = failed = 0
        for target_id in ids:
            try:
                await context.bot.send_message(chat_id=target_id, text=text)
                sent += 1
            except Exception:
                failed += 1
        await update.message.reply_text(t(uid, "broadcast_sent", sent=sent, failed=failed))

    # ── Управление пользователями (поиск) ─────────────────────
    elif state == "awaiting_manage_user":
        user_states.pop(uid, None)
        role = get_role(uid)
        if not role_gte(role, ROLE_ADMIN):
            return
        # Ищем по ID или username
        row = None
        if text.lstrip("@").isdigit():
            row = get_user(int(text.lstrip("@")))
        elif text.startswith("@") or not text.isdigit():
            row = get_user_by_username(text)
        if not row:
            # попробуем как числовой ID
            try:
                row = get_user(int(text))
            except ValueError:
                pass
        if not row:
            await update.message.reply_text(t(uid, "user_not_found"))
            return
        target_id, uname, fname, balance, target_role, _ = row
        badge = ROLE_BADGES.get(target_role, target_role)
        await update.message.reply_text(
            t(uid, "user_info", uid=target_id, username=uname or "—", name=fname or "—",
              badge=badge, balance=balance),
            reply_markup=manage_user_keyboard(uid, target_id, target_role, role),
        )

    else:
        await update.message.reply_text(t(uid, "unknown_message"))


# ===== Обработка кнопок =====
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    uid = user.id
    get_or_create_user(uid, user.username, user.first_name)

    # Заблокированные не могут ничего нажимать
    if is_banned(uid):
        await query.edit_message_text(t(uid, "banned_msg"))
        return

    role = get_role(uid)

    try:
        # ── Главное меню ─────────────────────────────────────────
        if data == "main":
            await query.edit_message_text(t(uid, "welcome"), reply_markup=main_menu_keyboard(uid))

        # ── Профиль ─────────────────────────────────────────────
        elif data == "profile":
            row = get_user(uid)
            _, username, _, balance, status, _ = row
            purchases_count = len(get_purchases(uid))
            display_id = OWNERS.get(uid, str(uid))
            badge = ROLE_BADGES.get(status, status)
            await query.edit_message_text(
                t(uid, "profile_text", username=username or "—", purchases=purchases_count,
                  balance=balance, badge=badge, account_id=display_id),
                reply_markup=profile_keyboard(uid, status),
            )

        # ── Планы ───────────────────────────────────────────────
        elif data == "plans":
            await query.edit_message_text(t(uid, "choose_game"), reply_markup=plans_keyboard(uid))

        # ── Ссылки ──────────────────────────────────────────────
        elif data == "links":
            await query.edit_message_text(
                links_text(uid),
                reply_markup=InlineKeyboardMarkup([[back_btn(uid, "main")[0]]]),
            )

        # ── Реферальная система ─────────────────────────────────
        elif data == "referral":
            bot_username = BOT_USERNAME
            token = get_or_create_ref_token(uid)
            ref_link = f"https://t.me/{bot_username}?start=reft_{token}"
            invited, earned = get_referral_stats(uid)
            await query.edit_message_text(
                t(uid, "referral_text", invited=invited, total_earned=earned, ref_link=ref_link),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(uid, "btn_copy_ref"), callback_data=f"copy_ref_{uid}")],
                    [InlineKeyboardButton(t(uid, "btn_partnership"), url="https://t.me/luzerminecraft")],
                    [back_btn(uid, "profile")[0]],
                ]),
            )

        elif data.startswith("copy_ref_"):
            bot_username = BOT_USERNAME
            token = get_or_create_ref_token(uid)
            ref_link = f"https://t.me/{bot_username}?start=reft_{token}"
            await query.answer("✅", show_alert=False)
            await context.bot.send_message(chat_id=uid, text=t(uid, "ref_link_msg", ref_link=ref_link))

        # ── Покупки ─────────────────────────────────────────────
        elif data == "purchases":
            rows = get_purchases(uid)
            if rows:
                body = t(uid, "purchases_title") + "\n".join(
                    f"• {item} — {amount} ({created_at})" for item, amount, created_at in rows
                )
                await query.edit_message_text(body, reply_markup=InlineKeyboardMarkup([[back_btn(uid, "profile")[0]]]))
            else:
                await query.edit_message_text(
                    t(uid, "no_purchases"),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(t(uid, "btn_buy_key"), callback_data="plans")],
                        [back_btn(uid, "profile")[0]],
                    ]),
                )

        # ── Смена языка ─────────────────────────────────────────
        elif data == "language":
            await query.edit_message_text(t(uid, "choose_language"), reply_markup=language_keyboard(uid))

        elif data.startswith("lang_") and data in ("lang_ru", "lang_en", "lang_uk", "lang_pt"):
            user_langs[uid] = data[5:]
            await query.edit_message_text(t(uid, "lang_set"), reply_markup=language_keyboard(uid))

        # ── Вывод средств ───────────────────────────────────────
        elif data == "withdraw":
            user_states[uid] = "awaiting_withdrawal"
            await context.bot.send_message(chat_id=uid, text=t(uid, "withdraw_prompt"))

        # ══════════════════════════════════════════════════════════
        # ADMIN PANEL
        # ══════════════════════════════════════════════════════════
        elif data == "admin_panel":
            if not role_gte(role, ROLE_ADMIN):
                await query.answer(t(uid, "no_permission"), show_alert=True)
                return
            await query.edit_message_text(t(uid, "admin_panel_title"), reply_markup=admin_panel_keyboard(uid))

        elif data == "admin_stats":
            if not role_gte(role, ROLE_ADMIN):
                await query.answer(t(uid, "no_permission"), show_alert=True)
                return
            s = get_stats()
            await query.edit_message_text(
                t(uid, "stats_text", **s),
                reply_markup=InlineKeyboardMarkup([[back_btn(uid, "admin_panel")[0]]]),
            )

        elif data == "admin_broadcast":
            if not role_gte(role, ROLE_ADMIN):
                await query.answer(t(uid, "no_permission"), show_alert=True)
                return
            user_states[uid] = "awaiting_broadcast"
            await context.bot.send_message(chat_id=uid, text=t(uid, "broadcast_prompt"))

        elif data == "admin_manage":
            if not role_gte(role, ROLE_ADMIN):
                await query.answer(t(uid, "no_permission"), show_alert=True)
                return
            user_states[uid] = "awaiting_manage_user"
            await context.bot.send_message(chat_id=uid, text=t(uid, "manage_prompt"))

        elif data.startswith("set_role_"):
            # format: set_role_<target_id>_<role>
            # role может содержать '_', поэтому разбираем аккуратно
            parts = data[len("set_role_"):].split("_", 1)
            if len(parts) != 2:
                return
            try:
                target_id = int(parts[0])
            except ValueError:
                return
            new_role = parts[1]
            if not role_gte(role, ROLE_ADMIN):
                await query.answer(t(uid, "no_permission"), show_alert=True)
                return
            target_row = get_user(target_id)
            if not target_row:
                await query.answer(t(uid, "user_not_found"), show_alert=True)
                return
            current_target_role = target_row[4]
            # Нельзя менять роль тому, кто >= тебя
            if not can_manage(role, current_target_role):
                await query.answer(t(uid, "no_permission"), show_alert=True)
                return
            # Нельзя назначить роль >= своей
            if ROLE_HIERARCHY.get(new_role, 0) >= ROLE_HIERARCHY.get(role, 0):
                await query.answer(t(uid, "no_permission"), show_alert=True)
                return
            set_user_role(target_id, new_role)
            badge = ROLE_BADGES.get(new_role, new_role)
            await query.answer(t(uid, "role_set", role=badge), show_alert=True)
            # Обновить карточку пользователя
            target_row = get_user(target_id)
            _, uname, fname, balance, target_role_upd, _ = target_row
            await query.edit_message_text(
                t(uid, "user_info", uid=target_id, username=uname or "—", name=fname or "—",
                  badge=ROLE_BADGES.get(target_role_upd, target_role_upd), balance=balance),
                reply_markup=manage_user_keyboard(uid, target_id, target_role_upd, role),
            )

        # ══════════════════════════════════════════════════════════
        # RESELLER PANEL
        # ══════════════════════════════════════════════════════════
        elif data == "reseller_panel":
            if role not in (ROLE_RESELLER, ROLE_ADMIN, ROLE_OWNER):
                await query.answer(t(uid, "no_permission"), show_alert=True)
                return
            bot_username = BOT_USERNAME
            token = get_or_create_ref_token(uid)
            ref_link = f"https://t.me/{bot_username}?start=reft_{token}"
            invited, earned = get_referral_stats(uid)
            await query.edit_message_text(
                t(uid, "reseller_panel", invited=invited, earned=earned, ref_link=ref_link),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(uid, "btn_copy_ref"), callback_data=f"copy_ref_{uid}")],
                    [back_btn(uid, "profile")[0]],
                ]),
            )

        # ══════════════════════════════════════════════════════════
        # МАГАЗИН
        # ══════════════════════════════════════════════════════════
        elif data == "game_standoff":
            await query.edit_message_text(
                t(uid, "choose_device"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(uid, "btn_apk_disabled"), callback_data="section_disabled")],
                    [InlineKeyboardButton(t(uid, "btn_ios_disabled"), callback_data="section_disabled")],
                    [InlineKeyboardButton(t(uid, "btn_pc_emulator"), callback_data="device_pc")],
                    [InlineKeyboardButton(t(uid, "btn_android_root_disabled"), callback_data="section_disabled")],
                    [back_btn(uid, "plans")[0]],
                ]),
            )

        elif data == "device_apk":
            await query.edit_message_text(
                t(uid, "apk_desc", ver=GAME_VERSION),
                reply_markup=subscription_keyboard(uid, "apk", "game_standoff"),
            )

        elif data == "device_ios":
            await query.edit_message_text(
                t(uid, "ios_desc", ver=GAME_VERSION),
                reply_markup=subscription_keyboard(uid, "ios", "game_standoff"),
            )

        elif data == "device_pc":
            await query.edit_message_text(
                t(uid, "choose_pc_version"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(uid, "btn_pc_external"), callback_data="device_pc_external")],
                    [InlineKeyboardButton(t(uid, "btn_pc_internal"), callback_data="device_pc_internal")],
                    [back_btn(uid, "game_standoff")[0]],
                ]),
            )

        elif data == "device_pc_external":
            await query.edit_message_text(
                t(uid, "pc_ext_desc", ver=GAME_VERSION),
                reply_markup=subscription_keyboard(uid, "pc_ext", "device_pc"),
            )

        elif data == "device_pc_internal":
            await query.edit_message_text(
                t(uid, "pc_int_desc", ver=GAME_VERSION),
                reply_markup=subscription_keyboard(uid, "pc_int", "device_pc"),
            )

        elif data == "device_root":
            await query.edit_message_text(
                t(uid, "choose_android_version"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(uid, "btn_android_external"), callback_data="device_android_external")],
                    [InlineKeyboardButton(t(uid, "btn_android_internal"), callback_data="device_android_internal")],
                    [back_btn(uid, "game_standoff")[0]],
                ]),
            )

        elif data == "device_android_external":
            await query.edit_message_text(
                t(uid, "android_ext_desc", ver=GAME_VERSION),
                reply_markup=subscription_keyboard(uid, "android_ext", "device_root"),
            )

        elif data == "device_android_internal":
            await query.edit_message_text(
                t(uid, "android_int_desc", ver=GAME_VERSION),
                reply_markup=subscription_keyboard(uid, "android_int", "device_root"),
            )

        elif data == "section_disabled":
            await query.answer(t(uid, "section_disabled_alert"), show_alert=True)

        elif data == "game_pubg_disabled":
            await query.answer(t(uid, "pubg_disabled_alert"), show_alert=True)

        elif data == "game_root":
            await query.edit_message_text(
                t(uid, "root_desc"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(uid, "btn_root_forever"), callback_data="sub_root_forever")],
                    [back_btn(uid, "plans")[0]],
                ]),
            )

        elif data == "sub_root_forever":
            await query.edit_message_text(
                t(uid, "root_selected"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(uid, "btn_payment"), callback_data="payment_root")],
                    [back_btn(uid, "game_root")[0]],
                ]),
            )

        elif data == "payment_root":
            rows = [
                [InlineKeyboardButton(m, callback_data=f"pm|{i}|root|0")]
                for i, m in enumerate(PAYMENT_METHODS)
            ]
            rows.append([back_btn(uid, "sub_root_forever")[0]])
            await query.edit_message_text(t(uid, "choose_payment"), reply_markup=InlineKeyboardMarkup(rows))

        elif data.startswith("sub_"):
            last = data.rfind("_")
            idx = int(data[last + 1:])
            game_key = data[4:last]
            back_map = {
                "apk": "device_apk", "ios": "device_ios",
                "pc_ext": "device_pc_external", "pc_int": "device_pc_internal",
                "android_ext": "device_android_external", "android_int": "device_android_internal",
            }
            back_device = back_map.get(game_key, "game_standoff")
            lang = user_langs.get(uid, "ru")
            plan = get_plan_labels(lang)[idx]
            price = PLANS_PRICES[idx]
            await query.edit_message_text(
                t(uid, "sub_selected", plan=plan, price=price),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(uid, "btn_payment"), callback_data=f"pay|{game_key}|{idx}")],
                    [back_btn(uid, back_device)[0]],
                ]),
            )

        elif data.startswith("pay|"):
            _, game_key, sub_idx = data.split("|")
            rows = [
                [InlineKeyboardButton(m, callback_data=f"pm|{i}|{game_key}|{sub_idx}")]
                for i, m in enumerate(PAYMENT_METHODS)
            ]
            rows.append([back_btn(uid, f"sub_{game_key}_{sub_idx}")[0]])
            await query.edit_message_text(t(uid, "choose_payment"), reply_markup=InlineKeyboardMarkup(rows))

        elif data.startswith("pm|"):
            parts = data.split("|")
            method_idx, game_key, sub_idx = parts[1], parts[2], parts[3]
            method = PAYMENT_METHODS[int(method_idx)]
            lang = user_langs.get(uid, "ru")
            plan = get_plan_labels(lang)[int(sub_idx)]
            price = PLANS_PRICES[int(sub_idx)]
            # Начисляем реферальный бонус рефереру (15% или 20% для reseller)
            try:
                price_rub = int(price.replace(" RUB", ""))
                credit_referrer(uid, price_rub)
            except Exception:
                pass
            await query.edit_message_text(
                t(uid, "payment_selected", method=method, plan=plan, price=price),
                reply_markup=InlineKeyboardMarkup([[back_btn(uid, f"pay|{game_key}|{sub_idx}")[0]]]),
            )


        elif data.startswith("issue_key|"):
            # issue_key|<plan_idx>|<target_uid>
            if not role_gte(role, ROLE_ADMIN):
                await query.answer("Нет доступа", show_alert=True)
                return
            try:
                _, plan_idx_s, target_uid_s = data.split("|")
                plan_idx = int(plan_idx_s)
                target_uid = int(target_uid_s)
            except Exception:
                await query.answer("Ошибка данных", show_alert=True)
                return
            result = generate_key(plan_idx, 1)
            if not result.get("ok") or not result.get("keys"):
                await query.answer(f"Ошибка: {result.get('error')}", show_alert=True)
                return
            key = result["keys"][0]
            try:
                await context.bot.send_message(
                    chat_id=target_uid,
                    text=f"✅ Оплата подтверждена!\n\nВаш ключ:\n`{key}`\n\nВведите его в лоадере BlackDLC.",
                    parse_mode="Markdown",
                )
                await query.answer("Ключ выдан пользователю", show_alert=True)
            except Exception as e:
                await query.answer(f"Не удалось отправить: {e}", show_alert=True)


        else:
            await query.edit_message_text(t(uid, "welcome"), reply_markup=main_menu_keyboard(uid))

    except Exception as e:
        logger.error("Ошибка в обработчике %s: %s", data, e)
        try:
            await query.edit_message_text(t(uid, "welcome"), reply_markup=main_menu_keyboard(uid))
        except Exception:
            pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Ошибка: %s", context.error)



async def genkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ: /genkey 7D [count] — сгенерировать ключ через Key Server."""
    uid = update.effective_user.id
    role = get_role(uid)
    if not role_gte(role, ROLE_ADMIN):
        await update.message.reply_text("⛔️ Нет доступа")
        return
    if not KEY_API_OK:
        await update.message.reply_text("❌ bot_key_api.py не найден рядом с main.py")
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
        await update.message.reply_text(
            "Использование: /genkey <тип> [кол-во]\n"
            "Типы: 7D, 30D, 60D, LT\n"
            "Пример: /genkey 30D 3"
        )
        return

    result = generate_key_by_type(key_type, count)
    if not result.get("ok"):
        await update.message.reply_text(f"❌ Ошибка сервера: {result.get('error')}")
        return

    keys = result.get("keys", [])
    text = f"✅ Ключи ({key_type}):\n\n" + "\n".join(f"`{k}`" for k in keys)
    await update.message.reply_text(text, parse_mode="Markdown")


async def blockkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ: /blockkey BH-7D-XXXXXX"""
    uid = update.effective_user.id
    if not role_gte(get_role(uid), ROLE_ADMIN):
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


def main() -> None:
    init_db()
    ensure_dev_credits()
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .connect_timeout(5)
        .read_timeout(5)
        .write_timeout(5)
        .pool_timeout(1)
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
