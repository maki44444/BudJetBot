"""
Парсер выписки Сбербанка. Ждёт файл-пример реальной выписки от пользователя —
точный формат колонок (Excel/CSV/PDF из Сбербанк Онлайн) пока неизвестен.
"""
from .base import BankStatementParser, ParsedTransaction


class SberbankParser(BankStatementParser):
    bank_code = "sber"
    display_name = "Сбербанк"
    supported_extensions = (".xlsx", ".csv", ".pdf")

    def parse(self, content: bytes, filename: str) -> list[ParsedTransaction]:
        raise NotImplementedError(
            "Парсер Сбербанка ещё не готов — нужен файл-пример реальной выписки."
        )
