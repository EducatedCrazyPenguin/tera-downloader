import os
from pathlib import Path
import subprocess
import sys

from test_delivery_c import BODY, Client, QueueFixture


class CrashRecoveryTests(QueueFixture):
    def test_crash_at_sync_and_both_sides_of_rename_recovers_exact_file(self):
        self.stop(self.manager)
        for stage, code in [('body', 23), ('before_rename', 24), ('after_rename', 25)]:
            with self.subTest(stage=stage):
                base = self.folder / stage
                base.mkdir()
                result = subprocess.run([sys.executable, str(Path(__file__).with_name('crash_transfer_fixture.py')), str(base), stage],
                                        capture_output=True, timeout=10,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self.assertEqual(result.returncode, code, result.stderr.decode(errors='replace'))
                print(result.stdout.decode().strip())
                previous = self.folder
                self.folder = base
                self.manager = self.make_manager()
                snapshot = self.manager.request('snapshot')
                self.assertFalse(snapshot['running'])
                job = snapshot['jobs'][0]
                self.assertGreater(job['checkpoint']['offset'], 0)
                path = base / 'videos' / ('.tera-' + job['checkpoint']['token'] + '.part')
                if stage == 'body':
                    with path.open('ab') as output: output.write(b'uncommitted tail')
                Client.gate.set()
                Client.calls = []
                self.manager.request('start')
                done = self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
                self.assertEqual(Path(done['jobs'][0]['path']).read_bytes(), BODY)
                self.assertEqual(Client.calls, [job['checkpoint']['offset']] if stage == 'body' else [])
                self.assertFalse(path.exists())
                self.stop(self.manager)
                self.folder = previous
