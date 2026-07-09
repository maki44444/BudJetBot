import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
_fernet = Fernet(_ENCRYPTION_KEY.encode()) if _ENCRYPTION_KEY else None

if not _fernet:
    logger.warning("ENCRYPTION_KEY не задан — сессии сайта хранятся в открытом виде")


def encrypt(value: str) -> str:
    if not _fernet or not value:
        return value
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not _fernet or not value:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return value  # уже plaintext (данные до включения шифрования)
