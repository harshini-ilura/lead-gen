import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    CompanyRead,
    DiscoveryTriggerRequest,
    DiscoveryTriggerResponse,
)
from app.db.models import Company, Contact, ContactEmail, DiscoveryArea
from app.db.session import get_db
from app.integrations.smartlead import parse_event
from app.services.suppression import add_to_suppression
from app.sources.google_places import build_discovery_query
from app.workers.discovery import get_areas_for_emirate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["companies"])


@router.get("/companies/search", response_model=list[CompanyRead])
async def search_companies(
    q: str = Query(..., min_length=2),
    emirate: str | None = None,
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(
            "SELECT * FROM companies "
            "WHERE (CAST(:emirate AS text) IS NULL OR emirate = :emirate) "
            "AND normalized_name IS NOT NULL "
            "AND similarity(normalized_name, :name) > 0.3 "
            "ORDER BY similarity(normalized_name, :name) DESC "
            "LIMIT :limit"
        ),
        {"name": q.lower(), "emirate": emirate, "limit": limit},
    )
    return [dict(r) for r in result.mappings().all()]


@router.get("/companies/{company_id}", response_model=CompanyRead)
async def get_company(company_id: int, db: AsyncSession = Depends(get_db)):
    company = (
        await db.execute(select(Company).where(Company.company_id == company_id))
    ).scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.get("/companies", response_model=list[CompanyRead])
