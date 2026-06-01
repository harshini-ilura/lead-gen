from kombu import Queue

task_queues = (
    Queue("discovery"),
    Queue("crawl"),
    Queue("contacts"),
    Queue("verify"),
    Queue("scoring"),
)

task_default_queue = "discovery"
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
task_acks_late = True
worker_prefetch_multiplier = 1
task_reject_on_worker_lost = True
task_track_started = True
