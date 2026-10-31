"""The API schema must generate without errors and list every endpoint (it feeds /api/docs/ in development)."""
from django.test import TestCase
from drf_spectacular.generators import SchemaGenerator


class SchemaTests(TestCase):
    def test_schema_generates_and_lists_the_endpoints(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        paths = set(schema["paths"])
        expected = {
            "/api/auth/register/", "/api/auth/verify-email/", "/api/auth/resend-verification/",
            "/api/auth/login/", "/api/auth/refresh/", "/api/auth/logout/",
            "/api/auth/password-reset/request/", "/api/auth/password-reset/confirm/",
            "/api/auth/change-password/", "/api/auth/email-change/request/", "/api/auth/email-change/confirm/",
            "/api/me/", "/api/me/current-avatar/",
            "/api/avatars/", "/api/avatars/upload-url/", "/api/avatars/confirm/", "/api/avatars/{id}/",
            "/api/reports/",
        }
        self.assertEqual(expected - paths, set(), "endpoints missing from the schema")

    def test_public_endpoints_are_not_marked_as_requiring_a_token(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        for path in ("/api/auth/login/", "/api/auth/register/", "/api/reports/"):
            security = schema["paths"][path]["post"].get("security")
            self.assertIn(security, (None, [], [{}]), path)