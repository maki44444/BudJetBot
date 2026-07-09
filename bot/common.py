from datetime import date as Date, datetime, timedelta

import pytz

MOSCOW = pytz.timezone("Europe/Moscow")

_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def fmt_amount(value) -> str:
    return f"{float(value):,.0f}".replace(",", " ")


def today_range() -> tuple[datetime, datetime]:
    return day_range(datetime.now(MOSCOW).date())


def day_range(day: Date) -> tuple[datetime, datetime]:
    start = MOSCOW.localize(datetime(day.year, day.month, day.day))
    return start, start + timedelta(days=1)


def parse_date_arg(text: str) -> Date | None:
    """Разбирает дату в формате DD.MM или DD.MM.YYYY (без года — текущий год)."""
    parts = text.strip().split(".")
    today = datetime.now(MOSCOW).date()
    try:
        if len(parts) == 2:
            return Date(today.year, int(parts[1]), int(parts[0]))
        if len(parts) == 3:
            year = int(parts[2])
            if year < 100:
                year += 2000
            return Date(year, int(parts[1]), int(parts[0]))
    except ValueError:
        return None
    return None


def month_range() -> tuple[datetime, datetime]:
    now = datetime.now(MOSCOW)
    start = MOSCOW.localize(datetime(now.year, now.month, 1))
    if now.month == 12:
        end = MOSCOW.localize(datetime(now.year + 1, 1, 1))
    else:
        end = MOSCOW.localize(datetime(now.year, now.month + 1, 1))
    return start, end


def month_label() -> str:
    now = datetime.now(MOSCOW)
    return f"{_MONTHS[now.month - 1]} {now.year}"
