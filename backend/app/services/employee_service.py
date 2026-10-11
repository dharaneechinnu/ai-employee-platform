"""AI Employee configuration: create, version, archive, preview."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import LimitReachedError, NotFoundError, ValidationError
from app.core.observability import get_logger
from app.db.models.ai_employee import (
    COUNTS_TOWARD_LIMIT,
    AIEmployee,
    AIEmployeeVersion,
    EmployeeStatus,
    Template,
)
from app.db.models.organization import Organization
from app.schemas.ai_employee import EmployeeConfig, GuidedInstructions

log = get_logger(__name__)


def build_system_prompt(config: EmployeeConfig, *, name: str, job_title: str | None) -> str:
    """Turn configuration into the text the model actually receives.

    An expert's raw instructions replace the guided text rather than
    being appended to it: two sets of instructions in one prompt
    contradict each other and the model picks arbitrarily.
    """
    if config.raw_instructions:
        return config.raw_instructions.strip()

    g: GuidedInstructions | None = config.guided
    if g is None:
        raise ValidationError("Provide either guided answers or raw instructions.")

    parts: list[str] = [
        f"You are {name}" + (f", the {job_title}." if job_title else "."),
        "",
        "YOUR JOB",
        g.what_it_does.strip(),
    ]

    if g.what_it_must_never_do:
        parts += ["", "YOU MUST NEVER", g.what_it_must_never_do.strip()]
    if g.tone:
        parts += ["", "TONE", g.tone.strip()]
    if g.when_to_ask_a_human:
        parts += ["", "ASK A HUMAN FIRST WHEN", g.when_to_ask_a_human.strip()]
    if g.what_good_looks_like:
        parts += ["", "A GOOD RESULT LOOKS LIKE", g.what_good_looks_like.strip()]

    parts += [
        "",
        "HOW TO WORK",
        "- Use the tools you have been given. Do not guess at information you could look up.",
        "- If a tool fails, read the error and try a different approach.",
        "- If you cannot complete the task, say so plainly and explain why. Never invent a result.",
    ]
    return "\n".join(parts)


@dataclass(slots=True)
class EmployeeWithVersion:
    employee: AIEmployee
    version: AIEmployeeVersion


class EmployeeService:
    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        self.session = session
        self.org_id = org_id

    # ------------------------------------------------------------- quota

    async def count_live(self) -> int:
        stmt = (
            select(func.count())
            .select_from(AIEmployee)
            .where(
                AIEmployee.org_id == self.org_id,
                AIEmployee.status.in_(COUNTS_TOWARD_LIMIT),
            )
        )
        return (await self.session.scalar(stmt)) or 0

    async def limit(self) -> int:
        org = await self.session.get(Organization, self.org_id)
        return org.max_employees if org else 0

    # ------------------------------------------------------------- read

    async def get(self, employee_id: uuid.UUID) -> EmployeeWithVersion:
        employee = await self.session.scalar(
            select(AIEmployee).where(AIEmployee.id == employee_id, AIEmployee.org_id == self.org_id)
        )
        if employee is None:
            # None both for "absent" and "another company's" - the caller
            # turns this into 404 either way, so ids cannot be probed.
            raise NotFoundError("No such AI Employee.")

        version = await self.session.scalar(
            select(AIEmployeeVersion)
            .where(AIEmployeeVersion.employee_id == employee_id)
            .order_by(AIEmployeeVersion.version_no.desc())
            .limit(1)
        )
        if version is None:  # pragma: no cover - creation always writes v1
            raise NotFoundError("That AI Employee has no configuration.")

        return EmployeeWithVersion(employee=employee, version=version)

    async def list_employees(self) -> list[AIEmployee]:
        result = await self.session.scalars(
            select(AIEmployee)
            .where(AIEmployee.org_id == self.org_id, AIEmployee.status != EmployeeStatus.ARCHIVED)
            .order_by(AIEmployee.created_at.desc())
        )
        return list(result.all())

    async def list_versions(self, employee_id: uuid.UUID) -> list[AIEmployeeVersion]:
        await self.get(employee_id)  # proves ownership first
        result = await self.session.scalars(
            select(AIEmployeeVersion)
            .where(AIEmployeeVersion.employee_id == employee_id)
            .order_by(AIEmployeeVersion.version_no.desc())
        )
        return list(result.all())

    # ------------------------------------------------------------- write

    async def create(
        self,
        *,
        name: str,
        job_title: str | None,
        department: str | None,
        avatar: str | None,
        config: EmployeeConfig,
        created_by: uuid.UUID,
    ) -> EmployeeWithVersion:
        used, allowed = await self.count_live(), await self.limit()
        if used >= allowed:
            # Checked here in the backend, not only on the screen: a
            # screen-only check is bypassed by calling the API directly.
            raise LimitReachedError(
                f"You have reached your limit of {allowed} AI Employees. "
                "Contact support to increase it."
            )

        # Fail before persisting anything if the configuration cannot
        # produce a prompt.
        build_system_prompt(config, name=name, job_title=job_title)

        employee = AIEmployee(
            org_id=self.org_id,
            name=name,
            job_title=job_title,
            department=department,
            avatar=avatar,
            status=EmployeeStatus.DRAFT,
            created_by=created_by,
        )
        self.session.add(employee)
        await self.session.flush()

        version = AIEmployeeVersion(
            org_id=self.org_id,
            employee_id=employee.id,
            version_no=1,
            config=config.model_dump(mode="json"),
            created_by=created_by,
        )
        self.session.add(version)
        await self.session.flush()

        employee.current_version_id = version.id
        log.info("ai_employee_created", employee_id=str(employee.id), org_id=str(self.org_id))
        return EmployeeWithVersion(employee=employee, version=version)

    async def update(
        self,
        employee_id: uuid.UUID,
        *,
        name: str | None = None,
        job_title: str | None = None,
        department: str | None = None,
        avatar: str | None = None,
        config: EmployeeConfig | None = None,
        updated_by: uuid.UUID,
    ) -> EmployeeWithVersion:
        current = await self.get(employee_id)
        employee, version = current.employee, current.version

        if name is not None:
            employee.name = name
        if job_title is not None:
            employee.job_title = job_title
        if department is not None:
            employee.department = department
        if avatar is not None:
            employee.avatar = avatar

        if config is not None:
            build_system_prompt(config, name=employee.name, job_title=employee.job_title)

            # A new row, never an update of the old one. Overwriting would
            # silently rewrite the history of every task that already ran
            # on the previous settings.
            version = AIEmployeeVersion(
                org_id=self.org_id,
                employee_id=employee.id,
                version_no=current.version.version_no + 1,
                config=config.model_dump(mode="json"),
                created_by=updated_by,
            )
            self.session.add(version)
            await self.session.flush()
            employee.current_version_id = version.id

        return EmployeeWithVersion(employee=employee, version=version)

    async def set_status(
        self, employee_id: uuid.UUID, status: EmployeeStatus
    ) -> EmployeeWithVersion:
        current = await self.get(employee_id)

        if (
            status in COUNTS_TOWARD_LIMIT
            and current.employee.status == EmployeeStatus.ARCHIVED
            and await self.count_live() >= await self.limit()
        ):
            # Restoring takes a slot back, so it has to respect the limit
            # just as creating does.
            raise LimitReachedError("Restoring this would exceed your AI Employee limit.")

        current.employee.status = status
        return current

    # ------------------------------------------------------------- templates

    async def list_templates(self) -> list[Template]:
        """Platform templates plus this company's own, never another's."""
        result = await self.session.scalars(
            select(Template)
            .where((Template.org_id.is_(None)) | (Template.org_id == self.org_id))
            .order_by(Template.org_id.is_(None).desc(), Template.name)
        )
        return list(result.all())

    async def save_as_template(
        self, *, employee_id: uuid.UUID, name: str, description: str | None
    ) -> Template:
        current = await self.get(employee_id)
        template = Template(
            org_id=self.org_id,  # always scoped: a company template is private
            name=name,
            description=description,
            department=current.employee.department,
            config=current.version.config,
        )
        self.session.add(template)
        await self.session.flush()
        return template

    async def get_template(self, template_id: uuid.UUID) -> Template:
        template = await self.session.scalar(
            select(Template).where(
                Template.id == template_id,
                (Template.org_id.is_(None)) | (Template.org_id == self.org_id),
            )
        )
        if template is None:
            raise NotFoundError("No such template.")
        return template
