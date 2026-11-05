import logging
import os
import signal

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import close_old_connections  # noqa: E402

from cloud.queue import get_queue  # noqa: E402
from jobs.events import STATUS_CHANGED  # noqa: E402
from jobs.emails import send_status_changed_email  # noqa: E402
from jobs.models import Application  # noqa: E402

logger = logging.getLogger("worker")

running = True


def stop(signum, frame):
    global running
    logger.info("Received signal %s, finishing current batch", signum)
    running = False


def handle(message):
    body = message.body
    if body.get("type") == STATUS_CHANGED:
        handle_status_changed(body)
        return
    raise ValueError(f"Unknown message type: {body.get('type')!r}")


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    queue = get_queue()
    logger.info("Worker started")

    while running:
        close_old_connections()
        for message in queue.receive():
            try:
                handle(message)
            except Exception:
                logger.exception(
                    "Failed to handle message %s; it will be retried", message.id
                )

                continue
            queue.delete(message)

    logger.info("Worker stopped")


def handle_status_changed(body):
    try:
        application = Application.objects.select_related("job__company", "candidate__user").get(
            id=body["application_id"]
        )
    except Application.DoesNotExist:
        logger.warning("Application %s no longer exists; skipping (event %s)", body["application_id"], body["event_id"])
        return

    send_status_changed_email(application, body["new_status"])
    logger.info(
        "Emailed user %s about application %s: %s -> %s (event %s)",
        application.candidate.user_id, application.id, body["old_status"], body["new_status"], body["event_id"],
    )


if __name__ == "__main__":
    main()
