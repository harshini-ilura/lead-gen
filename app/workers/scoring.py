"""Phase 6 — lead scoring worker.

Scores every contact of a company by combining the contact's primary (verified)
email, seniority, company quality, and completeness into Contact.confidence_score.
"""
import logging

from sqlalchemy import select, update

from app.db.models import Company, Contact, ContactEmail
from app.db.session import AsyncSessionLocal, run_task
from app.services.scoring import score_lead
from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="app.workers.scoring.score_company",
    queue="scoring",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def score_company(self, company_id: int):
    try:
        run_task(_score(company_id))
    except Exception as exc:
        logger.exception("score_company failed: company_id=%d", company_id)
        if self.request.retries >= self.max_retries:
            return
        raise self.retry(exc=exc)


async def _score(company_id: int):
    async with AsyncSessionLocal() as session:
        company_conf = (
            await session.execute(
                select(Company.confidence_score).where(Company.company_id == company_id)
            )
        ).scalar_one_or_none()

        # Each contact + its primary email (if any).
        rows = (
            await session.execute(
                select(
                    Contact.contact_id,
                    Contact.seniority,
                    Contact.job_title,
                    Contact.linkedin_url,
                    ContactEmail.verification_status,
                    ContactEmail.verification_source,
                    ContactEmail.is_role_email,
                )
                .outerjoin(
                    ContactEmail,
                    (ContactEmail.contact_id == Contact.contact_id)
                    & (ContactEmail.is_primary.is_(True)),
                )
                .where(Contact.company_id == company_id)
            )
        ).all()

        scored = 0
        for r in rows:
            score = score_lead(
                seniority=r.seniority,
                email_status=r.verification_status,
                email_source=r.verification_source,
                is_role_email=bool(r.is_role_email),
                has_title=bool(r.job_title),
                has_linkedin=bool(r.linkedin_url),
                company_confidence=float(company_conf) if company_conf is not None else 0.0,
            )
            await session.execute(
                update(Contact)
                .where(Contact.contact_id == r.contact_id)
                .values(confidence_score=score)
            )
            scored += 1
        await session.commit()
    logger.info("scored company_id=%d contacts=%d", company_id, scored)
