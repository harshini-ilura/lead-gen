"""Phase 4 — email generation.

For a contact without a real (crawled) email, generate likely addresses from the
person's name + company domain. The company's pattern is inferred from real emails
found in Phase 3 when available (high confidence); otherwise common patterns are
tried (low confidence). Each generated email is enqueued for Phase 5 verification.
"""
import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import Company, Contact, ContactEmail
from app.db.session import AsyncSessionLocal, run_task
from app.services.email_patterns import (
    DEFAULT_PATTERNS,
    generate,
    infer_company_patterns,
)
from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="app.workers.email_gen.generate_contact_emails",
    queue="contacts",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def generate_contact_emails(self, contact_id: int):
    try:
        run_task(_generate(contact_id))
    except Exception as exc:
        logger.exception("generate_contact_emails failed: contact_id=%d", contact_id)
        if self.request.retries >= self.max_retries:
            return
        raise self.retry(exc=exc)


async def _generate(contact_id: int):
    async with AsyncSessionLocal() as session:
        contact = (
            await session.execute(
                select(Contact).where(Contact.contact_id == contact_id)
            )
        ).scalar_one_or_none()
        if not contact:
            return

        # Trust real emails — never generate over a crawled one.
        existing = (
            await session.execute(
                select(ContactEmail.verification_source).where(
                    ContactEmail.contact_id == contact_id
                )
            )
        ).scalars().all()
        if "crawled" in existing:
            return

        domain = (
            await session.execute(
                select(Company.domain).where(Company.company_id == contact.company_id)
            )
        ).scalar_one_or_none()
        if not domain or not contact.first_name:
            logger.info("skip email_gen: contact_id=%d (no domain or first name)", contact_id)
            return

        # Infer the company's pattern from its real (corporate-domain) emails.
        rows = (
            await session.execute(
                select(Contact.first_name, Contact.last_name, ContactEmail.email)
                .join(ContactEmail, ContactEmail.contact_id == Contact.contact_id)
                .where(
                    Contact.company_id == contact.company_id,
                    ContactEmail.verification_source == "crawled",
                )
            )
        ).all()
        known = [
            (f, l, email.split("@", 1)[0])
            for f, l, email in rows
            if email.split("@", 1)[-1] == domain
        ]
        inferred = infer_company_patterns(known)

        if inferred:
            patterns, confidence = inferred[:2], "high"
        else:
            patterns, confidence = DEFAULT_PATTERNS, "low"

        candidates = generate(contact.first_name, contact.last_name, domain, patterns)

        new_email_ids = []
        for email, pattern_name in candidates:
            email_id = (
                await session.execute(
                    pg_insert(ContactEmail)
                    .values(
                        contact_id=contact_id,
                        email=email,
                        pattern=pattern_name,
                        generation_confidence=confidence,
                        verification_source="generated",
                        verification_status="unknown",
                        is_role_email=False,
                    )
                    .on_conflict_do_nothing(constraint="uq_contact_emails_contact_email")
                    .returning(ContactEmail.email_id)
                )
            ).scalar_one_or_none()
            if email_id is not None:
                new_email_ids.append(email_id)
        await session.commit()

    for email_id in new_email_ids:
        celery.send_task(
            "app.workers.verify.verify_contact_email", args=[email_id], queue="verify"
        )
    logger.info(
        "email_gen done: contact_id=%d generated=%d confidence=%s",
        contact_id, len(new_email_ids), confidence if candidates else "n/a",
    )
