from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from app.api.dependencies import bearer, current_user, identity_service
from app.modules.identity.application.service import IdentityService
from app.modules.identity.domain.entities import Principal, UserRole

router = APIRouter()
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9_.@-]+$",
    ),
]
Password = Annotated[SecretStr, Field(min_length=12, max_length=128)]
Service = Annotated[IdentityService, Depends(identity_service)]
Actor = Annotated[Principal, Depends(current_user)]


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    username: str
    role: UserRole
    family_member_id: UUID | None
    is_active: bool


class LoginInput(BaseModel):
    username: Username
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]


class LoginResult(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 28800
    user: UserView


class CreateUser(BaseModel):
    username: Username
    password: Password
    role: UserRole = UserRole.MEMBER
    family_member_id: UUID | None = None


class UpdateUser(BaseModel):
    role: UserRole
    is_active: bool
    family_member_id: UUID | None = None
    password: Password | None = None


@router.post("/auth/login", response_model=LoginResult)
async def login(
    body: LoginInput, request: Request, response: Response, service: Service
) -> LoginResult:
    # Trust the socket peer, not user-controlled forwarding headers.
    client = request.client.host if request.client else "unknown"
    token, user = await service.login(body.username, body.password.get_secret_value(), client)
    response.headers["Cache-Control"] = "no-store"
    return LoginResult(access_token=token, user=UserView.model_validate(user))


@router.get("/auth/me", response_model=UserView)
async def me(actor: Actor) -> UserView:
    return UserView.model_validate(actor)


@router.post("/auth/logout", status_code=204)
async def logout(
    service: Service,
    actor: Actor,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Response:
    assert isinstance(credentials, HTTPAuthorizationCredentials)
    await service.logout(credentials.credentials)
    return Response(status_code=204)


@router.get("/users", response_model=list[UserView])
async def users(
    service: Service,
    actor: Actor,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[UserView]:
    return [
        UserView.model_validate(user) for user in await service.list_users(actor, offset, limit)
    ]


@router.post("/users", response_model=UserView, status_code=201)
async def create_user(body: CreateUser, service: Service, actor: Actor) -> UserView:
    return UserView.model_validate(
        await service.create_user(
            actor, body.username, body.password.get_secret_value(), body.role, body.family_member_id
        )
    )


@router.put("/users/{user_id}", response_model=UserView)
async def update_user(user_id: UUID, body: UpdateUser, service: Service, actor: Actor) -> UserView:
    return UserView.model_validate(
        await service.update_user(
            actor,
            user_id,
            body.role,
            body.is_active,
            body.family_member_id,
            body.password.get_secret_value() if body.password else None,
        )
    )
