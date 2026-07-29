"""
Реестр парсеров банковских выписок. Каждый банк — свой модуль с классом
BankStatementParser (см. base.py). Тела parse() дописываются по реальным
файлам-примерам от пользователя — до этого бросают NotImplementedError,
и бот вежливо об этом сообщает, не ломаясь.
"""
from .alfabank import AlfaBankParser
from .base import BankStatementParser, ParsedTransaction
from .ozonbank import OzonBankParser
from .sberbank import SberbankParser

PARSERS: dict[str, BankStatementParser] = {
    "sber": SberbankParser(),
    "alfa": AlfaBankParser(),
    "ozon": OzonBankParser(),
}


def get_parser(bank_code: str) -> BankStatementParser | None:
    return PARSERS.get(bank_code)
