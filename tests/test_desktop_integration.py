"""Offline desktop checks: no Tk, shell, provider or real notifications."""
import queue
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from desktop_integration import Desktop, Notifications
from app_state import StateError, StateStore
from test_delivery_c import QueueFixture
from tera_gui import TeraApp


class FakeIcon:
    def __init__(self):
        self.visible = False
        self.exit = threading.Event()
        self.messages = []

    def run(self, setup):
        setup(self)
        self.exit.wait(3)

    def stop(self):
        self.exit.set()

    def notify(self, message, title):
        self.messages.append((message, title))


class DesktopTests(unittest.TestCase):
    def test_stop_during_registration_releases_worker(self):
        entered, gate = threading.Event(), threading.Event()
        class RegisteringIcon(FakeIcon):
            @property
            def visible(self): return False
            @visible.setter
            def visible(self, value):
                if value:
                    entered.set()
                    gate.wait(2)
        desktop = Desktop(queue.Queue(), lambda dispatch: RegisteringIcon())
        try:
            desktop.start()
            self.assertTrue(entered.wait(1))
            desktop.stop()
        finally:
            gate.set()
            self.assertTrue(desktop.stopped.wait(2))
            desktop.thread.join(1)
            desktop.stop_thread.join(1)
        self.assertFalse(desktop.thread.is_alive())
        self.assertFalse(desktop.stop_thread.is_alive())

    def test_close_waits_for_tray_without_claiming_a_save_failure(self):
        app = TeraApp.__new__(TeraApp)
        app.manager = Mock(events=queue.Queue())
        app.manager.closed.is_set.return_value = True
        app.ui_events = queue.Queue()
        app.desktop = Desktop(app.ui_events)
        app.desktop.stopped.clear()
        app.closing, app.close_error, app.destroyed = True, False, False
        app.login_thread = None
        app.root, app.status, app.configure_controls = Mock(), Mock(), Mock()
        app.root.winfo_children.return_value = []
        app.poll()
        self.assertFalse(app.destroyed)
        app.status.set.assert_not_called()
        app.root.after.assert_called_once()
        app.desktop.stopped.set()

    def test_ready_dispatch_and_stop_are_bounded(self):
        events, icon = queue.Queue(), FakeIcon()
        desktop = Desktop(events, lambda dispatch: icon)
        try:
            desktop.start()
            self.assertEqual(events.get(timeout=2), ('desktop', 'ready'))
            self.assertTrue(icon.visible)
            desktop.dispatch('restore')
            self.assertEqual(events.get(timeout=2), ('desktop', 'restore'))
            desktop.notify('Downloads finished. Open Tera for results.')
            self.assertEqual(len(icon.messages), 1)
        finally:
            desktop.stop()
            self.assertTrue(desktop.stopped.wait(2))
            desktop.thread.join(1)
        self.assertFalse(desktop.thread.is_alive())

    def test_cancel_before_ready_never_publishes_ready(self):
        gate, entered = threading.Event(), threading.Event()
        events, icon = queue.Queue(), FakeIcon()
        def factory(dispatch):
            entered.set()
            gate.wait(2)
            return icon
        desktop = Desktop(events, factory)
        try:
            desktop.start()
            self.assertTrue(entered.wait(1))
            desktop.stop()
        finally:
            gate.set()
            self.assertTrue(desktop.stopped.wait(2))
        self.assertNotIn(('desktop', 'ready'), list(events.queue))

    def test_failure_does_not_publish_ready_or_private_error(self):
        events = queue.Queue()
        def fail(dispatch):
            raise RuntimeError('https://private.example/secret')
        desktop = Desktop(events, fail)
        desktop.start()
        self.assertTrue(desktop.stopped.wait(2))
        self.assertEqual(list(events.queue), [('desktop', 'failed')])

    def test_notify_failure_is_reported_without_exception_text(self):
        desktop = Desktop(queue.Queue(), lambda dispatch: None)
        desktop.icon = FakeIcon()
        desktop.ready.set()
        with patch.object(desktop.icon, 'notify', side_effect=OSError('private')):
            desktop.notify('generic')
        self.assertEqual(desktop.events.get_nowait(), ('desktop', 'notification_failed'))


def snapshot(status='pending', *, running=False, message='', attempt=1, enabled=True):
    return {'preferences': {'notifications': enabled}, 'jobs': [{'id': 'a', 'status': status, 'attempt': attempt}],
            'running': running, 'message': message, 'closing': False, 'active': None,
            'policy_hold': '', 'run_state': {'id': 'run'}}


class NotificationTests(unittest.TestCase):
    def test_no_restore_or_disabled_notifications(self):
        for enabled in (False, True):
            tracker = Notifications()
            self.assertEqual(tracker.observe(snapshot('failed', enabled=enabled)), [])
            self.assertEqual(tracker.observe(snapshot('failed', enabled=enabled)), [])
        tracker = Notifications()
        tracker.observe(snapshot(running=True, enabled=False))
        self.assertEqual(tracker.observe(snapshot('completed', message='Queue finished: private', enabled=False)), [])

    def test_attention_once_per_attempt_and_generic_contents(self):
        tracker = Notifications()
        tracker.observe(snapshot(running=True))
        held = snapshot('login', running=True)
        self.assertEqual(tracker.observe(held), ['Downloads need attention. Open Tera for details.'])
        for unused in range(4):
            self.assertEqual(tracker.observe(held), [])
        tracker.observe(snapshot(running=True, attempt=2))
        self.assertEqual(len(tracker.observe(snapshot('login', running=True, attempt=2))), 1)

    def test_queue_finished_once_and_no_cancel_or_exit_popup(self):
        tracker = Notifications()
        tracker.observe(snapshot(running=True))
        done = snapshot('completed', message='Queue finished: private-name')
        self.assertEqual(tracker.observe(done), ['Downloads finished. Open Tera for results.'])
        self.assertEqual(tracker.observe(done), [])
        tracker.observe(snapshot(running=True))
        self.assertEqual(tracker.observe(snapshot('cancelled')), [])
        tracker.observe(snapshot(running=True))
        done['closing'] = True
        self.assertEqual(tracker.observe(done), [])

    def test_latched_run_limit_once_while_schedule_and_manual_holds_are_quiet(self):
        tracker = Notifications()
        value = snapshot(running=True)
        tracker.observe(value)
        for reason in ('schedule', ''):
            value['policy_hold'] = reason
            self.assertEqual(tracker.observe(value), [])
        value['policy_hold'] = 'bytes'
        self.assertEqual(tracker.observe(value), ['Run limit reached. Open Tera to start a new run.'])
        self.assertEqual(tracker.observe(value), [])


class DesktopPreferencesTests(QueueFixture):
    def test_notifications_default_off_and_persist_without_starting_work(self):
        self.assertNotIn('notifications', self.manager.request('snapshot')['preferences'])
        for value in ('yes', 1, None):
            with self.assertRaises(StateError):
                self.manager.request('preferences', changes={'notifications': value})
        self.manager.request('preferences', changes={'notifications': True})
        self.stop(self.manager)
        self.manager = self.make_manager()
        restored = self.manager.request('snapshot')
        self.assertIs(restored['preferences']['notifications'], True)
        self.assertFalse(restored['running'])

    def test_malformed_desktop_preference_refused_without_rewriting(self):
        with tempfile.TemporaryDirectory() as folder:
            with StateStore(folder) as store:
                path = Path(folder) / 'settings.json'
                text = '{"notifications":"yes"}'
                path.write_text(text)
                with self.assertRaises(StateError):
                    store.load_preferences()
                self.assertEqual(path.read_text(), text)
