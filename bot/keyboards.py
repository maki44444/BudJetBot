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


def confirm_keyboard(yes_data: str, no_data: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Да, удалить", callback_data=yes_data),
        InlineKeyboardButton("Отмена", callback_data=no_data),
    ]])
