import unittest
from pathlib import Path
from unittest.mock import patch

import terabox
from tera_gui import duration_text, size_text


class EntryTests(unittest.TestCase):
    def test_cli_routes_isolated_data_directory_to_gui(self):
        with patch('sys.argv', ['terabox.py', '--data-dir', 'synthetic-state']), patch('tera_gui.gui') as launch:
            terabox.main()
            launch.assert_called_once_with(Path('synthetic-state'))

    def test_readable_dashboard_units_and_unknown_eta(self):
        self.assertEqual(size_text(1024 ** 3), '1.0 GB')
        self.assertEqual(duration_text(None), '—')
        self.assertEqual(duration_text(3661), '1h 01m')


if __name__ == '__main__':
    unittest.main()
