from datetime import datetime, timezone, timedelta
import threading
import unittest

from run_policy import BandwidthLimiter, RunPolicy, in_window, validate_options


class FakeClock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value
    def wait(self, seconds): self.value += seconds; return False


class RunPolicyTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        options = validate_options({})
        self.assertEqual(options['speed_bps'], 0)
        self.assertFalse(options['schedule_enabled'])
        for changes in ({'speed_bps': -1}, {'speed_bps': True}, {'byte_budget': 1.5}, {'deadline_minutes': -1},
                        {'start': '25:00'}, {'end': '1:00'}, {'schedule_enabled': 1}, {'unknown': 0}, {'deadline_minutes': 2 ** 63 - 1},
                        {'schedule_enabled': True, 'start': '12:00', 'end': '12:00'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): validate_options(changes)

    def test_normal_overnight_boundaries_and_timezone_recalculation(self):
        local = datetime(2026, 10, 20, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        options = validate_options({'schedule_enabled': True, 'start': '09:00', 'end': '10:00'})
        self.assertTrue(in_window(options, local))
        self.assertFalse(in_window(options, local.replace(hour=10)))
        self.assertFalse(in_window(options, local.replace(hour=8, minute=59)))
        overnight = {**options, 'start': '22:00', 'end': '06:00'}
        for hour in (22, 23, 0, 5): self.assertTrue(in_window(overnight, local.replace(hour=hour)))
        for hour in (6, 21): self.assertFalse(in_window(overnight, local.replace(hour=hour)))
        self.assertFalse(in_window(options, local.astimezone(timezone.utc)))

    def test_deadline_bytes_and_latched_hold_do_not_reset_on_resume_or_reconfigure(self):
        policy = RunPolicy({'byte_budget': 10, 'deadline_minutes': 2})
        policy.begin(now=100)
        policy.add_bytes(4)
        self.assertEqual(policy.reason(now=150), '')
        policy.add_bytes(6)
        self.assertEqual(policy.reason(now=151), 'bytes')
        policy.options = validate_options({})
        self.assertEqual(policy.reason(now=1000), 'bytes')
        restored = RunPolicy({}, policy.record)
        self.assertEqual(restored.reason(now=1000), 'bytes')
        restored.begin(now=1100)
        self.assertEqual(restored.record['bytes'], 0)
        self.assertEqual(restored.reason(now=1100), '')
        restored.options = validate_options({'deadline_minutes': 1})
        self.assertEqual(restored.reason(now=1160), 'deadline')

    def test_schedule_hold_releases_without_releasing_a_budget_hold(self):
        policy = RunPolicy({'schedule_enabled': True, 'start': '09:00', 'end': '10:00', 'byte_budget': 1})
        policy.begin(now=100)
        self.assertEqual(policy.reason(now=101, local=datetime(2026, 10, 20, 8)), 'schedule')
        self.assertEqual(policy.reason(now=102, local=datetime(2026, 10, 20, 9)), '')
        policy.add_bytes(2)
        self.assertEqual(policy.reason(now=103, local=datetime(2026, 10, 20, 9)), 'bytes')
        self.assertEqual(policy.reason(now=104, local=datetime(2026, 10, 20, 8)), 'bytes')

    def test_corrupt_saved_run_is_rejected(self):
        policy = RunPolicy()
        policy.begin(now=100)
        for key, value in [('bytes', -1), ('started', float('nan')), ('started', 1e300), ('open', 1), ('limit_hold', 'schedule'), ('id', '../bad')]:
            with self.subTest(key=key), self.assertRaises(ValueError): RunPolicy({}, {**policy.record, key: value})

    def test_pacing_has_bounded_reads_and_no_credit_burst_after_idle(self):
        clock = FakeClock()
        limiter = BandwidthLimiter(100, clock=clock)
        self.assertEqual(limiter.read_size(), 10)
        checks = []
        limiter.received(10)
        limiter.wait(lambda: checks.append(True), clock)
        self.assertAlmostEqual(clock.value, .1)
        self.assertTrue(checks)
        clock.value += 100
        limiter.received(10)
        limiter.wait(lambda: None, clock)
        self.assertAlmostEqual(clock.value, 100.2)
        limiter.set_rate(1)
        self.assertEqual(limiter.read_size(), 1)
        limiter.received(1)
        limiter.wait(lambda: None, clock)
        self.assertAlmostEqual(clock.value, 101.2)
        limiter.set_rate(0)
        self.assertEqual(limiter.read_size(), 256 * 1024)

    def test_dynamic_cap_change_and_cancel_interrupt_throttle_wait(self):
        clock = FakeClock()
        limiter = BandwidthLimiter(1, clock=clock)
        limiter.received(1)
        def remove_limit(): limiter.set_rate(0)
        limiter.wait(remove_limit, clock)
        self.assertEqual(clock.value, 0)
        limiter.set_rate(1)
        limiter.received(1)
        cancel = threading.Event()
        cancel.set()
        def check():
            if cancel.is_set(): raise RuntimeError('Stopped')
        with self.assertRaisesRegex(RuntimeError, 'Stopped'): limiter.wait(check, cancel)
