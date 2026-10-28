"""Approval links: decide from an email or a Slack message.

The token in the link names one approval and its owner (the `owner`
claim; links sent earlier used the name `org`, still accepted), and
expires when the approval does. Two kinds:

- **Personal** (emailed to the owner): carries their user id, so the
  link alone is enough to decide, as them.
- **Shared** (posted to Slack): carries no user. Whoever clicks must be
  signed in, and the decision is recorded against them.

Either way the person's rights are checked now, at decision time: an
account suspended since the email was sent can no longer use its link.
Reading a link (GET) never decides anything; only the POST from the
page's button does, so a mail scanner that follows links is harmless.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Header
from pydantic import BaseModel

from app.api.v1.deps import SessionDep
from app.core.errors import AuthError, NotFoundError, PermissionDeniedError
from app.core.security import decode_access_token
from app.core.signed import InvalidSignedTokenError, verify
from app.db.models.identity import User
from app.db.models.policy import ApprovalStatus
from app.db.models.task import Run, Task
from app.services.approval_service import ApprovalService
from app.workers.queue import enqueue_task

router = APIRouter(prefix="/approval-links", tags=["approval links (public)"])


class ApprovalLinkView(BaseModel):
    approval_id: uuid.UUID
    owner_name: str
    task_title: str | None
    task_id: uuid.UUID | None
    tool_name: str
    side_effect: str
    proposed: dict[str, Any]
    status: ApprovalStatus
    expires_at: datetime
    # True for a shared (Slack) link: the page must sign the person in
    # before the decision buttons work.
    requires_sign_in: bool
    # Who the link acts as, for a personal link, so the page can say
    # "approving as ..." and nobody is surprised.
    acting_as: str | None


class DecideRequest(BaseModel):
    approve: bool


def _claims(token: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]:
    try:
        claims = verify(token, "approval_link")
        approval_id = uuid.UUID(claims["apr"])
        owner_id = uuid.UUID(claims.get("owner") or claims["org"])
        user_id = uuid.UUID(claims["sub"]) if claims.get("sub") else None
    except InvalidSignedTokenError as exc:
        raise NotFoundError(str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise NotFoundError("This link is not valid.") from exc
    return approval_id, owner_id, user_id


async def _view(
    session: SessionDep, approval_id: uuid.UUID, owner_id: uuid.UUID, user_id: uuid.UUID | None
) -> ApprovalLinkView:
    approval = await ApprovalService(session, owner_id).get(approval_id)
    run = await session.get(Run, approval.run_id)
    task = await session.get(Task, run.task_id) if run else None
    user = await session.get(User, user_id) if user_id else None
    return ApprovalLinkView(
        approval_id=approval.id,
        owner_name=(user.full_name or user.email) if user else "",
        task_title=(task.title or task.input[:120]) if task else None,
        task_id=task.id if task else None,
        tool_name=approval.tool_name,
        side_effect=approval.side_effect,
        proposed=approval.proposed,
        status=approval.status,
        expires_at=approval.expires_at,
        requires_sign_in=user_id is None,
        acting_as=user.email if user else None,
    )


@router.get("/{token}", response_model=ApprovalLinkView, summary="What this link would decide")
async def read_link(token: str, session: SessionDep) -> ApprovalLinkView:
    approval_id, owner_id, user_id = _claims(token)
    return await _view(session, approval_id, owner_id, user_id)


@router.post("/{token}/decide", response_model=ApprovalLinkView, summary="Approve or reject")
async def decide(
    token: str,
    body: DecideRequest,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> ApprovalLinkView:
    approval_id, owner_id, user_id = _claims(token)
    link_user = user_id

    if user_id is None:
        # A shared link: the clicker must prove who they are.
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError("Sign in to decide on this request.")
        try:
            payload = decode_access_token(authorization.split(" ", 1)[1].strip())
            user_id = uuid.UUID(payload["sub"])
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise AuthError("Your session is not valid. Please sign in again.") from exc

    user = await session.get(User, user_id)
    # The link names an owner; only that person may act on it.
    if user is None or not user.is_active or user_id != owner_id:
        raise PermissionDeniedError("This approval is not yours to decide.")

    approval = await ApprovalService(session, owner_id).decide(
        approval_id=approval_id, approve=body.approve, user_id=user_id
    )
    await session.commit()

    if body.approve:
        # Same as approving in the app: the paused run goes back on the
        # queue and resumes from the step that asked.
        run = await session.get(Run, approval.run_id)
        if run is not None:
            await enqueue_task(run.task_id, resume_after=approval.id)

    return await _view(session, approval_id, owner_id, link_user)
