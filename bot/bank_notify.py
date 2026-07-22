"""
Разбор пересланных банковских push-уведомлений (Сбер, Ozon Банк, Альфа-Банк) —
чтобы можно было переслать пуш о списании/пополнении вместо ручного ввода суммы.
Регулярки собраны по реальным образцам от пользователя (22.07.2026). У каждого
банка много других типов уведомлений (переводы, зачисления, отказы и т.д.) —
они распознаются по мере поступления новых образцов; пока не распознан текст,
просто возвращается None и срабатывает обычный быстрый ввод.
"""
import re
from decimal import Decimal, InvalidOperation

# "Счёт карты MIR-7738 23:07 Покупка 197р ЯндексСамокаты Баланс: 117.73р"
_SBER_PURCHASE_RE = re.compile(
    r"Сч[её]т карты\s+\S+\s+\d{1,2}:\d{2}\s+Покупка\s+"
    r"(?P<amount>\d+(?:[.,]\d{1,2})?)\s*р\.?\s+(?P<merchant>.+?)\s+Баланс",
    re.IGNORECASE | re.DOTALL,
)

# "Покупка в UFS-ONLINE. 12765.50 RUR. Звёзд +3. Баланс 4443.64 ₽"
_OZON_PURCHASE_RE = re.compile(
    r"Покупка\s+в\s+(?P<merchant>.+?)\.\s*(?P<amount>\d+(?:[.,]\d{1,2})?)\s*RUR\.",
    re.IGNORECASE | re.DOTALL,
)

# "Пополнение **3908 на 10 RUB" (возможен заголовок "Пополнения" отдельной строкой перед этим)
_ALFA_TOPUP_RE = re.compile(
    r"Пополнение\s+\*+\s*\d+\s+на\s+(?P<amount>\d+(?:[.,]\d{1,2})?)\s*RUB",
    re.IGNORECASE,
)


def try_parse(text: str) -> dict | None:
    """Пытается распознать пересланное банковское уведомление.
    Возвращает {"amount": Decimal, "type": "expense"|"income", "description": str}
    или None, если формат не узнан."""
    m = _SBER_PURCHASE_RE.search(text)
    if m:
        return _result(m["amount"], "expense", m["merchant"])

    m = _OZON_PURCHASE_RE.search(text)
    if m:
        return _result(m["amount"], "expense", m["merchant"])

    m = _ALFA_TOPUP_RE.search(text)
    if m:
        return _result(m["amount"], "income", "Пополнение")

    return None


def _result(raw_amount: str, type_: str, description: str) -> dict | None:
    try:
        amount = Decimal(raw_amount.replace(",", "."))
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return {"amount": amount, "type": type_, "description": description.strip()}
