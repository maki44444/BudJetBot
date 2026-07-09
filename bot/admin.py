from telegram import Update
from telegram.ext import ContextTypes

import db
from . import access


async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != access.ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /grant @username или /grant 123456789")
        return
    uid, err = await access.resolve_uid(context.args[0])
    if err:
        await update.message.reply_text(err)
        return
    await db.grant_access(uid)
    users = await db.get_allowed_users()
    uname = next((u["username"] for u in users if u["id"] == uid), None)
    label = f"@{uname} ({uid})" if uname else str(uid)
    await update.message.reply_text(f"Доступ выдан: {label}")


async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != access.ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /revoke @username или /revoke 123456789")
        return
    uid, err = await access.resolve_uid(context.args[0])
    if err:
        await update.message.reply_text(err)
        return
    await db.revoke_access(uid)
    await update.message.reply_text(f"Доступ отозван: ID {uid}")


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != access.ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    users = await db.get_allowed_users()
    if not users:
        await update.message.reply_text(f"Whitelist пуст. Доступ только у админа ({access.ADMIN_ID}).")
        return
    lines = [f"Пользователи с доступом ({len(users)}):"]
    for u in users:
        label = f"@{u['username']} ({u['id']})" if u["username"] else str(u["id"])
        lines.append(f"  {label}")
    await update.message.reply_text("\n".join(lines))
