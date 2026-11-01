import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

import boto3
from django.conf import settings


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


class SQSQueue(Queue):
    def __init__(self, queue_name: str):
        self.client = boto3.client(
            "sqs",
            endpoint_url=settings.AWS_SQS_ENDPOINT_URL,
            region_name=settings.AWS_REGION,
        )
        self.url = self.client.get_queue_url(QueueName=queue_name)["QueueUrl"]

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
        self.client.delete_message(QueueUrl=self.url, ReceiptHandle=message.receipt_handle)


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    return SQSQueue(settings.SQS_QUEUE_NAME)