import asyncio
import logging
from typing import Optional

import httpx
from sqlalchemy import func, select, update

from app.config import get_settings
from app.db.session import AsyncSessionLocal, run_task
from app.services.dedup import upsert_company
from app.services.normalize import normalize_company
from app.services.reliability import compute_company_confidence
from app.db.models import Company, DiscoveryArea
from app.sources.dld import dld_record_to_company_dict, fetch_all_licensed_agencies
from app.sources.google_places import (
    lookup_place_by_name_phone,
    place_to_company_dict,
    search_places,
    DUBAI_NEIGHBORHOODS,
    ABU_DHABI_AREAS,
    OTHER_EMIRATES_AREAS,
)
from app.sources.osm import fetch_osm_real_estate, osm_element_to_company_dict
from celery_app import celery

logger = logging.getLogger(__name__)

# An area returning the full 3-page cap (60) is truncated — more agencies exist.
PLACES_MAX_RESULTS = 60
_MAX_PAGES = 3

_EMIRATE_KEYWORDS = {
    "dubai": "Dubai",
    "abu dhabi": "Abu Dhabi",
    "sharjah": "Sharjah",
    "ajman": "Ajman",
    "ras al khaimah": "Ras Al Khaimah",
    "fujairah": "Fujairah",
    "umm al quwain": "Umm Al Quwain",
}


# ── DLD seed (Dubai only) ──────────────────────────────────────────────────

@celery.task(
    name="app.workers.discovery.run_dld_seed",
    queue="discovery",
    bind=True,
    max_retries=2,
)
def run_dld_seed(self):
    try:
        run_task(_run_dld_seed())
    except Exception as exc:
        logger.exception("DLD seed failed")
        raise self.retry(exc=exc, countdown=120)


async def _run_dld_seed():
    settings = get_settings()
    count = 0
    async with httpx.AsyncClient(timeout=30) as client:
        async with AsyncSessionLocal() as session:
            async for record in fetch_all_licensed_agencies(settings, client):
                raw = dld_record_to_company_dict(record)
                normalized = normalize_company(raw)
                normalized["confidence_score"] = compute_company_confidence(normalized)
                company_id = await upsert_company(session, normalized)
                celery.send_task(
                    "app.workers.discovery.enrich_place_from_dld",
                    args=[company_id],
                    queue="discovery",
                )
                count += 1
                if count % 100 == 0:
                    await session.commit()
                    logger.info("DLD seed: %d upserted", count)
            await session.commit()
    logger.info("DLD seed complete: %d total", count)


