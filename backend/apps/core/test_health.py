from unittest.mock import patch

from django.test import TestCase


class HealthTests(TestCase):
    def get(self):
        return self.client.get("/api/health/")

    def test_everything_reachable(self):
        with patch("apps.core.views.check_bucket", return_value="ok"):
            response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok", "s3": "ok"})

    def test_storage_problem_is_reported_as_degraded(self):
        with patch("apps.core.views.check_bucket", return_value="error: EndpointConnectionError"):
            body = self.get().json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["database"], "ok")
        self.assertTrue(body["s3"].startswith("error"))

    def test_database_problem_is_reported_as_degraded(self):
        with patch("apps.core.views.check_bucket", return_value="ok"), patch("apps.core.views.connection") as connection:
            connection.ensure_connection.side_effect = RuntimeError("db is down")
            body = self.get().json()
        self.assertEqual(body["status"], "degraded")
        self.assertTrue(body["database"].startswith("error"))

    def test_health_check_needs_no_login(self):
        with patch("apps.core.views.check_bucket", return_value="not configured"):
            self.assertEqual(self.get().status_code, 200)