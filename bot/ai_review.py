"""
ИИ-разбор месяца: /review — по запросу (текущий месяц, «/review прошлый» —
прошедший), плюс автоматически 1-го числа за закончившийся месяц.
Модель получает только агрегированные цифры из БД — не сырые данные.
"""
import logging
from datetime import datetime

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

import ai
import db
from . import access, common, keyboards

logger = logging.getLogger(__name__)

NO_AI_TEXT = (
    "ИИ-разбор не настроен. Нужен ключ API — бесплатный можно получить на openrouter.ai, "
    "затем добавить переменную AI_API_KEY в Railway."
)


async def _collect_data(uid: int, start: datetime, end: datetime) -> str | None:
    """Готовит агрегаты за период для модели; None — если данных нет."""
    totals = await db.get_totals(uid, start, end)
    if not totals["expense"] and not totals["income"]:
        return None

    lines = []
    now = datetime.now(common.MOSCOW)
    if start <= now < end:
        days_in = (end - start).days
        elapsed = (now - start).days + 1
        lines.append(f"Месяц ещё не закончился: прошло {elapsed} из {days_in} дней.")
    lines += [
        f"Итого расходы: {common.fmt_amount(totals['expense'])} ₽",
        f"  из них помечены как разовые (крупные, нетипичные): {common.fmt_amount(totals['expense_oneoff'])} ₽",
        f"Итого доходы: {common.fmt_amount(totals['income'])} ₽",
    ]

    py, pm = common.prev_month(start.year, start.month)
    p_start, p_end = common.month_range_for(py, pm)
    prev = {r["category_id"]: r["total"] for r in await db.get_category_breakdown(uid, p_start, p_end)}
    breakdown = await db.get_category_breakdown(uid, start, end)
    if breakdown:
        lines.append("\nРасходы по категориям (в скобках — прошлый месяц):")
        for row in breakdown:
            prev_val = prev.get(row["category_id"])
            prev_note = f" (было {common.fmt_amount(prev_val)} ₽)" if prev_val else ""
            lines.append(f"  {row['name']}: {common.fmt_amount(row['total'])} ₽{prev_note}")

    top = await db.get_top_expenses(uid, start, end)
    if top:
        lines.append("\nКрупнейшие траты:")
        for t in top:
            desc = t["description"] or t["category_name"] or "без описания"
            oneoff = " (разовая)" if t["is_oneoff"] else ""
            day = t["occurred_at"].astimezone(common.MOSCOW).strftime("%d.%m")
            lines.append(f"  {common.fmt_amount(t['amount'])} ₽ — {desc}, {day}{oneoff}")

    progress = await db.get_budget_progress(uid, start, end)
    if progress:
        lines.append("\nЛимиты (потрачено / лимит на месяц):")
        for p in progress:
            lines.append(
                f"  {p['name']}: {common.fmt_amount(p['spent'])} / {common.fmt_amount(p['budget'])} ₽"
            )
    return "\n".join(lines)


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    if not ai.enabled():
        await update.message.reply_text(NO_AI_TEXT)
        return
    uid = update.effective_user.id
    now = datetime.now(common.MOSCOW)
    year, month = now.year, now.month
    if context.args and context.args[0].lower().startswith("прошл"):
        year, month = common.prev_month(year, month)
    start, end = common.month_range_for(year, month)
    label = common.month_label_for(year, month)

    data = await _collect_data(uid, start, end)
    if data is None:
        await update.message.reply_text(f"За {label} записей нет — разбирать нечего.")
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    text = await ai.monthly_review(label, data)
    if not text:
        await update.message.reply_text("Не получилось связаться с ИИ — попробуй ещё раз чуть позже.")
        return
    await update.message.reply_text(
        f"🧠 Разбор за {label}:\n\n{text}",
        reply_markup=keyboards.site_keyboard() or keyboards.main_keyboard(),
    )


async def monthly_review_job(context: ContextTypes.DEFAULT_TYPE):
    """1-го числа — разбор закончившегося месяца каждому пользователю с данными."""
    if not ai.enabled():
        return
    now = datetime.now(common.MOSCOW)
    year, month = common.prev_month(now.year, now.month)
    start, end = common.month_range_for(year, month)
    label = common.month_label_for(year, month)

    uids = [u["id"] for u in await db.get_allowed_users()]
    if access.ADMIN_ID and access.ADMIN_ID not in uids:
        uids.append(access.ADMIN_ID)
    for uid in uids:
        try:
            data = await _collect_data(uid, start, end)
            if data is None:
                continue
            text = await ai.monthly_review(label, data)
            if not text:
                continue
            await context.bot.send_message(uid, f"🧠 Разбор за {label}:\n\n{text}")
        except Exception:
            logger.exception("Месячный ИИ-разбор не удался для %s", uid)
