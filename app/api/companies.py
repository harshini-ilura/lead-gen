from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    CompanyRead,
    DiscoveryTriggerRequest,
    DiscoveryTriggerResponse,
)
from app.db.models import Company, DiscoveryArea
from app.db.session import get_db
from app.sources.google_places import build_discovery_query
from app.workers.discovery import get_areas_for_emirate

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
