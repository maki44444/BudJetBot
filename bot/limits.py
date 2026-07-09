from decimal import Decimal, InvalidOperation

from telegram import Update
from telegram.ext import ContextTypes

import db
from . import access, keyboards, common


async def cmd_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /limit Продукты 20000")
        return
    *name_parts, amount_str = context.args
    name = " ".join(name_parts)
    try:
        amount = Decimal(amount_str.replace(",", "."))
    except InvalidOperation:
        await update.message.reply_text("Сумма должна быть числом. Пример: /limit Продукты 20000")
        return
    if amount < 0:
        await update.message.reply_text("Сумма должна быть 0 (снять лимит) или больше.")
        return

    uid = update.effective_user.id
    category = await db.find_category_by_name(uid, name)
    if category is None:
        await update.message.reply_text(f"Категория «{name}» не найдена. Список: /categories")
        return

    if amount == 0:
        await db.delete_budget(uid, category["id"])
        await update.message.reply_text(f"Лимит для {category['icon']} {category['name']} снят.")
        return

    await db.set_budget(uid, category["id"], amount)
    await update.message.reply_text(
        f"Лимит для {category['icon']} {category['name']}: {common.fmt_amount(amount)}₽/мес"
    )


async def cmd_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    uid = update.effective_user.id
    start, end = common.month_range()
    progress = await db.get_budget_progress(uid, start, end)
    if not progress:
        await update.message.reply_text(
            "Лимиты не заданы. Пример: /limit Продукты 20000",
            reply_markup=keyboards.main_keyboard(),
        )
        return
    lines = ["Лимиты за месяц:"]
    for p in progress:
        pct = int(p["spent"] / p["budget"] * 100) if p["budget"] else 0
        marker = "🔴" if pct >= 100 else "🟡" if pct >= 80 else "🟢"
        lines.append(
            f"{marker} {p['icon']} {p['name']}: "
            f"{common.fmt_amount(p['spent'])} / {common.fmt_amount(p['budget'])}₽ ({pct}%)"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=keyboards.main_keyboard())
