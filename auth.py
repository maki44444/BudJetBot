"""
Аутентификация сайта: проверка подписи Telegram Login Widget + session-cookie.

Важно: алгоритм отличается от Mini App initData (там ключ HMAC("WebAppData", token)).
Для Login Widget: secret_key = SHA256(BOT_TOKEN), подпись = HMAC-SHA256(data_check_string).
Документация: https://core.telegram.org/widgets/login#checking-authorization
"""
import hashlib
import hmac
import json
import logging
import os
import time

import crypto

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]

SESSION_TTL = 30 * 24 * 3600   # cookie живёт 30 дней
AUTH_MAX_AGE = 24 * 3600       # данные виджета не старше суток


def verify_login_widget(params: dict) -> int | None:
    """Проверяет подпись данных от Telegram Login Widget.
    Возвращает telegram_id или None, если подпись/срок невалидны."""
    received_hash = params.get("hash")
    if not received_hash or "id" not in params or "auth_date" not in params:
        return None
    check_pairs = {k: v for k, v in params.items() if k != "hash"}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(check_pairs.items()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        logger.warning("Login widget: неверная подпись")
        return None
    try:
        auth_date = int(params["auth_date"])
    except ValueError:
        return None
    if time.time() - auth_date > AUTH_MAX_AGE:
        logger.warning("Login widget: auth_date старше суток")
        return None
    try:
        return int(params["id"])
    except ValueError:
        return None


def issue_session(telegram_id: int) -> str:
    payload = {"uid": telegram_id, "exp": int(time.time()) + SESSION_TTL}
    return crypto.encrypt(json.dumps(payload))


def read_session(cookie_value: str | None) -> int | None:
    """Возвращает telegram_id из cookie или None, если сессия невалидна/истекла."""
    if not cookie_value:
        return None
    try:
        payload = json.loads(crypto.decrypt(cookie_value))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    uid = payload.get("uid")
    return int(uid) if isinstance(uid, int) else None
