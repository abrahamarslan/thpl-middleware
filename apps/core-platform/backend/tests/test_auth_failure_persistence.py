"""Regression: failed-auth state + failure audits must survive the 401.

HTTP requests run through the real ``get_db`` dependency, whose ``except``
rolls the transaction back when a domain error (``AuthError``) is raised. Any
counter/audit written just before the raise must be committed explicitly, or it
is silently lost — defeating lockout and the OTP/reset attempt caps.
"""

import uuid

import httpx
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database.db import engine
from app.main import app
from app.modules.activity.model import ActivityLog
from app.modules.users.model import User


async def test_failed_login_persists_counter_and_audit(db):
    email = f"persist-{uuid.uuid4().hex[:8]}@example.com"

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reg = await client.post(
            "/api/auth/register",
            json={"name": "Persist", "email": email, "password": "Str0ngPass1"},
        )
        assert reg.status_code == 201, reg.text

        bad = await client.post(
            "/api/auth/login", json={"identifier": email, "password": "wrong-pass"}
        )
        assert bad.status_code == 401, bad.text

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = (await session.scalars(select(User).where(User.email == email))).one()
        assert user.failed_login_attempts == 1, "failed-attempt counter was rolled back"

        audits = (
            await session.scalars(
                select(ActivityLog).where(
                    ActivityLog.action == "auth.login.failure",
                    ActivityLog.subject_id == str(user.id),
                )
            )
        ).all()
        assert audits, "failure audit was rolled back"
