"""Composition for uploads, with short DB reads rather than request-long connections."""

from app.modules.documents.application.download import DownloadDocument

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import bearer, identity_service
from app.modules.documents.application.indexing import InspectIndex
from app.modules.documents.infrastructure.chunk_repository import SqlChunkIndex
from app.modules.documents.application.processing import ManageProcessing
from app.modules.documents.infrastructure.processing_repository import SqlProcessingRepository
from app.modules.documents.application.upload import ListDocuments, UploadDocument
from app.modules.documents.application.extraction import ExtractDocument, ReadExtractedPages
from app.modules.documents.infrastructure.extraction_repository import SqlExtractionRepository
from app.modules.documents.infrastructure.repository import SqlDocumentRepository
from app.modules.documents.infrastructure.object_storage import MinioOriginalStorage
from app.modules.documents.infrastructure.family_access import (
    ScopedFamilyAccess as ScopedFamilyAccess,
)
from app.modules.identity.application.contracts import Principal
from app.modules.shared.domain.errors import ApplicationError


async def document_actor(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Principal:
    if credentials is None:
        raise ApplicationError("unauthorized", "Authentication required")
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    async with factory() as session:
        return await identity_service(request, session).authenticate(credentials.credentials)


def upload_use_case(request: Request) -> UploadDocument:
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    storage: MinioOriginalStorage = request.app.state.original_storage
    return UploadDocument(SqlDocumentRepository(factory), storage, ScopedFamilyAccess(factory))


def list_documents_use_case(request: Request) -> ListDocuments:
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    return ListDocuments(SqlDocumentRepository(factory), ScopedFamilyAccess(factory))


def extract_document_use_case(request: Request) -> ExtractDocument:
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    storage: MinioOriginalStorage = request.app.state.original_storage
    return ExtractDocument(
        SqlExtractionRepository(factory),
        storage,
        request.app.state.extractors,
        ScopedFamilyAccess(factory),
    )


def read_extracted_pages_use_case(request: Request) -> ReadExtractedPages:
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    storage: MinioOriginalStorage = request.app.state.original_storage
    return ReadExtractedPages(
        SqlExtractionRepository(factory), storage, ScopedFamilyAccess(factory)
    )


def processing_use_case(request: Request) -> ManageProcessing:
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    return ManageProcessing(
        SqlProcessingRepository(factory),
        SqlExtractionRepository(factory),
        ScopedFamilyAccess(factory),
        request.app.state.extractors,
    )


def inspect_index_use_case(request: Request) -> InspectIndex:
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    return InspectIndex(
        read_extracted_pages_use_case(request), SqlChunkIndex(factory), ScopedFamilyAccess(factory)
    )


def download_document_use_case(request: Request) -> "DownloadDocument":
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    return DownloadDocument(
        SqlExtractionRepository(factory),
        request.app.state.original_storage,
        ScopedFamilyAccess(factory),
    )
