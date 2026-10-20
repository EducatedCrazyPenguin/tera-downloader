import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_export_revalidates_tampered_logs_and_never_includes_private_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = 'https://terabox.com/private?token=secret'
            diagnostics.record(root, 'attempt', attempt=1, received=100)
            entry = json.loads((root / 'activity.log').read_text())
            entry.update(filename=secret, kind=secret, attempt=secret)
            with (root / 'activity.log').open('a') as output:
                output.write(json.dumps(entry) + '\n' + secret + '\n')
                output.write(json.dumps({**entry, 'event': secret}) + '\n')
                output.write(json.dumps({**entry, 'time': secret}) + '\n')
            report = root / 'report.json'
            diagnostics.export(root, report)
            content = report.read_text()
            self.assertNotIn(secret, content)
            self.assertNotIn('filename', content)
            self.assertEqual(len(json.loads(content)['events']), 2)
            with self.assertRaises(FileExistsError):
                diagnostics.export(root, report)

    def test_rotation_is_bounded_and_write_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostics, 'LIMIT', 400):
            root = Path(directory)
            for i in range(20):
                diagnostics.record(root, 'attempt', attempt=i)
            files = list(root.glob('*.log'))
            self.assertEqual(len(files), 2)
            self.assertTrue(all(f.stat().st_size <= 400 for f in files))
            with patch.object(Path, 'open', side_effect=PermissionError('synthetic secret')):
                diagnostics.record(root, 'completed')
            diagnostics.record(root, 'private unrecognized event')
            retained = list(root.glob('*.log'))
            self.assertTrue(retained)
            self.assertTrue(all('private' not in f.read_text() for f in retained))
            diagnostics.record(root, 'opened')
            self.assertEqual(json.loads((root / 'activity.log').read_text().splitlines()[-1])['event'], 'opened')
