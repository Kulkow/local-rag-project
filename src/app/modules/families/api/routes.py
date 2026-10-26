from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.api.dependencies import current_user, family_service
from app.modules.families.application.service import FamilyService
from app.modules.identity.domain.entities import Principal

router = APIRouter(prefix="/families", tags=["Families"])
Actor = Annotated[Principal, Depends(current_user)]
Service = Annotated[FamilyService, Depends(family_service)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Role = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class FamilyInput(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class FamilyView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str


class MemberInput(BaseModel):
    first_name: Name
    last_name: Name
    role: Role = "member"


class MemberRole(BaseModel):
    role: Role


class MemberView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    person_id: UUID
    first_name: str
    last_name: str
    role: str
    joined_at: date


@router.get("", response_model=list[FamilyView])
async def list_families(
    service: Service,
    actor: Actor,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[FamilyView]:
    return [FamilyView.model_validate(f) for f in await service.list_families(actor, offset, limit)]


@router.post("", response_model=FamilyView, status_code=201)
async def create(body: FamilyInput, service: Service, actor: Actor) -> FamilyView:
    return FamilyView.model_validate(await service.create(actor, body.name))


@router.put("/{family_id}", response_model=FamilyView)
async def rename(family_id: UUID, body: FamilyInput, service: Service, actor: Actor) -> FamilyView:
    return FamilyView.model_validate(await service.rename(actor, family_id, body.name))


@router.delete("/{family_id}", status_code=204)
async def delete(family_id: UUID, service: Service, actor: Actor) -> Response:
    await service.delete(actor, family_id)
    return Response(status_code=204)


@router.get("/{family_id}/members", response_model=list[MemberView])
async def members(
    family_id: UUID,
    service: Service,
    actor: Actor,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[MemberView]:
    return [
        MemberView.model_validate(m) for m in await service.members(actor, family_id, offset, limit)
    ]


@router.post("/{family_id}/members", response_model=MemberView, status_code=201)
async def add_member(
    family_id: UUID, body: MemberInput, service: Service, actor: Actor
) -> MemberView:
    return MemberView.model_validate(
        await service.add_member(actor, family_id, body.first_name, body.last_name, body.role)
    )


@router.patch("/{family_id}/members/{member_id}", response_model=MemberView)
async def change_member(
    family_id: UUID, member_id: UUID, body: MemberRole, service: Service, actor: Actor
) -> MemberView:
    return MemberView.model_validate(
        await service.change_member(actor, family_id, member_id, body.role)
    )


@router.delete("/{family_id}/members/{member_id}", status_code=204)
async def remove_member(
    family_id: UUID, member_id: UUID, service: Service, actor: Actor
) -> Response:
    await service.remove_member(actor, family_id, member_id)
    return Response(status_code=204)
