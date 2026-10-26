from app.infrastructure.db.connection import create_engine


async def test_sql_errors_hide_bound_document_and_credential_values() -> None:
    engine = create_engine("postgresql+asyncpg://synthetic:unused@postgres/synthetic")
    try:
        assert engine.sync_engine.hide_parameters is True
    finally:
        await engine.dispose()
