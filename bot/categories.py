from telegram import Update
from telegram.ext import ContextTypes

import db
from . import access, keyboards


def _looks_like_icon(token: str) -> bool:
    return len(token) > 0 and not token[0].isalnum()


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
    icon = "💰"
    name_parts = context.args
    if _looks_like_icon(context.args[0]):
        icon = context.args[0]
        name_parts = context.args[1:]
    name = " ".join(name_parts).strip()
    if not name:
        await update.message.reply_text("Укажи название категории: /addcategory 🎮 Хобби")
        return
    uid = update.effective_user.id
    category = await db.add_category(uid, name, icon, "expense")
    if category is None:
        await update.message.reply_text(f"Категория «{name}» уже есть.")
        return
    await update.message.reply_text(f"Добавлена категория: {category['icon']} {category['name']}")
