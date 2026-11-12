import logging
import uuid

from cloud.queue import QUEUE_ERRORS
from django.db import transaction

from cloud.queue import get_queue

logger = logging.getLogger(__name__)

STATUS_CHANGED = "application.status_changed"


def publish_status_changed(application, old_status):
    body = {
        "type": STATUS_CHANGED,
        "event_id": str(uuid.uuid4()),
        "application_id": application.id,
        "old_status": old_status,
        "new_status": application.status,
    }

    def send():
        try:
            message_id = get_queue().send(body)
            logger.info(
                "Queued %s for application %s (message %s)",
                STATUS_CHANGED,
                application.id,
                message_id,
                extra={
                    "event": STATUS_CHANGED,
                    "event_id": body["event_id"],
                    "application_id": application.id,
                    "message_id": message_id,
                },
            )
        except QUEUE_ERRORS:
            logger.exception(
                "Could not queue %s for application %s",
                STATUS_CHANGED,
                application.id,
                extra={
                    "event": STATUS_CHANGED,
                    "event_id": body["event_id"],
                    "application_id": application.id,
                },
            )

    transaction.on_commit(send)
