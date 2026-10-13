"""AI Employee configuration: the normal path."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_company

GUIDED = {
    "what_it_does": "Read bug reports and open a pull request with a fix.",
    "what_it_must_never_do": "Never delete code.",
    "tone": "Short and precise.",
    "when_to_ask_a_human": "Before opening a pull request.",
    "what_good_looks_like": "A pull request with a clear explanation.",
}


def _payload(name: str = "Bug Fixer Bot") -> dict[str, object]:
    return {
        "name": name,
        "job_title": "GitHub Helper",
        "department": "Engineering",
        "config": {"guided": GUIDED, "model": "gemini-flash", "max_steps": 15},
    }


async def test_create_and_read_an_ai_employee(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload(), headers=headers
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Bug Fixer Bot"
    assert body["version_no"] == 1
    assert body["status"] == "draft"

    fetched = await api.get(
        f"/api/v1/orgs/{acme.org_id}/ai-employees/{body['id']}", headers=headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["config"]["guided"]["what_it_does"] == GUIDED["what_it_does"]


async def test_editing_creates_a_new_version(api: AsyncClient, session: AsyncSession) -> None:
    """The old version stays readable. Otherwise "why did it do that last
    Tuesday?" becomes unanswerable after any edit."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload(), headers=headers
    )
    employee_id = created.json()["id"]

    updated = await api.patch(
        f"/api/v1/orgs/{acme.org_id}/ai-employees/{employee_id}",
        json={"config": {"guided": {**GUIDED, "tone": "Formal."}, "max_steps": 20}},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["version_no"] == 2

    versions = await api.get(
        f"/api/v1/orgs/{acme.org_id}/ai-employees/{employee_id}/versions", headers=headers
    )
    assert [v["version_no"] for v in versions.json()] == [2, 1]
    # Version 1 still holds the original wording.
    assert versions.json()[1]["config"]["guided"]["tone"] == "Short and precise."


async def test_preview_shows_the_assembled_prompt(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload(), headers=headers
    )
    preview = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees/{created.json()['id']}/preview-prompt",
        headers=headers,
    )

    assert preview.status_code == 200
    prompt = preview.json()["system_prompt"]
    assert "Bug Fixer Bot" in prompt
    assert "Never delete code." in prompt
    assert preview.json()["character_count"] == len(prompt)


async def test_employee_limit_is_enforced(api: AsyncClient, session: AsyncSession) -> None:
    """The company's limit is 3. The fourth is refused."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    for i in range(3):
        created = await api.post(
            f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload(f"Bot {i}"), headers=headers
        )
        assert created.status_code == 201

    fourth = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload("Bot 4"), headers=headers
    )
    assert fourth.status_code == 409
    assert "limit" in fourth.json()["detail"].lower()


async def test_archiving_frees_a_slot(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    ids = []
    for i in range(3):
        created = await api.post(
            f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload(f"Bot {i}"), headers=headers
        )
        ids.append(created.json()["id"])

    await api.delete(f"/api/v1/orgs/{acme.org_id}/ai-employees/{ids[0]}", headers=headers)

    allowed_again = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload("Bot 4"), headers=headers
    )
    assert allowed_again.status_code == 201


async def test_list_reports_usage_against_the_limit(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    await api.post(f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload(), headers=headers)

    listed = await api.get(f"/api/v1/orgs/{acme.org_id}/ai-employees", headers=headers)
    body = listed.json()
    assert body["used"] == 1
    assert body["limit"] == 3
    assert len(body["items"]) == 1


async def test_activate_and_pause(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload(), headers=headers
    )
    employee_id = created.json()["id"]

    activated = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees/{employee_id}/activate", headers=headers
    )
    assert activated.json()["status"] == "active"

    paused = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees/{employee_id}/pause", headers=headers
    )
    assert paused.json()["status"] == "paused"


async def test_platform_templates_are_available(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    listed = await api.get(f"/api/v1/orgs/{acme.org_id}/templates", headers=headers)
    assert listed.status_code == 200
    names = {t["name"] for t in listed.json()}
    assert {"DevOps Helper", "Support Agent", "HR Helper"} <= names
    assert all(t["is_platform_template"] for t in listed.json())


async def test_create_from_a_template(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    templates = await api.get(f"/api/v1/orgs/{acme.org_id}/templates", headers=headers)
    devops = next(t for t in templates.json() if t["name"] == "DevOps Helper")

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees",
        json={"name": "Ravi", "config": {}, "template_id": devops["id"]},
        headers=headers,
    )
    assert created.status_code == 201
    config = created.json()["config"]
    assert "incident" in config["guided"]["what_it_does"].lower()
    # Templates promise only what real tools can do, and come with them ticked.
    assert "run_query" in config["enabled_tools"]
    assert config["model"] == "auto"


async def test_save_an_employee_as_a_company_template(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees", json=_payload(), headers=headers
    )

    saved = await api.post(
        f"/api/v1/orgs/{acme.org_id}/templates",
        json={
            "name": "Our Bug Fixer",
            "description": "House style",
            "employee_id": created.json()["id"],
        },
        headers=headers,
    )
    assert saved.status_code == 201
    assert saved.json()["is_platform_template"] is False


async def test_a_company_template_stays_inside_that_company(
    api: AsyncClient, session: AsyncSession
) -> None:
    """A company template can encode private business rules, so it must
    never appear in another customer's list."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    globex = await seed_company(session, api, name="Globex", slug="globex")

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees",
        json=_payload(),
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )
    await api.post(
        f"/api/v1/orgs/{acme.org_id}/templates",
        json={"name": "Acme Secret Sauce", "employee_id": created.json()["id"]},
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )

    globex_templates = await api.get(
        f"/api/v1/orgs/{globex.org_id}/templates",
        headers={"Authorization": f"Bearer {globex.admin_token}"},
    )
    assert "Acme Secret Sauce" not in {t["name"] for t in globex_templates.json()}


async def test_a_member_cannot_create_an_ai_employee(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Admin builds, Member uses."""
    acme = await seed_company(session, api, name="Acme", slug="acme")

    response = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees",
        json=_payload(),
        headers={"Authorization": f"Bearer {acme.member_token}"},
    )
    assert response.status_code == 403
