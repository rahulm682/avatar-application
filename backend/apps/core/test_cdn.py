"""Tests for CDN invalidation (Step 6). No real Varnish is needed: HTTP calls are mocked."""
from unittest.mock import patch

import requests
from django.test import TestCase, override_settings

from apps.accounts.emailhash import hash_email
from apps.core import cdn

HASH_A = hash_email("a@example.com")
HASH_B = hash_email("b@example.com")


@override_settings(INVALIDATION_BACKEND="varnish", VARNISH_BAN_URL="http://varnish:80")
class VarnishBackendTests(TestCase):
    def invalidate(self, *hashes):
        """Runs the call and then the on-commit callbacks, as happens at the end of a real request."""
        with self.captureOnCommitCallbacks(execute=True):
            cdn.invalidate_email_hashes(*hashes)

    def test_sends_one_ban_per_hash(self):
        with patch("apps.core.cdn.requests.request") as request:
            request.return_value.status_code = 200
            self.invalidate(HASH_A, HASH_B)
        self.assertEqual(request.call_count, 2)
        first = request.call_args_list[0]
        self.assertEqual(first.args, ("BAN", "http://varnish:80/"))
        self.assertEqual(first.kwargs["headers"], {"X-Ban-Pattern": f"^/avatar/{HASH_A}"})
        self.assertEqual(first.kwargs["timeout"], cdn.BAN_TIMEOUT)
        self.assertEqual(request.call_args_list[1].kwargs["headers"], {"X-Ban-Pattern": f"^/avatar/{HASH_B}"})

    def test_duplicates_and_empty_values_are_ignored(self):
        with patch("apps.core.cdn.requests.request") as request:
            request.return_value.status_code = 200
            self.invalidate(HASH_A, HASH_A, "", None)
        self.assertEqual(request.call_count, 1)

    def test_nothing_is_sent_until_the_transaction_commits(self):
        with patch("apps.core.cdn.requests.request") as request:
            request.return_value.status_code = 200
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                cdn.invalidate_email_hashes(HASH_A)
            request.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            request.assert_called_once()

    def test_nothing_is_scheduled_for_an_empty_call(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            cdn.invalidate_email_hashes()
            cdn.invalidate_email_hashes("", None)
        self.assertEqual(callbacks, [])

    def test_connection_failure_never_raises_and_schedules_a_retry(self):
        with patch("apps.core.cdn.requests.request", side_effect=requests.ConnectionError("down")), patch(
            "apps.core.cdn._schedule_retry"
        ) as schedule:
            self.invalidate(HASH_A)
        schedule.assert_called_once_with([HASH_A])

    def test_a_refusal_counts_as_a_failure(self):
        with patch("apps.core.cdn.requests.request") as request, patch("apps.core.cdn._schedule_retry") as schedule:
            request.return_value.status_code = 403
            self.invalidate(HASH_A)
        schedule.assert_called_once_with([HASH_A])

    def test_only_the_failed_hashes_are_retried(self):
        outcomes = {HASH_A: True, HASH_B: False}
        with patch("apps.core.cdn._ban_varnish", side_effect=lambda h: outcomes[h]), patch(
            "apps.core.cdn._schedule_retry"
        ) as schedule:
            self.invalidate(HASH_A, HASH_B)
        schedule.assert_called_once_with([HASH_B])

    def test_malformed_hashes_are_refused(self):
        with patch("apps.core.cdn.requests.request") as request:
            with self.assertLogs("apps.core.cdn", level="ERROR"):
                self.invalidate("^/avatar/.*", HASH_A.upper())
        request.assert_not_called()

    @override_settings(VARNISH_BAN_URL="")
    def test_missing_ban_url_is_reported(self):
        with patch("apps.core.cdn.requests.request") as request:
            with self.assertLogs("apps.core.cdn", level="ERROR"):
                self.invalidate(HASH_A)
        request.assert_not_called()


class RetryTests(TestCase):
    def test_retry_stops_after_the_first_success(self):
        with patch("apps.core.cdn.time.sleep") as sleep, patch("apps.core.cdn._ban_varnish", side_effect=[False, True]) as ban:
            cdn._retry([HASH_A])
        self.assertEqual(ban.call_count, 2)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], list(cdn.RETRY_DELAYS[:2]))

    def test_retry_gives_up_after_the_last_delay(self):
        with patch("apps.core.cdn.time.sleep"), patch("apps.core.cdn._ban_varnish", return_value=False) as ban:
            with self.assertLogs("apps.core.cdn", level="ERROR"):
                cdn._retry([HASH_A])
        self.assertEqual(ban.call_count, len(cdn.RETRY_DELAYS))

    def test_retry_only_repeats_what_still_fails(self):
        results = {HASH_A: iter([True]), HASH_B: iter([False, True])}
        with patch("apps.core.cdn.time.sleep"), patch("apps.core.cdn._ban_varnish", side_effect=lambda h: next(results[h])) as ban:
            cdn._retry([HASH_A, HASH_B])
        self.assertEqual([call.args[0] for call in ban.call_args_list], [HASH_A, HASH_B, HASH_B])


class OtherBackendTests(TestCase):
    def run_invalidation(self):
        with self.captureOnCommitCallbacks(execute=True):
            cdn.invalidate_email_hashes(HASH_A)

    @override_settings(INVALIDATION_BACKEND="log")
    def test_log_backend_only_logs(self):
        with patch("apps.core.cdn.requests.request") as request:
            with self.assertLogs("apps.core.cdn", level="INFO") as logs:
                self.run_invalidation()
        request.assert_not_called()
        self.assertIn(HASH_A, logs.output[0])

    @override_settings(INVALIDATION_BACKEND="cloudfront")
    def test_cloudfront_is_a_reported_placeholder(self):
        with patch("apps.core.cdn.requests.request") as request:
            with self.assertLogs("apps.core.cdn", level="WARNING"):
                self.run_invalidation()
        request.assert_not_called()

    @override_settings(INVALIDATION_BACKEND="carrier-pigeon")
    def test_unknown_backend_is_reported(self):
        with self.assertLogs("apps.core.cdn", level="ERROR"):
            self.run_invalidation()