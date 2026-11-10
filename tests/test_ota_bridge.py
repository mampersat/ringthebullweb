"""Run the one-time trial expansion with injected failures; never touch a Pico."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import ota_recovery

ROOT=Path(__file__).resolve().parents[1]


class BridgeTests(unittest.TestCase):
    def setUp(self):
        # Construct a legacy-gate fixture; no ignored releases or Git history required.
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'releases/2026.11.09.4').mkdir(parents=True)
        for name in ota_recovery.FILES:
            data=(ROOT/name).read_bytes()
            if name=='main.py':
                text=data.decode();a=text.index('\ndef ota_idle():');b=text.index('\ndef ota_checkpoint():',a)
                text=text[:a]+'\ndef ota_safe():\n    return False\n\n'+text[b:]
                a=text.index('        idle = ota_idle()\n');b=text.index('        if ota_log_paused',a)
                data=(text[:a]+'        updater.poll(ota_safe())\n'+text[b:]).encode()
            (self.root/'releases/2026.11.09.4'/name).write_bytes(data)
        (self.root/'main.py').write_bytes((ROOT/'main.py').read_bytes())
        with patch.dict(sys.modules,ota_release=types.SimpleNamespace(ROOT=self.root,FILES=ota_recovery.FILES)):
            spec=importlib.util.spec_from_file_location('bridge',ROOT/'tools/ota_guard_bridge.py')
            self.bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.bridge)
        self.files,self.expanded=self.bridge.sources(self.root)
        for slot in ('ota_a','ota_b'):(self.root/slot).mkdir()
        for name,data in self.files.items():
            (self.root/'ota_a'/name).write_bytes(data)
            (self.root/'ota_b'/name).write_bytes((self.root/'releases/2026.11.09.4'/name).read_bytes())
        old=os.getcwd();os.chdir(self.root);self.addCleanup(os.chdir,old)
        self.state=dict(active='ota_a',previous='ota_b',version=self.bridge.VERSION,previous_version=self.bridge.BASE,phase='trial')
        ota_recovery.atomic_json(ota_recovery.STATE,self.state)
        self.code=self.files['main.py'].decode().split('with open(_a+\'/main.py\')')[0]
        self.watchdog=types.SimpleNamespace(feed=lambda:None)
    def test_expansion_is_independent_and_only_changes_update_gate(self):
        exec(self.code,{'ota_watchdog':self.watchdog})
        for name in ota_recovery.FILES:
            self.assertEqual((self.root/'ota_a'/name).read_bytes(),self.expanded[name])
            self.assertEqual((self.root/'ota_b'/name).read_bytes(),(self.root/'releases/2026.11.09.4'/name).read_bytes())
        import ast
        original=ast.parse((self.root/'ota_b/main.py').read_text());expanded=ast.parse((self.root/'ota_a/main.py').read_text())
        for name in ('read_touch','read_hook','grab_confirmed','reset_game','web_status'):
            def fn(tree):return ast.dump(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name))
            self.assertEqual(fn(original),fn(expanded))
        ota_recovery.confirm()
        (self.root/'ota_b/main.py').write_text('partially downloaded future release')
        self.assertEqual(ota_recovery.prepare_boot()['active'],'ota_a')
        self.assertEqual((self.root/'ota_a/main.py').read_bytes(),self.expanded['main.py'])
    def test_corrupt_base_fails_before_copy_and_rolls_back(self):
        (self.root/'ota_b/web_server.py').write_text('corrupt')
        with self.assertRaises(AssertionError):exec(self.code,{'ota_watchdog':self.watchdog})
        self.assertEqual((self.root/'ota_a/main.py').read_bytes(),self.files['main.py'])
        self.assertEqual(ota_recovery.prepare_boot()['active'],'ota_b')
    def test_interruption_after_each_file_keeps_fallback_intact(self):
        for fail_at in (1,2,3):
            ota_recovery.atomic_json(ota_recovery.STATE,self.state)
            calls=[]
            def sync():
                calls.append(1)
                if len(calls)==fail_at:raise OSError('power interruption')
            with patch.object(os,'sync',sync):
                with self.assertRaises(OSError):exec(self.code,{'ota_watchdog':self.watchdog})
            self.assertEqual(ota_recovery.prepare_boot()['active'],'ota_b')
            for name in ota_recovery.FILES:
                self.assertEqual((self.root/'ota_b'/name).read_bytes(),(self.root/'releases/2026.11.09.4'/name).read_bytes())
