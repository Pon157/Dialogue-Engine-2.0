"""Разово создаёт все таблицы по моделям. Позже, когда схема стабилизируется,
стоит перейти на alembic-миграции — но для старта разработки так быстрее.

Запуск:  python -m app.create_db
"""

import asyncio

from app.db import Base, engine
from app import models  # noqa: F401  -- нужно, чтобы все модели попали в Base.metadata


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Готово: все таблицы созданы.")


if __name__ == "__main__":
    asyncio.run(main())
