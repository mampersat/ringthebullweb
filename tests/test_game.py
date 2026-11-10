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

    def test_trial_confirms_from_offline_sensor_loop_progress(self):
        ns=self.ns
        feeds=[];confirmations=[]
        ns.update(web=None,ota_watchdog=types.SimpleNamespace(feed=lambda:feeds.append(1)),
                  ota_boot={'phase':'trial'},ota_iterations=0)
        def confirm():
            confirmations.append(1)
            return {'phase':'stable'}
        ns['confirm']=confirm
        self.samples(50,False,1550)
        self.assertEqual(confirmations,[1])
        self.assertEqual(len(feeds),1550)
        self.assertEqual(ns['throws'],0)
        self.assertEqual(ns['ota_boot']['phase'],'stable')

    def test_ota_staging_tolerates_noise_but_activation_waits_for_release(self):
        ns=self.ns
        ns.update(last_cap=842,last_contact=False,hooked=False,completed_held=False)
        self.assertTrue(ns['ota_idle']())
        self.assertFalse(ns['ota_safe']())
        calls=[]
        updater=types.SimpleNamespace(phase='ready',poll=lambda safe:calls.append(safe))
        ns.update(updater=updater,ota_config={'bench_mode':False})
        self.samples(842,False,1)
        self.assertEqual(calls,[],'unconfirmed grab must delay activation')
        self.samples(50,False,20)
        self.assertIn(True,calls,'stable released ring allows activation')
        calls.clear();ns['state']=ns['HELD']
        self.samples(1500,False,1)
        self.assertEqual(calls,[False],'confirmed play must pause even a verified release')
        self.assertFalse(ns['ota_idle']())
        ns.update(state=ns['READY'],last_cap=None)
        self.assertFalse(ns['ota_idle']())

    def test_sound_events_only_follow_new_resolved_scores(self):
        ns=self.ns
        self.samples(1500,False,12)
        self.samples(50,False,25)
        self.assertEqual(ns['score_event'],0)
        self.samples(50,True,18)
        self.assertEqual((ns['score_event'],ns['score_sound']),(1,'hit'))
        self.assertEqual(ns['web_status']()['score_event'],1)
        self.assertTrue(ns['web_action']('undo'))
        self.assertEqual(ns['score_event'],1)
        ns['web_action']('reset')
        self.assertEqual(ns['score_event'],1)
        ns.update(history=[True]*20,throws=21,hits=20,misses=0,state=ns['IN_FLIGHT'],throw_started=self.now)
        self.samples(50,False,155)
        self.assertEqual((ns['score_event'],ns['score_sound']),(2,'complete'))
        self.samples(1500,False,12)
        self.samples(50,False,25)
        self.assertEqual(ns['history'],[])
        self.assertEqual(ns['score_event'],2,'rollover must not emit a score')
        self.samples(50,False,155)
        self.assertEqual((ns['score_event'],ns['score_sound']),(3,'miss'))

    def test_update_flushes_log_and_resumes_it_without_changing_game(self):
        ns=self.ns
        class Log:
            text=''
            closed=False
            def write(self,text): self.text+=text
            def flush(self): pass
            def close(self): self.closed=True
        capture=Log();commands=[]
        updater=types.SimpleNamespace(phase='available',poll=lambda safe:None,
                                      command=lambda action,safe:commands.append((action,safe)) or True)
        ns.update(log=capture,log_buf=['old sensor row'],updater=updater,
                  ota_config={'bench_mode':False},last_cap=50,
                  LOG_FILE=str(Path(self.folder.name)/'log.csv'))
        self.assertTrue(ns['ota_command']('check'))
        self.assertEqual(capture.text,'old sensor row\n')
        self.assertTrue(capture.closed)
        self.assertEqual(commands,[('check',True)])
        self.samples(50,False,1)
        self.assertFalse(ns['ota_log_paused'])
        self.assertIsNotNone(ns['log']);ns['log'].close()
        ns['state']=ns['HELD']
        self.assertFalse(ns['ota_command']('install'))
        self.assertEqual(ns['throws'],0)

    def test_explicit_bench_allowance_exits_on_first_valid_sample(self):
        ns=self.ns
        ns.update(ota_bench=True,last_cap=None,last_contact=False,hooked=False)
        self.assertTrue(ns['ota_safe']())
        ns.update(history=[True],throws=1)
        self.assertFalse(ns['ota_safe']())
        ns.update(history=[],throws=0)
        self.samples(50,False,1)
        self.assertFalse(ns['ota_bench'])
        self.samples(None,False,1)
        self.assertFalse(ns['ota_safe']())

    def test_update_gate_stops_on_physical_activity_and_partial_game(self):
        ns=self.ns
        ns.update(last_cap=50,last_contact=False,hooked=False,completed_held=False)
        self.assertTrue(ns['ota_safe']())
        ns['last_cap']=1500
        self.assertFalse(ns['ota_safe']())
        ns['last_cap']=None
        self.assertFalse(ns['ota_safe']())
        ns.update(last_cap=50,history=[True],throws=1)
        self.assertFalse(ns['ota_safe']())
        ns.update(history=[True]*21,state=ns['COMPLETE'])
        self.assertTrue(ns['ota_safe']())
        ns['completed_held']=True
        self.assertFalse(ns['ota_safe']())
        ns.update(completed_held=False,last_contact=True)
        self.assertFalse(ns['ota_safe']())

    def test_scoring_identical_with_diagnostics_open_and_closed(self):
        results = []
        for enabled in (False, True):
            ns = self.ns
            ns['reset_game'](flash=False)
            reads = [0, 0]
            def touch():
                reads[0] += 1
                return self.cap
            def contact():
                reads[1] += 1
                return self.contact
            ns.update(read_touch=touch, read_hook=contact)
            def poll():
                if enabled:
                    before = tuple(reads)
                    for _ in range(3): ns['sensor_status']()
                    self.assertEqual(tuple(reads), before)
            ns['web'] = types.SimpleNamespace(poll=poll)
            self.samples(50, False, 25)
            baseline = ns['cap_baseline']
            self.assertEqual(baseline, 50)
            self.samples(1500, False, 12)
            self.assertTrue(ns['sensor_status']()['grabbed'])
            self.assertEqual(ns['sensor_status']()['delta'], 1450)
            self.assertEqual(ns['cap_baseline'], baseline)
            self.samples(50, False, 25)
            self.samples(50, True, 18)
            self.assertTrue(ns['sensor_status']()['hook_contact'])
            self.assertIsNone(ns['sensor_status']()['raw'])
            self.assertIsNone(ns['sensor_status']()['delta'])
            self.samples(50, False, 25)
            self.samples(1500, False, 12)
            self.samples(50, False, 25)
            self.samples(50, False, 155)
            results.append((ns['throws'], ns['hits'], ns['misses'], ns['history'][:]))
        self.assertEqual(results, [(2, 1, 1, [True, False])] * 2)

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
        self.assertEqual(ns['throws'], 21)
        self.assertTrue(ns['web_status']()['complete'])
        self.assertTrue(ns['web_action']('undo'))
        self.assertEqual((ns['throws'], ns['hits'], ns['misses']), (20, 20, 0))
        self.assertEqual(ns['state'], ns['WAIT_RELEASE'])
        self.assertEqual(ns['records'].values, (0, 20))
        self.assertIsNone(ns['last_completed'])
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
        self.assertTrue(ns['web_status']()['complete'])
        self.assertEqual((ns['hits'], ns['misses']), (10, 11))
        for _ in range(3):
            self.samples(1500, True, 10)
            self.samples(1500, False, 10)
        self.assertEqual(ns['history'], [])
        self.assertEqual(ns['records'].values, (10, 1))

    def check_rollover(self, final):
        ns = self.ns
        ns['web'] = None  # No browser or networking is needed for rollover.
        ns.update(history=[True] * 20, hits=20, throws=20, state=ns['HELD'])
        ns['records'].observe(ns['history'])
        self.samples(50, False, 25)
        self.assertEqual(ns['throws'], 21)
        self.assertFalse(ns['web_status']()['complete'])
        if final == 'hit':
            self.samples(50, True, 18)
        elif final == 'regrab':
            self.samples(1500, False, 30)
        else:
            self.samples(50, False, 155)
        self.assertEqual(len(ns['history']), 21)
        completed = ns['last_completed']
        self.assertEqual(len(completed['history']), 21)
        self.assertIsNot(completed['history'], ns['history'])
        best = 21 if final == 'hit' else 20
        self.assertEqual(ns['records'].values, (best, 20 if final != 'hit' else 21))
        if final != 'regrab':
            self.samples(1500, False, 22)
        # For regrab, this is the release of the ring already caught on shot 21.
        self.samples(50, False, 25)
        self.assertEqual((ns['throws'], ns['hits'], ns['misses']), (1, 0, 0))
        self.assertEqual(ns['state'], ns['IN_FLIGHT'])
        self.assertEqual(ns['history'], [])
        self.assertFalse(ns['web_status']()['complete'])
        self.assertEqual(ns['web_status']()['last_completed'], completed)
        self.samples(50, False, 155)
        self.assertEqual((ns['throws'], ns['misses']), (1, 1))
        self.assertEqual(ns['history'], [False])
        self.assertTrue(ns['web_action']('undo'))
        self.assertEqual(ns['throws'], 0)
        self.assertEqual(ns['last_completed'], completed)
        self.assertEqual(ns['records'].values[0], best)
        for _ in range(3):
            self.samples(1500, True, 10)
            self.samples(1500, False, 10)
        self.assertEqual(ns['history'], [])
        self.assertEqual(ns['last_completed'], completed)
        self.assertEqual(ns['records'].values[0], best)

    def test_offline_20_21_22_hit(self):
        self.check_rollover('hit')

    def test_offline_20_21_22_regrab(self):
        self.check_rollover('regrab')

    def test_offline_20_21_22_timeout(self):
        self.check_rollover('timeout')

    def test_undo_completion_restores_previous_archive_and_record_baseline(self):
        ns = self.ns
        prior = dict(hits=10, misses=11, throws=21, history=[True, False] * 10 + [False])
        ns['records'].observe(prior['history'], save=True)
        ns['records'].reset()
        ns.update(last_completed=prior, history=[True] * 20, hits=20, throws=21,
                  state=ns['IN_FLIGHT'], throw_started=self.now)
        self.samples(50, True, 18)
        self.assertEqual(ns['last_completed']['hits'], 21)
        self.assertTrue(ns['web_action']('undo'))
        self.assertEqual(ns['last_completed'], prior)
        self.assertEqual(ns['records'].values, (10, 20))
        self.samples(50, False, 25)
        self.assertEqual(records.json.loads(Path(self.path).read_text())['best'], 10)
