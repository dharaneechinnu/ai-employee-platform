"""Memory: storing, recalling, isolation, and switching provider."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_company


async def test_default_provider_is_local(api: AsyncClient, session: AsyncSession) -> None:
    """Local by default: free, no key, no rate limit, and no company
    document leaves the server."""
    acme = await seed_company(session, api, name="Acme", slug="acme")

    response = await api.get(
        f"/api/v1/me/embedding-config",
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["provider_key"] == "local"
    assert response.json()["memories_needing_reembedding"] == 0


async def test_add_and_list_a_memory(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    created = await api.post(
        f"/api/v1/me/memory",
        json={"content": "We always use tabs, never spaces.", "kind": "correction"},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["kind"] == "correction"

    listed = await api.get(f"/api/v1/me/memory", headers=headers)
    assert len(listed.json()) == 1


async def test_search_finds_a_stored_memory(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    for content in [
        "The deployment script lives in scripts/deploy.sh",
        "Our staging database is called acme_staging",
        "Error ERR_4021 means the payment gateway timed out",
    ]:
        await api.post(
            f"/api/v1/me/memory", json={"content": content}, headers=headers
        )

    found = await api.post(
        f"/api/v1/me/memory/search",
        json={"query": "ERR_4021"},
        headers=headers,
    )
    assert found.status_code == 200
    assert found.json()
    assert "ERR_4021" in found.json()[0]["content"]


async def test_keyword_search_catches_exact_strings(
    api: AsyncClient, session: AsyncSession
) -> None:
    """A vector model is weak on error codes and file names, which is
    exactly what gets searched for. The keyword half covers that."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    await api.post(
        f"/api/v1/me/memory",
        json={"content": "The login bug is in LoginButton.tsx line 24"},
        headers=headers,
    )

    found = await api.post(
        f"/api/v1/me/memory/search",
        json={"query": "LoginButton.tsx"},
        headers=headers,
    )
    assert found.json()
    assert found.json()[0]["matched_by"] in ("keyword", "both")


async def test_deleting_removes_it_from_search(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    created = await api.post(
        f"/api/v1/me/memory",
        json={"content": "Temporary note about PROJECT_ZEPHYR"},
        headers=headers,
    )
    await api.delete(f"/api/v1/me/memory/{created.json()['id']}", headers=headers)

    found = await api.post(
        f"/api/v1/me/memory/search",
        json={"query": "PROJECT_ZEPHYR"},
        headers=headers,
    )
    assert found.json() == []


async def test_memory_never_crosses_company_boundaries(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Memory holds the most sensitive text in the product: business
    rules, customer notes, internal documents. A leak here is the worst
    one available."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    globex = await seed_company(session, api, name="Globex", slug="globex")

    await api.post(
        f"/api/v1/me/memory",
        json={"content": "Acme's secret margin is 42 percent"},
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )

    globex_headers = {"Authorization": f"Bearer {globex.admin_token}"}

    listed = await api.get(f"/api/v1/me/memory", headers=globex_headers)
    assert listed.json() == []

    found = await api.post(
        f"/api/v1/me/memory/search",
        json={"query": "secret margin"},
        headers=globex_headers,
    )
    assert found.json() == []


async def test_an_employee_scoped_memory_is_private_to_that_employee(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    first = await api.post(
        f"/api/v1/me/ai-employees",
        json={"name": "Bot A", "config": {"guided": {"what_it_does": "A"}}},
        headers=headers,
    )
    second = await api.post(
        f"/api/v1/me/ai-employees",
        json={"name": "Bot B", "config": {"guided": {"what_it_does": "B"}}},
        headers=headers,
    )

    await api.post(
        f"/api/v1/me/memory",
        json={
            "content": "Bot A prefers the ZEBRA convention",
            "scope": "employee",
            "employee_id": first.json()["id"],
        },
        headers=headers,
    )

    for_b = await api.post(
        f"/api/v1/me/memory/search",
        json={"query": "ZEBRA convention", "employee_id": second.json()["id"]},
        headers=headers,
    )
    assert for_b.json() == []

    for_a = await api.post(
        f"/api/v1/me/memory/search",
        json={"query": "ZEBRA convention", "employee_id": first.json()["id"]},
        headers=headers,
    )
    assert for_a.json()


async def test_switching_provider_requires_reembedding_and_search_refuses(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Comparing vectors from two models computes a number and means
    nothing. Refusing is the only honest behaviour: silent nonsense is
    far worse than a clear error."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    await api.post(
        f"/api/v1/me/memory",
        json={"content": "Something worth remembering"},
        headers=headers,
    )

    switched = await api.put(
        f"/api/v1/me/embedding-config",
        json={"provider_key": "openai", "api_key": "sk-test-key-1234"},
        headers=headers,
    )
    assert switched.status_code == 200
    assert switched.json()["memories_needing_reembedding"] == 1

    refused = await api.post(
        f"/api/v1/me/memory/search",
        json={"query": "something"},
        headers=headers,
    )
    assert refused.status_code == 409
    assert "re-embedding" in refused.json()["detail"].lower()


async def test_switching_back_restores_search_without_reembedding(
    api: AsyncClient, session: AsyncSession
) -> None:
    """The original vectors were never deleted, so returning to the
    provider that wrote them makes search valid again immediately."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    await api.post(
        f"/api/v1/me/memory",
        json={"content": "The build runs on node 20"},
        headers=headers,
    )

    await api.put(
        f"/api/v1/me/embedding-config",
        json={"provider_key": "openai", "api_key": "sk-test-key-1234"},
        headers=headers,
    )
    await api.put(
        f"/api/v1/me/embedding-config",
        json={"provider_key": "local"},
        headers=headers,
    )

    config = await api.get(f"/api/v1/me/embedding-config", headers=headers)
    assert config.json()["memories_needing_reembedding"] == 0

    found = await api.post(
        f"/api/v1/me/memory/search", json={"query": "node 20"}, headers=headers
    )
    assert found.status_code == 200
    assert found.json()


async def test_reembedding_moves_vectors_to_the_new_model(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-embedding rewrites every vector with the current provider.

    The replacement provider is local with a different name and width,
    so the whole path runs - new table, new model recorded - with no
    network call and no API key.
    """
    import app.services.memory_service as memory_service
    from app.agent.embeddings import LocalEmbeddingProvider

    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    await api.post(
        f"/api/v1/me/memory",
        json={"content": "The build runs on node 20"},
        headers=headers,
    )

    def fake_builder(provider_key: str, *, api_key: str | None = None, model: str | None = None):
        # A 768-wide local embedder, so the row has to move tables.
        return LocalEmbeddingProvider(model or "text-embedding-004", 768)

    monkeypatch.setattr(memory_service, "build_embedding_provider", fake_builder)

    await api.put(
        f"/api/v1/me/embedding-config",
        json={"provider_key": "gemini", "api_key": "test-key"},
        headers=headers,
    )

    before = await api.get(f"/api/v1/me/embedding-config", headers=headers)
    assert before.json()["memories_needing_reembedding"] == 1

    done = await api.post(f"/api/v1/me/embedding-config/reembed", headers=headers)
    assert done.json()["reembedded"] == 1

    after = await api.get(f"/api/v1/me/embedding-config", headers=headers)
    assert after.json()["memories_needing_reembedding"] == 0

    found = await api.post(
        f"/api/v1/me/memory/search", json={"query": "node 20"}, headers=headers
    )
    assert found.status_code == 200
    assert found.json()


