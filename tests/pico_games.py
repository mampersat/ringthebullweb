"""ampy run tests/pico_games.py: isolated synthetic tests on the actual Pico.
Stops the running game; restart afterwards. Never touches production records.
"""
import json
import os
import records

path = '/records-test.json'
original_records = records.Records
for name in (path, path + '.tmp'):
    try:
        os.remove(name)
    except OSError:
        pass
records.Records = lambda: original_records(path)
source = open('main.py').read()
prefix, loop = source.split('while True:\n    now = time.ticks_ms()', 1)
ns = {}
try:
    exec(prefix, ns)
finally:
    records.Records = original_records
server = ns['web']
assert server is not None
server.wlan.active(False)
ns['web'] = None
if ns['log'] is not None:
    ns['log'].close()
ns['log'] = None
real_time = ns['time']
class Clock:
    now = 0
    @staticmethod
    def ticks_ms(): return Clock.now
    @staticmethod
    def ticks_diff(a, b): return real_time.ticks_diff(a, b)
    @staticmethod
    def ticks_add(a, b): return real_time.ticks_add(a, b)
    @staticmethod
    def sleep_ms(ms): Clock.now += ms
ns['time'] = Clock
ns['test_cap'], ns['test_contact'] = 50, False
ns['read_hook'] = lambda: ns['test_contact']
ns['read_touch'] = lambda: ns['test_cap']
ns['draw_dashboard'] = lambda *args: None
ns['update_pixels'] = lambda *args: None
ns['update_attract'] = lambda *args: None
iteration = compile('for _once in range(1):\n    now = time.ticks_ms()' + loop, '<game-test>', 'exec')
def samples(cap, contact, count):
    ns['test_cap'], ns['test_contact'] = cap, contact
    for _ in range(count): exec(iteration, ns)
try:
    ns.update(history=[True] * 20, hits=20, throws=20, state=ns['HELD'])
    ns['records'].observe(ns['history'])
    samples(50, False, 25)
    assert ns['throws'] == 21 and ns['state'] == ns['IN_FLIGHT']
    assert not ns['web_status']()['complete']
    assert not ns['web_action']('undo')
    samples(50, True, 18)
    assert ns['state'] == ns['COMPLETE']
    assert original_records(path).values == (21, 21)
    samples(1500, False, 30)
    assert ns['throws'] == 21 and ns['web_status']()['complete']
    response = server._response(b'POST /undo HTTP/1.1\r\nHost: pico\r\n\r\n')
    assert b'200 OK' in response and ns['throws'] == 20
    samples(50, False, 25)
    assert original_records(path).values == (0, 20)
    samples(1500, False, 12)
    samples(50, False, 25)
    samples(50, False, 155)
    assert ns['state'] == ns['COMPLETE'] and ns['misses'] == 1
    assert original_records(path).values == (20, 20)
    response = server._response(b'POST /reset HTTP/1.1\r\nHost: pico\r\n\r\n')
    assert b'200 OK' in response and not ns['history']
    samples(50, False, 1)
    assert original_records(path).values == (20, 20)
    print('PASS Pico: resolved throw 21, POST undo/corrected checkpoint, timeout completion, POST reset preserves records')
    print('PASS Pico: offline scoring with WLAN disabled; atomic overwrite and record reload')
    for ending in ('hit', 'regrab', 'timeout'):
        ns['reset_game'](flash=False)
        ns.update(history=[True] * 20, hits=20, misses=0, throws=20, state=ns['HELD'])
        ns['records'].observe(ns['history'])
        samples(50, False, 25)
        assert ns['throws'] == 21 and not ns['web_status']()['complete']
        if ending == 'hit':
            samples(50, True, 18)
        elif ending == 'regrab':
            samples(1500, False, 30)
        else:
            samples(50, False, 155)
        assert len(ns['history']) == 21
        completed = ns['last_completed']
        if ending != 'regrab':
            samples(1500, False, 22)
        samples(50, False, 25)
        assert ns['throws'] == 1 and ns['state'] == ns['IN_FLIGHT']
        assert ns['history'] == [] and ns['last_completed'] == completed
        samples(50, False, 155)
        assert ns['history'] == [False] and ns['throws'] == 1
        assert ns['web_action']('undo') and ns['throws'] == 0
        assert ns['last_completed'] == completed
        for _ in range(3):
            samples(1500, True, 10)
            samples(1500, False, 10)
        assert not ns['history'] and ns['last_completed'] == completed
        print('PASS offline 20->21->22:', ending, 'final shot; next release counted as shot 1; undo/reset retain archive')
    print('RTC calendar:', real_time.localtime()[:3], '(no clock synchronization configured; weekly streak deferred)')
finally:
    for name in (path, path + '.tmp'):
        try:
            os.remove(name)
        except OSError:
            pass
