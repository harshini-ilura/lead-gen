import asyncio
import logging
from typing import Optional

import httpx
from sqlalchemy import select, update

from app.config import get_settings
from app.db.models import Company
from app.db.session import AsyncSessionLocal
from app.services.dedup import upsert_company
from app.services.normalize import normalize_company
from app.services.reliability import compute_company_confidence
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
        asyncio.run(_run_dld_seed())
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
        asyncio.run(_enrich_place_from_dld(company_id))
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
def run_discovery(self, query: str, page_token: Optional[str] = None):
    try:
        asyncio.run(_run_discovery(query, page_token))
    except Exception as exc:
        logger.exception("Discovery failed: query=%s", query)
        raise self.retry(exc=exc)


async def _run_discovery(query: str, page_token: Optional[str] = None):
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        places, next_token = await search_places(query, settings, client, page_token=page_token)

    async with AsyncSessionLocal() as session:
        for place in places:
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
        await session.commit()

    if next_token:
        # Google requires ≥2s before fetching the next page
        run_discovery.apply_async(
            args=[query, next_token],
            queue="discovery",
            countdown=2,
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
        asyncio.run(_run_osm_discovery())
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
    address = (company.get("address") or "").lower()
    for keyword, emirate in _EMIRATE_KEYWORDS.items():
        if keyword in address:
            company.setdefault("emirate", emirate)
            company.setdefault("city", emirate)
            break
    company.setdefault("country", "AE")
    company.setdefault("industry", "real_estate")
    return company


def get_areas_for_emirate(emirate: str) -> list[str]:
    if emirate == "Dubai":
        return DUBAI_NEIGHBORHOODS
    if emirate == "Abu Dhabi":
        return ABU_DHABI_AREAS
    return OTHER_EMIRATES_AREAS
