"""Create the first platform admin.

    python -m scripts.bootstrap_admin --email you@example.com --password '...'

Prints the TOTP secret exactly once, for entering into an authenticator
app. It is stored encrypted and cannot be read back afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import get_engine
from app.services.platform_service import PlatformService


async def main(email: str, password: str | None) -> None:
    password = password or secrets.token_urlsafe(24)

    maker = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with maker() as session:
        admin, totp_secret = await PlatformService(session).create_admin(
            email=email, password=password
        )
        await session.commit()

    print("\nPlatform admin created.")
    print(f"  email:       {admin.email}")
    print(f"  password:    {password}")
    print(f"  TOTP secret: {totp_secret}")
    print("\nAdd the TOTP secret to an authenticator app now.")
    print("It is stored encrypted and will not be shown again.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default=None, help="generated if omitted")
    args = parser.parse_args()
    asyncio.run(main(args.email, args.password))
