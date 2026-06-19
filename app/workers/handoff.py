"""Phase 7 — outreach handoff.

For each scored lead of a company: qualify it (score + deliverable email), clear it
against the suppression list, deliver it to the outreach webhook, and record the
outcome on the contact. The pipeline's terminal step.
"""
import logging

from sqlalchemy import func, select, update

from app.config import get_settings
from app.db.models import Company, Contact, ContactEmail
from app.db.session import AsyncSessionLocal, run_task
from app.integrations.outreach_handoff import build_payload, deliver
from app.services.suppression import is_suppressed
from celery_app import celery

logger = logging.getLogger(__name__)

# Email statuses we're willing to send to (not invalid / risky / unknown).
_SENDABLE = {"valid", "mx_ok"}


@celery.task(
    name="app.workers.handoff.handoff_to_outreach",
    queue="scoring",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def handoff_to_outreach(self, company_id: int):
    try:
        run_task(_handoff(company_id))
    except Exception as exc:
        logger.exception("handoff_to_outreach failed: company_id=%d", company_id)
        if self.request.retries >= self.max_retries:
            return
        raise self.retry(exc=exc)


async def _handoff(company_id: int):
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        company = (
            await session.execute(
                select(Company.company_name, Company.domain).where(
                    Company.company_id == company_id
                )
            )
        ).first()
        if not company:
            return

        rows = (
            await session.execute(
                select(
                    Contact.contact_id, Contact.full_name, Contact.job_title,
                    Contact.seniority, Contact.linkedin_url, Contact.confidence_score,
                    ContactEmail.email, ContactEmail.verification_status,
                )
                .outerjoin(
                    ContactEmail,
                    (ContactEmail.contact_id == Contact.contact_id)
                    & (ContactEmail.is_primary.is_(True)),
                )
                .where(Contact.company_id == company_id, Contact.handoff_status == "pending")
            )
        ).all()

        counts: dict[str, int] = {}
        for r in rows:
            status = await _decide(session, settings, company, r)
            await session.execute(
                update(Contact)
                .where(Contact.contact_id == r.contact_id)
                .values(handoff_status=status, handed_off_at=func.now())
            )
            counts[status] = counts.get(status, 0) + 1
        await session.commit()
    logger.info("handoff company_id=%d %s", company_id, counts)


async def _decide(session, settings, company, r) -> str:
    """Return the handoff outcome for one lead."""
    score = float(r.confidence_score or 0.0)

    # 1. Qualify: deliverable email + score threshold.
    if not r.email or r.verification_status not in _SENDABLE:
        return "skipped"
    if score < settings.handoff_min_score:
        return "skipped"

    # 2. Suppression gate (email and its domain).
    domain = r.email.split("@", 1)[-1]
    if await is_suppressed(r.email, "email", session) or await is_suppressed(domain, "domain", session):
        return "suppressed"

    # 3. Deliver (or mark ready if no webhook configured).
    payload = build_payload({
        "company_name": company.company_name,
        "domain": company.domain,
        "full_name": r.full_name,
        "job_title": r.job_title,
        "seniority": r.seniority,
        "email": r.email,
        "email_status": r.verification_status,
        "linkedin_url": r.linkedin_url,
        "lead_score": score,
    })
    if not settings.outreach_webhook_url:
        return "ready"
    return "sent" if await deliver(payload, settings.outreach_webhook_url) else "failed"
