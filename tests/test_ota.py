"""Desktop failure injection. No USB, radio, real watchdog, or heating equipment."""
import errno
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import ota_client as client
import ota_recovery as recovery


class Poll:
    def register(self, *args): pass
    def unregister(self, *args): pass
    def modify(self, *args): pass
    def poll(self, timeout):
        assert timeout == 0
        return [(0, client.select.POLLIN | client.select.POLLOUT)]


class Socket:
    def __init__(self, owner):
        self.owner, self.data, self.request = owner, b'', b''
        self.closed = False
    def setblocking(self, flag): assert flag is False
    def connect(self, addr):
        if self.owner.offline: raise OSError(113)
        raise OSError(errno.EINPROGRESS)
    def close(self): self.closed = True
    def send(self, data):
        self.owner.writes += 1
        data = data[:17]
        self.request += data
        if self.request.endswith(b'\r\n\r\n'):
            path = self.request.split()[1].decode()
            body = self.owner.responses[path]
            self.data = b'HTTP/1.0 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body
        return len(data)
    def recv(self, count):
        self.owner.reads += 1
        assert count <= 512
        part, self.data = self.data[:41], self.data[41:]
        return part


class OtaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        old = os.getcwd();os.chdir(temp.name);self.addCleanup(os.chdir,old)
        self.now = self.reads = self.writes = self.checkpoints = self.resets = 0
        self.offline = False
        self.key = 'a'*64
        self.stable = dict(active='ota_a', phase='stable', version='v1', previous=None)
        recovery.atomic_json(recovery.STATE,self.stable)
        Path('ota_a').mkdir();Path('ota_a/main.py').write_bytes(b'original')
        self.responses = {}
        entries=[]
        for name in recovery.FILES:
            data = (b'# new application\n' * 60) + name.encode()
            self.responses['/v2/'+name]=data
            entries.append(dict(name=name,size=len(data),sha256=hashlib.sha256(data).hexdigest()))
        self.release=dict(format=1,version='v2',files=entries)
        self.responses['/manifest.json']=self.sign(self.release)
        patches=[patch.object(client.time,'ticks_ms',lambda:self.now,create=True),
                 patch.object(client.time,'ticks_diff',lambda a,b:a-b,create=True),
                 patch.object(client.select,'poll',Poll),
                 patch.object(client.socket,'socket',lambda:Socket(self))]
        for item in patches:item.start();self.addCleanup(item.stop)
        self.updater=client.Updater(dict(host='192.168.1.145',key=self.key),self.checkpoint,self.reset)
    def sign(self, release):
        payload=json.dumps(release,separators=(',',':'))
        return json.dumps(dict(payload=payload,hmac=hmac.new(self.key.encode(),payload.encode(),hashlib.sha256).hexdigest())).encode()
    def checkpoint(self): self.checkpoints+=1
    def reset(self): self.resets+=1
    def drive(self, terminal=('idle','available','ready','error','paused','restarting')):
        for _ in range(3000):
            before=(self.reads,self.writes)
            self.updater.poll(True);self.now+=20
            self.assertLessEqual(self.reads-before[0],1)
            self.assertLessEqual(self.writes-before[1],1)
            if self.updater.phase in terminal:return
        self.fail('Updater never yielded terminal state')
    def check(self):
        self.assertTrue(self.updater.command('check',True));self.drive()
        self.assertEqual(self.updater.phase,'available',self.updater.error)
    def install(self):
        self.check();self.assertTrue(self.updater.command('install',True));self.drive()
    def test_hmac_matches_standard_library_and_rejects_tampering(self):
        for key in (b'short',b'long'*40):
            self.assertEqual(client.mac(key,b'test'),hmac.new(key,b'test',hashlib.sha256).digest())
        self.assertFalse(self.updater.authorized(b'wrong'))
        self.assertTrue(self.updater.authorized(self.key.encode()))
        packet=self.responses['/manifest.json'].replace(b'v2',b'v3')
        with self.assertRaises(ValueError):client.manifest(packet,self.key.encode())
    def test_verified_stage_activation_trial_and_confirmation(self):
        self.install();self.assertEqual(self.updater.phase,'ready')
        self.assertEqual(recovery.load_state(),self.stable)
        for name in recovery.FILES:
            self.assertEqual(Path('ota_b',name).read_bytes(),self.responses['/v2/'+name])
        self.drive();self.assertEqual(self.resets,1);self.assertEqual(self.checkpoints,1)
        state=recovery.prepare_boot();self.assertEqual(state['phase'],'trial')
        state=recovery.confirm();self.assertEqual(state['phase'],'stable')
        self.assertEqual(recovery.prepare_boot()['active'],'ota_b')
    def test_corrupt_file_never_activates(self):
        self.responses['/v2/main.py']=b'x'*len(self.responses['/v2/main.py'])
        self.install();self.assertEqual(self.updater.phase,'error')
        self.assertIn('hash',self.updater.error)
        self.assertEqual(recovery.load_state(),self.stable);self.assertEqual(self.resets,0)
    def test_partial_download_power_loss_keeps_current_then_restart_succeeds(self):
        self.check();self.updater.command('install',True)
        for _ in range(20): self.updater.poll(True)
        self.updater._close()
        self.assertEqual(recovery.prepare_boot(),self.stable)
        self.updater=client.Updater(dict(host='192.168.1.145',key=self.key),self.checkpoint,self.reset)
        self.install();self.drive();self.assertEqual(self.resets,1)
    def test_power_loss_after_activation_and_during_trial_rolls_back(self):
        self.install();self.drive()
        self.assertEqual(recovery.prepare_boot()['active'],'ota_b')
        fallback=recovery.prepare_boot()
        self.assertEqual(fallback['active'],'ota_a');self.assertEqual(fallback['version'],'v1')
        self.assertTrue(fallback['restore_pending'])
        self.assertEqual(Path('ota_a/main.py').read_bytes(),b'original')
    def test_atomic_pointer_interruption_keeps_old_pointer(self):
        self.install()
        with patch.object(recovery.os,'rename',side_effect=OSError('power loss')):
            with self.assertRaises(OSError):recovery.activate('ota_b','v2')
        self.assertEqual(recovery.load_state(),self.stable)
        self.assertTrue(Path(recovery.STATE+'.tmp').exists())
        self.assertEqual(recovery.prepare_boot(),self.stable)
    def test_offline_timeout_and_active_game_never_touch_active_slot(self):
        self.assertFalse(self.updater.command('check',False))
        self.offline=True
        self.assertFalse(self.updater.command('check',True))
        self.assertEqual(recovery.prepare_boot(),self.stable)
        self.offline=False;self.check();self.updater.command('install',True)
        self.updater.poll(False);self.assertEqual(self.updater.phase,'paused')
        self.assertEqual(self.checkpoints,0)
        self.assertFalse(self.updater.command('install',False))
        self.updater.command('install',True)
        self.now+=16000;self.updater.poll(True)
        self.assertEqual(self.updater.phase,'error');self.assertIn('timed out',self.updater.error)
        self.assertEqual(Path('ota_a/main.py').read_bytes(),b'original')
    def test_manifest_rejects_recovery_paths_and_size_abuse(self):
        for name in ('../main.py','ota_client.py','ota_recovery.py','wifi_config.py'):
            data=json.loads(json.dumps(self.release));data['files'][0]['name']=name
            with self.assertRaises(ValueError):client.manifest(self.sign(data),self.key.encode())
        self.release['files'][0]['size']=999999
        with self.assertRaises(ValueError):client.manifest(self.sign(self.release),self.key.encode())
    def test_checkpoint_failure_prevents_activation(self):
        self.install()
        self.updater.checkpoint=lambda:(_ for _ in ()).throw(OSError('disk full'))
        self.drive();self.assertEqual(self.updater.phase,'error')
        self.assertEqual(recovery.load_state(),self.stable)
    def test_paused_install_restarts_cleanly(self):
        self.check();self.updater.command('install',True)
        for _ in range(20):self.updater.poll(True)
        self.updater.poll(False)
        self.assertTrue(self.updater.command('install',True));self.drive();self.drive()
        self.assertEqual(self.resets,1)
    def test_short_response_never_activates(self):
        self.check();self.updater.command('install',True)
        for _ in range(8):self.updater.poll(True)
        self.updater.sock.data=self.updater.sock.data[:80]
        self.drive();self.assertEqual(self.updater.phase,'error')
        self.assertEqual(recovery.load_state(),self.stable)

    def test_application_exception_leaves_trial_marker_then_rolls_back(self):
        self.install();self.drive()
        import sys
        class Reset(Exception): pass
        events=[]
        machine=types.SimpleNamespace(WDT=lambda timeout:events.append(('wdt',timeout)),
            reset=lambda:(_ for _ in ()).throw(Reset()))
        with patch.dict(sys.modules,machine=machine),patch.object(sys,'path',sys.path[:]):
            with self.assertRaises(Reset):recovery.run()
        self.assertEqual(events,[('wdt',8000)])
        self.assertEqual(recovery.load_state()['phase'],'trial')
        self.assertEqual(recovery.prepare_boot()['active'],'ota_a')

    def test_corruption_in_staged_flash_detected_before_activation(self):
        self.check();self.updater.command('install',True)
        self.drive(('verifying','error'))
        self.assertEqual(self.updater.phase,'verifying')
        path=Path('ota_b/main.py');path.write_bytes(b'x'*path.stat().st_size)
        self.drive();self.assertEqual(self.updater.phase,'error')
        self.assertIn('Staged file hash mismatch',self.updater.error)
        self.assertEqual(recovery.load_state(),self.stable)

    def test_usb_maintenance_works_even_with_invalid_pointer_without_network(self):
        Path('ota_maintenance').touch()
        Path(recovery.STATE).write_text('invalid')
        self.assertIsNone(recovery.run())
