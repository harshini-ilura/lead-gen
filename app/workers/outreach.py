"""Phase 8 — outreach push worker.

Pushes handoff-cleared leads into the Smartlead campaign. Selection honors
outreach_valid_only (paid-confirmed emails only, by default) to protect sender
reputation. Smartlead then sends, warms, rotates inboxes, and runs sequences.
"""
import logging

from sqlalchemy import select, update

from app.config import get_settings
from app.db.models import Company, Contact, ContactEmail
from app.db.session import AsyncSessionLocal, run_task
from app.integrations.smartlead import push_leads
from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="app.workers.outreach.push_ready_leads",
    queue="scoring",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def push_ready_leads(self):
    try:
        run_task(_push())
    except Exception as exc:
        logger.exception("push_ready_leads failed")
        if self.request.retries >= self.max_retries:
            return
        raise self.retry(exc=exc)


async def _push():
    settings = get_settings()
    if not settings.smartlead_api_key or not settings.smartlead_campaign_id:
        logger.warning("Smartlead not configured (api_key / campaign_id) — skipping push")
        return

    async with AsyncSessionLocal() as session:
        q = (
            select(
                Contact.contact_id, Contact.first_name, Contact.last_name,
                Contact.job_title, Contact.seniority, Contact.linkedin_url,
                Contact.confidence_score,
                Company.company_name, Company.domain, Company.city,
                ContactEmail.email, ContactEmail.verification_status,
            )
            .join(Company, Company.company_id == Contact.company_id)
            .join(
                ContactEmail,
                (ContactEmail.contact_id == Contact.contact_id)
                & (ContactEmail.is_primary.is_(True)),
            )
            .where(Contact.handoff_status == "ready", Contact.outreach_status.is_(None))
        )
        if settings.outreach_valid_only:
            q = q.where(ContactEmail.verification_status == "valid")
        else:
            q = q.where(ContactEmail.verification_status.in_(["valid", "mx_ok"]))

        rows = (await session.execute(q)).all()
        if not rows:
            logger.info("no eligible leads to push")
            return

        leads = [
            {
                "email": r.email,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "company_name": r.company_name,
                "job_title": r.job_title,
                "seniority": r.seniority,
                "city": r.city,
                "linkedin_url": r.linkedin_url,
                "lead_score": float(r.confidence_score) if r.confidence_score is not None else None,
            }
            for r in rows
        ]

        pushed = await push_leads(leads, settings)

        await session.execute(
            update(Contact)
            .where(Contact.contact_id.in_([r.contact_id for r in rows]))
            .values(outreach_status="pushed")
        )
        await session.commit()
    logger.info("pushed %d leads to Smartlead campaign %s", pushed, settings.smartlead_campaign_id)
