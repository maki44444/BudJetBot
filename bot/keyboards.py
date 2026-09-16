import os

from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from .common import fmt_amount

SITE_URL = os.environ.get("SITE_URL", "")


def main_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        ["Сегодня", "За месяц"],
        ["Категории", "Лимиты"],
        ["Цели", "Отменить последнюю"],
        ["Помощь", "Сайт"] if SITE_URL else ["Помощь"],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def site_keyboard() -> InlineKeyboardMarkup | None:
    """Инлайн-кнопка на сайт с подробной аналитикой; None, если SITE_URL не задан."""
    if not SITE_URL:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Подробнее на сайте", url=SITE_URL)
    ]])


def category_keyboard(categories: list[dict], columns: int = 2) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{c['icon']} {c['name']}", callback_data=f"cat:{c['id']}")
        for c in categories
    ]
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(rows)


def change_category_keyboard(categories: list[dict], tx_id: int, columns: int = 2) -> InlineKeyboardMarkup:
    """Выбор новой категории для уже сохранённой записи (кнопка 🔁)."""
    buttons = [
        InlineKeyboardButton(f"{c['icon']} {c['name']}", callback_data=f"chgc:{tx_id}:{c['id']}")
        for c in categories
    ]
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(rows)


def sort_group_keyboard(categories: list[dict], token: int, columns: int = 2) -> InlineKeyboardMarkup:
    """Выбор категории сразу для всей группы записей (разбор после импорта).
    token — номер текущей группы: по нему отсекаются нажатия на старые
    сообщения, иначе выбор уехал бы не в ту группу."""
    buttons = [
        InlineKeyboardButton(f"{c['icon']} {c['name']}", callback_data=f"srtc:{token}:{c['id']}")
        for c in categories
    ]
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    rows.append([InlineKeyboardButton("➕ Новая категория", callback_data=f"srtnew:{token}")])
    rows.append([
        InlineKeyboardButton("⏭ Пропустить", callback_data=f"srtskip:{token}"),
        InlineKeyboardButton("✖️ Закончить", callback_data="srtstop"),
    ])
    return InlineKeyboardMarkup(rows)


def day_delete_keyboard(txs: list[dict], fmt_amount) -> InlineKeyboardMarkup:
    """Кнопка удаления на каждую запись дня + ссылка на сайт."""
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
    if SITE_URL:
        rows.append([InlineKeyboardButton("📊 Подробнее на сайте", url=SITE_URL)])
    return InlineKeyboardMarkup(rows)


def goal_contribute_keyboard(goal_id: int) -> InlineKeyboardMarkup:
    """Готовые суммы пополнения цели + отмена."""
    amounts = [1000, 5000, 10000]
    row = [
        InlineKeyboardButton(f"+{fmt_amount(a)}", callback_data=f"goalamt:{goal_id}:{a}")
        for a in amounts
    ]
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("Отмена", callback_data="goalcancel")]])


def import_bank_keyboard() -> InlineKeyboardMarkup:
    """Выбор банка после того, как пользователь прислал файл выписки."""
    import parsers
    rows = [
        [InlineKeyboardButton(p.display_name, callback_data=f"impbank:{code}")]
        for code, p in parsers.PARSERS.items()
    ]
    rows.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def import_review_keyboard(batch_id: int, seq: int, options: list[tuple[str, int]]) -> InlineKeyboardMarkup:
    """options — [(подпись, id похожей записи), ...] для ручной сверки одной строки импорта.

    В callback зашиты номер партии и номер строки: по ним обработчик отличает
    актуальную кнопку от нажатия по старому сообщению (в том числе от прошлого
    импорта) и не применяет решение к чужой строке."""
    rows = [
        [InlineKeyboardButton(label, callback_data=f"impuse:{batch_id}:{seq}:{tx_id}")]
        for label, tx_id in options
    ]
    rows.append([InlineKeyboardButton("➕ Это новая запись", callback_data=f"impnew:{batch_id}:{seq}")])
    rows.append([InlineKeyboardButton("⏭ Пропустить", callback_data=f"impskip:{batch_id}:{seq}")])
    return InlineKeyboardMarkup(rows)


def confirm_keyboard(yes_data: str, no_data: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Да, удалить", callback_data=yes_data),
        InlineKeyboardButton("Отмена", callback_data=no_data),
    ]])
