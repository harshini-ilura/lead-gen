import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.workers.handoff.handoff_to_outreach", queue="scoring")
def handoff_to_outreach(company_id: int):
    logger.info(
        "handoff_to_outreach queued for company_id=%d (Phase 8 pending)", company_id
    )
