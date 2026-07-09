import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from telegram import Update
from telegram.ext import ContextTypes

import db
from . import access, keyboards, common

_LEADING_AMOUNT_RE = re.compile(r"^([+-]?\d+(?:[.,]\d{1,2})?)\s*(.*)$")
_TRAILING_AMOUNT_RE = re.compile(r"^(.+?)\s+([+-]?\d+(?:[.,]\d{1,2})?)$")
_DATE_PREFIX_RE = re.compile(r"^(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s+(.*)$")


def _extract_amount(text: str) -> tuple[str, str] | None:
    """Ищет сумму в сообщении — поддерживает оба порядка: "350 такси" и "такси 350"."""
    match = _LEADING_AMOUNT_RE.match(text)
    if match:
        return match.group(1), match.group(2)
    match = _TRAILING_AMOUNT_RE.match(text)
    if match:
        return match.group(2), match.group(1)
    return None


def _extract_date_prefix(text: str):
    """Ищет дату в начале сообщения (05.07 350 такси — запись задним числом).
    Дату принимаем, только если после неё остаётся распознаваемая сумма —
    иначе "5.07 такси" превратился бы в дату вместо суммы 5.07₽."""
    match = _DATE_PREFIX_RE.match(text)
    if not match:
        return None
    day = common.parse_date_arg(match.group(1))
    if day is None:
        return None
    rest = match.group(2)
    if not _extract_amount(rest):
        return None
    return day, rest


