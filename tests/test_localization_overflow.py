import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/localization-overflow/scripts/measure_dimensions.py'


class OverflowTest(unittest.TestCase):
    def test_checks_per_file_width_and_actual_rows(self):
        draft = {'engine': 'unity', 'units': [
            {'id': 1, 'path': ['a.assets'], 'source': 'abcd\nef', 'translation': 'abcd\nef'},
            {'id': 2, 'path': ['b.assets'], 'source': 'xy', 'translation': 'xyz\ny'},
            {'id': 3, 'path': ['b.assets'], 'source': 'xy', 'translation': None},
        ]}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'draft.json'
            path.write_text(json.dumps(draft))
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Unit 2: 2 rows exceeds source limit 1', result.stdout)
            self.assertIn('Unit 2 row 1: width 3 exceeds b.assets limit 2', result.stdout)
            self.assertIn('Checked 2 translations; 2 violations.', result.stdout)
            draft['units'][1]['translation'] = 'xy'
            path.write_text(json.dumps(draft))
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('Checked 2 translations; 0 violations.', result.stdout)
            path.write_text('{"units": []}')
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('No nonempty source units', result.stdout)


if __name__ == '__main__':
    unittest.main()
