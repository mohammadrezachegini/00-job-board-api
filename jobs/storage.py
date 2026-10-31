from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config
from django.conf import settings


@lru_cache
def _public_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_PUBLIC_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version="s3v4"),
    )

def resume_download_url(application):
    extension = Path(application.resume.name).suffix
    return _public_s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "Key": application.resume.name,
            "ResponseContentDisposition": f'attachment; filename=\"resume-{application.id}{extension}"'
        },
        ExpiresIn=settings.RESUME_URL_EXPIRE_SECONDS,  # URL expiration time in seconds
    )