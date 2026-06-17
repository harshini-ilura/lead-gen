"""Phase 5 — email verification worker.

Verifies one contact_email's deliverability (free MX tier + optional paid tier),
writes the status, and recomputes which of a contact's candidate emails is primary.
"""
import logging

import redis.asyncio as aioredis
from sqlalchemy import func, select, update

from app.config import get_settings
from app.db.models import ContactEmail
from app.db.session import AsyncSessionLocal, run_task
from app.services.email_verify import is_role, verify_email
from celery_app import celery

logger = logging.getLogger(__name__)

# Ranking weights for choosing a contact's primary email.
_STATUS_RANK = {"valid": 4, "mx_ok": 3, "risky": 2, "unknown": 1, "invalid": 0}


@celery.task(
    name="app.workers.verify.verify_contact_email",
    queue="verify",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    rate_limit="100/m",
)
def verify_contact_email(self, email_id: int):
    try:
        run_task(_verify(email_id))
    except Exception as exc:
        logger.exception("verify_contact_email failed: email_id=%d", email_id)
        if self.request.retries >= self.max_retries:
            return
        raise self.retry(exc=exc)


async def _verify(email_id: int):
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url)
    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(ContactEmail).where(ContactEmail.email_id == email_id)
                )
            ).scalar_one_or_none()
            if not row:
                return

            status = await verify_email(row.email, settings, redis)
            local_part = row.email.split("@", 1)[0]

            await session.execute(
                update(ContactEmail)
                .where(ContactEmail.email_id == email_id)
                .values(
                    verification_status=status,
                    is_role_email=is_role(local_part),
                    verified_at=func.now(),
                )
            )
            await _recompute_primary(session, row.contact_id)
            await session.commit()
        logger.info("verified email_id=%d status=%s", email_id, status)
    finally:
        await redis.aclose()


async def _recompute_primary(session, contact_id):
    """Pick the single best email for a contact. Deterministic ranking so
    concurrent per-email verifies converge to the same winner."""
    if contact_id is None:
        return
    rows = (
        await session.execute(
            select(ContactEmail)
            .where(ContactEmail.contact_id == contact_id)
            .with_for_update()
        )
    ).scalars().all()
    if not rows:
        return

    def rank(e: ContactEmail):
        return (
            _STATUS_RANK.get(e.verification_status, 1),
            0 if e.is_role_email else 1,                      # personal > role
            1 if e.verification_source == "crawled" else 0,   # real > generated
            1 if e.generation_confidence == "high" else 0,    # high > low
            -e.email_id,                                      # tiebreak: lowest id
        )

    best = max(rows, key=rank)
    await session.execute(
        update(ContactEmail)
        .where(ContactEmail.contact_id == contact_id)
        .values(is_primary=False)
    )
    # Never make a known-undeliverable address the primary.
    if best.verification_status != "invalid":
        await session.execute(
            update(ContactEmail)
            .where(ContactEmail.email_id == best.email_id)
            .values(is_primary=True)
        )
