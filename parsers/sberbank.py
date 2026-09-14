"""
Парсер выписки Сбербанка — «Выписка по платёжному счёту» (PDF).

Формат по реальному файлу пользователя: одна операция занимает две строки.
  1) дата, время, категория Сбера, сумма, остаток
     «13.09.2026 20:35 Оплата по QR–коду СБП 196,86 5 103,18»
  2) дата обработки, код авторизации, описание (может переноситься)
     «13.09.2026 042946 SBSCR_WHOOSH_SBP. Операция по карте ****7738»

Знак: «+» у поступлений, у расходов знака нет вообще. Разделитель дробной
части — запятая (у Ozon точка), поэтому шаблон суммы здесь свой.

Код авторизации шестизначный и сам по себе не уникален, поэтому в external_id
идёт вместе с датой: в один день коды не повторяются, а без него три поездки
CITYDRIVE по 48,89 в одну минуту схлопнулись бы в одну операцию.
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

_NUM = r"[\d\s\xa0]+,\d{2}"

_HEAD_RE = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})[ \t]+(?P<time>\d{2}:\d{2})[ \t]+"
    r"(?P<category>\S.*?)[ \t]+"
    r"(?P<sign>\+?)[ \t]*(?P<amount>" + _NUM + r")[ \t]+"
    r"(?P<balance>-?" + _NUM + r")[ \t]*$",
    re.MULTILINE,
)

_BODY_RE = re.compile(r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<code>\S+)\s+(?P<desc>.*)", re.DOTALL)

_OWNER_RE = re.compile(r"Владелец счёта\s*\n?\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2})")

# Служебный текст страниц, который нельзя утащить в описание операции
_FURNITURE = (
    "Продолжение на следующей странице",
    "Выписка по платёжному счёту",
    "ДАТА ОПЕРАЦИИ",
    "Дата обработки",
    "Дата формирования документа",
    "ПАО Сбербанк",
)

_WS_RE = re.compile(r"\s+")
# «SBSCR_WHOOSH_SBP. Операция по карте ****7738» -> «SBSCR_WHOOSH_SBP»
_TAIL_RE = re.compile(r"\.\s*Операци[яи]\s+по\s+(?:карте|счету|счёту)\s*\*+\d+.*$", re.IGNORECASE)


def _parse_amount(raw: str) -> Decimal:
    return Decimal(raw.replace("\xa0", "").replace(" ", "").replace(",", "."))


def _cut_furniture(text: str) -> str:
    for marker in _FURNITURE:
        pos = text.find(marker)
        if pos != -1:
            text = text[:pos]
    return text


def _clean_description(text: str) -> str:
    text = _WS_RE.sub(" ", _cut_furniture(text)).strip()
    text = _TAIL_RE.sub("", text).strip()
    return text.rstrip(".").strip()[:120]


def _is_self_transfer(description: str, owner: str) -> bool:
    """Перевод на свой же счёт в другом банке.

    Сбер подписывает переводы людям именем («Перевод от Ш. Светлана Евгеньевна»),
    а переводы между своими счетами — названием банка-получателя без имени
    («Перевод в Ozon Bank (Ozon)», «Альфа-банк»). На это и опираемся.
    """
    if re.search(r"Перевод\s+(?:в|из)\s+\w", description) and not re.search(
        r"Перевод\s+(?:от|на)\s+[А-ЯЁ]", description
    ):
        return True
    if re.match(r"^(Альфа-банк|Озон Банк|Ozon Bank)\b", description, re.IGNORECASE):
        return True
    m = re.search(r"Перевод\s+(?:от|на)\s+(.+)$", description)
    if m and is_same_person(m.group(1), owner):
        return True
    return False


class SberbankParser(BankStatementParser):
    bank_code = "sber"
    display_name = "Сбербанк"
    supported_extensions = (".pdf",)

    def parse(self, content: bytes, filename: str) -> list[ParsedTransaction]:
        with pdfplumber.open(BytesIO(content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return self._parse_text(text)

    def _parse_text(self, text: str) -> list[ParsedTransaction]:
        owner_match = _OWNER_RE.search(text)
        owner = owner_match.group(1) if owner_match else ""

        heads = list(_HEAD_RE.finditer(text))
        result = []
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            body = _BODY_RE.search(text[m.end():end])
            code = body["code"] if body else ""
            raw_desc = body["desc"] if body else m["category"]

            description = _clean_description(raw_desc) or m["category"].strip()
            occurred_at = MOSCOW.localize(
                datetime.strptime(f"{m['date']} {m['time']}", "%d.%m.%Y %H:%M")
            )
            result.append(ParsedTransaction(
                occurred_at,
                _parse_amount(m["amount"]),
                "income" if m["sign"] == "+" else "expense",
                description,
                f"{m['date']}-{code}" if code else None,
                _is_self_transfer(description, owner),
            ))
        return result
