import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="app.workers.verify.verify_contact_email",
    queue="verify",
    rate_limit="100/m",
)
def verify_contact_email(email_id: int):
    logger.info(
        "verify_contact_email queued for email_id=%d (Phase 5 pending)", email_id
    )
