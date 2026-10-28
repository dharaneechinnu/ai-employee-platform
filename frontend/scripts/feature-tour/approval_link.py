"""Print the signed approval link token for a person's oldest pending approval.

The same token the app puts in an approval email (approval_link_token), so
capture.mjs can open the real /approve/<token> page without a mail server.
Run from backend/ with the API's environment:

    ENVIRONMENT=dev python ../frontend/scripts/feature-tour/approval_link.py priya
"""

import asyncio
import sys

from sqlalchemy import select

from app.db.models.identity import User
from app.db.models.policy import Approval, ApprovalStatus
from app.db.session import get_sessionmaker
from app.services.notification_service import approval_link_token


async def main(username: str) -> None:
    async with get_sessionmaker()() as s:
        user = (await s.execute(select(User).where(User.username == username))).scalar_one()
        approval = (
            await s.execute(
                select(Approval)
                .where(Approval.owner_id == user.id, Approval.status == ApprovalStatus.PENDING)
                .order_by(Approval.created_at)
            )
        ).scalars().first()
        if approval is None:
            sys.exit(f"{username} has nothing waiting for approval: run seed.mjs first")
        print(approval_link_token(approval, user.id))


asyncio.run(main(sys.argv[1]))
