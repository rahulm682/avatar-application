"""S3 client helpers. Works against Silo locally and AWS S3 later; only settings differ."""
import boto3
from botocore.config import Config
from django.conf import settings


def _config():
    return Config(
        signature_version="s3v4",
        s3={"addressing_style": settings.AWS_S3_ADDRESSING_STYLE},
        # Some S3-compatible servers reject the checksum headers newer boto3 adds by default.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        connect_timeout=3,
        read_timeout=5,
        retries={"max_attempts": 2},
    )


def get_s3_client(public=False):
    """Internal client for server-side calls; public=True signs URLs with the browser-reachable address."""
    endpoint = settings.AWS_S3_PUBLIC_ENDPOINT_URL if public else settings.AWS_S3_ENDPOINT_URL
    return boto3.client(
        "s3",
        endpoint_url=endpoint or settings.AWS_S3_ENDPOINT_URL,
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        config=_config(),
    )


def check_bucket():
    """Returns 'ok', 'not configured', or a short error description."""
    if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_STORAGE_BUCKET_NAME:
        return "not configured"
    try:
        get_s3_client().head_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
        return "ok"
    except Exception as exc:  # noqa: BLE001 - report any failure as text
        return f"error: {exc.__class__.__name__} (did you run 'make setup'?)"
