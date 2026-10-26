import asyncio
from datetime import datetime
from typing import Annotated
from uuid import UUID
from urllib.parse import quote

from app.api.document_dependencies import download_document_use_case
from app.modules.documents.application.download import DownloadDocument

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from app.api.document_dependencies import document_actor, list_documents_use_case, upload_use_case
from app.modules.documents.application.upload import ListDocuments, UploadDocument
from app.modules.documents.application.extraction import (
    ExtractDocument,
    ReadExtractedPages,
    ExtractorRegistry,
)
from app.modules.documents.domain.extraction import ExtractionStatus
from app.modules.documents.application.processing import ManageProcessing
from app.modules.documents.domain.processing import ProcessingStatus
from app.api.document_dependencies import processing_use_case, inspect_index_use_case
from app.modules.documents.application.indexing import InspectIndex
from app.api.document_dependencies import extract_document_use_case, read_extracted_pages_use_case
from app.modules.documents.domain.entities import DocumentStatus, MAX_FILE_BYTES, Visibility
from app.modules.identity.application.contracts import Principal
from app.modules.shared.domain.errors import ApplicationError

router = APIRouter(prefix="/documents", tags=["Documents"])
Actor = Annotated[Principal, Depends(document_actor)]


class DocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    family_id: UUID
    owner_id: UUID
    filename: str
    title: str | None = None
    content_type: str
    size_bytes: int
    checksum: str
    visibility: Visibility
    status: DocumentStatus
    error_code: str | None
    created_at: datetime | None


@router.post(
    "",
    response_model=DocumentView,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                mime: {"schema": {"type": "string", "format": "binary"}}
                for mime in (
                    "application/pdf",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "text/html",
                    "application/octet-stream",
                )
            },
        }
    },
)
async def upload(
    request: Request,
    response: Response,
    actor: Actor,
    use_case: Annotated[UploadDocument, Depends(upload_use_case)],
    family_id: UUID,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    filename: str = Query(min_length=1, max_length=255),
    visibility: Visibility = Visibility.PRIVATE,
) -> DocumentView:
    # Authorization precedes body consumption; the application repeats this check.
    await use_case.access.authorize(actor, family_id, write=False)
    length = request.headers.get("content-length")
    if length:
        try:
            size = int(length)
        except ValueError:
            raise ApplicationError("invalid", "Invalid Content-Length") from None
        if size < 0:
            raise ApplicationError("invalid", "Invalid Content-Length")
        if size > MAX_FILE_BYTES:
            raise ApplicationError("payload_too_large", "File exceeds the 10 MiB limit")
    gate: asyncio.Semaphore = request.app.state.upload_slots
    try:
        async with asyncio.timeout(3):
            await gate.acquire()
    except TimeoutError:
        raise ApplicationError("throttled", "Upload capacity reached; retry later") from None
    try:
        content = bytearray()
        try:
            async with asyncio.timeout(30):
                async for chunk in request.stream():
                    if len(content) + len(chunk) > MAX_FILE_BYTES:
                        raise ApplicationError("payload_too_large", "File exceeds the 10 MiB limit")
                    content.extend(chunk)
        except TimeoutError:
            raise ApplicationError("upload_timeout", "File upload timed out") from None
        document = await use_case.execute(
            actor,
            family_id,
            filename,
            request.headers.get("content-type", "application/octet-stream"),
            bytes(content),
            idempotency_key,
            visibility,
        )
        response.headers["Location"] = f"/documents?family_id={family_id}"
        return DocumentView.model_validate(document)
    finally:
        gate.release()


