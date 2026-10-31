#!/bin/sh
# Runs INSIDE the Silo container (see `make app-key`).
# Creates the application's own access key, restricted to the one dev bucket.
# Uses only shell built-ins plus mcli/mc, because the Silo image has no sed, cat, awk, etc.
set -eu

MC="$(command -v mcli || command -v mc || true)"
if [ -z "$MC" ]; then
  echo "Could not find 'mcli' or 'mc' in the Silo image. Create the user and policy in the console at http://localhost:9001 instead." >&2
  exit 1
fi

: "${MINIO_ROOT_USER:?missing}" "${MINIO_ROOT_PASSWORD:?missing}"
: "${AWS_ACCESS_KEY_ID:?Set AWS_ACCESS_KEY_ID in .env}" "${AWS_SECRET_ACCESS_KEY:?Set AWS_SECRET_ACCESS_KEY in .env}"
: "${AWS_STORAGE_BUCKET_NAME:?missing}"

"$MC" alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

# Policy: list the one bucket, and read/write/delete objects in it. Nothing else.
BUCKET_ARN="arn:aws:s3:::${AWS_STORAGE_BUCKET_NAME}"
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

# The sub-commands differ between versions, so try the newer syntax first.
# Failures are shown but not fatal (the policy or user may already exist); `make smoke` verifies the result.
if ! out1="$("$MC" admin policy create local avatars-app /tmp/app-policy.json 2>&1)"; then
  if ! out2="$("$MC" admin policy add local avatars-app /tmp/app-policy.json 2>&1)"; then
    echo "note: policy not created (it may already exist):"
    echo "  $out1"
  fi
fi

if ! out="$("$MC" admin user add local "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" 2>&1)"; then
  echo "note: user not added (it may already exist):"
  echo "  $out"
fi

if ! out1="$("$MC" admin policy attach local avatars-app --user "$AWS_ACCESS_KEY_ID" 2>&1)"; then
  if ! out2="$("$MC" admin policy set local avatars-app user="$AWS_ACCESS_KEY_ID" 2>&1)"; then
    echo "note: policy not attached (it may already be attached):"
    echo "  $out1"
  fi
fi

echo "[ok] application key '$AWS_ACCESS_KEY_ID' is set up for bucket '$AWS_STORAGE_BUCKET_NAME'"
