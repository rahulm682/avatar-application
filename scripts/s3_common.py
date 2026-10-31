"""Shared helpers for the S3 setup and smoke-test scripts."""
import os
import sys
import time

import boto3
from botocore.config import Config


def _config():
    return Config(
        signature_version="s3v4",
        s3={"addressing_style": os.environ.get("AWS_S3_ADDRESSING_STYLE", "path")},
        # Newer boto3 versions add checksum headers that some S3-compatible servers reject.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        retries={"max_attempts": 3},
    )


def make_client(access_key, secret_key, endpoint):
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=_config(),
    )


def root_client():
    """Silo root user. Only for setup scripts, never for the application."""
    return make_client(
        os.environ["SILO_ROOT_USER"],
        os.environ["SILO_ROOT_PASSWORD"],
        os.environ["AWS_S3_ENDPOINT_URL"],
    )


def app_client():
    """The application's restricted access key, using the internal endpoint."""
    return make_client(
        os.environ["AWS_ACCESS_KEY_ID"],
        os.environ["AWS_SECRET_ACCESS_KEY"],
        os.environ["AWS_S3_ENDPOINT_URL"],
    )


def public_signing_client():
    """Signs presigned POSTs with the address the BROWSER will use."""
    return make_client(
        os.environ["AWS_ACCESS_KEY_ID"],
        os.environ["AWS_SECRET_ACCESS_KEY"],
        os.environ.get("AWS_S3_PUBLIC_ENDPOINT_URL") or os.environ["AWS_S3_ENDPOINT_URL"],
    )


def wait_for_s3(client, timeout=90):
    """Wait until the S3 server accepts requests."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            client.list_buckets()
            return
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready yet"
            last_error = exc
            time.sleep(2)
    print(f"S3 server did not become ready within {timeout}s: {last_error}", file=sys.stderr)
    sys.exit(1)