async def list_companies(
    emirate: str | None = None,
    industry: str | None = None,
    source: str | None = None,
    min_confidence: float | None = None,
    crawl_status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    q = select(Company)
    if emirate:
        q = q.where(Company.emirate == emirate)
    if industry:
        q = q.where(Company.industry == industry)
    if source:
        q = q.where(Company.source.contains(source))
    if min_confidence is not None:
        q = q.where(Company.confidence_score >= min_confidence)
    if crawl_status:
        q = q.where(Company.crawl_status == crawl_status)
    q = q.order_by(Company.confidence_score.desc().nullslast()).limit(limit).offset(offset)
    return (await db.execute(q)).scalars().all()


@router.post("/discovery/trigger", response_model=DiscoveryTriggerResponse)
async def trigger_discovery(
    req: DiscoveryTriggerRequest, db: AsyncSession = Depends(get_db)
):
    from celery_app import celery

    enqueued = 0

    if req.emirate == "Dubai" and req.use_dld:
        celery.send_task("app.workers.discovery.run_dld_seed", queue="discovery")
        enqueued += 1

    # Explicit override (req.areas) → ad-hoc queries with no area_id.
    if req.areas:
        for area in req.areas:
            celery.send_task(
                "app.workers.discovery.run_discovery",
                args=[build_discovery_query(area, req.emirate)],
                queue="discovery",
            )
            enqueued += 1
    else:
        # Default path: fan out the curated discovery_areas table (Bug 2).
        rows = (
            await db.execute(
                select(DiscoveryArea.id, DiscoveryArea.area_name).where(
                    DiscoveryArea.emirate == req.emirate,
                    DiscoveryArea.is_active.is_(True),
                )
            )
        ).all()
        if not rows:
            # Fallback to the legacy hardcoded list if the table isn't seeded yet.
            for area in get_areas_for_emirate(req.emirate):
                celery.send_task(
                    "app.workers.discovery.run_discovery",
                    args=[build_discovery_query(area, req.emirate)],
                    queue="discovery",
                )
                enqueued += 1
        else:
            for area_id, area_name in rows:
                celery.send_task(
                    "app.workers.discovery.run_discovery",
                    args=[build_discovery_query(area_name, req.emirate), area_id],
                    queue="discovery",
                )
                enqueued += 1

    return DiscoveryTriggerResponse(
        enqueued=enqueued,
        message=f"Discovery triggered for {req.emirate}: {enqueued} tasks enqueued",
    )


@router.post("/discovery/trigger-osm", response_model=DiscoveryTriggerResponse)
async def trigger_osm_discovery():
    from celery_app import celery

    celery.send_task("app.workers.discovery.run_osm_discovery", queue="discovery")
    return DiscoveryTriggerResponse(enqueued=1, message="OSM discovery triggered (UAE-wide)")


@router.post("/contacts/trigger", response_model=DiscoveryTriggerResponse)
async def trigger_contacts(
    reprocess: bool = False, db: AsyncSession = Depends(get_db)
):
    """Enqueue Phase 3 contact extraction for crawled companies.

    By default skips companies already extracted; pass reprocess=true to re-run
    all crawled companies (idempotent — dedup keys prevent duplicates).
    """
    from celery_app import celery

    q = select(Company.company_id).where(Company.crawl_status == "crawled")
    if not reprocess:
        q = q.where(Company.contact_status != "extracted")
    ids = (await db.execute(q)).scalars().all()

    for company_id in ids:
        celery.send_task(
            "app.workers.contacts.extract_contacts", args=[company_id], queue="contacts"
        )

    return DiscoveryTriggerResponse(
        enqueued=len(ids),
        message=f"Contact extraction triggered for {len(ids)} crawled companies",
    )


@router.post("/verify/trigger", response_model=DiscoveryTriggerResponse)
async def trigger_verify(
    reprocess: bool = False, db: AsyncSession = Depends(get_db)
):
    """Enqueue Phase 5 verification for contact emails.

    By default only unverified ('unknown') emails; pass reprocess=true to re-verify
    every email (idempotent — statuses/primary recompute deterministically).
    """
    from celery_app import celery

    q = select(ContactEmail.email_id)
    if not reprocess:
        q = q.where(ContactEmail.verification_status == "unknown")
    ids = (await db.execute(q)).scalars().all()

    for email_id in ids:
        celery.send_task(
            "app.workers.verify.verify_contact_email", args=[email_id], queue="verify"
        )

    return DiscoveryTriggerResponse(
        enqueued=len(ids),
        message=f"Verification triggered for {len(ids)} emails",
    )


@router.post("/scoring/trigger", response_model=DiscoveryTriggerResponse)
async def trigger_scoring(db: AsyncSession = Depends(get_db)):
    """Enqueue Phase 6 lead scoring for every company that has extracted contacts."""
    from celery_app import celery

    ids = (
        await db.execute(
            select(Company.company_id).where(Company.contact_status == "extracted")
        )
    ).scalars().all()

    for company_id in ids:
        celery.send_task(
            "app.workers.scoring.score_company", args=[company_id], queue="scoring"
        )

    return DiscoveryTriggerResponse(
        enqueued=len(ids),
        message=f"Lead scoring triggered for {len(ids)} companies",
    )


@router.post("/handoff/trigger", response_model=DiscoveryTriggerResponse)
async def trigger_handoff(db: AsyncSession = Depends(get_db)):
    """Enqueue Phase 7 outreach handoff for every company with extracted contacts."""
    from celery_app import celery

    ids = (
        await db.execute(
            select(Company.company_id).where(Company.contact_status == "extracted")
        )
    ).scalars().all()

    for company_id in ids:
        celery.send_task(
            "app.workers.handoff.handoff_to_outreach", args=[company_id], queue="scoring"
        )

    return DiscoveryTriggerResponse(
        enqueued=len(ids),
        message=f"Handoff triggered for {len(ids)} companies",
    )


@router.post("/outreach/push", response_model=DiscoveryTriggerResponse)
async def trigger_outreach_push():
    """Push handoff-cleared leads into the Smartlead campaign (Phase 8)."""
    from celery_app import celery

    celery.send_task("app.workers.outreach.push_ready_leads", queue="scoring")
    return DiscoveryTriggerResponse(
        enqueued=1, message="Outreach push enqueued (handoff-ready leads → Smartlead)"
    )


@router.post("/outreach/events")
async def outreach_events(request: Request, db: AsyncSession = Depends(get_db)):
    """Inbound Smartlead webhook (Phase 8 reply/status sync): reply / bounce /
    unsubscribe → update the matching contact(s) and suppress on bounce/unsubscribe.

    Matching is case-insensitive and may resolve to >1 contact (e.g. a shared role
    email), so every contact carrying that address is updated.
    """
    payload = await request.json()
    status, email = parse_event(payload)
    if not email or not status:
        logger.info("outreach event ignored (unmapped): %s", payload.get("event_type") or payload)
        return {"ok": True, "ignored": True}

    contact_ids = (
        await db.execute(
            select(ContactEmail.contact_id).where(
                func.lower(ContactEmail.email) == email,
                ContactEmail.contact_id.is_not(None),
            )
        )
    ).scalars().all()

    if contact_ids:
        await db.execute(
            update(Contact)
            .where(Contact.contact_id.in_(contact_ids))
            .values(outreach_status=status)
        )
    if status in ("bounced", "unsubscribed"):
        await add_to_suppression(email, "email", f"outreach:{status}", db)

    logger.info(
        "outreach event %s for %s → %d contact(s)%s",
        status, email, len(contact_ids),
        " + suppressed" if status in ("bounced", "unsubscribed") else "",
    )
    return {"ok": True, "email": email, "status": status, "contacts": len(contact_ids)}
