"""Voice typing: Whisper through the company's own Groq key.

Groq is never contacted: its HTTP client is replaced with a fake that
records what it was sent.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_company

GROQ_KEY = "gsk_test-key-5678"
WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 2048  # a WebM header, then silence


@pytest.fixture
def fake_groq(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        if seen["status"] != 200:
            return httpx.Response(seen["status"], json={"error": {"message": "nope"}})
        return httpx.Response(200, json={"text": "  Why did checkouts fail overnight?  "})

    import app.services.speech_service as svc

    monkeypatch.setattr(
        svc, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return seen


async def _company(
    api: AsyncClient, session: AsyncSession, *, groq: bool
) -> tuple[Any, dict[str, str]]:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}
    if groq:
        connected = await api.post(
            f"/api/v1/orgs/{acme.org_id}/providers",
            json={"provider_key": "groq", "api_key": GROQ_KEY},
            headers=headers,
        )
        assert connected.status_code in (200, 201), connected.text
    return acme, headers


async def test_without_a_groq_key_the_browser_does_the_listening(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme, headers = await _company(api, session, groq=False)
    response = await api.get(f"/api/v1/orgs/{acme.org_id}/speech", headers=headers)
    assert response.status_code == 200
    assert response.json()["engine"] == "browser"
    assert response.json()["model"] is None


async def test_with_a_groq_key_whisper_transcribes(
    api: AsyncClient, session: AsyncSession, fake_groq: dict[str, Any]
) -> None:
    acme, headers = await _company(api, session, groq=True)

    engine = await api.get(f"/api/v1/orgs/{acme.org_id}/speech", headers=headers)
    assert engine.json() == {
        "engine": "whisper",
        "model": "whisper-large-v3-turbo",
        "max_bytes": 10 * 1024 * 1024,
    }

    response = await api.post(
        f"/api/v1/orgs/{acme.org_id}/speech/transcribe?language=en",
        content=WEBM,
        headers={**headers, "Content-Type": "audio/webm;codecs=opus"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"text": "Why did checkouts fail overnight?"}

    # The company's own key, decrypted only for this call, and the file
    # named so Groq can tell the format.
    assert fake_groq["auth"] == f"Bearer {GROQ_KEY}"
    assert fake_groq["url"].endswith("/openai/v1/audio/transcriptions")
    assert b'filename="speech.webm"' in fake_groq["body"]
    assert b"whisper-large-v3-turbo" in fake_groq["body"]


async def test_a_member_can_use_voice_typing(
    api: AsyncClient, session: AsyncSession, fake_groq: dict[str, Any]
) -> None:
    acme, _ = await _company(api, session, groq=True)
    response = await api.post(
        f"/api/v1/orgs/{acme.org_id}/speech/transcribe",
        content=WEBM,
        headers={"Authorization": f"Bearer {acme.member_token}", "Content-Type": "audio/webm"},
    )
    assert response.status_code == 200, response.text


async def test_transcribing_without_a_groq_key_says_what_to_do(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme, headers = await _company(api, session, groq=False)
    response = await api.post(
        f"/api/v1/orgs/{acme.org_id}/speech/transcribe",
        content=WEBM,
        headers={**headers, "Content-Type": "audio/webm"},
    )
    assert response.status_code == 422
    assert "Groq key" in response.json()["detail"]


async def test_bad_uploads_are_refused_before_groq_is_called(
    api: AsyncClient, session: AsyncSession, fake_groq: dict[str, Any]
) -> None:
    acme, headers = await _company(api, session, groq=True)
    url = f"/api/v1/orgs/{acme.org_id}/speech/transcribe"

    wrong_type = await api.post(
        url, content=WEBM, headers={**headers, "Content-Type": "text/plain"}
    )
    assert wrong_type.status_code == 422

    empty = await api.post(url, content=b"", headers={**headers, "Content-Type": "audio/webm"})
    assert empty.status_code == 422

    too_big = await api.post(
        url,
        content=b"\x00" * (10 * 1024 * 1024 + 1),
        headers={**headers, "Content-Type": "audio/webm"},
    )
    assert too_big.status_code == 422

    assert "url" not in fake_groq


@pytest.mark.parametrize(("groq_status", "ours"), [(401, 422), (429, 429), (500, 502)])
async def test_groq_failures_become_clear_errors(
    api: AsyncClient,
    session: AsyncSession,
    fake_groq: dict[str, Any],
    groq_status: int,
    ours: int,
) -> None:
    acme, headers = await _company(api, session, groq=True)
    fake_groq["status"] = groq_status
    response = await api.post(
        f"/api/v1/orgs/{acme.org_id}/speech/transcribe",
        content=WEBM,
        headers={**headers, "Content-Type": "audio/webm"},
    )
    assert response.status_code == ours
    # Groq's own error text is not passed through to the browser.
    assert "nope" not in response.text


async def test_another_company_cannot_use_your_groq_key(
    api: AsyncClient, session: AsyncSession, fake_groq: dict[str, Any]
) -> None:
    acme, _ = await _company(api, session, groq=True)
    other = await seed_company(session, api, name="Globex", slug="globex")
    response = await api.post(
        f"/api/v1/orgs/{acme.org_id}/speech/transcribe",
        content=WEBM,
        headers={"Authorization": f"Bearer {other.admin_token}", "Content-Type": "audio/webm"},
    )
    assert response.status_code in (403, 404)
    assert "url" not in fake_groq
