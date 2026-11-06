import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property, lru_cache

import boto3
from django.conf import settings
from botocore.config import Config


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


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    return SQSQueue(settings.SQS_QUEUE_NAME)
