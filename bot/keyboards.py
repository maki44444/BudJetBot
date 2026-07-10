from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton


def main_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        ["Сегодня", "За месяц"],
        ["Категории", "Лимиты"],
        ["Отменить последнюю"],
        ["Помощь"],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def category_keyboard(categories: list[dict], columns: int = 2) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{c['icon']} {c['name']}", callback_data=f"cat:{c['id']}")
        for c in categories
    ]
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(rows)


def day_delete_keyboard(txs: list[dict], fmt_amount) -> InlineKeyboardMarkup:
    """Кнопка удаления на каждую запись дня."""
    rows = []
    for t in txs:
        sign = "+" if t["type"] == "income" else "-"
        label = t["description"] or t["category_name"] or "без категории"
        if len(label) > 20:
            label = label[:20] + "…"
        rows.append([InlineKeyboardButton(
            f"❌ {sign}{fmt_amount(t['amount'])}₽ {label}",
            callback_data=f"delq:{t['id']}",
        )])
    return InlineKeyboardMarkup(rows)


def confirm_keyboard(yes_data: str, no_data: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Да, удалить", callback_data=yes_data),
        InlineKeyboardButton("Отмена", callback_data=no_data),
    ]])