@celery.task(
    name="app.workers.discovery.enrich_place_from_dld",
    queue="discovery",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def enrich_place_from_dld(self, company_id: int):
    try:
        run_task(_enrich_place_from_dld(company_id))
    except Exception as exc:
        logger.exception("enrich_place_from_dld failed: company_id=%d", company_id)
        raise self.retry(exc=exc)


async def _enrich_place_from_dld(company_id: int):
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        company = (
            await session.execute(
                select(Company).where(Company.company_id == company_id)
            )
        ).scalar_one_or_none()
        if not company or company.place_id:
            return  # Already enriched or not found

        async with httpx.AsyncClient(timeout=20) as client:
            place = await lookup_place_by_name_phone(
                company.company_name,
                company.phone,
                company.emirate or "Dubai",
                settings,
                client,
            )
        if not place:
            return

        place_data = place_to_company_dict(place)
        updates = {
            k: v
            for k, v in {
                "place_id": place_data.get("place_id"),
                "website": place_data.get("website") or company.website,
                "google_rating": place_data.get("google_rating"),
                "rating_count": place_data.get("rating_count"),
                "latitude": place_data.get("latitude"),
                "longitude": place_data.get("longitude"),
                "source": f"{company.source or 'dld'},google",
            }.items()
            if v is not None
        }
        await session.execute(
            update(Company).where(Company.company_id == company_id).values(**updates)
        )
        await session.commit()

        if updates.get("website"):
            celery.send_task(
                "app.workers.crawler.schedule_crawl",
                args=[company_id],
                queue="crawl",
            )


# ── Google Places discovery (all emirates) ────────────────────────────────

@celery.task(
    name="app.workers.discovery.run_discovery",
    queue="discovery",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def run_discovery(self, query: str, area_id: Optional[int] = None):
    try:
        run_task(_run_discovery(query, area_id))
    except Exception as exc:
        logger.exception("Discovery failed: query=%s", query)
        raise self.retry(exc=exc)


async def _run_discovery(query: str, area_id: Optional[int] = None):
    """Fetch ALL pages for one area query, store companies, record stats.

    Pagination is done inline (not via re-enqueue) so we can count total
    results per area and flag saturation — Google caps Text Search at 3
    pages × 20 = 60 results (Bug 1).
    """
    settings = get_settings()
    all_places: list[dict] = []
    token: Optional[str] = None

    async with httpx.AsyncClient(timeout=20) as client:
        for _ in range(_MAX_PAGES):
            places, token = await search_places(
                query, settings, client, page_token=token
            )
            all_places.extend(places)
            if not token:
                break
            # Google requires a short delay before the next-page token is valid.
            await asyncio.sleep(2)

    async with AsyncSessionLocal() as session:
        for place in all_places:
            raw = _enrich_emirate(place_to_company_dict(place))
            normalized = normalize_company(raw)
            normalized["confidence_score"] = compute_company_confidence(normalized)
            company_id = await upsert_company(session, normalized)
            if normalized.get("website"):
                celery.send_task(
                    "app.workers.crawler.schedule_crawl",
                    args=[company_id],
                    queue="crawl",
                )

        if area_id is not None:
            await session.execute(
                update(DiscoveryArea)
                .where(DiscoveryArea.id == area_id)
                .values(
                    last_run_at=func.now(),
                    last_result_count=len(all_places),
                    is_saturated=len(all_places) >= PLACES_MAX_RESULTS,
                )
            )
        await session.commit()

    if len(all_places) >= PLACES_MAX_RESULTS:
        logger.warning(
            "Area saturated (%d results) — consider sub-tiling: %s",
            len(all_places), query,
        )


# ── OSM supplementary (all UAE) ───────────────────────────────────────────

@celery.task(
    name="app.workers.discovery.run_osm_discovery",
    queue="discovery",
    bind=True,
    max_retries=2,
)
def run_osm_discovery(self):
    try:
        run_task(_run_osm_discovery())
    except Exception as exc:
        logger.exception("OSM discovery failed")
        raise self.retry(exc=exc, countdown=120)


async def _run_osm_discovery():
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        elements = await fetch_osm_real_estate(settings, client)

    async with AsyncSessionLocal() as session:
        count = 0
        for element in elements:
            raw = osm_element_to_company_dict(element)
            if not raw.get("company_name"):
                continue
            normalized = normalize_company(raw)
            normalized["confidence_score"] = compute_company_confidence(normalized)
            await upsert_company(session, normalized)
            count += 1
            if count % 100 == 0:
                await session.commit()
        await session.commit()
    logger.info("OSM discovery complete: %d elements", count)


# ── Helpers ───────────────────────────────────────────────────────────────

def _enrich_emirate(company: dict) -> dict:
    """Fallback enrichment when addressComponents didn't yield emirate/city.

    place_to_company_dict sets these keys but they may be None, so we fill
    None values here (setdefault wouldn't, since the keys already exist).
    """
    if not company.get("emirate"):
        address = (company.get("address") or "").lower()
        for keyword, emirate in _EMIRATE_KEYWORDS.items():
            if keyword in address:
                company["emirate"] = emirate
                if not company.get("city"):
                    company["city"] = emirate
                break
    if not company.get("country"):
        company["country"] = "AE"
    if not company.get("industry"):
        company["industry"] = "real_estate_agency"
    return company


def get_areas_for_emirate(emirate: str) -> list[str]:
    if emirate == "Dubai":
        return DUBAI_NEIGHBORHOODS
    if emirate == "Abu Dhabi":
        return ABU_DHABI_AREAS
    return OTHER_EMIRATES_AREAS
