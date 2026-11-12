from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import boto3
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from botocore.config import Config
from django.conf import settings


def resume_download_url(application):
    if settings.CLOUD_PROVIDER == "azure":
        return _azure_download_url(application)
    return _s3_download_url(application)


def _download_filename(application):
    return f"resume-{application.id}{Path(application.resume.name).suffix}"


@lru_cache
def _public_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_PUBLIC_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version="s3v4"),
    )


def _s3_download_url(application):
    return _public_s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "Key": application.resume.name,
            "ResponseContentDisposition": f'attachment; filename="{_download_filename(application)}"',
        },
        ExpiresIn=settings.RESUME_URL_EXPIRE_SECONDS,
    )


def _azure_download_url(application):
    name = application.resume.name
    sas = generate_blob_sas(
        account_name=settings.AZURE_ACCOUNT_NAME,
        container_name=settings.AZURE_CONTAINER,
        blob_name=name,
        account_key=settings.AZURE_ACCOUNT_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(seconds=settings.RESUME_URL_EXPIRE_SECONDS),
        content_disposition=f'attachment; filename="{_download_filename(application)}"',
    )
    return f"{settings.AZURE_PUBLIC_BLOB_ENDPOINT}/{settings.AZURE_CONTAINER}/{quote(name)}?{sas}"
