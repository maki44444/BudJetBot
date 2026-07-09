import asyncpg
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

DEFAULT_CATEGORIES = [
    # (name, icon, type, sort_order)
    ("Продукты", "🛒", "expense", 10),
    ("Транспорт", "🚕", "expense", 20),
    ("Жильё/ЖКХ", "🏠", "expense", 30),
    ("Развлечения", "🎉", "expense", 40),
    ("Здоровье", "💊", "expense", 50),
    ("Одежда", "👕", "expense", 60),
    ("Связь/Интернет", "📱", "expense", 70),
    ("Кафе и рестораны", "☕", "expense", 80),
    ("Образование", "📚", "expense", 90),
    ("Путешествия", "✈️", "expense", 100),
    ("Подарки", "🎁", "expense", 110),
    ("Другое", "🔧", "expense", 120),
    ("Зарплата", "💵", "income", 10),
    ("Прочий доход", "💰", "income", 20),
]


async def init_db(database_url: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    await _create_tables()
    await _seed_default_categories()
    logger.info("База данных подключена")


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def _create_tables() -> None:
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id      BIGINT PRIMARY KEY,
                username         TEXT,
                first_name       TEXT,
                is_allowed       BOOLEAN NOT NULL DEFAULT FALSE,
                reminder_hour    SMALLINT NOT NULL DEFAULT 21,
                reminder_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id          SERIAL PRIMARY KEY,
                telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                icon        TEXT NOT NULL DEFAULT '💰',
                type        TEXT NOT NULL DEFAULT 'expense' CHECK (type IN ('expense', 'income')),
                sort_order  SMALLINT NOT NULL DEFAULT 100,
                is_archived BOOLEAN NOT NULL DEFAULT FALSE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_default_name
            ON categories(name) WHERE telegram_id IS NULL
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_user_name
            ON categories(telegram_id, name) WHERE telegram_id IS NOT NULL
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id              BIGSERIAL PRIMARY KEY,
                telegram_id     BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                category_id     INT REFERENCES categories(id),
                type            TEXT NOT NULL DEFAULT 'expense' CHECK (type IN ('expense', 'income')),
                amount          NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
                currency        TEXT NOT NULL DEFAULT 'RUB',
                description     TEXT,
                occurred_at     TIMESTAMPTZ NOT NULL,
                source          TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'import')),
                bank            TEXT,
                raw_description TEXT,
                import_batch_id INT,
                import_hash     TEXT,
                reconciled      BOOLEAN NOT NULL DEFAULT FALSE,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tx_user_date
            ON transactions(telegram_id, occurred_at DESC)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tx_user_category
            ON transactions(telegram_id, category_id)
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_import_hash
            ON transactions(telegram_id, import_hash) WHERE import_hash IS NOT NULL
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id          SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                category_id INT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                amount      NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
                period      TEXT NOT NULL DEFAULT 'monthly' CHECK (period IN ('monthly')),
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (telegram_id, category_id, period)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS no_spend_days (
                telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                day         DATE NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (telegram_id, day)
            )
        """)


async def _seed_default_categories() -> None:
    async with _pool.acquire() as conn:
        for name, icon, type_, sort_order in DEFAULT_CATEGORIES:
            await conn.execute("""
                INSERT INTO categories (telegram_id, name, icon, type, sort_order)
                VALUES (NULL, $1, $2, $3, $4)
                ON CONFLICT (name) WHERE telegram_id IS NULL DO NOTHING
            """, name, icon, type_, sort_order)


# ---------- users ----------

async def ensure_user(telegram_id: int, username: str | None, first_name: str | None) -> None:
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, username, first_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (telegram_id) DO UPDATE
                SET username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name
                WHERE users.username IS DISTINCT FROM EXCLUDED.username
                   OR users.first_name IS DISTINCT FROM EXCLUDED.first_name
        """, telegram_id, username, first_name)


async def is_allowed(telegram_id: int) -> bool:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_allowed FROM users WHERE telegram_id = $1", telegram_id
        )
        return bool(row and row["is_allowed"])


async def grant_access(telegram_id: int) -> None:
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, is_allowed)
            VALUES ($1, TRUE)
            ON CONFLICT (telegram_id) DO UPDATE SET is_allowed = TRUE
        """, telegram_id)


async def revoke_access(telegram_id: int) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_allowed = FALSE WHERE telegram_id = $1", telegram_id
        )


async def get_allowed_users() -> list[dict]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT telegram_id, username FROM users WHERE is_allowed = TRUE ORDER BY telegram_id"
        )
        return [{"id": r["telegram_id"], "username": r["username"]} for r in rows]


async def get_user_by_username(username: str) -> int | None:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT telegram_id FROM users WHERE LOWER(username) = LOWER($1)", username
        )
        return row["telegram_id"] if row else None


async def get_reminder_candidates() -> list[int]:
    """telegram_id пользователей, которым можно слать вечернее напоминание."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT telegram_id FROM users WHERE is_allowed = TRUE AND reminder_enabled = TRUE"
        )
        return [r["telegram_id"] for r in rows]


# ---------- categories ----------

