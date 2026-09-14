"""ABC для парсеров банковских выписок + структура одной распознанной операции."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class ParsedTransaction:
    occurred_at: datetime    # обязательно timezone-aware (МСК — common.MOSCOW)
    amount: Decimal           # всегда положительная
    type: str                  # 'expense' | 'income'
    raw_description: str       # как в выписке — идёт в память категорий и историю
    external_id: str | None = None
    """Номер операции по версии банка (колонка «Документ» и аналоги).
    Если банк его даёт, именно он делает строку уникальной: две одинаковые
    покупки в один день на одну сумму различаются только по нему."""
    is_transfer: bool = False
    """Перевод между своими же счетами (в том числе в другой банк).
    Такая операция видна в истории, но не идёт в суммы месяца, разбивку по
    категориям, лимиты, прогноз и ИИ-разбор: иначе одни и те же деньги
    считаются расходом в одной выписке и доходом в другой."""


class BankStatementParser(ABC):
    bank_code: str
    display_name: str
    supported_extensions: tuple[str, ...]

    def __init__(self, own_phones: set[str] | None = None):
        """own_phones — телефоны самого пользователя в нормализованном виде
        (79991234567). По ним опознаются СБП-переводы на свой же счёт: банк
        пишет там только номер, без имени."""
        self.own_phones = own_phones or set()

    @abstractmethod
    def parse(self, content: bytes, filename: str) -> list[ParsedTransaction]:
        """Разбирает файл выписки в список операций."""
        raise NotImplementedError
