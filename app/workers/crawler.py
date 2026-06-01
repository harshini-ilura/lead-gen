import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="app.workers.crawler.schedule_crawl",
    queue="crawl",
    bind=True,
    max_retries=2,
)
def schedule_crawl(self, company_id: int):
    # Milestone 3 — not yet implemented
    logger.info("schedule_crawl queued for company_id=%d (Phase 2 pending)", company_id)
