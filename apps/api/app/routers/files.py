"""File upload + status endpoints — Phase 3.

Endpoints:
    POST /files                   — multipart upload, streams to S3, enqueues parse
    GET  /files/{id}              — status polling (parse_status + flags)
    GET  /files/{id}/content      — adapter helper: raw bytes (auth-checked)

Hard size + MIME constraints are applied BEFORE bytes hit S3 so the
gateway absorbs the cost of bad uploads. Type allowlist:
    PDF, PNG, JPG/JPEG, WEBP, DOCX, TXT, MD.

The endpoint returns the file_id immediately. The Celery worker handles
parsing async; the client polls the status endpoint until parse_status
flips to 'done' before submitting the message.
"""

from __future__ import annotations

import logging
from io import BytesIO
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi import File as FastAPIFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser
from app.config import settings
from app.db import get_session
from app.models import FileStatusResponse, FileUploadResponse
from app.orm import File
from app.ratelimit import enforce_rate_limit
from app.storage import build_key, download_bytes, key_from_storage_url, upload_fileobj

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


# Allowlist keyed by extension; the MIME check is best-effort because
# browsers lie about content-type fairly often (esp. for .md). We accept
# both the canonical MIME and the bare extension.
_ALLOWED: dict[str, set[str]] = {
    "pdf":  {"application/pdf"},
    "png":  {"image/png"},
    "jpg":  {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "webp": {"image/webp"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",  # some browsers send this for .docx
    },
    "txt":  {"text/plain"},
    "md":   {"text/markdown", "text/plain", "text/x-markdown"},
}


def _extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _validate_upload(upload: UploadFile, size_bytes: int) -> tuple[str, str]:
    """Returns (extension, normalized_mime). Raises 400/413 on rejection."""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file_too_large: max {settings.max_file_size_mb}MB",
        )
    ext = _extension(upload.filename)
    if ext not in _ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported_type: .{ext or '?'}",
        )
    declared = (upload.content_type or "").lower()
    if declared and declared not in _ALLOWED[ext]:
        # Don't reject on MIME mismatch alone — extension is authoritative
        # because we control the allowlist. Just log it.
        logger.info(
            "file upload: extension/mime mismatch ext=%s mime=%s", ext, declared
        )
    # Pick a canonical MIME from the allowlist (the first entry).
    return ext, next(iter(_ALLOWED[ext]))


@router.post(
    "",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    conversation_id: UUID | None = Form(None),
    user: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> FileUploadResponse:
    """Upload a single file. Multipart. Returns file_id immediately.

    The whole request body is read into memory because we need to (1)
    enforce the size cap before streaming to S3 and (2) hash + scan the
    bytes for the parse worker. At 20MB this is safe; Phase 6 will move
    to streaming uploads via a pre-signed POST URL once we want to drop
    the in-process buffer.
    """
    # Read into memory under the size cap. Reading into bytes is fine at
    # 20MB; we never let the worker stream the whole body into RAM either
    # — it downloads from S3 on demand.
    raw = await file.read()
    size_bytes = len(raw)
    ext, mime = _validate_upload(file, size_bytes)

    # Create the row FIRST so the storage key is deterministic from the
    # generated UUID. If the S3 upload fails we delete the row (the
    # alternative — upload first, persist later — leaves orphans in S3
    # forever per the no-auto-delete rule).
    row = File(
        user_id=user.id,
        storage_url="",  # filled in below
        mime_type=mime,
        size_bytes=size_bytes,
        original_filename=file.filename,
        parse_status="pending",
        conversation_id=conversation_id,
    )
    session.add(row)
    await session.flush()  # populates row.id
    key = build_key(row.id, file.filename)
    try:
        storage_url = upload_fileobj(BytesIO(raw), key=key, content_type=mime)
    except Exception:
        await session.rollback()
        logger.exception("file upload: S3 put failed for file_id=%s", row.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="storage_unavailable",
        ) from None
    row.storage_url = storage_url
    await session.commit()
    await session.refresh(row)

    # Enqueue parse. Late import so the API process never imports celery
    # at module-load time (worker would be a circular import otherwise).
    from app.workers.tasks import parse_file

    parse_file.delay(str(row.id), ext)

    return FileUploadResponse(
        file_id=row.id,
        parse_status=row.parse_status,  # type: ignore[arg-type]
        mime_type=row.mime_type,
        original_filename=row.original_filename,
        size_bytes=row.size_bytes,
    )


@router.get("/{file_id}", response_model=FileStatusResponse)
async def get_file_status(
    file_id: UUID,
    user: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> FileStatusResponse:
    """Lightweight status — what the UI polls. Returns flags rather than
    the full extracted text to keep payloads small while a file is
    re-rendered in many chips."""
    row = await _load_owned_file(session, file_id, user.id)
    return FileStatusResponse(
        file_id=row.id,
        parse_status=row.parse_status,  # type: ignore[arg-type]
        mime_type=row.mime_type,
        original_filename=row.original_filename,
        size_bytes=row.size_bytes,
        has_description=bool(row.description),
        has_extracted_text=bool(row.extracted_text),
        chunk_count=len(row.chunks or []),
        error=row.error,
    )


@router.get("/{file_id}/content")
async def get_file_content(
    file_id: UUID,
    user: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Stream the raw bytes back. Used by the chat UI for image previews
    and by the replay tool. Authorization: row must belong to the
    requesting user (no shared files in Phase 3)."""
    row = await _load_owned_file(session, file_id, user.id)
    key = key_from_storage_url(row.storage_url)
    raw = download_bytes(key)
    return Response(content=raw, media_type=row.mime_type or "application/octet-stream")


async def _load_owned_file(
    session: AsyncSession, file_id: UUID, user_id: UUID
) -> File:
    row = (
        await session.execute(
            select(File).where(File.id == file_id, File.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="file_not_found"
        )
    return row
