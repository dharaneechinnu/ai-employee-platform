"""Tenant-isolation guard.

This is the most important test in the repository.

Every table that holds customer data must carry ``owner_id`` directly —
not inferred by joining through a parent. That is what lets the
repository layer filter on it in one place, and what makes a leak a
single-file audit rather than a codebase-wide one.

A table added without ``owner_id`` fails CI. Adding a name to
GLOBAL_TABLES requires a reviewer to agree it genuinely holds no
customer data.
"""

from app.db.models import Base

# Tables that are deliberately NOT tenant-scoped, with the reason.
GLOBAL_TABLES: dict[str, str] = {
    "users": "the owner itself — scoped by its own id",
    "refresh_tokens": "belongs to a user, and is reached only through that user's id",
    "setup_tokens": (
        "a one-time link for an account that has no password yet, so it is "
        "looked up by its own hash before anyone is signed in"
    ),
    "platform_admins": "platform staff, deliberately separate from users",
    "platform_admin_audit": "platform-level audit trail, not customer data",
    "supported_providers": "the provider menu, curated platform-wide",
    "platform_oauth_apps": (
        "one Google/Microsoft app registration serves every company; "
        "the per-company half is the refresh token in connections, which is scoped"
    ),
    "policy_defaults": "platform-wide starting values, overridden per company",
    "platform_service_access": (
        "which parts of an app (Gmail, Drive, Sheets; read or edit) the platform allows "
        "at all; the per-company half is org_service_access, which is scoped"
    ),
    "platform_connection_access": (
        "whether each kind of app (GitHub, PostgreSQL, Slack...) is open to everyone; "
        "the per-person half is org_connection_access, which is scoped"
    ),
}


def test_every_scoped_table_has_owner_id() -> None:
    missing: list[str] = []

    for mapper in Base.registry.mappers:
        table = mapper.class_.__tablename__
        if table in GLOBAL_TABLES:
            continue
        if "owner_id" not in mapper.class_.__table__.columns:
            missing.append(table)

    assert not missing, (
        f"These tables are missing owner_id: {sorted(missing)}. "
        "Add the column, or add the table to GLOBAL_TABLES with a written reason."
    )


def test_global_table_whitelist_is_documented() -> None:
    """Every exemption must carry a reason, so none is added silently."""
    undocumented = [name for name, reason in GLOBAL_TABLES.items() if not reason.strip()]
    assert not undocumented, f"GLOBAL_TABLES entries need a reason: {undocumented}"


def test_global_table_whitelist_entries_exist() -> None:
    """Stop the whitelist drifting out of date as tables are renamed."""
    known = {mapper.class_.__tablename__ for mapper in Base.registry.mappers}
    stale = [name for name in GLOBAL_TABLES if name not in known]
    assert not stale, f"GLOBAL_TABLES names tables that no longer exist: {stale}"
