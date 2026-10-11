"""The permission matrix.

Permissions live in one table rather than scattered `if role == "admin"`
checks. Two reasons:

1. A test can walk every route and assert it declares a permission, so a
   forgotten guard fails CI instead of shipping.
2. Adding a read-only Viewer role later is an edit to this dict, not a
   hunt through the codebase.

The guiding split: **Admin builds, Member uses.**
"""

from __future__ import annotations

from enum import StrEnum

from app.db.models.identity import Role


class Permission(StrEnum):
    # people
    MEMBER_READ = "member:read"
    MEMBER_MANAGE = "member:manage"
    ORG_MANAGE = "org:manage"

    # AI employees (phase 2)
    EMPLOYEE_READ = "employee:read"
    EMPLOYEE_WRITE = "employee:write"

    # daily work (phase 4)
    TASK_READ = "task:read"
    TASK_CREATE = "task:create"
    TASK_CANCEL_ANY = "task:cancel_any"

    # integrations and providers (phases 3, 5)
    CONNECTION_MANAGE = "connection:manage"
    PROVIDER_MANAGE = "provider:manage"

    # permissions and approvals (phase 5)
    POLICY_MANAGE = "policy:manage"
    APPROVAL_DECIDE = "approval:decide"

    # memory (phase 6)
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"

    # cost (phase 9)
    USAGE_READ = "usage:read"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),  # admin holds every company-level permission
    Role.MEMBER: frozenset(
        {
            Permission.MEMBER_READ,
            Permission.EMPLOYEE_READ,
            Permission.TASK_READ,
            Permission.TASK_CREATE,
            Permission.MEMORY_READ,
        }
    ),
}


def role_has(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
