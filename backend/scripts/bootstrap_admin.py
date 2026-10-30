"""Create the first platform admin.

    python -m scripts.bootstrap_admin --email admin@example.com --password '...'

Prints the password once if one was generated. Sign-in is email and
password only; there is no second factor on this account, so treat
the password as the key that can create and suspend every account on
the platform. It cannot read anyone's content.

Next step: sign in at /platform, create a person's account on People,
and send them the one-time setup link it shows.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets

from pydantic import TypeAdapter, ValidationError
from pydantic.networks import EmailStr
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import get_engine
from app.services.platform_service import PlatformService


async def main(email: str, password: str | None) -> None:
    # Validate exactly as the login endpoint does. Without this the
    # script happily creates an admin at a reserved domain such as
    # .local or .test, and that account can never sign in.
    try:
        TypeAdapter(EmailStr).validate_python(email)
    except ValidationError as exc:
        raise SystemExit(f"That email will be rejected at login: {exc.errors()[0]['msg']}") from exc

    password = password or secrets.token_urlsafe(24)

    maker = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with maker() as session:
        admin = await PlatformService(session).create_admin(email=email, password=password)
        await session.commit()

    print("\nPlatform admin created.")
    print(f"  email:       {admin.email}")
    print(f"  password:    {password}")
    print("\nThis password is the only thing guarding every account on the")
    print("platform. Store it in a password manager and do not reuse it.")
    print("Next: sign in at /platform and create an account on People.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default=None, help="generated if omitted")
    args = parser.parse_args()
    asyncio.run(main(args.email, args.password))
