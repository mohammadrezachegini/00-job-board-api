import logging
import signal
import uuid
from smtplib import SMTPException

import pytest
from botocore.exceptions import EndpointConnectionError

from cloud.queue import QueueMessage
from jobs.events import STATUS_CHANGED
from jobs.models import ProcessedEvent
from worker import run_worker


@pytest.fixture
def application(make_company, make_candidate, make_job, make_application):
    return make_application(make_job(make_company("acme")), make_candidate("sam"))


def event(application_id, event_id=None):
    return {
        "type": STATUS_CHANGED,
        "event_id": event_id or str(uuid.uuid4()),
        "application_id": application_id,
        "old_status": "submitted",
        "new_status": "interview",
    }


def claimed(body):
    return ProcessedEvent.objects.filter(event_id=body["event_id"]).exists()


# ---------- handling one event ----------


def test_sends_one_email_and_claims_the_event(application, mailoutbox):
    body = event(application.id)

    run_worker.handle_status_changed(body)

    assert len(mailoutbox) == 1
    assert mailoutbox[0].subject.endswith(": Interview")
    assert claimed(body)


def test_duplicate_event_sends_no_second_email(application, mailoutbox, caplog):
    caplog.set_level(logging.INFO)
    body = event(application.id)

    run_worker.handle_status_changed(body)
    run_worker.handle_status_changed(body)

    assert len(mailoutbox) == 1
    assert ProcessedEvent.objects.count() == 1
    assert "already processed; skipping duplicate" in caplog.text


def test_failed_send_releases_the_claim(application, mailoutbox, monkeypatch):
    body = event(application.id)
    real_send = run_worker.send_status_changed_email

    def mail_server_down(*args):
        raise SMTPException("mail server down")

    monkeypatch.setattr(run_worker, "send_status_changed_email", mail_server_down)
    with pytest.raises(SMTPException):
        run_worker.handle_status_changed(body)
    assert not claimed(body)                      # rolled back with the failed send

    monkeypatch.setattr(run_worker, "send_status_changed_email", real_send)
    run_worker.handle_status_changed(body)        # the redelivery
    assert len(mailoutbox) == 1
    assert claimed(body)


def test_deleted_application_is_skipped_and_marked_done(db, mailoutbox, caplog):
    body = event(999999)

    run_worker.handle_status_changed(body)

    assert mailoutbox == []
    assert claimed(body)
    assert "no longer exists; skipping" in caplog.text


def test_handle_routes_by_message_type(application, mailoutbox):
    run_worker.handle(QueueMessage(id="m1", body=event(application.id), receipt_handle="r1"))
    assert len(mailoutbox) == 1

    with pytest.raises(ValueError, match="Unknown message type: 'nope'"):
        run_worker.handle(QueueMessage(id="m2", body={"type": "nope"}, receipt_handle="r2"))


def test_claim_event_only_once(db):
    assert run_worker.claim_event("e-1", STATUS_CHANGED) is True
    assert run_worker.claim_event("e-1", STATUS_CHANGED) is False


# ---------- the main loop ----------


class FakeQueue:
    url = "fake://job-board-status"

    def __init__(self, *batches):
        self.batches = list(batches)
        self.deleted = []

    def receive(self):
        batch = self.batches.pop(0)
        if not self.batches:
            run_worker.running = False            # last batch: let main() finish this pass and stop
        if isinstance(batch, Exception):
            raise batch
        return batch

    def delete(self, message):
        if message.id == "undeletable":
            raise EndpointConnectionError(endpoint_url="http://sqs.invalid")
        self.deleted.append(message.id)


def msg(message_id):
    return QueueMessage(id=message_id, body={"id": message_id}, receipt_handle=f"rh-{message_id}")


@pytest.fixture
def loop(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(run_worker, "running", True)
    monkeypatch.setattr(run_worker.signal, "signal", lambda *args: None)
    monkeypatch.setattr(run_worker, "close_old_connections", lambda: None)
    sleeps = []
    monkeypatch.setattr(run_worker.time, "sleep", sleeps.append)

    def _run(queue, handle=lambda message: None):
        monkeypatch.setattr(run_worker, "get_queue", lambda: queue)
        monkeypatch.setattr(run_worker, "handle", handle)
        run_worker.main()
        return sleeps

    return _run


def test_handled_messages_are_deleted(loop):
    queue = FakeQueue([msg("a"), msg("b")])
    handled = []

    loop(queue, lambda message: handled.append(message.id))

    assert handled == ["a", "b"]
    assert queue.deleted == ["a", "b"]


def test_failed_message_is_kept_and_the_batch_continues(loop, caplog):
    def handle(message):
        if message.id == "bad":
            raise RuntimeError("boom")

    queue = FakeQueue([msg("a"), msg("bad"), msg("c")])
    loop(queue, handle)

    assert queue.deleted == ["a", "c"]
    assert "Failed to handle message bad; it will be retried" in caplog.text


def test_receive_error_waits_5_seconds_and_retries(loop, caplog):
    queue = FakeQueue(EndpointConnectionError(endpoint_url="http://sqs.invalid"), [msg("a")])

    sleeps = loop(queue)

    assert sleeps == [5]
    assert queue.deleted == ["a"]
    assert "Could not receive messages; retrying in 5 s" in caplog.text


def test_delete_error_does_not_stop_the_worker(loop, caplog):
    queue = FakeQueue([msg("undeletable"), msg("a")])

    loop(queue)

    assert queue.deleted == ["a"]
    assert "Could not delete message undeletable; it will be redelivered" in caplog.text


def test_start_and_stop_are_logged(loop, caplog):
    loop(FakeQueue([]))

    assert "Worker started, queue fake://job-board-status" in caplog.text
    assert "Worker stopped" in caplog.text


def test_sigterm_and_sigint_are_handled(loop, monkeypatch):
    registered = []
    monkeypatch.setattr(run_worker.signal, "signal", lambda sig, handler: registered.append((sig, handler)))

    loop(FakeQueue([]))

    assert registered == [(signal.SIGTERM, run_worker.stop), (signal.SIGINT, run_worker.stop)]


def test_stop_ends_the_loop(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(run_worker, "running", True)

    run_worker.stop(15, None)

    assert run_worker.running is False
    assert "Received signal 15, finishing current batch" in caplog.text