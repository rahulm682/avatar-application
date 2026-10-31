#!/usr/bin/env python3
"""Create and configure the dev bucket in Silo. Safe to run repeatedly.

Uses the Silo ROOT credentials, because it changes bucket-level configuration.
The same boto3 calls work against real AWS S3 later.
"""
import os
import sys

from botocore.exceptions import ClientError

import s3_common as s3c

BUCKET = os.environ["AWS_STORAGE_BUCKET_NAME"]
ORIGINS = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]


def ensure_bucket(client):
    try:
        client.head_bucket(Bucket=BUCKET)
        print(f"[ok] bucket '{BUCKET}' already exists")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound"):
            client.create_bucket(Bucket=BUCKET)
            print(f"[ok] created bucket '{BUCKET}'")
        else:
            raise


def apply_cors(client):
    client.put_bucket_cors(
        Bucket=BUCKET,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": ORIGINS,
                    "AllowedMethods": ["POST", "GET", "HEAD"],
                    "AllowedHeaders": ["*"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3000,
                }
            ]
        },
    )
    print(f"[ok] CORS rule applied for origins: {', '.join(ORIGINS)}")


def apply_lifecycle(client):
    client.put_bucket_lifecycle_configuration(
        Bucket=BUCKET,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "expire-raw-uploads",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "uploads/"},
                    "Expiration": {"Days": 1},
                }
            ]
        },
    )
    print("[ok] lifecycle rule applied: objects under 'uploads/' expire after 1 day")


def main():
    client = s3c.root_client()
    s3c.wait_for_s3(client)
    ensure_bucket(client)
    apply_cors(client)
    apply_lifecycle(client)
    print("\nBucket setup finished. Next: create the app access key (make app-key), then run the smoke test (make smoke).")


if __name__ == "__main__":
    try:
        main()
    except ClientError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        sys.exit(1)
