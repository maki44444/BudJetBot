"""
Парсер выписки Ozon Банка. Ждёт файл-пример реальной выписки от пользователя —
точный формат колонок (Excel/CSV из приложения Ozon Банк) пока неизвестен.
"""
from .base import BankStatementParser, ParsedTransaction


class OzonBankParser(BankStatementParser):
    bank_code = "ozon"
    display_name = "Ozon Банк"
    supported_extensions = (".xlsx", ".csv")

    def parse(self, content: bytes, filename: str) -> list[ParsedTransaction]:
        raise NotImplementedError(
            "Парсер Ozon Банка ещё не готов — нужен файл-пример реальной выписки."
        )
