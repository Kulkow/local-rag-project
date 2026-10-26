from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args={"timeout": 3},
        pool_size=5,
        max_overflow=5,
    )
