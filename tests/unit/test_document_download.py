import hashlib
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.documents.application.download import DownloadDocument
from app.modules.documents.domain.entities import Document, DocumentStatus, Visibility
from app.modules.identity.application.contracts import Principal, UserRole
from app.modules.shared.domain.errors import ApplicationError


@pytest.mark.parametrize("case", ["ok", "denied", "pending", "missing", "corrupt"])
async def test_download_authorization_and_original_integrity(case: str) -> None:
    actor = Principal(uuid4(), "synthetic", UserRole.MEMBER, uuid4())
    content = b"<html>synthetic</html>"
    document = Document(
        uuid4(),
        uuid4(),
        actor.id,
        "файл.html",
        "text/html",
        len(content),
        hashlib.sha256(content).hexdigest(),
        "originals/synthetic",
        Visibility.PRIVATE,
        DocumentStatus.UPLOADING if case == "pending" else DocumentStatus.UPLOADED,
    )
    repository, storage, access = AsyncMock(), AsyncMock(), AsyncMock()
    repository.get_visible.return_value = document
    storage.get.return_value = b"altered" if case == "corrupt" else content
    if case == "denied":
        access.authorize.side_effect = ApplicationError("not_found", "Family not found")
    if case == "missing":
        storage.get.side_effect = OSError("private MinIO details")
    use_case = DownloadDocument(repository, storage, access)
    if case == "ok":
        assert await use_case.execute(actor, document.id) == (document, content)
    else:
        with pytest.raises(ApplicationError) as error:
            await use_case.execute(actor, document.id)
        assert error.value.code == {"denied": "not_found", "pending": "conflict"}.get(
            case, "storage_unavailable"
        )
        assert "private MinIO" not in str(error.value)
    if case in ("denied", "pending"):
        storage.get.assert_not_awaited()
