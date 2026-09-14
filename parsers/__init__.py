"""
Реестр парсеров банковских выписок. Каждый банк — свой модуль с классом
BankStatementParser (см. base.py).

В реестре лежат классы, а не готовые объекты: парсеру нужны настройки
конкретного пользователя (свои телефоны для опознания переводов самому себе),
поэтому экземпляр создаётся на каждый импорт.
"""
from .alfabank import AlfaBankParser
from .base import BankStatementParser, ParsedTransaction
from .ozonbank import OzonBankParser
from .sberbank import SberbankParser

PARSERS: dict[str, type[BankStatementParser]] = {
    "sber": SberbankParser,
    "alfa": AlfaBankParser,
    "ozon": OzonBankParser,
}


def get_parser(bank_code: str, own_phones: set[str] | None = None) -> BankStatementParser | None:
    cls = PARSERS.get(bank_code)
    return cls(own_phones=own_phones) if cls else None
