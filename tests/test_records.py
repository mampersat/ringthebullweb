import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import records


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name) / 'records.json')
        self.records = records.Records(self.path)
        self.clock = patch.object(records.time, 'ticks_diff', lambda a, b: a-b, create=True)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_complete_undo_reset_and_reboot(self):
        r = self.records
        r.observe([True] * 21, save=True)
        r.flush(0)
        self.assertEqual(records.Records(self.path).values, (21, 21))
        r.observe([True] * 20, save=True)
        r.flush(1)
        self.assertEqual(records.Records(self.path).values, (0, 20))
        r.observe([True] * 20 + [False], save=True)
        r.flush(2)
        r.reset()
        r.observe([])
        r.flush(3)
        self.assertEqual(records.Records(self.path).values, (20, 20))
        r.observe([True, False] * 10 + [False], save=True)
        r.flush(4)
        self.assertEqual(r.values, (20, 20))

    def test_incomplete_streak_checkpointed_at_reset(self):
        r = self.records
        r.observe([True] * 5)
        r.flush(0)
        self.assertFalse(Path(self.path).exists())
        self.assertEqual(r.values, (0, 5))
        r.reset()
        r.observe([])
        r.flush(1)
        self.assertEqual(records.Records(self.path).values, (0, 5))
        before = Path(self.path).read_bytes()
        with patch.object(records.os, 'rename') as rename:
            r.reset()
            r.flush(2)
            rename.assert_not_called()
        self.assertEqual(before, Path(self.path).read_bytes())

    def test_failed_checkpoint_keeps_previous_and_retries(self):
        r = self.records
        r.observe([True, False] * 10 + [False], save=True)
        r.flush(0)
        old = Path(self.path).read_bytes()
        r.observe([True] * 21, save=True)
        with patch.object(records.os, 'rename', side_effect=OSError('full')):
            r.flush(1)
        self.assertTrue(r.pending)
        self.assertEqual(Path(self.path).read_bytes(), old)
        self.assertEqual(records.Records(self.path).values, (10, 1))
        with patch.object(records.os, 'rename') as rename:
            r.flush(2)
            rename.assert_not_called()
        r.flush(30001)
        self.assertIsNone(r.error)
        self.assertEqual(records.Records(self.path).values, (21, 21))

    def test_corrupt_checkpoint_and_ignored_temporary_file(self):
        Path(self.path).write_text('{broken')
        Path(self.path + '.tmp').write_text(json.dumps({'version': 1, 'best': 21, 'streak': 21}))
        r = records.Records(self.path)
        self.assertEqual(r.values, (0, 0))
        self.assertIsNotNone(r.error)
        for bad in ({'version': 1, 'best': True, 'streak': 4},
                    {'version': 1, 'best': 22, 'streak': 4}):
            Path(self.path).write_text(json.dumps(bad))
            self.assertIsNotNone(records.Records(self.path).error)
