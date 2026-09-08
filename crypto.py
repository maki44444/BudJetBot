"""
Шифрование значений (Fernet). Используется для session-cookie сайта.

ВАЖНО: decrypt() НЕ возвращает исходную строку, если расшифровать не удалось.
Раньше здесь был фолбэк "считать значение открытым текстом" (наследство ozz_bot,
где так читались ключи, записанные до включения шифрования). Для сессий это
означало дыру: подделанный открытый JSON принимался за расшифрованные данные,
и куку можно было выписать себе самому, не зная ENCRYPTION_KEY.
"""
import os
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
_fernet = Fernet(_ENCRYPTION_KEY.encode()) if _ENCRYPTION_KEY else None

if not _fernet:
    logger.error(
        "ENCRYPTION_KEY не задан — вход на сайт работать не будет "
        "(сессии без шифрования принимать нельзя)"
    )


def available() -> bool:
    """Есть ли ключ шифрования. Без него сессии не выдаются и не принимаются."""
    return _fernet is not None


def encrypt(value: str) -> str:
    if not _fernet:
        raise RuntimeError("ENCRYPTION_KEY не задан — шифровать нечем")
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    """Расшифровывает значение. None — если ключа нет, значение пустое
    или это не валидный Fernet-токен (в том числе подделка)."""
    if not _fernet or not value:
        return None
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return None
