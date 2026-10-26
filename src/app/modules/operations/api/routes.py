from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.api.security import require_admin
from app.modules.operations.application.readiness import InspectReadiness

router = APIRouter()


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ready", "degraded"]
    services: dict[str, bool]


def readiness_use_case(request: Request) -> InspectReadiness:
    use_case: InspectReadiness = request.app.state.readiness
    return use_case


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health()


@router.get("/ready", response_model=Readiness, dependencies=[Depends(require_admin)])
async def ready(
    response: Response, use_case: Annotated[InspectReadiness, Depends(readiness_use_case)]
) -> Readiness:
    result = await use_case.execute()
    response.status_code = 200 if result.ready else 503
    return Readiness(status="ready" if result.ready else "degraded", services=result.services)
