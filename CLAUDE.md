# budget_bot — личный трекер бюджета

## Что делает проект
Telegram-бот для быстрого ввода трат/доходов (1-2 действия) + полноценный сайт (не Mini App)
с входом через Telegram Login Widget. Решает проблему заброшенных прошлых попыток вести
бюджет (Excel, самодельный бот): забывчивость закрывает вечернее напоминание, неудобство —
быстрый ввод, отсутствие плана — лимиты по категориям, отсутствие наглядности — сайт-дашборд.

Полный архитектурный план: `C:\Users\Maki4\.claude\plans\distributed-pondering-eclipse.md`.

## Статус реализации
- **Фаза 1 (бот, MVP) — готово**: быстрый ввод (оба порядка + задним числом), категории,
  лимиты (`/limit Категория 0` — снять), `/day` с удалением записей, вечернее напоминание,
  whitelist-админка, подсказки команд (setMyCommands).
- **Фаза 2 (сайт) — готово**: `auth.py` (Telegram Login Widget + Fernet session-cookie),
  `/api/*` (summary, transactions с PATCH/DELETE, categories, limits), `web/` —
  Дашборд (KPI-плитки, бары по категориям, метры лимитов), История (фильтр, смена
  категории, удаление), Лимиты. Vue 3 через CDN, светлая/тёмная тема.
- **Фаза 3 (цели накопления)** — не начата.
- **Фаза 4 (импорт банковских выписок)** — каркас `parsers/` не создан; парсеры Сбербанка,
  Альфа-Банка и Ozon Банка требуют реальных файлов-примеров от пользователя перед реализацией.

## Фаза 2 — требования к окружению
- Переменные Railway: `BOT_USERNAME` (без @), `SITE_URL` (https-домен сервиса),
  `ENCRYPTION_KEY` (Fernet-ключ — без него session-cookie не шифруется).
- BotFather: `/setdomain` → домен сервиса Railway (иначе Login Widget не работает).
- Домен: Railway → Settings → Networking → Generate Domain.

## Структура файлов
```
main.py          — точка входа: бот (polling) + FastAPI (uvicorn) в одном asyncio event loop
db.py            — все операции с PostgreSQL (asyncpg), идемпотентный DDL при старте
api.py           — FastAPI; пока минимальный health-check, в Фазе 2 — /api/* и раздача web/
crypto.py        — Fernet encrypt/decrypt (в Фазе 2 — для session-cookie сайта)
bot/
  __init__.py    — build_app(), регистрация хендлеров и JobQueue
  access.py      — whitelist-проверка доступа, resolve_uid()
  keyboards.py   — главная клавиатура, инлайн-категории, confirm-кнопки
  common.py      — часовой пояс МСК, диапазоны дат, форматирование сумм
  transactions.py — быстрый ввод "сумма [описание]", /today, /month, /undo
  categories.py  — /categories, /addcategory
  limits.py      — /limit, /limits
  reminders.py   — вечернее напоминание, если за день нет записей
  admin.py       — /grant, /revoke, /users
requirements.txt
Procfile         — web: python3 -u main.py
```

## Деплой
Планируется Railway, отдельный сервис (аналогично ozz_bot). Пока не задеплоено.

## Переменные окружения
| Переменная       | Описание |
|------------------|----------|
| `BOT_TOKEN`      | Telegram Bot API токен |
| `ADMIN_ID`       | Telegram ID администратора |
| `ENCRYPTION_KEY` | Fernet-ключ (используется в Фазе 2 для session-cookie сайта) |
| `DATABASE_URL`   | PostgreSQL connection string |
| `SITE_URL`       | URL сайта — показывает кнопку в боте, нужен в Фазе 2 для Login Widget |
| `REMINDER_HOUR`  | час вечернего напоминания по МСК, дефолт `21` |
| `PORT`           | выставляется Railway автоматически |

## База данных (PostgreSQL)
Создаётся идемпотентно в `db.py:_create_tables()` (`CREATE TABLE IF NOT EXISTS` +
`ALTER TABLE ADD COLUMN IF NOT EXISTS`, без Alembic).

- `users` — telegram_id, whitelist (`is_allowed`), настройки напоминаний
- `categories` — глобальные дефолтные (`telegram_id IS NULL`) + пользовательские
- `transactions` — расходы/доходы, `source` ('manual'|'import'), поля под будущий импорт выписок
- `budgets` — месячные лимиты по категории
- `no_spend_days` — ручная отметка "сегодня трат не было" (чтобы напоминание не спамило)

Данные полностью изолированы по `telegram_id` — не общий семейный бюджет.

## Быстрый ввод трат
Свободный текст `сумма [описание]`: без знака — расход, `+` — доход
(`350 такси`, `+50000 зарплата`). Бот показывает инлайн-клавиатуру категорий,
по тапу транзакция сразу пишется в БД.

## Безопасность
- Whitelist: только пользователи из `users.is_allowed=TRUE` + `ADMIN_ID`
- Только личные чаты (`filters.ChatType.PRIVATE`)
- В Фазе 2 сайт будет использовать Telegram Login Widget + Fernet session-cookie
  (алгоритм подписи отличается от Mini App initData — см. план)

## Зависимости
- `python-telegram-bot[job-queue]==21.6`
- `httpx==0.27.0`, `pytz==2024.1`, `cryptography==42.0.8`
- `asyncpg==0.29.0`, `fastapi==0.115.0`, `uvicorn[standard]==0.30.6`
- `pandas==2.2.2`, `openpyxl==3.1.2`, `pdfplumber==0.11.4` — под Фазу 4 (импорт выписок)
