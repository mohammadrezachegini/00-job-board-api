import json
import threading
import time
from types import SimpleNamespace

import pytest
from azure.servicebus.exceptions import ServiceBusError

import cloud.queue as queue_module
from cloud.queue import QUEUE_ERRORS, QueueMessage, ServiceBusQueue, SQSQueue, get_queue

CS = (
    "Endpoint=sb://servicebus;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)


class FakeReceived:
    """Stands in for azure.servicebus.ServiceBusReceivedMessage: only what ServiceBusQueue reads."""

    def __init__(self, body, message_id="m-1", lock_token="lt-1", sequence_number=1):
        self.text = body
        self.message_id = message_id
        self.lock_token = lock_token
        self.sequence_number = sequence_number

    def __str__(self):
        return self.text


@pytest.fixture
def sb(monkeypatch):
    """Replace ServiceBusClient in cloud.queue with a fake. `world` controls how the fakes behave."""
    world = SimpleNamespace(
        clients=[], inbox=[], send_error=None, receive_error=None, open_error=None, close_error=None,
        hang_send=False, hang_open=False, release=threading.Event(),
    )

    class FakeSender:
        def __init__(self):
            self.sent = []
            self.closed = False

        def send_messages(self, message):
            if world.hang_send:
                world.release.wait(5)
            if world.send_error:
                raise world.send_error
            self.sent.append(message)

        def close(self):
            self.closed = True
            if world.close_error:
                raise world.close_error

    class FakeReceiver:
        def __init__(self):
            self.calls = []
            self.completed = []
            self.closed = False

        def receive_messages(self, max_message_count, max_wait_time):
            self.calls.append((max_message_count, max_wait_time))
            if world.receive_error:
                raise world.receive_error
            return world.inbox.pop(0) if world.inbox else []

        def complete_message(self, message):
            self.completed.append(message)

        def close(self):
            self.closed = True

        def __enter__(self):  # used by ping(): opening = connect + login + attach
            if world.hang_open:
                world.release.wait(5)
            if world.open_error:
                raise world.open_error
            return self

        def __exit__(self, *exc):
            self.close()

    class FakeClient:
        def __init__(self, connection_string, **kwargs):
            self.connection_string = connection_string
            self.kwargs = kwargs
            self.senders = []
            self.receivers = []
            self.closed = False

        @classmethod
        def from_connection_string(cls, connection_string, **kwargs):
            client = cls(connection_string, **kwargs)
            world.clients.append(client)
            return client

        def get_queue_sender(self, queue_name):
            self.senders.append(FakeSender())
            return self.senders[-1]

        def get_queue_receiver(self, queue_name, **kwargs):
            self.receivers.append(FakeReceiver())
            return self.receivers[-1]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.closed = True

    monkeypatch.setattr(queue_module, "ServiceBusClient", FakeClient)
    yield world
    world.release.set()  # free any thread a test left waiting


def make_queue():
    return ServiceBusQueue(CS, "job-board-status")


def wait_until_free(lock, seconds=2):
    deadline = time.monotonic() + seconds
    while lock.locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not lock.locked(), "background thread never released the lock"


# --- construction -------------------------------------------------------------------------------


def test_init_connects_nowhere_and_the_url_hides_the_key(sb):
    q = make_queue()

    assert q.url == "sb://servicebus/job-board-status"
    assert "SAS_KEY_VALUE" not in q.url
    assert [c.kwargs for c in sb.clients] == [
        {"retry_total": 3, "try_timeout": 5},  # receiver client (worker)
        {"retry_total": 1, "try_timeout": 2},  # send client (web requests)
    ]
    assert all(not c.senders and not c.receivers for c in sb.clients)


# --- send ---------------------------------------------------------------------------------------


def test_send_reuses_one_sender_and_returns_our_message_id(sb):
    q = make_queue()

    first = q.send({"n": 1})
    second = q.send({"n": 2})

    receiver_client, send_client = sb.clients
    [sender] = send_client.senders
    assert [m.message_id for m in sender.sent] == [first, second]
    assert first != second
    assert [json.loads(str(m)) for m in sender.sent] == [{"n": 1}, {"n": 2}]
    assert receiver_client.senders == []


def test_send_error_discards_the_sender_and_is_raised(sb):
    q = make_queue()
    sb.send_error = ServiceBusError("broker down")

    with pytest.raises(ServiceBusError, match="broker down"):
        q.send({"n": 1})

    [broken] = sb.clients[1].senders
    assert broken.closed is True
    sb.send_error = None
    q.send({"n": 2})
    assert len(sb.clients[1].senders) == 2  # a fresh sender, not the broken one


def test_discard_ignores_errors_from_close(sb):
    q = make_queue()
    sb.send_error = ServiceBusError("broker down")
    sb.close_error = RuntimeError("close failed too")

    with pytest.raises(ServiceBusError, match="broker down"):  # the ORIGINAL error, not the close error
        q.send({"n": 1})

    assert q._sender is None


def test_send_gives_up_after_SEND_SECONDS_and_says_it_may_still_arrive(sb):
    q = make_queue()
    q.SEND_SECONDS = 0.2
    sb.hang_send = True

    started = time.monotonic()
    with pytest.raises(ServiceBusError, match="may still be delivered"):
        q.send({"n": 1})
    assert time.monotonic() - started < 1

    sb.release.set()  # the broker "answers": the stuck send completes in the background
    wait_until_free(q._send_lock)
    [sender] = sb.clients[1].senders
    assert len(sender.sent) == 1


def test_send_fails_fast_while_a_previous_send_is_stuck(sb):
    q = make_queue()
    q.SEND_SECONDS = 0.1
    sb.hang_send = True
    with pytest.raises(ServiceBusError, match="may still be delivered"):
        q.send({"n": 1})

    started = time.monotonic()
    with pytest.raises(ServiceBusError, match="Previous send still running"):
        q.send({"n": 2})
    assert 0.9 <= time.monotonic() - started < 2  # waited acquire(timeout=1), no more
    assert len(sb.clients[1].senders) == 1  # no second sender, no pile-up


# --- receive / delete ---------------------------------------------------------------------------


def test_receive_maps_messages_and_delete_completes_them_on_the_same_receiver(sb):
    q = make_queue()
    a = FakeReceived('{"type": "a"}', message_id="m-1", lock_token="lt-1")
    b = FakeReceived('{"type": "b"}', message_id=None, lock_token="lt-2", sequence_number=7)
    sb.inbox = [[a, b]]

    messages = q.receive(max_messages=5, wait_seconds=1)

    assert messages == [
        QueueMessage(id="m-1", body={"type": "a"}, receipt_handle="lt-1"),
        QueueMessage(id="7", body={"type": "b"}, receipt_handle="lt-2"),
    ]
    [receiver] = sb.clients[0].receivers
    assert receiver.calls == [(5, 1)]

    q.delete(messages[1])

    assert receiver.completed == [b]
    assert sb.clients[1].receivers == []  # the send client never receives


def test_receive_reuses_one_receiver(sb):
    q = make_queue()
    q.receive()
    q.receive()

    [receiver] = sb.clients[0].receivers
    assert receiver.calls == [(10, 20), (10, 20)]  # the interface defaults, same as SQS


def test_a_new_receive_forgets_old_lock_tokens(sb):
    q = make_queue()
    sb.inbox = [[FakeReceived('{"type": "a"}')], []]
    [old] = q.receive()
    q.receive()

    with pytest.raises(ServiceBusError, match="No lock held for message m-1"):
        q.delete(old)


def test_delete_without_a_receive_raises_a_queue_error(sb):
    q = make_queue()

    with pytest.raises(QUEUE_ERRORS):
        q.delete(QueueMessage(id="x", body={}, receipt_handle="never-received"))


def test_receive_error_discards_the_receiver_and_is_raised(sb):
    q = make_queue()
    sb.receive_error = ServiceBusError("link detached")

    with pytest.raises(ServiceBusError, match="link detached"):
        q.receive()

    [broken] = sb.clients[0].receivers
    assert broken.closed is True
    assert q._receiver is None
    sb.receive_error = None
    q.receive()
    assert len(sb.clients[0].receivers) == 2


# --- ping ---------------------------------------------------------------------------------------


def test_ping_opens_a_receiver_on_its_own_client_with_no_retries(sb):
    q = make_queue()

    q.ping()

    ping_client = sb.clients[2]
    assert ping_client.kwargs == {"retry_total": 0, "try_timeout": q.PING_SECONDS}
    [receiver] = ping_client.receivers
    assert receiver.closed is True
    assert ping_client.closed is True
    assert receiver.calls == []  # opened only: no receive, no peek


def test_ping_error_is_raised(sb):
    q = make_queue()
    sb.open_error = ServiceBusError("entity not found")

    with pytest.raises(ServiceBusError, match="entity not found"):
        q.ping()
    assert not q._ping_lock.locked()


def test_frozen_broker_ping_times_out_then_fails_fast_then_recovers(sb):
    q = make_queue()
    q.PING_SECONDS = 0.2
    sb.hang_open = True

    started = time.monotonic()
    with pytest.raises(ServiceBusError, match="Ping timed out"):
        q.ping()
    assert time.monotonic() - started < 1

    started = time.monotonic()
    with pytest.raises(ServiceBusError, match="Previous ping still running"):
        q.ping()
    assert time.monotonic() - started < 0.1
    assert len(sb.clients) == 3  # 2 from __init__ + 1 stuck ping; the 2nd ping started nothing

    sb.hang_open = False
    sb.release.set()
    wait_until_free(q._ping_lock)
    q.ping()  # broker back: pings work again


# --- choosing the cloud -------------------------------------------------------------------------


@pytest.fixture
def fresh_get_queue():
    get_queue.cache_clear()
    yield get_queue
    get_queue.cache_clear()


def test_get_queue_picks_service_bus_for_azure(sb, settings, fresh_get_queue):
    settings.CLOUD_PROVIDER = "azure"
    settings.SERVICE_BUS_CONNECTION_STRING = CS
    settings.SERVICE_BUS_QUEUE_NAME = "job-board-status"

    q = fresh_get_queue()

    assert isinstance(q, ServiceBusQueue)
    assert q is fresh_get_queue()  # one shared instance per process


def test_get_queue_picks_sqs_for_aws(settings, fresh_get_queue):
    settings.CLOUD_PROVIDER = "aws"

    assert isinstance(fresh_get_queue(), SQSQueue)


def test_service_bus_errors_count_as_queue_errors():
    assert issubclass(ServiceBusError, QUEUE_ERRORS)
