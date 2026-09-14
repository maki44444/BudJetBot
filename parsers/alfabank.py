"""
Парсер выписки Альфа-Банка — «Выписка по счету» (PDF).

Формат по реальным файлам пользователя (два счёта):
  «10.08.2026 F310608000175654 Комиссия за услугу ... Мак Матвей Евгеньевич -99,00 RUR»
  дата проводки | код операции | описание (может переноситься) | сумма RUR

Знак обратный Сберу: минус у расхода, у поступления знака нет.
Времени в выписке нет вообще, поэтому ставим полдень по Москве — дата при
любом пересчёте часовых поясов остаётся той же.

Внутри описания встречаются суммы вида «на сумму: 83.00 RUR» — с точкой.
Колонка суммы всегда с запятой, на этом их и различаем.
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

_RECORD_RE = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})[ \t]+(?P<code>\S+)[ \t]+"
    r"(?P<desc>.*?)"
    r"(?P<sign>-?)[ \t]*(?P<amount>[\d\s\xa0]+,\d{2})[ \t]+RUR",
    re.MULTILINE | re.DOTALL,
)

_OWNER_RE = re.compile(r"Клиент\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2})")

_FURNITURE = (
    "Страница",
    "Дата проводки",
    "АО «АЛЬФА-БАНК»",
    "Уполномоченное лицо",
    "alfabank.ru",
)

_WS_RE = re.compile(r"\s+")
# перенос по строкам: «593-36-\n13», «SM-\nKLINIKA»
_HYPHEN_WRAP_RE = re.compile(r"(\w)-\s+(\w)")


def _parse_amount(raw: str) -> Decimal:
    return Decimal(raw.replace("\xa0", "").replace(" ", "").replace(",", "."))


def _clean_description(text: str) -> str:
    text = _HYPHEN_WRAP_RE.sub(r"\1-\2", _WS_RE.sub(" ", text).strip())
    for marker in _FURNITURE:
        pos = text.find(marker)
        if pos != -1:
            text = text[:pos]
    text = re.sub(r"\.?\s*(?:Без НДС|НДС не облагается)\.?\s*$", "", text).strip()

    # «Операция по карте: 220015++++++7369, на сумму: 83.00 RUR, дата совершения
    #  операции: 18.08.26, место совершения операции: W0009664\RU\MOSKVA\Mos
    #  Transport MCC4111» -> «Mos Transport»
    m = re.search(r"место совершения операции:\s*(.+)$", text)
    if m:
        place = m.group(1).strip()
        place = place.split("\\")[-1]
        place = re.sub(r"\s*MCC\d+\s*$", "", place).strip()
        if place:
            return place[:120]

    m = re.match(r"^Платеж\s+\S+\s+в пользу\s+([^,]+)", text)
    if m:
        return m.group(1).strip()[:120]

    m = re.match(r'^Комиссия за услугу\s+"([^"]+)"', text)
    if m:
        return f"Комиссия: {m.group(1).strip()}"[:120]

    m = re.match(r"^Взыскание задолженности по Договору\s+(.+?)\s+№", text)
    if m:
        return f"Взыскание по договору: {m.group(1).strip()}"[:120]

    m = re.search(r"через Систему быстрых платежей\s+(?:от|на)\s+(.+)$", text)
    if m:
        return f"СБП {m.group(1).strip()}"[:120]

    return text[:120]


def _is_self_transfer(raw_desc: str, owner: str, own_phones: set[str]) -> bool:
    """Свой перевод: между своими счетами внутри Альфы, служебные переносы
    банка или СБП на собственный телефон."""
    from .identity import normalize_phone

    if "Внутрибанковский перевод между счетами" in raw_desc:
        return True
    if "Перевод средств для списания комиссии" in raw_desc:
        return True
    if "Перевод ср-в с доп.сч" in raw_desc:
        return True
    if own_phones:
        for phone in re.findall(r"\+?\d[\d\s()\-]{9,}", raw_desc):
            if normalize_phone(phone) in own_phones:
                return True
    m = re.search(r"через Систему быстрых платежей\s+(?:от|на)\s+([А-ЯЁ][^.,]+)", raw_desc)
    if m and is_same_person(m.group(1), owner):
        return True
    return False


class AlfaBankParser(BankStatementParser):
    bank_code = "alfa"
    display_name = "Альфа-Банк"
    supported_extensions = (".pdf",)

    def parse(self, content: bytes, filename: str) -> list[ParsedTransaction]:
        with pdfplumber.open(BytesIO(content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return self._parse_text(text)

    def _parse_text(self, text: str) -> list[ParsedTransaction]:
        owner_match = _OWNER_RE.search(text)
        owner = owner_match.group(1) if owner_match else ""

        result = []
        for m in _RECORD_RE.finditer(text):
            raw_desc = _WS_RE.sub(" ", m["desc"]).strip()
            # неподтверждённые операции (строка HOLD) пропускаем: они ещё могут
            # не состояться, а позже придут настоящей проводкой и задвоятся
            if "Неподтвержденная операция" in raw_desc:
                continue
            occurred_at = MOSCOW.localize(
                datetime.strptime(f"{m['date']} 12:00", "%d.%m.%Y %H:%M")
            )
            result.append(ParsedTransaction(
                occurred_at,
                _parse_amount(m["amount"]),
                "expense" if m["sign"] == "-" else "income",
                _clean_description(raw_desc),
                f"{m['date']}-{m['code']}",
                _is_self_transfer(raw_desc, owner, self.own_phones),
            ))
        return result
