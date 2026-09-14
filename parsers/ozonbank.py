"""
Парсер выписки Ozon Банка - "Справка о движении средств" (PDF).
Формат подтверждён реальным файлом-примером пользователя: таблица со строками
"Дата операции | Документ | Назначение платежа | Сумма операции (руб | Валюта)".
Для рублёвых счетов оба столбца суммы совпадают, знак явный (+ доход, - расход).
Номер документа иногда переносится на следующую строку прямо посреди числа -
поэтому после времени операции съедаются все идущие подряд группы цифр,
а не одно число.
"""
import re
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pdfplumber
import pytz

from .base import BankStatementParser, ParsedTransaction
from .identity import is_same_person

MOSCOW = pytz.timezone("Europe/Moscow")

_OWNER_RE = re.compile(r"Владелец:\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2})")
# перенос слова по строкам: «смс-\nинформирование», «UFS-\nONLINE»
_HYPHEN_WRAP_RE = re.compile(r"(\w)-\s+(\w)")

_AMOUNT = r"[\d\s ]+[.,]\d{2}"

# Номер документа пишется как "\d+(?:\s+\d+)*", а не "(?:\d+\s*)+": вложенный
# квантификатор давал катастрофический откат (22 цифры подряд без совпадения
# дальше по строке — уже 3 секунды на одну попытку, и это блокировало бы бота).
_RECORD_RE = re.compile(
    r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<doc>\d+(?:\s+\d+)*)\s*"
    r"(?P<desc>.*?)"
    r"(?P<sign>[+\-−])\s*(?P<amount>" + _AMOUNT + r")\s*₽\s*"
    r"[+\-−]\s*" + _AMOUNT + r"\s*₽",
    re.DOTALL,
)

_WS_RE = re.compile(r"\s+")


def _parse_amount(raw: str) -> Decimal:
    cleaned = raw.replace(" ", "").replace(" ", "").replace(",", ".")
    return Decimal(cleaned)


def _clean_description(text: str) -> str:
    """Достаёт из "Назначение платежа" короткую суть - контрагента/магазин,
    без служебных СБП-кодов, дат и "Без НДС". Не узнал формат - возвращает как есть."""
    text = _HYPHEN_WRAP_RE.sub(r"\1-\2", _WS_RE.sub(" ", text).strip()).rstrip(".")

    m = re.match(r"^(Возврат оплаты|Оплата) товаров по карте \S+ сумма [\d.,\s]+ в (.+?)\s+дата\s", text)
    if m:
        merchant = re.sub(r"\s+[A-Z]{2,3}$", "", m.group(2).strip())
        return f"Возврат {merchant}"[:120] if m.group(1) == "Возврат оплаты" else merchant

    m = re.match(r"^Снятие наличных денежных средств по карте \S+ сумма [\d.,\s]+ в (.+?)\s+дата\s", text)
    if m:
        place = re.sub(r"\s+[A-Z]{2,3}$", "", m.group(1).strip())
        return f"Снятие наличных {place}"[:120]

    if text.startswith("Комиссия за"):
        return re.sub(r",?\s*без НДС.*$", "", text, flags=re.IGNORECASE).strip()[:120]

    m = re.match(r"^Перевод .*?через СБП\.\s*(?:Получатель|Отправитель): (.+?)\.\s*Без НДС", text)
    if m:
        return m.group(1).strip()

    m = re.match(r"^Платеж в пользу (.+?),", text)
    if m:
        return m.group(1).strip()

    m = re.match(r"^Оплата товаров/услуг на Платформе Ozon, заказ № (.+?)\.\s*(?:Без НДС)?$", text)
    if m:
        order = re.sub(r"\s+", "", m.group(1))  # номер иногда переносится по строке пробелом
        return f"Ozon, заказ {order}"

    m = re.match(r"^Оплата товаров и услуг \([\d.,\s]+ руб\.,\s*(\S+)", text)
    if m:
        return m.group(1).rstrip(",").replace("https://", "").replace("http://", "").rstrip("/")

    m = re.match(r"^Перевод\s+.+?\.\s*\d{6,}\s+(.+?)\.\s*Без НДС", text)
    if m:
        return m.group(1).strip()

    # ничего специфичного не подошло — просто срезаем юридический хвост
    text = re.sub(r"\.?\s*(?:НДС не облагается|Без НДС)\.?$", "", text).strip()
    return text[:120]


def _is_self_transfer(raw_desc: str, owner: str) -> bool:
    """Перевод самому себе: внутреннее движение по своим продуктам Ozon либо
    СБП-перевод, где получатель или отправитель — сам владелец счёта."""
    text = _HYPHEN_WRAP_RE.sub(r"\1-\2", _WS_RE.sub(" ", raw_desc))
    if "Перевод собственных средств" in text:
        return True
    m = re.search(r"(?:Получатель|Отправитель):\s*([^.]+)", text)
    return bool(m and is_same_person(m.group(1), owner))


class OzonBankParser(BankStatementParser):
    bank_code = "ozon"
    display_name = "Ozon Банк"
    supported_extensions = (".pdf",)

    def parse(self, content: bytes, filename: str) -> list[ParsedTransaction]:
        with pdfplumber.open(BytesIO(content)) as pdf:
            full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return self._parse_text(full_text)

    def _parse_text(self, full_text: str) -> list[ParsedTransaction]:
        owner_match = _OWNER_RE.search(full_text)
        owner = owner_match.group(1) if owner_match else ""

        result = []
        for m in _RECORD_RE.finditer(full_text):
            occurred_at = MOSCOW.localize(
                datetime.strptime(f"{m['date']} {m['time']}", "%d.%m.%Y %H:%M:%S")
            )
            amount = _parse_amount(m["amount"])
            type_ = "expense" if m["sign"] in "-−" else "income"
            # номер документа мог перенестись на новую строку прямо посреди числа
            external_id = re.sub(r"\s+", "", m["doc"])
            result.append(ParsedTransaction(
                occurred_at, amount, type_, _clean_description(m["desc"]), external_id,
                _is_self_transfer(m["desc"], owner),
            ))
        return result
