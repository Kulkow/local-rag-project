"""Administrator checks for signed access tokens and the local smoke-test credential."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials

from app.api.dependencies import bearer, identity_service
from app.core.settings import Settings
from app.modules.identity.application.service import IdentityService

basic = HTTPBasic(auto_error=False)


async def require_admin(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)],
    access_token: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    service: Annotated[IdentityService, Depends(identity_service)],
) -> None:
    if access_token is not None:
        actor = await service.authenticate(access_token.credentials)
        service.require_admin(actor)
        return
    settings: Settings = request.app.state.settings
    if credentials is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Basic"})
    username_ok = secrets.compare_digest(
        credentials.username.encode(), settings.admin_username.encode()
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(), settings.admin_password.get_secret_value().encode()
    )
    if not (username_ok and password_ok):
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Basic"})
