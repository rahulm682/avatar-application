#!/bin/sh

# Runs inside the Silo container.
# Creates the application's restricted access key.

set -eu

MC="$(command -v mcli || command -v mc || true)"

if [ -z "$MC" ]; then
    echo "[FAIL] Could not find mcli or mc in the Silo image." >&2
    exit 1
fi

: "${MINIO_ROOT_USER:?Missing MINIO_ROOT_USER}"
: "${MINIO_ROOT_PASSWORD:?Missing MINIO_ROOT_PASSWORD}"

: "${AWS_ACCESS_KEY_ID:?Set AWS_ACCESS_KEY_ID in .env}"
: "${AWS_SECRET_ACCESS_KEY:?Set AWS_SECRET_ACCESS_KEY in .env}"
: "${AWS_STORAGE_BUCKET_NAME:?Set AWS_STORAGE_BUCKET_NAME in .env}"

echo "[1/4] Configuring Silo admin connection..."

"$MC" alias set local \
    http://localhost:9000 \
    "$MINIO_ROOT_USER" \
    "$MINIO_ROOT_PASSWORD"

BUCKET_ARN="arn:aws:s3:::${AWS_STORAGE_BUCKET_NAME}"

echo "[2/4] Creating application policy..."

printf '%s\n' \
    '{' \
    '  "Version": "2012-10-17",' \
    '  "Statement": [' \
    '    {' \
    '      "Effect": "Allow",' \
    '      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],' \
    "      \"Resource\": [\"${BUCKET_ARN}\"]" \
    '    },' \
    '    {' \
    '      "Effect": "Allow",' \
    '      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],' \
    "      \"Resource\": [\"${BUCKET_ARN}/*\"]" \
    '    }' \
    '  ]' \
    '}' > /tmp/app-policy.json

if "$MC" admin policy info local avatars-app >/dev/null 2>&1; then
    echo "[ok] Policy already exists."
else
    "$MC" admin policy create local avatars-app /tmp/app-policy.json
    echo "[ok] Policy created."
fi

echo "[3/4] Creating application user..."

if "$MC" admin user info local "$AWS_ACCESS_KEY_ID" >/dev/null 2>&1; then
    echo "[warning] User already exists: $AWS_ACCESS_KEY_ID"
    echo "[warning] Its existing secret key has not been verified."
    echo "[warning] If the secret differs from .env, use a fresh access key."
else
    "$MC" admin user add local \
        "$AWS_ACCESS_KEY_ID" \
        "$AWS_SECRET_ACCESS_KEY"

    echo "[ok] Application user created."
fi

echo "[4/4] Attaching application policy..."

"$MC" admin policy attach local avatars-app \
    --user="$AWS_ACCESS_KEY_ID"

echo "[ok] Application user and policy are configured."
echo "Run 'make smoke' to verify S3 access."