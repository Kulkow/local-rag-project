import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.operations.application.readiness import InspectReadiness


async def test_partial_failure_keeps_other_service_results() -> None:
    healthy, broken = Mock(), Mock()
    healthy.check = AsyncMock(return_value=True)
    broken.check = AsyncMock(side_effect=OSError("offline"))
    result = await InspectReadiness({"healthy": healthy, "broken": broken}).execute()
    assert not result.ready
    assert result.services == {"healthy": True, "broken": False}


async def test_timeout_is_degraded() -> None:
    class SlowProbe:
        async def check(self) -> bool:
            await asyncio.Event().wait()
            return True

    result = await InspectReadiness({"slow": SlowProbe()}, timeout_seconds=0.01).execute()
    assert result.services == {"slow": False}
    assert not result.ready


async def test_cancellation_propagates() -> None:
    probe = Mock()
    probe.check = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await InspectReadiness({"cancelled": probe}).execute()


async def test_no_probes_is_not_ready() -> None:
    assert not (await InspectReadiness({}).execute()).ready
