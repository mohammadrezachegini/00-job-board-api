import dataclasses
import json
import uuid

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from django.db import transaction

from cloud.queue import QueueMessage, SQSQueue, get_queue
from jobs.events import STATUS_CHANGED, publish_status_changed


def queued(aws):
    response = aws.sqs.receive_message(QueueUrl=aws.queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0)
    return [json.loads(message["Body"]) for message in response.get("Messages", [])]


def counts(aws):
    attributes = aws.sqs.get_queue_attributes(
        QueueUrl=aws.queue_url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return int(attributes["ApproximateNumberOfMessages"]), int(attributes["ApproximateNumberOfMessagesNotVisible"])


# ---------- cloud/queue.py ----------


def test_send_receive_delete(aws):
    queue = get_queue()

    message_id = queue.send({"hello": "world"})
    assert counts(aws) == (1, 0)                    # waiting

    [message] = queue.receive(wait_seconds=0)
    assert (message.id, message.body) == (message_id, {"hello": "world"})
    assert counts(aws) == (0, 1)                    # in flight: hidden for the visibility timeout

    queue.delete(message)
    assert counts(aws) == (0, 0)                    # gone


def test_received_messages_are_immutable(aws):
    get_queue().send({"a": 1})
    [message] = get_queue().receive(wait_seconds=0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        message.body = {}
    assert isinstance(message, QueueMessage)


def test_get_queue_is_one_shared_instance(aws):
    assert get_queue() is get_queue()
    assert get_queue().url == aws.queue_url


def test_ping(aws):
    assert get_queue().ping() is None
    with pytest.raises(ClientError):
        SQSQueue("no-such-queue").ping()


# ---------- publishing status changes ----------


@pytest.fixture
def application(make_company, make_candidate, make_job, make_application):
    acme = make_company("acme")
    return make_application(make_job(acme), make_candidate("sam"))


def set_status(api_as, application, status):
    return api_as(application.job.company.user).patch(
        f"/api/applications/{application.id}/status/", {"status": status}, format="json"
    )


def test_status_change_is_published_only_after_commit(api_as, aws, application, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks() as callbacks:
        response = set_status(api_as, application, "interview")

    assert response.status_code == 200
    assert queued(aws) == []                        # not committed yet: nothing sent

    for callback in callbacks:
        callback()                                  # "commit"

    [body] = queued(aws)
    assert body == {
        "type": STATUS_CHANGED,
        "event_id": body["event_id"],
        "application_id": application.id,
        "old_status": "submitted",
        "new_status": "interview",
    }
    assert uuid.UUID(body["event_id"]).version == 4


def test_unchanged_status_publishes_nothing(api_as, aws, application, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = set_status(api_as, application, "submitted")

    assert response.status_code == 200
    assert queued(aws) == []


def test_rolled_back_change_publishes_nothing(aws, application, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError), transaction.atomic():
            application.status = "interview"
            application.save()
            publish_status_changed(application, "submitted")
            raise RuntimeError("something failed after the publish call")

    assert callbacks == []
    assert queued(aws) == []
    application.refresh_from_db()
    assert application.status == "submitted"


def test_queue_outage_is_logged_not_raised(api_as, application, django_capture_on_commit_callbacks, monkeypatch, caplog):
    class BrokenQueue:
        def send(self, body):
            raise EndpointConnectionError(endpoint_url="http://sqs.invalid")

    monkeypatch.setattr("jobs.events.get_queue", lambda: BrokenQueue())

    with django_capture_on_commit_callbacks(execute=True):
        response = set_status(api_as, application, "interview")

    application.refresh_from_db()
    assert response.status_code == 200
    assert application.status == "interview"
    assert "Could not queue application.status_changed" in caplog.text