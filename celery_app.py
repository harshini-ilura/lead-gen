from celery import Celery

from app.config import get_settings

settings = get_settings()

celery = Celery(
    "leadgen",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery.config_from_object("app.workers.celeryconfig")
celery.autodiscover_tasks(
    [
        "app.workers.discovery",
        "app.workers.crawler",
        "app.workers.contacts",
        "app.workers.email_gen",
        "app.workers.verify",
        "app.workers.scoring",
        "app.workers.handoff",
    ]
)
