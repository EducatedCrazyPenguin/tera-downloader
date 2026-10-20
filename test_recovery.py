import unittest

from recovery import can_retry, retry_delay


class RecoveryTests(unittest.TestCase):
    def test_retry_after_seconds_dates_and_invalid_values(self):
        self.assertEqual(retry_delay('12', 0), 12)
        self.assertEqual(retry_delay('Thu, 01 Jan 1970 00:00:10 GMT', 3), 7)
        for value in ('nan', 'inf', 'invalid', None):
            self.assertEqual(retry_delay(value), 5)
        self.assertEqual(retry_delay('-1'), 0)

    def test_two_attempt_budget_and_no_automatic_full_restart(self):
        for kind in ('transient', 'expired'):
            self.assertTrue(can_retry(kind, 1, {}))
            self.assertTrue(can_retry(kind, 1, {'offset': 5, 'etag': '"strong"'}))
            self.assertFalse(can_retry(kind, 2, {}))
            self.assertFalse(can_retry(kind, 1, {'offset': 5, 'etag': ''}))
            self.assertFalse(can_retry(kind, 1, {'phase': 'invalid'}))
        for kind in ('login', 'storage', 'integrity', 'restart', 'unknown', 'access'):
            self.assertFalse(can_retry(kind, 1, {}))
