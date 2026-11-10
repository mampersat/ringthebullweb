#!/usr/bin/env python3
"""One-time USB bootstrap using existing ampy; refuses active games/wrong boards."""
import argparse
import json
from pathlib import Path
import time
import urllib.request
from ampy.pyboard import Pyboard
from ampy.files import Files

ROOT = Path(__file__).resolve().parents[1]
BOARD_ID = 'e66428c51fa06e28'


def install(port, url, version, config, bench=False):
    # The USB identity must match before opening the serial port.
    identity = Path('/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_'+BOARD_ID+'-if00')
    if not identity.exists() or identity.resolve() != Path(port).resolve():
        raise RuntimeError('Expected Ring the Bull USB identity not present; no serial access')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url.rstrip('/')+'/status', timeout=3) as response:
        live = json.load(response)
    if (live['state'] not in ('READY', 'WAIT RELEASE', 'COMPLETE') or live['hook']
            or (live['history'] and len(live['history']) != 21)):
        raise RuntimeError('Game active: finish/reset/release before installing')
    backup = Path('/tmp/ring-ota-bootstrap-'+str(int(time.time())))
    backup.mkdir(mode=0o700)
    board = Pyboard(port, baudrate=115200, rawdelay=.3)
    board.serial.write_timeout = 3
    board.serial.timeout = .2
    interrupted = False
    try:
        # Enter raw REPL without ampy's soft reset, preserving the current result.
        board.serial.write(b'\r\x03\x03')
        time.sleep(.2)
        board.serial.reset_input_buffer()
        board.serial.write(b'\r\x01')
        data = board.read_until(1, b'raw REPL; CTRL-B to exit\r\n')
        if not data.endswith(b'raw REPL; CTRL-B to exit\r\n'):
            raise RuntimeError('Could not enter raw REPL')
        interrupted = True
        board.enter_raw_repl = lambda: None
        board.exit_raw_repl = lambda: None
        ident = board.eval("__import__('binascii').hexlify(__import__('machine').unique_id()).decode()").decode().strip()
        if ident != BOARD_ID:
            interrupted = False
            raise RuntimeError('Wrong board identity')
        # A second check catches play beginning between HTTP preflight and Ctrl-C.
        safe = board.eval("state in (READY, WAIT_RELEASE, COMPLETE) and not last_contact and not hooked and not completed_held and (not history or len(history)==21) and last_cap is not None and last_cap<=RELEASE_THRESHOLD").decode()
        if safe != 'True' and bench:
            safe = board.eval("state in (READY, WAIT_RELEASE) and not history and not last_contact and not hooked and last_cap is None").decode()
        if safe != 'True':
            marker = 'while True:\n    now = time.ticks_ms()'
            source = "_source=open('main.py').read();_body=_source.split(%r,1)[1];exec(%r+_body)" % (marker, marker)
            board.exec_raw_no_follow(source)
            interrupted = False
            raise RuntimeError('Physical activity detected; resumed original loop without resetting')
        board.exec_("if log is not None:\n    if log_buf:log.write('\\n'.join(log_buf)+'\\n');log_buf=[]\n    log.flush();log.close();log=None")
        print('Device', ident, flush=True)
        report = board.exec_("import sys,os,gc;print(sys.implementation);gc.collect();print('free_ram',gc.mem_free());s=os.statvfs('/');print('free_flash',s[0]*s[3]);import hashlib;assert hasattr(hashlib,'sha256')")
        print(report.decode(), flush=True)
        free = int(board.eval("__import__('os').statvfs('/')[0]*__import__('os').statvfs('/')[3]").decode())
        needed = 2 * sum((ROOT/name).stat().st_size for name in ('main.py','web_server.py','records.py')) + sum((ROOT/name).stat().st_size for name in ('ota_client.py','ota_recovery.py')) + 64000
        if free < needed:
            raise RuntimeError('Insufficient flash for two slots and recovery margin')
        files = Files(board)
        try:
            files.get('ota_state.json')
        except Exception as exc:
            if 'No such file' not in str(exc) and 'ENOENT' not in str(exc) and 'Errno 2' not in str(exc):
                raise
        else:
            raise RuntimeError('OTA already initialized; use OTA instead of overwriting recovery')
        for name in ('main.py','web_server.py','records.py','wifi_config.py','records.json'):
            try:
                (backup/name).write_bytes(files.get(name))
            except Exception:
                if name not in ('wifi_config.py','records.json'):
                    raise
        board.exec_("import json;_ota_snapshot={'history':history,'throws':throws,'hits':hits,'misses':misses,'last_completed':last_completed,'previous_completed':previous_completed,'record_base':records.base,'record_values':records.values};_ota_snapshot_bytes=json.dumps(_ota_snapshot).encode()")
        board.exec_("with open('_ota_bootstrap_snapshot.tmp','wb') as _snapshot_file:\n    _snapshot_file.write(_ota_snapshot_bytes)")
        saved_game = files.get('_ota_bootstrap_snapshot.tmp')
        board.exec_("import os;os.remove('_ota_bootstrap_snapshot.tmp');os.mkdir('ota_a')")
        puts = {
            'ota_a/main.py': (ROOT/'main.py').read_bytes(),
            'ota_a/web_server.py': (ROOT/'web_server.py').read_bytes(),
            'ota_a/records.py': (ROOT/'records.py').read_bytes(),
            'ota_recovery.py': (ROOT/'ota_recovery.py').read_bytes(),
            'ota_client.py': (ROOT/'ota_client.py').read_bytes(),
            'ota_config.json': json.dumps(dict(json.loads(config.read_text()), bench_mode=bench)).encode(),
            'ota_game.json': saved_game,
            'ota_state.json': json.dumps(dict(active='ota_a',phase='stable',version=version,previous=None,restore_pending=True)).encode(),
        }
        # Upload and verify all dependencies before the boot entrypoint changes.
        for name, data in puts.items():
            files.put(name+'.upload',data)
            if files.get(name+'.upload') != data:
                raise RuntimeError('Readback mismatch: '+name)
            if name.endswith('.py'):
                board.exec_("import gc;gc.collect();compile(open(%r).read(),%r,'exec');gc.collect()"%(name+'.upload',name))
            else:
                board.exec_("import json;json.load(open(%r))"%(name+'.upload'))
            print('Verified',name,flush=True)
        for name in puts:
            board.exec_("import os;os.rename(%r,%r)"%(name+'.upload',name))
        launcher=(ROOT/'ota/launcher.py').read_bytes()
        files.put('main.py.upload',launcher)
        assert files.get('main.py.upload')==launcher
        board.exec_("import os;os.sync();os.rename('main.py.upload','main.py');os.sync()")
        print('Bootstrap installed. Backup:',backup,flush=True)
    finally:
        if interrupted:
            try:
                board.exec_raw_no_follow('import machine;machine.reset()')
            except Exception:
                pass
        board.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',default='/dev/ttyACM0')
    parser.add_argument('--url',default='http://ringthebull.local')
    parser.add_argument('--version',required=True)
    parser.add_argument('--config',type=Path,default=ROOT/'ota_config.json')
    parser.add_argument('--bench',action='store_true',help='Explicitly allow a disconnected-sensor bench board; auto-disables on valid sensing')
    args=parser.parse_args()
    install(args.port,args.url,args.version,args.config,args.bench)


if __name__=='__main__':
    main()
