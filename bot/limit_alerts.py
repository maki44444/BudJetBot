"""
Ежедневная проверка лимитов (12:00 МСК). Два вида предупреждений,
каждое шлётся один раз за месяц на категорию:
- exceeded: лимит уже превышен
- forecast: лимит ещё не превышен, но при текущем темпе будет превышен к концу месяца
"""
import logging
from datetime import datetime

from telegram.ext import ContextTypes

import db
from . import access, common

logger = logging.getLogger(__name__)

MIN_DAYS_FOR_FORECAST = 5  # первые дни месяца прогноз слишком шумный


async def check_limits(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(common.MOSCOW)
    start, end = common.month_range()
    days_in_month = (end - start).days
    days_elapsed = now.day
    month_key = f"{now.year:04d}-{now.month:02d}"

    for user in await db.get_users_with_budgets():
        uid = user["telegram_id"]
        if not user["is_allowed"] and uid != access.ADMIN_ID:
            continue
        try:
            alerts = []  # (category_id, kind, строка сообщения)
            for r in await db.get_budget_progress(uid, start, end):
                spent, budget = float(r["spent"]), float(r["budget"])
                if budget <= 0:
                    continue
                if spent >= budget:
                    kind = "exceeded"
                    line = (
                        f"🔴 {r['icon']} {r['name']}: лимит превышен — "
                        f"{common.fmt_amount(spent)} из {common.fmt_amount(budget)} ₽"
                    )
                elif days_elapsed >= MIN_DAYS_FOR_FORECAST:
                    projection = spent / days_elapsed * days_in_month
                    if projection <= budget:
                        continue
                    kind = "forecast"
                    pct = round(spent / budget * 100)
                    line = (
                        f"⚠️ {r['icon']} {r['name']}: потрачено {common.fmt_amount(spent)} "
                        f"из {common.fmt_amount(budget)} ₽ ({pct}%), при текущем темпе "
                        f"к концу месяца будет ~{common.fmt_amount(projection)} ₽"
                    )
                else:
                    continue
                if not await db.was_limit_alert_sent(uid, r["category_id"], month_key, kind):
                    alerts.append((r["category_id"], kind, line))

            if not alerts:
                continue
            text = "Предупреждение по лимитам:\n\n" + "\n".join(line for _, _, line in alerts)
            await context.bot.send_message(uid, text)
            for category_id, kind, _ in alerts:
                await db.mark_limit_alert_sent(uid, category_id, month_key, kind)
        except Exception:
            logger.exception("Проверка лимитов не удалась для пользователя %s", uid)
