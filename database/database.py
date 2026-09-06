"""Database engine and session helpers."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

from .models import Base, PaymentSettings, Setting

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

DEFAULT_SETTINGS = {
    "bot_token": settings.bot_token or "",
    "admin_ids": "",
    "welcome_text": (
        "👋 Добро пожаловать в цифровой магазин!\n\n"
        "Выберите действие в меню ниже."
    ),
}


def _sqlite_add_missing_columns(sync_conn) -> None:
    rows = sync_conn.exec_driver_sql("PRAGMA table_info(orders)").fetchall()
    names = {r[1] for r in rows}
    if "payment_ref" not in names:
        sync_conn.exec_driver_sql(
            "ALTER TABLE orders ADD COLUMN payment_ref VARCHAR(128)"
        )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sqlite_add_missing_columns)

    async with async_session() as session:
        for key, value in DEFAULT_SETTINGS.items():
            existing = await session.get(Setting, key)
            if existing is None:
                session.add(Setting(key=key, value=value))
            elif key == "bot_token" and not existing.value and value:
                existing.value = value

        pay = await session.get(PaymentSettings, 1)
        if pay is None:
            session.add(PaymentSettings(id=1))
        await session.commit()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
