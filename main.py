"""
Точка входа: запускает Telegram-бот и FastAPI в одном asyncio event loop.
Railway выставляет PORT, uvicorn слушает его — сервис становится web-типом.
"""
import asyncio
import logging
import os

import uvicorn

import db
from api import app as fastapi_app
from bot import build_app

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL не задан")

    await db.init_db(database_url)
    logger.info("БД инициализирована")

    bot_app = build_app()
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram-бот запущен")

    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info("FastAPI запущен на порту %d", port)

    try:
        await server.serve()
    finally:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
