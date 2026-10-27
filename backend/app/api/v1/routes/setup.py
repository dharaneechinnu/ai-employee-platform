"""Setup progress: the one endpoint the setup bar and the guides read."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.v1.deps import ContextDep, SessionDep
from app.services.setup_service import STEPS, SetupService, SetupStatus

router = APIRouter(prefix="/me", tags=["setup"])


class SetupResponse(BaseModel):
    steps: list[str]
    done: list[str]
    next_step: str | None
    complete: bool
    # provider key -> guide steps already finished
    guide: dict[str, list[str]]


class GuideStepBody(BaseModel):
    provider: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$")
    step: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_-]+$")


def _response(status: SetupStatus) -> SetupResponse:
    return SetupResponse(
        steps=list(STEPS),
        done=status.done,
        next_step=status.next_step,
        complete=status.complete,
        guide=status.guide,
    )


@router.get("/setup", response_model=SetupResponse, summary="How far setup has got")
async def get_setup(ctx: ContextDep, session: SessionDep) -> SetupResponse:
    return _response(await SetupService(session, ctx.owner_id).status())


@router.post("/setup/guide", response_model=SetupResponse, summary="Mark a guide step done")
async def mark_guide_step(
    body: GuideStepBody, ctx: ContextDep, session: SessionDep
) -> SetupResponse:
    return _response(
        await SetupService(session, ctx.owner_id).mark_guide_step(body.provider, body.step)
    )
