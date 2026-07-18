import logging
import os
from datetime import time as dtime

from telegram import BotCommand, BotCommandScopeChat, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

import ai
from . import access, keyboards, common, transactions, categories, limits, limit_alerts, auto_limits, ai_review, reminders, admin

BOT_TOKEN = os.environ["BOT_TOKEN"]
SITE_URL = os.environ.get("SITE_URL", "")
REMINDER_HOUR = int(os.environ.get("REMINDER_HOUR", "21"))

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

USER_COMMANDS = [
    BotCommand("start", "Начать / показать меню"),
    BotCommand("today", "Траты и доходы за сегодня"),
    BotCommand("day", "Записи за день, напр. /day 05.07"),
    BotCommand("month", "Разбивка по категориям за месяц"),
    BotCommand("undo", "Отменить последнюю запись"),
    BotCommand("categories", "Список категорий"),
    BotCommand("addcategory", "Добавить категорию"),
    BotCommand("limit", "Задать лимит, напр. /limit Продукты 20000"),
    BotCommand("limits", "Прогресс по лимитам"),
    BotCommand("review", "ИИ-разбор трат за месяц"),
]

ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand("grant", "Выдать доступ пользователю"),
    BotCommand("revoke", "Отозвать доступ"),
    BotCommand("users", "Список пользователей с доступом"),
]


async def setup_commands(app: Application) -> None:
    await app.bot.set_my_commands(USER_COMMANDS)
    if access.ADMIN_ID:
        await app.bot.set_my_commands(
            ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=access.ADMIN_ID)
        )

HELP_TEXT = (
    "Кнопки:\n"
    "  Сегодня — траты и доходы за сегодня\n"
    "  За месяц — разбивка по категориям + лимиты\n"
    "  Категории — список категорий\n"
    "  Лимиты — прогресс по лимитам\n"
    "  Отменить последнюю — удалить последнюю ручную запись\n"
    "  Сайт — подробная аналитика в браузере\n\n"
    "Быстрый ввод:\n"
    "  350 такси — расход 350₽ с описанием «такси»\n"
    "  +50000 зарплата — доход 50000₽\n"
    "  05.07 350 такси — запись задним числом (на 5 июля)\n"
    "  Категорию бот угадывает по описанию сам — если ошибся, жми 🔁\n\n"
    "Команды:\n"
    "  /day 05.07 — записи за конкретный день\n"
    "  /addcategory 🎮 Хобби — добавить категорию\n"
    "  /limit Продукты 20000 — задать месячный лимит\n"
    "  /limit Продукты 0 — снять лимит\n"
    "  /review — ИИ-разбор трат за месяц (/review прошлый)\n\n"
    f"Каждый вечер в {REMINDER_HOUR}:00 МСК бот напомнит, если за день не было ни одной записи."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    text = "Привет! Я помогу вести личный бюджет.\n\n" + HELP_TEXT
    await update.message.reply_text(text, reply_markup=keyboards.main_keyboard())
    if SITE_URL:
        await update.message.reply_text(
            "Также доступен сайт с историей и графиками:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Открыть сайт", url=SITE_URL)]]),
        )


async def route_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    text = update.message.text
    if text == "Сегодня":
        await transactions.cmd_today(update, context)
    elif text == "За месяц":
        await transactions.cmd_month(update, context)
    elif text == "Категории":
        await categories.cmd_categories(update, context)
    elif text == "Лимиты":
        await limits.cmd_limits(update, context)
    elif text == "Отменить последнюю":
        await transactions.cmd_undo(update, context)
    elif text == "Помощь":
        await update.message.reply_text(HELP_TEXT, reply_markup=keyboards.main_keyboard())
    elif text == "Сайт" and SITE_URL:
        await update.message.reply_text(
            "Подробная аналитика: графики, история, лимиты и настройки:",
            reply_markup=keyboards.site_keyboard(),
        )
    else:
        handled = await transactions.handle_quick_entry(update, context)
        if not handled:
            await update.message.reply_text(
                "Не понял. Чтобы внести трату, напиши сумму, например: 350 такси",
                reply_markup=keyboards.main_keyboard(),
            )


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    private = filters.ChatType.PRIVATE

    app.add_handler(CommandHandler("start", cmd_start, filters=private))
    app.add_handler(CommandHandler("today", transactions.cmd_today, filters=private))
    app.add_handler(CommandHandler("day", transactions.cmd_day, filters=private))
    app.add_handler(CommandHandler("month", transactions.cmd_month, filters=private))
    app.add_handler(CommandHandler("undo", transactions.cmd_undo, filters=private))
    app.add_handler(CommandHandler("categories", categories.cmd_categories, filters=private))
    app.add_handler(CommandHandler("addcategory", categories.cmd_addcategory, filters=private))
    app.add_handler(CommandHandler("limit", limits.cmd_limit, filters=private))
    app.add_handler(CommandHandler("limits", limits.cmd_limits, filters=private))
    app.add_handler(CommandHandler("review", ai_review.cmd_review, filters=private))
    app.add_handler(CommandHandler("grant", admin.cmd_grant, filters=private))
    app.add_handler(CommandHandler("revoke", admin.cmd_revoke, filters=private))
    app.add_handler(CommandHandler("users", admin.cmd_users, filters=private))

    app.add_handler(CallbackQueryHandler(transactions.handle_category_choice, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(transactions.handle_change_request, pattern=r"^chg:"))
    app.add_handler(CallbackQueryHandler(transactions.handle_change_choice, pattern=r"^chgc:"))
    app.add_handler(CallbackQueryHandler(transactions.handle_oneoff, pattern=r"^oneoff:"))
    app.add_handler(CallbackQueryHandler(transactions.handle_delete_request, pattern=r"^delq:"))
    app.add_handler(CallbackQueryHandler(transactions.handle_undo_confirm, pattern=r"^undo:"))
    app.add_handler(CallbackQueryHandler(transactions.handle_cancel, pattern=r"^cancel$"))
    app.add_handler(CallbackQueryHandler(reminders.handle_add_hint, pattern=r"^reminder_add$"))
    app.add_handler(CallbackQueryHandler(reminders.handle_no_spend, pattern=r"^reminder_nospend$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & private, route_text))

    app.job_queue.run_daily(
        reminders.evening_reminder, time=dtime(REMINDER_HOUR, 0, 0, tzinfo=common.MOSCOW)
    )
    app.job_queue.run_daily(
        limit_alerts.check_limits, time=dtime(12, 0, 0, tzinfo=common.MOSCOW)
    )
    app.job_queue.run_monthly(
        auto_limits.recalc_auto_limits, when=dtime(9, 0, 0, tzinfo=common.MOSCOW), day=1
    )
    app.job_queue.run_monthly(
        ai_review.monthly_review_job, when=dtime(9, 30, 0, tzinfo=common.MOSCOW), day=1
    )
    logger.info(
        "Bot configured, evening reminder at %02d:00 MSK, limit check at 12:00 MSK, "
        "auto-limits recalc on 1st at 09:00 MSK, AI review on 1st at 09:30 MSK", REMINDER_HOUR
    )
    if ai.enabled():
        logger.info("ИИ включён: модель %s через %s", ai.AI_MODEL, ai.AI_BASE_URL)
    else:
        logger.info("ИИ выключен — переменная AI_API_KEY не задана")
    return app