async def get_categories(telegram_id: int, type_: str | None = None) -> list[dict]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, telegram_id, name, icon, type, sort_order
            FROM categories
            WHERE (telegram_id = $1 OR telegram_id IS NULL)
              AND is_archived = FALSE
              AND ($2::text IS NULL OR type = $2)
            ORDER BY sort_order, name
        """, telegram_id, type_)
        return [dict(r) for r in rows]


async def find_category_by_name(telegram_id: int, name: str) -> dict | None:
    """Ищет категорию по имени (без учёта регистра); своя категория пользователя приоритетнее дефолтной."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, telegram_id, name, icon, type
            FROM categories
            WHERE (telegram_id = $1 OR telegram_id IS NULL)
              AND is_archived = FALSE
              AND LOWER(name) = LOWER($2)
            ORDER BY telegram_id NULLS LAST
            LIMIT 1
        """, telegram_id, name)
        return dict(row) if row else None


async def get_category(category_id: int) -> dict | None:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, telegram_id, name, icon, type FROM categories WHERE id = $1", category_id
        )
        return dict(row) if row else None


async def add_category(telegram_id: int, name: str, icon: str, type_: str) -> dict | None:
    """Добавляет пользовательскую категорию. Возвращает None если имя уже занято."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO categories (telegram_id, name, icon, type, sort_order)
            VALUES ($1, $2, $3, $4, 200)
            ON CONFLICT (telegram_id, name) WHERE telegram_id IS NOT NULL DO NOTHING
            RETURNING id, name, icon, type
        """, telegram_id, name, icon, type_)
        return dict(row) if row else None


# ---------- transactions ----------

async def add_transaction(
    telegram_id: int,
    category_id: int | None,
    type_: str,
    amount,
    description: str | None,
    occurred_at: datetime,
    source: str = "manual",
) -> int:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO transactions (telegram_id, category_id, type, amount, description, occurred_at, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, telegram_id, category_id, type_, amount, description, occurred_at, source)
        return row["id"]


async def get_transactions_between(telegram_id: int, start: datetime, end: datetime) -> list[dict]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.id, t.type, t.amount, t.description, t.occurred_at, t.source,
                   c.name AS category_name, c.icon AS category_icon
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.telegram_id = $1 AND t.occurred_at >= $2 AND t.occurred_at < $3
            ORDER BY t.occurred_at DESC
        """, telegram_id, start, end)
        return [dict(r) for r in rows]


async def get_category_breakdown(telegram_id: int, start: datetime, end: datetime, type_: str = "expense") -> list[dict]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id AS category_id, c.name, c.icon, COALESCE(SUM(t.amount), 0) AS total
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.telegram_id = $1 AND t.type = $2 AND t.occurred_at >= $3 AND t.occurred_at < $4
            GROUP BY c.id, c.name, c.icon
            ORDER BY total DESC
        """, telegram_id, type_, start, end)
        return [dict(r) for r in rows]


async def has_transactions_between(telegram_id: int, start: datetime, end: datetime) -> bool:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT EXISTS(
                SELECT 1 FROM transactions
                WHERE telegram_id = $1 AND occurred_at >= $2 AND occurred_at < $3
            ) AS found
        """, telegram_id, start, end)
        return bool(row["found"])


async def get_last_manual_transaction(telegram_id: int) -> dict | None:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, type, amount, description, category_id
            FROM transactions
            WHERE telegram_id = $1 AND source = 'manual'
            ORDER BY created_at DESC
            LIMIT 1
        """, telegram_id)
        return dict(row) if row else None


async def delete_transaction(telegram_id: int, transaction_id: int) -> bool:
    async with _pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM transactions WHERE id = $1 AND telegram_id = $2",
            transaction_id, telegram_id,
        )
        return result != "DELETE 0"


# ---------- budgets ----------

async def set_budget(telegram_id: int, category_id: int, amount) -> None:
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO budgets (telegram_id, category_id, amount)
            VALUES ($1, $2, $3)
            ON CONFLICT (telegram_id, category_id, period)
            DO UPDATE SET amount = EXCLUDED.amount
        """, telegram_id, category_id, amount)


async def delete_budget(telegram_id: int, category_id: int) -> bool:
    async with _pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM budgets WHERE telegram_id = $1 AND category_id = $2",
            telegram_id, category_id,
        )
        return result != "DELETE 0"


async def get_budget_progress(telegram_id: int, start: datetime, end: datetime) -> list[dict]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id AS category_id, c.name, c.icon, b.amount AS budget,
                   COALESCE(SUM(t.amount), 0) AS spent
            FROM budgets b
            JOIN categories c ON c.id = b.category_id
            LEFT JOIN transactions t ON t.category_id = b.category_id
                AND t.telegram_id = b.telegram_id
                AND t.type = 'expense'
                AND t.occurred_at >= $2 AND t.occurred_at < $3
            WHERE b.telegram_id = $1
            GROUP BY c.id, c.name, c.icon, b.amount
            ORDER BY c.name
        """, telegram_id, start, end)
        return [dict(r) for r in rows]


# ---------- no_spend_days ----------

async def mark_no_spend_day(telegram_id: int, day: date) -> None:
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO no_spend_days (telegram_id, day)
            VALUES ($1, $2)
            ON CONFLICT (telegram_id, day) DO NOTHING
        """, telegram_id, day)


async def has_no_spend_checkin(telegram_id: int, day: date) -> bool:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM no_spend_days WHERE telegram_id = $1 AND day = $2", telegram_id, day
        )
        return row is not None
