"""Phase 3 — contact extraction.

Reads a company's cached pages, uses Claude to extract people + emails, dedupes
into contacts / contact_emails, and enqueues Phase 4 (email generation) for any
contact without a real email.
"""
import logging
from typing import Optional

import openai
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.db.models import Company, Contact, ContactEmail, CrawlCache
from app.db.session import AsyncSessionLocal, run_task
from app.services.contact_extract import extract_people
from app.services.normalize import normalize_person_name
from celery_app import celery

logger = logging.getLogger(__name__)

_ROLE_LOCALPARTS = {
    "info", "sales", "contact", "hello", "admin", "support",
    "office", "enquiry", "enquiries", "marketing",
}


@celery.task(
    name="app.workers.contacts.extract_contacts",
    queue="contacts",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def extract_contacts(self, company_id: int):
    try:
        run_task(_extract_contacts(company_id))
    except (openai.RateLimitError, openai.APIStatusError,
            openai.APIConnectionError) as exc:
        logger.warning("contact extraction LLM error for company_id=%d: %s", company_id, exc)
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("extract_contacts failed: company_id=%d", company_id)
        if self.request.retries >= self.max_retries:
            run_task(_set_contact_status(company_id, "failed"))
            return
        raise self.retry(exc=exc)


async def _extract_contacts(company_id: int):
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        await _set_contact_status(company_id, "extracting", session=session)
        await session.commit()

        pages = (
            await session.execute(
                select(CrawlCache.url, CrawlCache.raw_html).where(
                    CrawlCache.company_id == company_id,
                    CrawlCache.status_code == 200,
                    CrawlCache.raw_html.isnot(None),
                )
            )
        ).all()

        result = await extract_people([(u, h) for u, h in pages], settings)

        contacts_made = 0
        for person in result.people:
            norm = normalize_person_name(person.full_name)
            if not norm:
                continue
            first, last = _split_name(person.full_name)
            ins = pg_insert(Contact).values(
                company_id=company_id,
                full_name=person.full_name.strip(),
                normalized_name=norm,
                first_name=first,
                last_name=last,
                job_title=person.job_title,
                seniority=person.seniority,
                linkedin_url=person.linkedin_url,
            )
            # Re-runs enrich existing rows, never blank them out.
            stmt = ins.on_conflict_do_update(
                constraint="uq_contacts_company_norm",
                set_={
                    "full_name": func.coalesce(ins.excluded.full_name, Contact.full_name),
                    "first_name": func.coalesce(ins.excluded.first_name, Contact.first_name),
                    "last_name": func.coalesce(ins.excluded.last_name, Contact.last_name),
                    "job_title": func.coalesce(ins.excluded.job_title, Contact.job_title),
                    "seniority": func.coalesce(ins.excluded.seniority, Contact.seniority),
                    "linkedin_url": func.coalesce(ins.excluded.linkedin_url, Contact.linkedin_url),
                },
            ).returning(Contact.contact_id)
            contact_id = (await session.execute(stmt)).scalar_one()
            contacts_made += 1

            email = _clean_email(person.email)
            if email:
                await session.execute(
                    pg_insert(ContactEmail)
                    .values(
                        contact_id=contact_id,
                        email=email,
                        verification_source="crawled",
                        verification_status="unknown",
                        generation_confidence="high",
                        is_role_email=False,
                    )
                    .on_conflict_do_nothing(constraint="uq_contact_emails_contact_email")
                )

        # Generic/role email → company.email if not already set.
        generic = _first_role_email(result.generic_emails)
        if generic:
            await session.execute(
                update(Company)
                .where(Company.company_id == company_id, Company.email.is_(None))
                .values(email=generic)
            )

        status = "extracted" if contacts_made else "no_contacts"
        await _set_contact_status(company_id, status, session=session)
        await session.commit()

        # Enqueue Phase 4 for contacts that still have no email (idempotent re-check).
        email_less = (
            await session.execute(
                select(Contact.contact_id)
                .outerjoin(ContactEmail, ContactEmail.contact_id == Contact.contact_id)
                .where(Contact.company_id == company_id, ContactEmail.email_id.is_(None))
            )
        ).scalars().all()

    for cid in email_less:
        celery.send_task(
            "app.workers.email_gen.generate_contact_emails", args=[cid], queue="contacts"
        )
    logger.info(
        "contacts done: company_id=%d status=%s contacts=%d email_gen_enqueued=%d",
        company_id, status, contacts_made, len(email_less),
    )


async def _set_contact_status(company_id: int, status: str, session=None):
    async def _do(s):
        await s.execute(
            update(Company).where(Company.company_id == company_id).values(contact_status=status)
        )

    if session is not None:
        await _do(session)
    else:
        async with AsyncSessionLocal() as s:
            await _do(s)
            await s.commit()


def _split_name(full_name: str) -> tuple[Optional[str], Optional[str]]:
    parts = full_name.strip().split()
    if not parts:
        return None, None
    first = parts[0]
    last = " ".join(parts[1:]) or None
    return first, last


def _clean_email(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    e = raw.strip().lower()
    if e.startswith("mailto:"):
        e = e[len("mailto:"):]
    e = e.split("?")[0].strip()
    return e if "@" in e and "." in e.split("@")[-1] else None


def _first_role_email(emails: list[str]) -> Optional[str]:
    for raw in emails:
        e = _clean_email(raw)
        if e and e.split("@")[0] in _ROLE_LOCALPARTS:
            return e
    return None
