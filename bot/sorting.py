"""
Разбор категорий группами (/sort).

После импорта выписки сотни записей, у которых не удалось угадать категорию,
лежат в «Другое». Перебирать их по одной бессмысленно: на реальных данных
419 записей дали всего 142 разных описания, а первые десять групп закрывали
94% суммы. Поэтому бот спрашивает не про запись, а про группу — одно решение
применяется сразу ко всем её записям и запоминается на будущие импорты.

Группы идут по убыванию суммы: сначала то, что реально влияет на статистику.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
from . import access, categories, common, keyboards

logger = logging.getLogger(__name__)


def _group_line(group: dict) -> str:
    sign = "+" if group["type"] == "income" else "−"
    period = ""
    if group["first_at"] and group["last_at"]:
        first = group["first_at"].astimezone(common.MOSCOW)
        last = group["last_at"].astimezone(common.MOSCOW)
        period = (f", {first:%d.%m}" if first.date() == last.date()
                  else f", {first:%d.%m}—{last:%d.%m}")
    return (f"«{group['description']}»\n"
            f"{group['cnt']} записей на {sign}{common.fmt_amount(group['total'])}₽{period}")


async def _show_next(message, context: ContextTypes.DEFAULT_TYPE, uid: int, done: str = ""):
    """Показывает самую весомую неразобранную группу. Пусто — завершает разбор."""
    groups = await db.get_category_groups(uid, limit=1)
    left = await db.count_category_groups(uid)
    if not groups:
        text = (done + "\n\n" if done else "") + "🎉 Разбирать больше нечего."
        await message.reply_text(text, reply_markup=keyboards.main_keyboard())
        context.user_data.pop("sort_group", None)
        return

    group = groups[0]
    token = context.user_data.get("sort_token", 0) + 1
    context.user_data["sort_token"] = token
    context.user_data["sort_group"] = {
        "description": group["description"], "type": group["type"], "token": token,
    }
    cats = await db.get_categories(uid, group["type"])
    head = (done + "\n\n" if done else "") + f"Осталось групп: {left}\n\n"
    await message.reply_text(head + _group_line(group) + "\n\nЧто это?",
                             reply_markup=keyboards.sort_group_keyboard(cats, token))


async def cmd_sort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    uid = update.effective_user.id
    left = await db.count_category_groups(uid)
    if not left:
        await update.message.reply_text(
            "Всё разобрано — записей без категории нет.",
            reply_markup=keyboards.main_keyboard(),
        )
        return
    await update.message.reply_text(
        f"Разбор категорий: {left} групп.\n"
        "Отвечаю за всю группу сразу — один выбор закрывает все её записи "
        "и запоминается для будущих импортов."
    )
    await _show_next(update.message, context, uid)


def _current(context: ContextTypes.DEFAULT_TYPE, token: int) -> dict | None:
    """Группа, к которой относится нажатие, либо None у устаревшей кнопки."""
    group = context.user_data.get("sort_group")
    if not group or group.get("token") != token:
        return None
    return group


async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, token, category_id = query.data.split(":")
    group = _current(context, int(token))
    if not group:
        await query.edit_message_text("Эта группа уже разобрана — смотри сообщение ниже.")
        return
    uid = update.effective_user.id
    category = await db.get_category(int(category_id))
    if not category:
        await query.edit_message_text("Категория не найдена.")
        return
    await _apply(query, context, uid, group, category)


async def _apply(query, context: ContextTypes.DEFAULT_TYPE, uid: int,
                 group: dict, category: dict):
    """Проставляет категорию всей группе и переходит к следующей."""
    # выбор попадает в память категорий внутри assign_category_to_group
    count, total = await db.assign_category_to_group(
        uid, group["description"], group["type"], category["id"]
    )
    await query.edit_message_text(
        f"✅ «{group['description']}» → {category['icon']} {category['name']}\n"
        f"Записей обновлено: {count} на {common.fmt_amount(total)}₽"
    )
    await _show_next(query.message, context, uid)


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    token = int(query.data.split(":", 1)[1])
    group = _current(context, token)
    if not group:
        await query.edit_message_text("Эта группа уже разобрана — смотри сообщение ниже.")
        return
    uid = update.effective_user.id
    count = await db.skip_category_group(uid, group["description"], group["type"])
    await query.edit_message_text(
        f"⏭ «{group['description']}» оставлено как есть ({count} записей)."
    )
    await _show_next(query.message, context, uid)


async def handle_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("sort_group", None)
    uid = update.effective_user.id
    left = await db.count_category_groups(uid)
    await query.edit_message_text(
        f"Разбор остановлен. Осталось групп: {left} — продолжить можно командой /sort."
    )


async def handle_new_category_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка «➕ Новая категория» — просим название и ждём обычное сообщение."""
    query = update.callback_query
    await query.answer()
    token = int(query.data.split(":", 1)[1])
    group = _current(context, token)
    if not group:
        await query.edit_message_text("Эта группа уже разобрана — смотри сообщение ниже.")
        return
    context.user_data["pending_sort_category"] = True
    kind = "дохода" if group["type"] == "income" else "расхода"
    await query.edit_message_text(
        f"«{group['description']}»\n\n"
        f"Пришли название новой категории {kind} — можно с эмодзи, например «🎁 Подарки».\n"
        "Создам её и сразу применю ко всей группе."
    )


async def handle_new_category_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Название новой категории пришло текстом (ветка из route_text)."""
    context.user_data.pop("pending_sort_category", None)
    uid = update.effective_user.id
    group = context.user_data.get("sort_group")
    if not group:
        await update.message.reply_text(
            "Разбор уже закрыт — начни заново командой /sort.",
            reply_markup=keyboards.main_keyboard(),
        )
        return

    icon, name = categories._split_icon_name(update.message.text.strip())
    if not name:
        context.user_data["pending_sort_category"] = True
        await update.message.reply_text(
            "Не разобрал название. Пришли ещё раз, например «🎁 Подарки»."
        )
        return

    category = await db.add_category(uid, name, icon or "💰", group["type"])
    if not category:
        existing = await db.find_category_by_name(uid, name)
        if not existing:
            await update.message.reply_text("Не получилось создать категорию, попробуй другое имя.")
            return
        category = existing

    count, total = await db.assign_category_to_group(
        uid, group["description"], group["type"], category["id"]
    )
    await update.message.reply_text(
        f"✅ Создана {category['icon']} {category['name']}\n"
        f"«{group['description']}» → записей обновлено: {count} "
        f"на {common.fmt_amount(total)}₽"
    )
    await _show_next(update.message, context, uid)
