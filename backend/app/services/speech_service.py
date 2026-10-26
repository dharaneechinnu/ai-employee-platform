"""Voice typing: turn a short recording into text.

Whisper Large v3 Turbo, served by Groq, using the person's own Groq
key, so voice costs the platform nothing and needs no GPU here. A
person without a Groq key gets the browser's built-in recogniser
instead; that fallback lives entirely in the frontend.

The audio passes straight through. It is never stored, and neither the
audio nor the transcript is logged.
"""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, RateLimitError, UpstreamError, ValidationError
from app.core.observability import get_logger
from app.services.provider_service import ProviderService

log = get_logger(__name__)

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-large-v3-turbo"

# A task is a sentence or two. Ten megabytes is several minutes of
# compressed audio, well under Groq's own limit.
MAX_AUDIO_BYTES = 10 * 1024 * 1024

# Groq detects the format from the file name, so the extension matters.
EXTENSIONS: dict[str, str] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}


def _client() -> httpx.AsyncClient:
    # A seam for tests, which swap in a mock transport.
    return httpx.AsyncClient(timeout=30.0)


def audio_extension(content_type: str | None) -> str:
    """The file extension for an upload, ignoring codec parameters.

    Browsers send e.g. ``audio/webm;codecs=opus``; only the type matters.
    """
    base = (content_type or "").split(";", 1)[0].strip().lower()
    if base not in EXTENSIONS:
        raise ValidationError("That audio format is not supported. Try WebM, Ogg, MP4, MP3 or WAV.")
    return EXTENSIONS[base]


class SpeechService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.providers = ProviderService(session, owner_id)
        self.owner_id = owner_id

    async def engine(self) -> str:
        """``whisper`` when the person has a Groq key, else ``browser``."""
        connected = await self.providers.connected()
        return "whisper" if any(c.provider_key == "groq" for c in connected) else "browser"

    async def transcribe(
        self, audio: bytes, *, content_type: str | None, language: str | None = None
    ) -> str:
        extension = audio_extension(content_type)
        if not audio:
            raise ValidationError("The recording was empty.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValidationError("That recording is too long. Keep it under a few minutes.")

        try:
            api_key = await self.providers.resolve_api_key("groq")
        except NotFoundError as exc:
            raise ValidationError(
                "Voice typing with Whisper needs a Groq key. Connect one in Providers."
            ) from exc

        data = {"model": WHISPER_MODEL, "response_format": "json", "temperature": "0"}
        if language:
            data["language"] = language

        async with _client() as client:
            try:
                response = await client.post(
                    GROQ_TRANSCRIBE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=data,
                    files={"file": (f"speech.{extension}", audio, content_type or "")},
                )
            except httpx.HTTPError as exc:
                raise UpstreamError("Could not reach Groq to transcribe. Try again.") from exc

        if response.status_code in (401, 403):
            raise ValidationError("Groq rejected the API key. Check it in Providers.")
        if response.status_code == 429:
            raise RateLimitError("Groq's speech limit was reached. Wait a moment and try again.")
        if not response.is_success:
            log.warning(
                "transcription_failed", owner_id=str(self.owner_id), status=response.status_code
            )
            raise UpstreamError("Groq could not transcribe that recording.")

        text = str(response.json().get("text", "")).strip()
        log.info(
            "transcribed",
            owner_id=str(self.owner_id),
            audio_bytes=len(audio),
            chars=len(text),
        )
        return text
