"""
Ежемесячный пересчёт автолимитов (1-го числа, 9:00 МСК).
Лимиты в режиме 'auto' тянутся к текущему темпу трат категории
(без разовых ⚡), но не быстрее ±10% за месяц. Все изменения
приходят пользователю сводкой — молчаливых правок нет.
"""
import logging
from decimal import Decimal

from telegram.ext import ContextTypes

import db
import smartlimits
from . import access, common

logger = logging.getLogger(__name__)


async def recalc_auto_limits(context: ContextTypes.DEFAULT_TYPE):
    for user in await db.get_users_with_budgets():
        uid = user["telegram_id"]
        if not user["is_allowed"] and uid != access.ADMIN_ID:
            continue
        try:
            auto_budgets = [b for b in await db.get_budgets(uid) if b["mode"] == "auto"]
            if not auto_budgets:
                continue
            rates = {r["category_id"]: r["monthly_est"] for r in await db.get_spend_rates(uid)}
            # молодой учёт: оценки ещё грубые — даём лимитам прыгнуть сразу к среднему
            snap = await db.get_tracking_days(uid) < smartlimits.YOUNG_DATA_DAYS
            lines = []
            for b in auto_budgets:
                current = float(b["amount"])
                target = rates.get(b["category_id"], 0.0)
                new = smartlimits.next_auto_limit(current, target, snap=snap)
                if new <= 0 or new == smartlimits.nice_round(current):
                    continue
                await db.set_budget(uid, b["category_id"], Decimal(new), mode="auto")
                lines.append(
                    f"{b['icon']} {b['name']}: {common.fmt_amount(current)} → {common.fmt_amount(new)} ₽"
                )
            if lines:
                await context.bot.send_message(
                    uid,
                    f"🔄 Автолимиты на {common.month_label()} пересчитаны по твоим тратам:\n\n"
                    + "\n".join(lines)
                    + "\n\nЗакрепить лимит вручную можно на сайте (✋) или командой /limit.",
                )
        except Exception:
            logger.exception("Пересчёт автолимитов не удался для пользователя %s", uid)
