import logging
from datetime import datetime

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes

import db
from . import common

logger = logging.getLogger(__name__)

_REMINDER_KEYBOARD = InlineKeyboardMarkup([[
    InlineKeyboardButton("Добавить трату", callback_data="reminder_add"),
    InlineKeyboardButton("Сегодня трат не было", callback_data="reminder_nospend"),
]])


async def evening_reminder(context: ContextTypes.DEFAULT_TYPE):
    start, end = common.today_range()
    today = datetime.now(common.MOSCOW).date()
    for uid in await db.get_reminder_candidates():
        try:
            if await db.has_transactions_between(uid, start, end):
                continue
            if await db.has_no_spend_checkin(uid, today):
                continue
            await context.bot.send_message(
                uid,
                "Сегодня ты ещё не вносил(а) траты. Что произошло?",
                reply_markup=_REMINDER_KEYBOARD,
            )
        except Exception:
            logger.exception("Не удалось отправить напоминание пользователю %s", uid)


async def handle_add_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Просто напиши сумму, например: 350 такси")


async def handle_no_spend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    today = datetime.now(common.MOSCOW).date()
    await db.mark_no_spend_day(uid, today)
    await query.edit_message_text("Записал — сегодня трат не было 👍")
