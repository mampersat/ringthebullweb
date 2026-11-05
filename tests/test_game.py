"""Execute the unchanged sensor state machine with deterministic sensor samples."""
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest.mock import patch
import records


class Pin:
    OUT = 1
    IN = 0
    PULL_UP = 2
    def __init__(self, *a, **kw): pass
    def on(self): pass
    def off(self): pass
    def value(self, *a): return 0


class Pixels:
    def __init__(self, *a): pass
    def fill(self, *a): pass
    def write(self): pass
    def __setitem__(self, key, value): pass


class GameTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name) / 'records.json')
        store = records.Records(self.path)
        self.now = 0
        fake_web = types.SimpleNamespace(WebServer=lambda *a, **kw: types.SimpleNamespace(poll=lambda: None))
        patches = [
            patch.dict(sys.modules, machine=types.SimpleNamespace(Pin=Pin),
                       neopixel=types.SimpleNamespace(NeoPixel=Pixels), web_server=fake_web),
            patch.object(records, 'Records', lambda: store),
            patch.object(records.time, 'ticks_ms', lambda: self.now, create=True),
            patch.object(records.time, 'ticks_diff', lambda a, b: a-b, create=True),
            patch.object(records.time, 'ticks_add', lambda a, b: a+b, create=True),
            patch.object(records.time, 'sleep_ms', self.sleep, create=True),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        source = Path('main.py').read_text()
        prefix, loop = source.split('while True:\n    now = time.ticks_ms()', 1)
        self.ns = {}
        exec(prefix.replace('LOG_ENABLED = True', 'LOG_ENABLED = False'), self.ns)
        self.cap, self.contact = 50, False
        self.ns.update(read_touch=lambda: self.cap, read_hook=lambda: self.contact,
                       update_pixels=lambda *a: None, update_attract=lambda *a: None,
                       draw_dashboard=lambda *a: None)
        self.iteration = compile('for _once in range(1):\n    now = time.ticks_ms()' + loop, '<game>', 'exec')

    def sleep(self, duration):
        self.now += duration

    def samples(self, cap, contact, count):
        self.cap, self.contact = cap, contact
        for _ in range(count):
            exec(self.iteration, self.ns)

    def test_finish_only_when_throw_21_resolves_then_undo(self):
        ns = self.ns
        ns.update(history=[True] * 20, hits=20, throws=20, state=ns['HELD'])
        ns['records'].observe(ns['history'])
        self.samples(50, False, 25)
        self.assertEqual(ns['throws'], 21)
        self.assertEqual(ns['state'], ns['IN_FLIGHT'])
        self.assertFalse(ns['web_status']()['complete'])
        self.assertFalse(ns['web_action']('undo'))
        self.samples(50, True, 18)
        self.assertEqual(ns['state'], ns['COMPLETE'])
        self.assertEqual(ns['history'], [True] * 21)
        self.assertEqual(records.json.loads(Path(self.path).read_text())['best'], 21)
        self.samples(1500, False, 20)
        self.samples(50, False, 40)
        self.assertEqual(ns['throws'], 21)
        self.assertTrue(ns['web_action']('undo'))
        self.assertEqual((ns['throws'], ns['hits'], ns['misses']), (20, 20, 0))
        self.assertEqual(ns['state'], ns['WAIT_RELEASE'])
        self.assertEqual(ns['records'].values, (0, 20))
        self.samples(50, False, 25)
        self.assertEqual(records.json.loads(Path(self.path).read_text())['best'], 0)
        self.samples(1500, False, 12)
        self.samples(50, False, 25)
        self.samples(50, False, 155)
        self.assertEqual(ns['state'], ns['COMPLETE'])
        self.assertEqual((ns['hits'], ns['misses']), (20, 1))
        self.assertTrue(ns['web_action']('reset'))
        self.assertEqual(ns['records'].values, (20, 20))
        self.assertEqual(ns['history'], [])

    def test_regrab_miss_21_and_gesture_preserves_records(self):
        ns = self.ns
        ns.update(history=[True, False] * 10, hits=10, misses=10, throws=21,
                  throw_started=self.now, state=ns['IN_FLIGHT'])
        self.samples(1500, False, 30)
        self.assertEqual(ns['state'], ns['COMPLETE'])
        self.assertEqual((ns['hits'], ns['misses']), (10, 11))
        for _ in range(3):
            self.samples(1500, True, 10)
            self.samples(1500, False, 10)
        self.assertEqual(ns['history'], [])
        self.assertEqual(ns['records'].values, (10, 1))
