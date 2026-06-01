import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.workers.scoring.score_company", queue="scoring")
def score_company(company_id: int):
    logger.info("score_company queued for company_id=%d (Phase 7 pending)", company_id)
