import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.workers.email_gen.generate_contact_emails", queue="contacts")
def generate_contact_emails(contact_id: int):
    logger.info(
        "generate_contact_emails queued for contact_id=%d (Phase 4 pending)", contact_id
    )
