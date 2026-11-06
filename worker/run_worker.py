import logging
import os
import signal

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import time  # noqa: E402

from botocore.exceptions import BotoCoreError, ClientError  # noqa: E402

from django.db import IntegrityError, close_old_connections, transaction  # noqa: E402

from cloud.queue import get_queue  # noqa: E402
from jobs.events import STATUS_CHANGED  # noqa: E402
from jobs.emails import send_status_changed_email  # noqa: E402
from jobs.models import Application, ProcessedEvent  # noqa: E402

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

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    queue = get_queue()
    logger.info("Worker started, queue %s", queue.url)

    while running:
        close_old_connections()
        try:
            messages = queue.receive()
        except (BotoCoreError, ClientError):
            logger.exception("Could not receive messages; retrying in 5 s")
            time.sleep(5)
            continue

        for message in messages:
            try:
                handle(message)
            except Exception:
                logger.exception(
                    "Failed to handle message %s; it will be retried", message.id,
                    extra={"message_id": message.id},
                )
                continue
            try:
                queue.delete(message)
            except (BotoCoreError, ClientError):
                logger.exception(
                    "Could not delete message %s; it will be redelivered", message.id,
                    extra={"message_id": message.id},
                )

    logger.info("Worker stopped")


def claim_event(event_id, event_type):
    try:
        with transaction.atomic():
            ProcessedEvent.objects.create(event_id=event_id, event_type=event_type)
    except IntegrityError:
        return False
    return True


def handle_status_changed(body):
    with transaction.atomic():
        if not claim_event(body["event_id"], STATUS_CHANGED):
            logger.info(
                "Event %s already processed; skipping duplicate", body["event_id"],
                extra={"event": STATUS_CHANGED, "event_id": body["event_id"]},
            )
            return

        try:
            application = Application.objects.select_related(
                "job__company", "candidate__user"
            ).get(id=body["application_id"])
        except Application.DoesNotExist:
            logger.warning(
                "Application %s no longer exists; skipping (event %s)",
                body["application_id"],
                body["event_id"],
                extra={
                    "event": STATUS_CHANGED,
                    "event_id": body["event_id"],
                    "application_id": body["application_id"],
                },
            )
            return

        send_status_changed_email(application, body["new_status"])

    logger.info(
        "Emailed user %s about application %s: %s -> %s (event %s)",
        application.candidate.user_id,
        application.id,
        body["old_status"],
        body["new_status"],
        body["event_id"],
        extra={
            "event": STATUS_CHANGED,
            "event_id": body["event_id"],
            "application_id": application.id,
            "user_id": application.candidate.user_id,
            "old_status": body["old_status"],
            "new_status": body["new_status"],
        },
    )


if __name__ == "__main__":
    main()
