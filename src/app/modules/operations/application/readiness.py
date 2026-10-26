"""Readiness orchestration depends on a port, not on service clients."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class ServiceProbe(Protocol):
    async def check(self) -> bool: ...


@dataclass(frozen=True)
class ReadinessResult:
    services: dict[str, bool]

    @property
    def ready(self) -> bool:
        return bool(self.services) and all(self.services.values())


class InspectReadiness:
    def __init__(self, probes: Mapping[str, ServiceProbe], timeout_seconds: float = 4) -> None:
        self._probes = dict(probes)
        self._timeout_seconds = timeout_seconds

    async def _check(self, probe: ServiceProbe) -> bool:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await probe.check()
        except Exception:
            return False

    async def execute(self) -> ReadinessResult:
        values = await asyncio.gather(*(self._check(probe) for probe in self._probes.values()))
        return ReadinessResult(dict(zip(self._probes, values, strict=True)))
