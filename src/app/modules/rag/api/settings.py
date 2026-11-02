from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.document_dependencies import document_actor
from app.modules.identity.application.contracts import Principal
from app.modules.rag.application.prompt_settings import (
    DEFAULT_SYSTEM_PROMPT,
    MAX_PROMPT_LENGTH,
    ManagePrompt,
)
from app.modules.rag.infrastructure.prompt_repository import SqlPromptStore

router = APIRouter(prefix="/settings/rag", tags=["Settings"])


class PromptSettingsView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    system_prompt: str
    default_system_prompt: str = DEFAULT_SYSTEM_PROMPT
    version: int
    updated_at: datetime | None


class UpdatePromptInput(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH, pattern=r"\S")
    version: int = Field(ge=0)


def prompt_service(request: Request) -> ManagePrompt:
    return ManagePrompt(SqlPromptStore(request.app.state.db_session_factory))


@router.get("", response_model=PromptSettingsView)
async def get_prompt_settings(
    actor: Annotated[Principal, Depends(document_actor)],
    service: Annotated[ManagePrompt, Depends(prompt_service)],
    response: Response,
) -> PromptSettingsView:
    response.headers["Cache-Control"] = "no-store"
    return PromptSettingsView.model_validate(await service.get(actor))


@router.put("", response_model=PromptSettingsView)
async def update_prompt_settings(
    body: UpdatePromptInput,
    actor: Annotated[Principal, Depends(document_actor)],
    service: Annotated[ManagePrompt, Depends(prompt_service)],
    response: Response,
) -> PromptSettingsView:
    response.headers["Cache-Control"] = "no-store"
    return PromptSettingsView.model_validate(
        await service.save(actor, body.system_prompt, body.version)
    )