async def handle_quick_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Пытается распознать сообщение как быстрый ввод траты/дохода. Возвращает True, если распознал."""
    text = (update.message.text or "").strip()

    occurred_date = None
    date_prefix = _extract_date_prefix(text)
    if date_prefix:
        occurred_date, text = date_prefix

    extracted = _extract_amount(text)
    if not extracted:
        return False
    raw_amount, description = extracted
    is_income = raw_amount.startswith("+")
    try:
        amount = Decimal(raw_amount.lstrip("+-").replace(",", "."))
    except InvalidOperation:
        return False
    if amount <= 0:
        return False

    type_ = "income" if is_income else "expense"
    uid = update.effective_user.id
    categories = await db.get_categories(uid, type_)
    if not categories:
        await update.message.reply_text(
            "Нет категорий для этого типа. Добавь: /addcategory 🎮 Хобби"
        )
        return True

    context.user_data["pending_tx"] = {
        "amount": amount,
        "type": type_,
        "description": description.strip() or None,
        "occurred_date": occurred_date,
    }
    kind = "доход" if is_income else "трата"
    date_note = f" за {occurred_date.strftime('%d.%m.%Y')}" if occurred_date else ""
    await update.message.reply_text(
        f"{common.fmt_amount(amount)}₽ ({kind}){date_note} — выбери категорию:",
        reply_markup=keyboards.category_keyboard(categories),
    )
    return True


async def handle_category_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = context.user_data.pop("pending_tx", None)
    if not pending:
        await query.edit_message_text("Сессия истекла, начни заново — просто напиши сумму.")
        return
    category_id = int(query.data.split(":", 1)[1])
    category = await db.get_category(category_id)
    if not category:
        await query.edit_message_text("Категория не найдена.")
        return
    uid = update.effective_user.id
    occurred_date = pending.get("occurred_date")
    if occurred_date:
        occurred_at = common.MOSCOW.localize(
            datetime.combine(occurred_date, datetime.now(common.MOSCOW).time())
        )
    else:
        occurred_at = datetime.now(common.MOSCOW)
    await db.add_transaction(
        uid, category_id, pending["type"], pending["amount"], pending["description"], occurred_at,
    )
    sign = "+" if pending["type"] == "income" else "-"
    date_note = f" ({occurred_date.strftime('%d.%m.%Y')})" if occurred_date else ""
    await query.edit_message_text(
        f"✅ {sign}{common.fmt_amount(pending['amount'])}₽ — {category['icon']} {category['name']}{date_note}"
    )


async def _reply_day(update: Update, uid: int, day, label: str):
    start, end = common.day_range(day)
    txs = await db.get_transactions_between(uid, start, end)
    if not txs:
        await update.message.reply_text(
            f"{label}: трат и доходов не было.", reply_markup=keyboards.main_keyboard()
        )
        return
    lines = [f"{label}:"]
    total_expense = Decimal(0)
    total_income = Decimal(0)
    for t in txs:
        icon = t["category_icon"] or "💰"
        name = t["category_name"] or "Без категории"
        sign = "+" if t["type"] == "income" else "-"
        desc = f" ({t['description']})" if t["description"] else ""
        lines.append(f"  {sign}{common.fmt_amount(t['amount'])}₽ {icon} {name}{desc}")
        if t["type"] == "income":
            total_income += t["amount"]
        else:
            total_expense += t["amount"]
    lines.append(f"\nРасходы: {common.fmt_amount(total_expense)}₽")
    if total_income:
        lines.append(f"Доходы: {common.fmt_amount(total_income)}₽")
    await update.message.reply_text("\n".join(lines), reply_markup=keyboards.main_keyboard())


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    today = datetime.now(common.MOSCOW).date()
    await _reply_day(update, update.effective_user.id, today, "Сегодня")


async def cmd_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text("Использование: /day 05.07 или /day 05.07.2026")
        return
    day = common.parse_date_arg(context.args[0])
    if day is None:
        await update.message.reply_text("Не понял дату. Формат: DD.MM или DD.MM.YYYY")
        return
    await _reply_day(update, update.effective_user.id, day, day.strftime("%d.%m.%Y"))


async def cmd_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    uid = update.effective_user.id
    start, end = common.month_range()
    breakdown = await db.get_category_breakdown(uid, start, end, "expense")
    income = await db.get_category_breakdown(uid, start, end, "income")

    lines = [f"Расходы за {common.month_label()}:"]
    total = Decimal(0)
    if not breakdown:
        lines.append("  пока пусто")
    for row in breakdown:
        lines.append(f"  {row['icon']} {row['name']} — {common.fmt_amount(row['total'])}₽")
        total += row["total"]
    lines.append(f"\nИтого расходов: {common.fmt_amount(total)}₽")
    if income:
        total_income = sum((row["total"] for row in income), Decimal(0))
        lines.append(f"Доходы: {common.fmt_amount(total_income)}₽")

    progress = await db.get_budget_progress(uid, start, end)
    if progress:
        lines.append("\nЛимиты:")
        for p in progress:
            pct = int(p["spent"] / p["budget"] * 100) if p["budget"] else 0
            marker = "🔴" if pct >= 100 else "🟡" if pct >= 80 else "🟢"
            lines.append(
                f"  {marker} {p['icon']} {p['name']}: "
                f"{common.fmt_amount(p['spent'])} / {common.fmt_amount(p['budget'])}₽ ({pct}%)"
            )
    await update.message.reply_text("\n".join(lines), reply_markup=keyboards.main_keyboard())


async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    uid = update.effective_user.id
    tx = await db.get_last_manual_transaction(uid)
    if not tx:
        await update.message.reply_text(
            "Нечего отменять — ручных записей нет.", reply_markup=keyboards.main_keyboard()
        )
        return
    category = await db.get_category(tx["category_id"]) if tx["category_id"] else None
    label = f"{category['icon']} {category['name']}" if category else "без категории"
    sign = "+" if tx["type"] == "income" else "-"
    desc = f" ({tx['description']})" if tx["description"] else ""
    await update.message.reply_text(
        f"Удалить последнюю запись: {sign}{common.fmt_amount(tx['amount'])}₽ — {label}{desc}?",
        reply_markup=keyboards.confirm_keyboard(f"undo:{tx['id']}"),
    )


async def handle_undo_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tx_id = int(query.data.split(":", 1)[1])
    uid = update.effective_user.id
    deleted = await db.delete_transaction(uid, tx_id)
    await query.edit_message_text("Запись удалена." if deleted else "Уже удалено или не найдено.")


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отменено.")
