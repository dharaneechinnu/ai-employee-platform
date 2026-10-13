"""Voice typing for the task box."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.v1.deps import RequestContext, SessionDep, require_permission
from app.core.errors import ValidationError
from app.core.permissions import Permission
from app.services.speech_service import MAX_AUDIO_BYTES, WHISPER_MODEL, SpeechService

router = APIRouter(prefix="/orgs/{org_id}/speech", tags=["speech"])

CanCreate = Annotated[RequestContext, Depends(require_permission(Permission.TASK_CREATE))]


class SpeechEngineResponse(BaseModel):
    # "browser" means the frontend uses the browser's own recogniser
    # and never sends audio here.
    engine: Literal["whisper", "browser"]
    model: str | None
    max_bytes: int


class TranscriptResponse(BaseModel):
    text: str


@router.get("", summary="Which voice-typing engine this company uses")
async def speech_engine(ctx: CanCreate, session: SessionDep) -> SpeechEngineResponse:
    engine = await SpeechService(session, ctx.org_id).engine()
    return SpeechEngineResponse(
        engine="whisper" if engine == "whisper" else "browser",
        model=WHISPER_MODEL if engine == "whisper" else None,
        max_bytes=MAX_AUDIO_BYTES,
    )


@router.post("/transcribe", summary="Turn a short recording into text")
async def transcribe(
    request: Request,
    ctx: CanCreate,
    session: SessionDep,
    language: Annotated[str | None, Query(pattern=r"^[a-z]{2}$")] = None,
) -> TranscriptResponse:
    """The raw recording is the request body, with its audio type as
    the Content-Type. Reading it as a capped stream means an oversized
    upload is refused without being held in memory first."""
    audio = bytearray()
    async for chunk in request.stream():
        audio.extend(chunk)
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValidationError("That recording is too long. Keep it under a few minutes.")

    text = await SpeechService(session, ctx.org_id).transcribe(
        bytes(audio), content_type=request.headers.get("content-type"), language=language
    )
    return TranscriptResponse(text=text)
