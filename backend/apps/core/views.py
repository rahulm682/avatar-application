from django.db import connection
from django.http import JsonResponse

from .s3 import check_bucket


def health(request):
    """Reports whether the backend can reach its database and the S3 bucket."""
    database = "ok"
    try:
        connection.ensure_connection()
    except Exception as exc:  # noqa: BLE001
        database = f"error: {exc.__class__.__name__}"

    s3 = check_bucket()
    overall = "ok" if database == "ok" and s3 == "ok" else "degraded"
    return JsonResponse({"status": overall, "database": database, "s3": s3})