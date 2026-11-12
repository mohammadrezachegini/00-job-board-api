import pytest

from jobs.models import Application, CandidateProfile, Company, Job, User

PASSWORD = "test-pass-123"


@pytest.fixture
def make_company(db):
    def _make(username="acme", verified=True, name=None):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password=PASSWORD,
            role=User.Role.COMPANY,
        )
        return Company.objects.create(
            user=user, name=name or username.title(), is_verified=verified
        )

    return _make


@pytest.fixture
def make_candidate(db):
    def _make(username="sam", skills=None):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password=PASSWORD,
            role=User.Role.CANDIDATE,
        )
        return CandidateProfile.objects.create(user=user, skills=skills or [])

    return _make


@pytest.fixture
def make_job(db):
    def _make(company, title="Junior DevOps Engineer", required_skills=None, location="Vancouver", **fields):
        return Job.objects.create(
            company=company,
            title=title,
            description="Build and run things.",
            location=location,
            required_skills=required_skills or [],
            **fields,
        )

    return _make

@pytest.fixture
def make_application(db):
    def _make(job, candidate, **fields):
        return Application.objects.create(job=job, candidate=candidate, **fields)

    return _make


@pytest.fixture(autouse=True)
def local_cache(settings):
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
    from django.core.cache import cache

    cache.clear()


@pytest.fixture(autouse=True)
def fast_password_hashing(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def api_as():
    from rest_framework.test import APIClient

    def _client(user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        return client

    return _client



@pytest.fixture
def aws(settings):
    import json
    from types import SimpleNamespace

    import boto3
    from moto import mock_aws

    from cloud.queue import get_queue
    from jobs.storage import _public_s3_client

    settings.AWS_S3_ENDPOINT_URL = None
    settings.AWS_S3_PUBLIC_ENDPOINT_URL = None
    settings.AWS_SQS_ENDPOINT_URL = None
    settings.STORAGES = {**settings.STORAGES}
    get_queue.cache_clear()
    _public_s3_client.cache_clear()

    with mock_aws():
        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        s3.create_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)

        sqs = boto3.client("sqs", region_name=settings.AWS_REGION)
        dlq_url = sqs.create_queue(QueueName=f"{settings.SQS_QUEUE_NAME}-dlq")["QueueUrl"]
        dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        queue_url = sqs.create_queue(
            QueueName=settings.SQS_QUEUE_NAME,
            Attributes={
                "VisibilityTimeout": "30",
                "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}),
            },
        )["QueueUrl"]

        yield SimpleNamespace(s3=s3, sqs=sqs, queue_url=queue_url, bucket=settings.AWS_STORAGE_BUCKET_NAME)

    get_queue.cache_clear()
    _public_s3_client.cache_clear()

@pytest.fixture
def azure_blob(settings):
    """Switch storage to Azure Blob (Azurite) with a fresh container for this test."""
    import os
    import time
    import uuid
    from types import SimpleNamespace

    from azure.core.exceptions import AzureError
    from azure.storage.blob import BlobServiceClient

    account = os.environ["AZURE_ACCOUNT_NAME"]
    key = os.environ["AZURE_ACCOUNT_KEY"]
    endpoint = os.environ["AZURE_BLOB_ENDPOINT"]
    container = f"test-{uuid.uuid4().hex[:12]}"
    connection_string = (
        f"DefaultEndpointsProtocol=http;AccountName={account};AccountKey={key};BlobEndpoint={endpoint};"
    )

    settings.CLOUD_PROVIDER = "azure"
    settings.AZURE_ACCOUNT_NAME = account
    settings.AZURE_ACCOUNT_KEY = key
    settings.AZURE_CONTAINER = container
    settings.AZURE_BLOB_ENDPOINT = endpoint
    settings.AZURE_PUBLIC_BLOB_ENDPOINT = endpoint  # tests download from inside the Compose network
    settings.AZURE_CONNECTION_STRING = connection_string
    settings.AZURE_OVERWRITE_FILES = False
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "storages.backends.azure_storage.AzureStorage"},
    }

    # retry_total=0 + connection_timeout=2: each attempt fails in ~2 s, so OUR 15 s deadline decides,
    # not the SDK's default retries (~80 s per call when Azurite is down).
    client = BlobServiceClient.from_connection_string(
        connection_string, retry_total=0, connection_timeout=2
    ).get_container_client(container)
    deadline = time.monotonic() + 15
    while True:
        try:
            client.create_container()
            break
        except AzureError:
            if time.monotonic() > deadline:
                pytest.fail(f"Azurite not reachable at {endpoint}: is the azurite service running?")
            time.sleep(0.5)

    yield SimpleNamespace(container=client, name=container)

    client.delete_container()
