"""
Цели накопления — виртуальная копилка: пополнение НЕ создаёт транзакцию и не
влияет на расходы/лимиты/прогнозы, это просто отметка «отложил в сторону».
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
from . import access, common, keyboards

_NO_DATE = object()  # сентинел «дату не указывали» — отличать от «снять дату»

# Отделяет ведущий эмодзи/символ от остального текста, даже если между ними нет
# пробела (частый случай на телефоне: клавиатура вставляет эмодзи без пробела).
_ICON_PREFIX_RE = re.compile(r"^([^\w\s]+)\s*(.*)$", re.UNICODE)


def _progress_bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "▰" * filled + "▱" * (width - filled)


def _goal_line(g: dict) -> str:
    saved, target = g["saved"], g["target_amount"]
    pct = float(saved / target * 100) if target else 0.0
    title = f"{g['icon']} {g['name']}"
    if g["is_completed"]:
        title = f"🎉 {title} — готово!"
    lines = [
        title,
        f"{_progress_bar(pct)} {pct:.0f}%",
        f"{common.fmt_amount(saved)} / {common.fmt_amount(target)} ₽",
    ]
    if not g["is_completed"] and g["target_date"]:
        today = datetime.now(common.MOSCOW).date()
        days_left = (g["target_date"] - today).days
        remaining = target - saved
        date_label = g["target_date"].strftime("%d.%m.%Y")
        if days_left > 0 and remaining > 0:
            monthly = remaining / (days_left / 30.44)
            lines.append(f"к {date_label} — откладывай ~{common.fmt_amount(monthly)} ₽/мес")
        else:
            lines.append(f"срок ({date_label}) наступил")
    return "\n".join(lines)


async def cmd_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    uid = update.effective_user.id
    goals = await db.get_goals(uid)
    if not goals:
        await update.message.reply_text(
            "Целей пока нет. Добавь: /goal Отпуск 100000 01.09.2026",
            reply_markup=keyboards.main_keyboard(),
        )
        return
    lines = ["Цели:"]
    for g in goals:
        lines.append("")
        lines.append(_goal_line(g))
    lines.append("")
    lines.append("Добавить цель: /goal Название Сумма [ДД.ММ.ГГГГ]")
    buttons = [
        [InlineKeyboardButton(f"➕ {g['icon']} {g['name']}", callback_data=f"goaladd:{g['id']}")]
        for g in goals if not g["is_completed"]
    ]
    await update.message.reply_text(
        "\n".join(lines).strip(),
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else keyboards.main_keyboard(),
    )


async def cmd_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Использование: /goal Отпуск 100000 01.09.2026\n"
            "Без срока: /goal Отпуск 100000\n"
            "Удалить: /goal Отпуск 0"
        )
        return
    text = " ".join(context.args)
    match = _ICON_PREFIX_RE.match(text)
    icon, rest = (match.group(1), match.group(2)) if match else ("🎯", text)
    args = rest.split()

    target_date = _NO_DATE
    if len(args) >= 2:
        maybe_date = common.parse_date_arg(args[-1])
        if maybe_date is not None:
            target_date = maybe_date
            args.pop()

    if not args:
        await update.message.reply_text("Укажи сумму. Пример: /goal Отпуск 100000")
        return
    amount_str = args.pop()
    try:
        amount = Decimal(amount_str.replace(",", "."))
    except InvalidOperation:
        await update.message.reply_text("Сумма должна быть числом. Пример: /goal Отпуск 100000")
        return
    if amount < 0:
        await update.message.reply_text("Сумма должна быть 0 (удалить цель) или больше.")
        return
    name = " ".join(args).strip()
    if not name:
        await update.message.reply_text("Укажи название цели: /goal Отпуск 100000")
        return

    uid = update.effective_user.id
    if amount == 0:
        existing = await db.find_goal_by_name(uid, name)
        if not existing:
            await update.message.reply_text(f"Цель «{name}» не найдена.")
            return
        await db.delete_goal(uid, existing["id"])
        await update.message.reply_text(f"Цель {existing['icon']} {existing['name']} удалена.")
        return

    created = await db.create_goal(
        uid, name, amount, None if target_date is _NO_DATE else target_date, icon,
    )
    if created:
        date_note = f" к {target_date.strftime('%d.%m.%Y')}" if target_date is not _NO_DATE else ""
        await update.message.reply_text(
            f"🎯 Новая цель: {created['icon']} {created['name']} — {common.fmt_amount(amount)} ₽{date_note}"
        )
        return

    # имя уже занято — обновляем существующую цель (срок меняем, только если указан явно)
    existing = await db.find_goal_by_name(uid, name)
    if not existing:
        await update.message.reply_text("Не получилось сохранить цель.")
        return
    await db.update_goal(uid, existing["id"], target_amount=amount, target_date=target_date)
    await update.message.reply_text(
        f"Цель {existing['icon']} {existing['name']} обновлена: {common.fmt_amount(amount)} ₽"
    )


async def _apply_contribution(update: Update, uid: int, goal_id: int, amount: Decimal):
    result = await db.add_goal_contribution(uid, goal_id, amount)
    chat = update.effective_chat
    if result is None:
        goal = await db.get_goal(uid, goal_id)
        if goal is None:
            text = "Цель не найдена — возможно, удалена."
        else:
            text = f"Нельзя снять больше, чем накоплено (сейчас {common.fmt_amount(goal['saved'])} ₽)."
        await chat.send_message(text)
        return
    verb = "Отложено" if amount > 0 else "Снято"
    text = f"💰 {verb} {common.fmt_amount(abs(amount))} ₽\n\n{_goal_line(result)}"
    if result.get("just_completed"):
        text += "\n\n🎉 Цель достигнута!"
    await chat.send_message(text, reply_markup=keyboards.main_keyboard())


async def handle_goal_add_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка «➕ Пополнить» под списком целей."""
    query = update.callback_query
    await query.answer()
    goal_id = int(query.data.split(":", 1)[1])
    uid = update.effective_user.id
    goal = await db.get_goal(uid, goal_id)
    if not goal:
        await query.message.reply_text("Цель не найдена — возможно, удалена.")
        return
    context.user_data["pending_goal"] = goal_id
    await query.message.reply_text(
        f"Пополнить {goal['icon']} {goal['name']}: выбери сумму или напиши свою "
        f"(отрицательная — снять, например -2000).",
        reply_markup=keyboards.goal_contribute_keyboard(goal_id),
    )


async def handle_goal_amount_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка с готовой суммой (+1000/+5000/+10000)."""
    query = update.callback_query
    await query.answer()
    _, goal_id, amount = query.data.split(":")
    context.user_data.pop("pending_goal", None)
    await _apply_contribution(update, update.effective_user.id, int(goal_id), Decimal(amount))


async def handle_goal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("pending_goal", None)
    await query.edit_message_text("Отменено.")


async def handle_goal_amount_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Свободный текст, пока ждём сумму пополнения (см. route_text)."""
    goal_id = context.user_data.get("pending_goal")
    text = (update.message.text or "").strip().replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        await update.message.reply_text(
            "Не понял сумму. Напиши число, например 5000 или -2000 (снять), "
            "или нажми «Отмена» в сообщении выше."
        )
        return
    if amount == 0:
        await update.message.reply_text("Сумма не может быть нулевой.")
        return
    context.user_data.pop("pending_goal", None)
    await _apply_contribution(update, update.effective_user.id, goal_id, amount)
