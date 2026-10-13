"""Platform Admin operations: creating and governing companies.

The boundary that matters: nothing here reads customer content. A
Platform Admin sees how many and how healthy, never what. There is no
method on this service that returns a task, a memory, a credential or a
message — by design, so the capability does not exist to be misused.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.core.errors import ConflictError, InvalidCredentialsError, NotFoundError
from app.core.observability import get_logger
from app.core.security import create_access_token, hash_password, hash_token, verify_password
from app.db.models.ai_employee import COUNTS_TOWARD_LIMIT, AIEmployee
from app.db.models.identity import Invitation, Membership, PlatformAdmin, Role
from app.db.models.organization import Organization, OrgStatus
from app.db.repositories.identity_repo import OrganizationRepository, PlatformAdminRepository

log = get_logger(__name__)


@dataclass(slots=True)
class CompanyStats:
    org: Organization
    member_count: int
    employee_count: int = 0  # populated from phase 2 onward


class PlatformService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.admins = PlatformAdminRepository(session)
        self.orgs = OrganizationRepository(session)
        self.settings = get_settings()

    # ------------------------------------------------------------- admins

    async def create_admin(self, *, email: str, password: str) -> tuple[PlatformAdmin, str]:
        """Create a platform admin and return the TOTP secret once.

        Used by the bootstrap script. The secret is shown exactly here,
        for entering into an authenticator app; afterwards only the
        encrypted form exists.
        """
        email = email.lower()
        if await self.admins.get_by_email(email):
            raise ConflictError("A platform admin with that email already exists.")

        totp_secret = pyotp.random_base32()
        admin = PlatformAdmin(
            email=email,
            password_hash=hash_password(password),
            totp_secret_enc=encrypt(totp_secret, scope="platform"),
            totp_confirmed=True,
        )
        self.session.add(admin)
        await self.session.flush()
        return admin, totp_secret

    async def login(self, *, email: str, password: str, totp_code: str) -> str:
        """Password *and* a valid TOTP code. Both, always.

        This account can create and suspend every company, so a leaked
        password alone must not be enough.
        """
        admin = await self.admins.get_by_email(email)

        if admin is None:
            hash_password(password)  # keep timing similar to a real miss
            raise InvalidCredentialsError()

        if not verify_password(password, admin.password_hash) or not admin.is_active:
            raise InvalidCredentialsError()

        secret = decrypt(admin.totp_secret_enc, scope="platform")
        if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
            log.warning("platform_admin_totp_failed", admin_id=str(admin.id))
            raise InvalidCredentialsError("Email, password or code is incorrect.")

        admin.last_login_at = datetime.now(UTC)
        self.admins.record_audit(admin_id=admin.id, action="platform_login")

        return create_access_token(
            subject=admin.id,
            token_type="platform_access",  # noqa: S106 - a token kind, not a secret
        )

    # ------------------------------------------------------------- companies

    async def create_company(
        self,
        *,
        admin_id: uuid.UUID,
        name: str,
        slug: str,
        first_admin_email: str,
        max_employees: int,
    ) -> tuple[Organization, str]:
        """Create a company and its first invite.

        There is no public sign-up, so this is how every company begins.
        It is Active immediately — no approval queue, because the
        Platform Admin creating it *is* the approval.
        """
        slug = slug.lower().strip()
        if await self.orgs.get_by_slug(slug):
            raise ConflictError(f"A company with the slug '{slug}' already exists.")

        org = Organization(
            name=name, slug=slug, max_employees=max_employees, status=OrgStatus.ACTIVE
        )
        self.session.add(org)
        await self.session.flush()

        raw_token = secrets.token_urlsafe(32)
        self.session.add(
            Invitation(
                org_id=org.id,
                email=first_admin_email.lower(),
                role=Role.ADMIN,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(hours=self.settings.invite_expiry_hours),
            )
        )

        self.admins.record_audit(
            admin_id=admin_id,
            action="company_created",
            target_type="organization",
            target_id=str(org.id),
            detail=f"slug={slug} max_employees={max_employees}",
        )
        log.info("company_created", org_id=str(org.id), slug=slug)
        return org, raw_token

    async def list_companies(self) -> list[CompanyStats]:
        """Counts and health only. No customer content.

        Members and AI Employees are counted in separate subqueries
        rather than two joins: joining both at once multiplies the rows
        together, so a company with 2 members and 3 employees would
        report 6 of each.
        """
        member_counts = (
            select(Membership.org_id, func.count().label("members"))
            .group_by(Membership.org_id)
            .subquery()
        )
        employee_counts = (
            select(AIEmployee.org_id, func.count().label("employees"))
            .where(AIEmployee.status.in_(COUNTS_TOWARD_LIMIT))
            .group_by(AIEmployee.org_id)
            .subquery()
        )

        rows = await self.session.execute(
            select(
                Organization,
                func.coalesce(member_counts.c.members, 0),
                func.coalesce(employee_counts.c.employees, 0),
            )
            .outerjoin(member_counts, member_counts.c.org_id == Organization.id)
            .outerjoin(employee_counts, employee_counts.c.org_id == Organization.id)
            .order_by(Organization.created_at)
        )
        return [
            CompanyStats(org=org, member_count=members, employee_count=employees)
            for org, members, employees in rows.all()
        ]

    async def set_status(
        self, *, admin_id: uuid.UUID, org_id: uuid.UUID, status: OrgStatus
    ) -> Organization:
        org = await self.orgs.get(org_id)
        if org is None:
            raise NotFoundError("No such company.")

        org.status = status
        self.admins.record_audit(
            admin_id=admin_id,
            action=f"company_{status.value}",
            target_type="organization",
            target_id=str(org_id),
        )
        return org

    async def set_employee_limit(
        self, *, admin_id: uuid.UUID, org_id: uuid.UUID, max_employees: int
    ) -> Organization:
        org = await self.orgs.get(org_id)
        if org is None:
            raise NotFoundError("No such company.")

        previous = org.max_employees
        org.max_employees = max_employees
        self.admins.record_audit(
            admin_id=admin_id,
            action="employee_limit_changed",
            target_type="organization",
            target_id=str(org_id),
            detail=f"{previous} -> {max_employees}",
        )
        return org
