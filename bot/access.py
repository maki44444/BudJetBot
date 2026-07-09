import os

from telegram import Update
from telegram.ext import ContextTypes

import db

ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))


async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    await db.ensure_user(user.id, user.username, user.first_name)
    if ADMIN_ID and user.id == ADMIN_ID:
        return True
    if await db.is_allowed(user.id):
        return True
    await update.message.reply_text("У тебя нет доступа к боту.")
    return False


async def resolve_uid(arg: str) -> tuple[int | None, str | None]:
    """Принимает @username или числовой ID. Возвращает (user_id, error)."""
    clean = arg.lstrip("@")
    if clean.lstrip("-").isdigit():
        return int(clean), None
    uid = await db.get_user_by_username(clean)
    if uid is None:
        return None, f"Пользователь @{clean} ещё не писал боту. Попроси его написать /start."
    return uid, None
