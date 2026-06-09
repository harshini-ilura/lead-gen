"""Phase 2 — website crawling.

Fetches each company's site (homepage + a focused set of contact-relevant pages),
caches the cleaned HTML in `crawl_cache`, and hands off to Phase 3 (contacts).

httpx-only (no JS rendering); robots.txt is intentionally not consulted. Per-domain
politeness is enforced via the Redis cooldown in app/services/reliability.py.
"""
import asyncio
import hashlib
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx
import tldextract
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.db.models import Company, CrawlCache
from app.db.session import AsyncSessionLocal, run_task
from app.services.html_parser import clean_and_cap_html, extract_internal_links
from app.services.reliability import CooldownError, acquire_domain_slot, detect_block
from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="app.workers.crawler.schedule_crawl",
    queue="crawl",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def schedule_crawl(self, company_id: int):
    try:
        run_task(_schedule_crawl(company_id))
    except CooldownError as exc:
        # Domain busy — expected backpressure, not a failure. Re-enqueue later;
        # already-cached pages skip on resume so the retry is cheap.
        settings = get_settings()
        raise self.retry(
            exc=exc,
            countdown=random.randint(
                settings.crawl_delay_min_seconds, settings.crawl_delay_max_seconds
            ),
        )
    except Exception as exc:
        logger.exception("crawl failed: company_id=%d", company_id)
        if self.request.retries >= self.max_retries:
            run_task(_set_status(company_id, "failed"))
            return  # give up cleanly after retries exhausted
        raise self.retry(exc=exc)


# ── async core ──────────────────────────────────────────────────────────────

async def _schedule_crawl(company_id: int):
    settings = get_settings()
    redis = aioredis_from_settings(settings)
    try:
        async with AsyncSessionLocal() as session:
            company = (
                await session.execute(
                    select(Company).where(Company.company_id == company_id)
                )
            ).scalar_one_or_none()

            if not company or not company.website:
                if company:
                    await _set_status(company_id, "no_pages", session=session)
                    await session.commit()
                return

            website = company.website
            domain = company.domain or _registrable_domain(website)

            # Politeness gate BEFORE marking crawling — CooldownError → wrapper retry.
            await acquire_domain_slot(
                domain, redis,
                settings.crawl_delay_min_seconds, settings.crawl_delay_max_seconds,
            )

            await _set_status(company_id, "crawling", session=session)
            await session.commit()

            status, pages = await _crawl_site(
                session, company_id, domain, website, settings
            )

            await _set_status(company_id, status, session=session)
            await session.commit()

        if status == "crawled":
            celery.send_task(
                "app.workers.contacts.extract_contacts",
                args=[company_id],
                queue="contacts",
            )
        logger.info(
            "crawl done: company_id=%d status=%s pages=%d", company_id, status, pages
        )
    finally:
        await redis.aclose()


async def _crawl_site(session, company_id, domain, website, settings) -> tuple[str, int]:
    pages = 0
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": settings.crawl_user_agent},
    ) as client:
        home_html, home_status = await _get_page(
            session, client, company_id, domain, website, settings
        )
        if home_status == "blocked":
            return "blocked", 0
        if home_html is None:
            return "no_pages", 0
        pages = 1

        budget = min(settings.crawl_target_pages, settings.crawl_max_pages_per_domain) - 1
        links = extract_internal_links(home_html, website, domain)[:budget]
        for link in links:
            await asyncio.sleep(
                random.uniform(
                    settings.crawl_delay_min_seconds, settings.crawl_delay_max_seconds
                )
            )
            _, st = await _get_page(session, client, company_id, domain, link, settings)
            if st == "blocked":
                return "blocked", pages
            if st in ("stored", "cached"):
                pages += 1
        await session.commit()

    return ("crawled" if pages > 0 else "no_pages"), pages


async def _get_page(session, client, company_id, domain, url, settings):
    """Return (html_or_None, status) where status ∈ stored|cached|skipped|blocked."""
    url_hash = _url_hash(url)

    row = (
        await session.execute(
            select(CrawlCache.raw_html, CrawlCache.next_recrawl_at).where(
                CrawlCache.url_hash == url_hash
            )
        )
    ).first()
    if row and row.next_recrawl_at and row.next_recrawl_at > datetime.now(timezone.utc):
        return row.raw_html, "cached"  # fresh in cache — counts, no network

    resp = await _fetch(client, url)
    if resp is None:
        return None, "skipped"
    if detect_block(resp.status_code, resp.text):
        return None, "blocked"
    if "html" not in resp.headers.get("content-type", "").lower():
        return None, "skipped"

    cleaned = clean_and_cap_html(resp.text, settings.crawl_html_max_bytes)
    next_recrawl = datetime.now(timezone.utc) + timedelta(days=settings.recrawl_days)
    values = {
        "url_hash": url_hash,
        "company_id": company_id,
        "domain": domain,
        "url": str(resp.url),
        "raw_html": cleaned,
        "content_type": resp.headers.get("content-type"),
        "status_code": resp.status_code,
        "next_recrawl_at": next_recrawl,
    }
    stmt = pg_insert(CrawlCache).values(**values).on_conflict_do_update(
        index_elements=["url_hash"],
        set_={
            "company_id": company_id,
            "domain": domain,
            "url": str(resp.url),
            "raw_html": cleaned,
            "content_type": resp.headers.get("content-type"),
            "status_code": resp.status_code,
            "fetched_at": func.now(),
            "next_recrawl_at": next_recrawl,
        },
    )
    await session.execute(stmt)
    return cleaned, "stored"


async def _fetch(client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
    try:
        return await client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("fetch failed %s: %s", url, exc)
        return None


async def _set_status(company_id: int, status: str, session=None):
    async def _do(s):
        await s.execute(
            update(Company).where(Company.company_id == company_id).values(crawl_status=status)
        )

    if session is not None:
        await _do(session)
    else:
        async with AsyncSessionLocal() as s:
            await _do(s)
            await s.commit()


# ── helpers ─────────────────────────────────────────────────────────────────

def _url_hash(url: str) -> str:
    parsed = urlparse(url)
    norm = parsed._replace(fragment="", netloc=parsed.netloc.lower()).geturl().rstrip("/")
    return hashlib.sha256(norm.encode()).hexdigest()


def _registrable_domain(url: str) -> str:
    host = urlparse(url).netloc or url
    ext = tldextract.extract(host)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


def aioredis_from_settings(settings):
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.redis_url)
