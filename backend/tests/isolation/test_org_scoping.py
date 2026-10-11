"""Tenant-isolation guard.

This is the most important test in the repository.

Every table that holds customer data must carry ``org_id`` directly —
not inferred by joining through a parent. That is what lets the
repository layer filter on it in one place, and what makes a leak a
single-file audit rather than a codebase-wide one.

A table added without ``org_id`` fails CI. Adding a name to
GLOBAL_TABLES requires a reviewer to agree it genuinely holds no
customer data.
"""

from app.db.models import Base

# Tables that are deliberately NOT tenant-scoped, with the reason.
GLOBAL_TABLES: dict[str, str] = {
    "organizations": "the tenant itself — scoped by its own id",
    "users": "a person may belong to several companies; the link is memberships",
    "refresh_tokens": "belongs to a user, who spans companies",
    "platform_admins": "platform staff, deliberately separate from users",
    "platform_admin_audit": "platform-level audit trail, not customer data",
    "supported_providers": "the provider menu, curated platform-wide",
    "policy_defaults": "platform-wide starting values, overridden per company",
}


def test_every_tenant_table_has_org_id() -> None:
    missing: list[str] = []

    for mapper in Base.registry.mappers:
        table = mapper.class_.__tablename__
        if table in GLOBAL_TABLES:
            continue
        if "org_id" not in mapper.class_.__table__.columns:
            missing.append(table)

    assert not missing, (
        f"These tables are missing org_id: {sorted(missing)}. "
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
