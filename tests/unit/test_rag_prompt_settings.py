import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.api.document_dependencies import document_actor
from app.main import create_app
from app.modules.identity.application.contracts import Principal, UserRole
from app.modules.rag.api.settings import prompt_service
from app.modules.rag.application.prompt_settings import (
    DEFAULT_SYSTEM_PROMPT,
    ManagePrompt,
    PromptSettings,
)
from app.modules.rag.infrastructure.providers import OllamaChat
from app.modules.shared.domain.errors import ApplicationError


@pytest.mark.parametrize("role", list(UserRole))
async def test_prompt_settings_require_active_admin(role: UserRole) -> None:
    store = AsyncMock()
    store.get.return_value = PromptSettings()
    service = ManagePrompt(store)
    actor = Principal(uuid4(), "synthetic", role, None)
    if role == UserRole.ADMIN:
        assert (await service.get(actor)).system_prompt == DEFAULT_SYSTEM_PROMPT
        await service.save(actor, "Synthetic prompt", 0)
        store.save.assert_awaited_once_with("Synthetic prompt", 0)
    else:
        for call in (service.get(actor), service.save(actor, "Synthetic prompt", 0)):
            with pytest.raises(ApplicationError) as exc:
                await call
            assert exc.value.code == "forbidden"
        store.get.assert_not_awaited()
        store.save.assert_not_awaited()
    inactive = Principal(actor.id, "synthetic", UserRole.ADMIN, None, is_active=False)
    with pytest.raises(ApplicationError):
        await service.save(inactive, "Synthetic prompt", 0)


@pytest.mark.parametrize("prompt", ["", " \n\t", "x" * 8001, "x\x00y"])
async def test_invalid_prompt_never_reaches_storage(prompt: str) -> None:
    store = AsyncMock()
    with pytest.raises(ApplicationError):
        await ManagePrompt(store).save(Principal(uuid4(), "admin", UserRole.ADMIN, None), prompt, 0)
    store.save.assert_not_awaited()


async def test_provider_loads_saved_prompt_for_each_call_and_preserves_data_boundary() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "{}"}})

    store = AsyncMock()
    store.get.side_effect = [
        PromptSettings("Custom {literal} инструкции", 1),
        PromptSettings("Updated prompt", 2),
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = OllamaChat(client, "http://ollama", "synthetic", prompts=store)
        await provider.answer("UNTRUSTED QUESTION", [])
        await provider.answer("UNTRUSTED QUESTION", [])
        await OllamaChat(client, "http://ollama", "synthetic").answer("Question", [])
    assert [item["messages"][0]["content"] for item in requests] == [
        "Custom {literal} инструкции",
        "Updated prompt",
        DEFAULT_SYSTEM_PROMPT,
    ]
    assert requests[0]["messages"][1]["role"] == "user"
    assert "UNTRUSTED QUESTION" not in requests[0]["messages"][0]["content"]
    assert set(requests[0]["format"]["required"]) == {
        "answer",
        "citations",
        "insufficient_evidence",
    }


async def test_settings_http_validation_permissions_and_conflict() -> None:
    app = create_app()
    store = AsyncMock()
    store.get.return_value = PromptSettings()
    store.save.return_value = PromptSettings("Custom prompt", 1)
    app.dependency_overrides[prompt_service] = lambda: ManagePrompt(store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/settings/rag")).status_code == 401
        for role in (UserRole.MEMBER, UserRole.MANAGER):
            app.dependency_overrides[document_actor] = lambda: Principal(
                uuid4(), "user", role, None
            )
            assert (await client.get("/settings/rag")).status_code == 403
            assert (
                await client.put(
                    "/settings/rag", json={"system_prompt": "Custom prompt", "version": 0}
                )
            ).status_code == 403
        app.dependency_overrides[document_actor] = lambda: Principal(
            uuid4(), "admin", UserRole.ADMIN, None
        )
        response = await client.get("/settings/rag")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["default_system_prompt"] == DEFAULT_SYSTEM_PROMPT
        assert response.json()["version"] == 0
        response = await client.put(
            "/settings/rag", json={"system_prompt": "Custom prompt", "version": 0}
        )
        assert response.status_code == 200 and response.json()["system_prompt"] == "Custom prompt"
        for prompt in ("", " \n", "x" * 8001, "PRIVATE\x00"):
            response = await client.put(
                "/settings/rag", json={"system_prompt": prompt, "version": 0}
            )
            assert response.status_code == 422 and "PRIVATE" not in response.text
        store.save.side_effect = ApplicationError(
            "conflict", "Settings changed; reload before saving"
        )
        assert (
            await client.put("/settings/rag", json={"system_prompt": "Custom prompt", "version": 0})
        ).status_code == 409
