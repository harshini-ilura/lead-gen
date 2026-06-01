import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.workers.contacts.extract_contacts", queue="contacts")
def extract_contacts(company_id: int):
    logger.info("extract_contacts queued for company_id=%d (Phase 3 pending)", company_id)
