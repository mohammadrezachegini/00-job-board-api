import json
import threading
import uuid
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from functools import cached_property, lru_cache

import boto3
from azure.core.exceptions import AzureError
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.servicebus.exceptions import ServiceBusError
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

# Errors a caller should treat as "the queue is unavailable right now", on either cloud.
QUEUE_ERRORS = (BotoCoreError, ClientError, AzureError)


@dataclass(frozen=True)
class QueueMessage:
    id: str
    body: dict
    receipt_handle: str


class Queue(ABC):
    @abstractmethod
    def send(self, body: dict) -> str: ...

    @abstractmethod
    def receive(
        self, max_messages: int = 10, wait_seconds: int = 20
    ) -> list[QueueMessage]: ...

    @abstractmethod
    def delete(self, message: QueueMessage) -> None: ...

    @abstractmethod
    def ping(self) -> None: ...


class SQSQueue(Queue):
    def __init__(self, queue_name: str):
        self.name = queue_name
        common = {
            "endpoint_url": settings.AWS_SQS_ENDPOINT_URL,
            "region_name": settings.AWS_REGION,
        }
        self.client = boto3.client(
            "sqs",
            config=Config(
                connect_timeout=5,
                read_timeout=30,
                retries={"mode": "standard", "total_max_attempts": 3},
            ),
            **common,
        )
        self._ping_client = boto3.client(
            "sqs",
            config=Config(
                connect_timeout=1,
                read_timeout=1,
                retries={"mode": "standard", "total_max_attempts": 1},
            ),
            **common,
        )

    def send(self, body: dict) -> str:
        response = self.client.send_message(
            QueueUrl=self.url, MessageBody=json.dumps(body)
        )
        return response["MessageId"]

    def receive(
        self, max_messages: int = 10, wait_seconds: int = 20
    ) -> list[QueueMessage]:
        response = self.client.receive_message(
            QueueUrl=self.url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        return [
            QueueMessage(
                id=m["MessageId"],
                body=json.loads(m["Body"]),
                receipt_handle=m["ReceiptHandle"],
            )
            for m in response.get("Messages", [])
        ]

    def delete(self, message: QueueMessage) -> None:
        self.client.delete_message(
            QueueUrl=self.url, ReceiptHandle=message.receipt_handle
        )

    @cached_property
    def url(self) -> str:
        return self.client.get_queue_url(QueueName=self.name)["QueueUrl"]

    def ping(self) -> None:
        self._ping_client.get_queue_url(QueueName=self.name)


class ServiceBusQueue(Queue):
    """Azure Service Bus queue, peek-lock mode.

    The SDK's clients are not thread-safe. The API only sends (under a lock);
    the worker only receives and deletes, from one thread.
    """

    def __init__(self, connection_string: str, queue_name: str):
        self.name = queue_name
        self._connection_string = connection_string
        parts = dict(p.split("=", 1) for p in connection_string.split(";") if p)
        self.url = f"{parts['Endpoint'].rstrip('/')}/{queue_name}"  # no key in it: safe to log
        self._client = ServiceBusClient.from_connection_string(
            connection_string, retry_total=3, try_timeout=5
        )
        self._send_lock = threading.Lock()
        self._ping_lock = threading.Lock()
        self._sender = None
        self._receiver = None
        self._pending = {}

    def send(self, body: dict) -> str:
        message_id = str(uuid.uuid4())
        message = ServiceBusMessage(json.dumps(body), message_id=message_id)
        with self._send_lock:
            try:
                if self._sender is None:
                    self._sender = self._client.get_queue_sender(self.name)
                self._sender.send_messages(message)
            except AzureError:
                self._sender = self._discard(self._sender)
                raise
        return message_id

    def receive(
        self, max_messages: int = 10, wait_seconds: int = 20
    ) -> list[QueueMessage]:
        try:
            if self._receiver is None:
                self._receiver = self._client.get_queue_receiver(self.name)
            received = self._receiver.receive_messages(
                max_message_count=max_messages, max_wait_time=wait_seconds
            )
        except AzureError:
            self._receiver = self._discard(self._receiver)
            raise
        self._pending = {str(m.lock_token): m for m in received}
        return [
            QueueMessage(
                id=str(m.message_id or m.sequence_number),
                body=json.loads(str(m)),
                receipt_handle=token,
            )
            for token, m in self._pending.items()
        ]

    def delete(self, message: QueueMessage) -> None:
        received = self._pending.pop(message.receipt_handle, None)
        if received is None or self._receiver is None:
            raise ServiceBusError(f"No lock held for message {message.id}; it will be redelivered")
        self._receiver.complete_message(received)

    PING_SECONDS = 2

    def ping(self) -> None:
        # The SDK has no limit on the AMQP login (SASL) step: a frozen broker hangs it.
        # So the check runs in a thread and we wait at most PING_SECONDS for it.
        # One ping at a time: while an old one is stuck, fail fast instead of piling up threads.
        if not self._ping_lock.acquire(blocking=False):
            raise ServiceBusError("Previous ping still running; the broker is not answering")
        outcome = {}

        def attempt():
            try:
                with ServiceBusClient.from_connection_string(
                    self._connection_string, retry_total=0, try_timeout=self.PING_SECONDS
                ) as client, client.get_queue_receiver(self.name):
                    pass  # opening = connect + login + attach to the queue
            except Exception as exc:
                outcome["error"] = exc
            finally:
                self._ping_lock.release()

        thread = threading.Thread(target=attempt, name="servicebus-ping", daemon=True)
        thread.start()
        thread.join(self.PING_SECONDS)
        if thread.is_alive():
            raise ServiceBusError(f"Ping timed out after {self.PING_SECONDS} s")
        if "error" in outcome:
            raise outcome["error"]

    @staticmethod
    def _discard(handler):
        if handler is not None:
            with suppress(Exception):
                handler.close()
        return None


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    if settings.CLOUD_PROVIDER == "azure":
        return ServiceBusQueue(
            settings.SERVICE_BUS_CONNECTION_STRING, settings.SERVICE_BUS_QUEUE_NAME
        )
    return SQSQueue(settings.SQS_QUEUE_NAME)