@router.get("", response_model=list[DocumentView])
async def list_documents(
    actor: Actor,
    use_case: Annotated[ListDocuments, Depends(list_documents_use_case)],
    family_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> list[DocumentView]:
    return [
        DocumentView.model_validate(document)
        for document in await use_case.execute(actor, family_id, offset, limit)
    ]


class ExtractionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_id: UUID
    generation: UUID
    status: ExtractionStatus
    page_count: int
    character_count: int
    error_code: str | None


class ExtractedPageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    page_number: int
    text: str


class ExtractedPagesView(BaseModel):
    total_pages: int
    pages: list[ExtractedPageView]


@router.get("/extraction-formats", response_model=list[str])
async def extraction_formats(request: Request, actor: Actor) -> list[str]:
    registry: ExtractorRegistry = request.app.state.extractors
    return registry.content_types()


@router.post("/{document_id}/extract", response_model=ExtractionView)
async def extract(
    document_id: UUID,
    request: Request,
    actor: Actor,
    use_case: Annotated[ExtractDocument, Depends(extract_document_use_case)],
) -> ExtractionView:
    gate: asyncio.Semaphore = request.app.state.extraction_slots
    try:
        async with asyncio.timeout(3):
            await gate.acquire()
    except TimeoutError:
        raise ApplicationError(
            "throttled", "PDF extraction capacity reached; retry later"
        ) from None
    try:
        return ExtractionView.model_validate(await use_case.execute(actor, document_id))
    finally:
        gate.release()


@router.get("/{document_id}/extraction", response_model=ExtractionView)
async def extraction_status(
    document_id: UUID,
    actor: Actor,
    use_case: Annotated[ExtractDocument, Depends(extract_document_use_case)],
) -> ExtractionView:
    document = await use_case.repository.get_visible(actor, document_id)
    await use_case.access.authorize(actor, document.family_id)
    result = await use_case.repository.get(document_id)
    if result is None:
        raise ApplicationError("not_found", "Text extraction has not been requested")
    return ExtractionView.model_validate(result)


@router.get("/{document_id}/pages", response_model=ExtractedPagesView)
async def extracted_pages(
    document_id: UUID,
    actor: Actor,
    use_case: Annotated[ReadExtractedPages, Depends(read_extracted_pages_use_case)],
    offset: int = Query(0, ge=0),
    limit: int = Query(5, ge=1, le=10),
) -> ExtractedPagesView:
    result, pages = await use_case.execute(actor, document_id, offset, limit)
    return ExtractedPagesView(
        total_pages=result.page_count,
        pages=[ExtractedPageView.model_validate(page) for page in pages],
    )


class ProcessingJobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_id: UUID
    status: ProcessingStatus
    attempts: int
    error_code: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


@router.post("/{document_id}/process", response_model=ProcessingJobView, status_code=202)
async def schedule_processing(
    document_id: UUID,
    actor: Actor,
    use_case: Annotated[ManageProcessing, Depends(processing_use_case)],
) -> ProcessingJobView:
    return ProcessingJobView.model_validate(
        await use_case.execute(actor, document_id, schedule=True)
    )


@router.get("/{document_id}/processing", response_model=ProcessingJobView)
async def processing_status(
    document_id: UUID,
    actor: Actor,
    use_case: Annotated[ManageProcessing, Depends(processing_use_case)],
) -> ProcessingJobView:
    return ProcessingJobView.model_validate(await use_case.execute(actor, document_id))


class DocumentIndexView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_id: UUID
    status: str
    embedding_model: str
    embedding_digest: str
    dimensions: int
    chunk_count: int
    error_code: str | None


@router.get("/{document_id}/index", response_model=DocumentIndexView)
async def index_status(
    document_id: UUID,
    actor: Actor,
    use_case: Annotated[InspectIndex, Depends(inspect_index_use_case)],
) -> DocumentIndexView:
    return DocumentIndexView.model_validate(await use_case.execute(actor, document_id))


@router.post("/{document_id}/reindex", response_model=ProcessingJobView, status_code=202)
async def reindex_document(
    document_id: UUID,
    actor: Actor,
    use_case: Annotated[ManageProcessing, Depends(processing_use_case)],
) -> ProcessingJobView:
    return ProcessingJobView.model_validate(
        await use_case.execute(actor, document_id, schedule=True, reindex=True)
    )


@router.get(
    "/{document_id}/download",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            }
        }
    },
)
async def download_document(
    document_id: UUID,
    actor: Actor,
    use_case: Annotated[DownloadDocument, Depends(download_document_use_case)],
) -> Response:
    document, content = await use_case.execute(actor, document_id)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=download; filename*=UTF-8''{quote(document.filename, safe='')}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
