import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch, MagicMock

from app import updater


class TestUpdateCache(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cache = Path(temporary.name) / 'cache.json'
        self.clock = 100000.0
        self.addCleanup(patch.stopall)
        patch.object(updater, 'update_cache_path', return_value=self.cache, create=True).start()
        patch('time.time', side_effect=lambda: self.clock).start()
        self.http = patch.object(updater.urllib.request, 'urlopen').start()
        self.response({'tag_name': 'v3.0.0', 'html_url': 'https://github.com/release',
                       'draft': False, 'prerelease': False})

    def response(self, value, headers=None):
        response = MagicMock()
        response.read.return_value = json.dumps(value).encode()
        response.headers = headers or {}
        self.http.return_value.__enter__.return_value = response

    def error(self, code, headers=None):
        message = Message()
        for key, value in (headers or {}).items():
            message[key] = value
        self.http.side_effect = urllib.error.HTTPError(updater.API_URL, code, 'error', message, None)

    def test_restart_within_interval_uses_persistent_result(self):
        expected = updater.get_latest_release()
        self.clock += 60
        self.assertEqual(updater.get_latest_release(), expected)
        self.assertEqual(self.http.call_count, 1)
        self.assertTrue(self.cache.exists())

    def test_expiry_and_manual_check_query_again(self):
        updater.get_latest_release()
        updater.get_latest_release(is_manual=True)
        self.clock += updater.CHECK_INTERVAL_MS / 1000 + 1
        updater.get_latest_release()
        self.assertEqual(self.http.call_count, 3)

    def test_network_failure_preserves_last_success_time(self):
        updater.get_latest_release()
        original = self.cache.read_bytes()
        self.clock += updater.CHECK_INTERVAL_MS / 1000 + 1
        self.http.side_effect = urllib.error.URLError('offline')
        with self.assertRaises(urllib.error.URLError):
            updater.get_latest_release()
        self.assertEqual(self.cache.read_bytes(), original)

    def test_retry_after_blocks_manual_and_automatic_checks_across_restart(self):
        self.error(429, {'Retry-After': '120'})
        with self.assertRaises(urllib.error.HTTPError):
            updater.get_latest_release()
        self.http.side_effect = None
        for manual in (False, True):
            with self.assertRaises(updater.UpdateDeferred):
                updater.get_latest_release(is_manual=manual)
        self.assertEqual(self.http.call_count, 1)
        self.clock += 121
        updater.get_latest_release(is_manual=True)
        self.assertEqual(self.http.call_count, 2)

    def test_rate_limit_reset_and_retry_date(self):
        from email.utils import formatdate
        for headers in ({'X-RateLimit-Remaining':'0', 'X-RateLimit-Reset':str(self.clock+300)},
                        {'Retry-After':formatdate(self.clock+300, usegmt=True)}):
            with self.subTest(headers=headers):
                self.cache.unlink(missing_ok=True)
                self.error(403, headers)
                with self.assertRaises(urllib.error.HTTPError):
                    updater.get_latest_release()
                with self.assertRaises(updater.UpdateDeferred):
                    updater.get_latest_release(is_manual=True)

    def test_ordinary_403_does_not_impose_rate_limit(self):
        self.error(403)
        for _ in range(2):
            with self.assertRaises(urllib.error.HTTPError):
                updater.get_latest_release()
        self.assertEqual(self.http.call_count, 2)

    def test_success_with_exhausted_quota_defers_manual_check(self):
        self.response({'tag_name':'v3.0.0', 'html_url':'https://github.com/release'},
                      {'X-RateLimit-Remaining':'0', 'X-RateLimit-Reset':str(self.clock+300)})
        updater.get_latest_release()
        with self.assertRaises(updater.UpdateDeferred):
            updater.get_latest_release(is_manual=True)
        self.assertEqual(self.http.call_count, 1)

    def test_corrupt_cache_and_clock_rollback_force_refresh(self):
        self.cache.write_text('{bad')
        updater.get_latest_release()
        self.clock -= 60
        updater.get_latest_release()
        self.assertEqual(self.http.call_count, 2)

    def test_cache_timestamp_without_result_is_not_a_proven_success(self):
        self.cache.write_text(json.dumps({'schema': 1, 'api': updater.API_URL, 'checked_at': self.clock}))
        self.assertEqual(updater.get_latest_release()[0], 'v3.0.0')
        self.assertEqual(self.http.call_count, 1)

    def test_malformed_retry_header_does_not_hide_http_error(self):
        self.error(429, {'Retry-After': 'not-a-date'})
        with self.assertRaises(urllib.error.HTTPError):
            updater.get_latest_release()
        with self.assertRaises(updater.UpdateDeferred):
            updater.get_latest_release(is_manual=True)

    def test_out_of_range_cache_timestamp_does_not_disable_updates(self):
        for field in ('checked_at', 'retry_until'):
            self.cache.write_text(json.dumps({'schema': 1, 'api': updater.API_URL,
                                             'result': None, field: 10**400}))
            self.assertEqual(updater.get_latest_release()[0], 'v3.0.0')
        self.assertEqual(self.http.call_count, 2)

    def test_invalid_release_is_not_a_successful_check(self):
        self.response({'tag_name': 'invalid'})
        with self.assertRaises(ValueError):
            updater.get_latest_release()
        self.assertFalse(self.cache.exists())

    def test_thread_passes_manual_flag_and_emits_deferred_failure(self):
        thread = updater.UpdateCheckThread('1.0.0', True)
        failures = []
        thread.failed.connect(lambda message, manual: failures.append((message, manual)))
        with patch.object(updater, 'get_latest_release', side_effect=updater.UpdateDeferred(60)) as query:
            thread.run()
        query.assert_called_once_with(is_manual=True)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0][1])
