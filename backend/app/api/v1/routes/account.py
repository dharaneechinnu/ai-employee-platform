"""The signed-in person's own account.

What is left of the old `orgs` routes once companies went: members,
invites and role changes all described a company, and there is none.
First-time setup progress is not about a company at all — it is about
whether *this person* has what they need to run anything — so it moves
here.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.v1.deps import ContextDep, SessionDep
from app.db.models.ai_employee import AIEmployee, EmployeeStatus
from app.db.models.policy import Connection
from app.db.models.provider import ProviderConfig
from app.db.models.task import Task

router = APIRouter(prefix="/me", tags=["account"])


class SetupStatus(BaseModel):
    """How far this account is through first-time setup.

    Counts only. Enough to explain why nothing runs yet — no AI key,
    no apps connected — without showing the key itself.
    """

    ai_connected: bool
    apps_connected: bool
    employees: int
    employees_active: int
    tasks: int


@router.get("/setup", summary="First-time setup progress")
async def setup_status(ctx: ContextDep, session: SessionDep) -> SetupStatus:
    async def count(stmt: object) -> int:
        return int(await session.scalar(stmt) or 0)  # type: ignore[call-overload]

    me = ctx.owner_id
    return SetupStatus(
        ai_connected=await count(
            select(func.count()).select_from(ProviderConfig).where(ProviderConfig.owner_id == me)
        )
        > 0,
        apps_connected=await count(
            select(func.count())
            .select_from(Connection)
            .where(Connection.owner_id == me, Connection.enabled.is_(True))
        )
        > 0,
        employees=await count(
            select(func.count()).select_from(AIEmployee).where(AIEmployee.owner_id == me)
        ),
        employees_active=await count(
            select(func.count())
            .select_from(AIEmployee)
            .where(AIEmployee.owner_id == me, AIEmployee.status == EmployeeStatus.ACTIVE)
        ),
        tasks=await count(select(func.count()).select_from(Task).where(Task.owner_id == me)),
    )


__all__ = ["router"]
