import re

from telegram import Update
from telegram.ext import ContextTypes

import db
from . import access, keyboards

# Отделяет ведущий эмодзи/символ от названия, даже если между ними нет пробела
# (частый случай на телефоне: клавиатура вставляет эмодзи без пробела) —
# "🏠квартира" распознаётся как иконка 🏠 + имя "квартира", а не целиком как иконка.
_ICON_PREFIX_RE = re.compile(r"^([^\w\s]+)\s*(.*)$", re.UNICODE)


def _split_icon_name(text: str) -> tuple[str, str]:
    """Возвращает (icon, name); icon = '' если текст начинается с буквы/цифры."""
    match = _ICON_PREFIX_RE.match(text)
    if match:
        return match.group(1), match.group(2).strip()
    return "", text.strip()


async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    uid = update.effective_user.id
    expense = await db.get_categories(uid, "expense")
    income = await db.get_categories(uid, "income")
    lines = ["Категории расходов:"]
    lines += [f"  {c['icon']} {c['name']}" for c in expense]
    lines.append("\nКатегории доходов:")
    lines += [f"  {c['icon']} {c['name']}" for c in income]
    lines.append("\nДобавить свою: /addcategory 🎮 Хобби")
    await update.message.reply_text("\n".join(lines), reply_markup=keyboards.main_keyboard())


async def cmd_addcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text("Использование: /addcategory 🎮 Хобби")
        return
    icon, name = _split_icon_name(" ".join(context.args))
    icon = icon or "💰"
    if not name:
        await update.message.reply_text("Укажи название категории: /addcategory 🎮 Хобби")
        return
    uid = update.effective_user.id
    category = await db.add_category(uid, name, icon, "expense")
    if category is None:
        await update.message.reply_text(f"Категория «{name}» уже есть.")
        return
    await update.message.reply_text(f"Добавлена категория: {category['icon']} {category['name']}")
