"""Host tests for bounded HTTP servicing; no Pico hardware or network needed."""
import importlib.util
from pathlib import Path
import select
import sys
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('web_server', Path(__file__).resolve().parents[1] / 'web_server.py')
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


class Poll:
    def __init__(self):
        self.registered = {}
        self.events = []

    def register(self, sock, flags):
        self.registered[sock] = flags

    modify = register

    def unregister(self, sock):
        self.registered.pop(sock, None)

    def poll(self, timeout):
        assert timeout == 0
        events, self.events = self.events, []
        return events


class Socket:
    def __init__(self, incoming=b'', limit=37):
        self.incoming = incoming
        self.output = b''
        self.limit = limit
        self.closed = False
        self.reads = 0
        self.writes = 0

    def setblocking(self, value):
        assert value is False

    def recv(self, count):
        self.reads += 1
        chunk, self.incoming = self.incoming[:count], self.incoming[count:]
        return chunk

    def send(self, data):
        self.writes += 1
        assert len(data) <= web.WebServer.CHUNK
        data = bytes(data[:self.limit])
        self.output += data
        return len(data)

    def close(self):
        self.closed = True


class WebTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.connected = True
        self.wlan = types.SimpleNamespace(isconnected=lambda: self.connected)
        network = types.SimpleNamespace(STA_IF=0, WLAN=lambda _: self.wlan, hostname=lambda _: None)
        self.patches = [
            patch.dict(sys.modules, network=network, wifi_config=None),
            patch.object(web.time, 'ticks_ms', lambda: self.now, create=True),
            patch.object(web.time, 'ticks_diff', lambda a, b: (a-b+32768) % 65536-32768, create=True),
            patch.object(web.select, 'poll', Poll),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.state = dict(hits=1, misses=1, throws=2, state='READY', history=[True, False], hook=False)
        self.server = web.WebServer(lambda: dict(self.state))
        self.server.listener = Socket()

    def attach(self, request):
        sock = Socket(request)
        self.server.clients[sock] = [self.now, b'', None, 0]
        self.server.poller.register(sock, select.POLLIN)
        return sock

    def tick(self, sock, flags):
        self.server.poller.events = [(sock, flags)]
        self.server.poll()

    def request(self, path='/', method='GET'):
        sock = self.attach(('{} {} HTTP/1.1\r\nHost: pico\r\n\r\n'.format(method, path)).encode())
        self.tick(sock, select.POLLIN)
        for _ in range(len(web.PAGE) // sock.limit + 20):
            if sock.closed:
                break
            before = sock.writes
            self.tick(sock, select.POLLOUT)
            self.assertLessEqual(sock.writes - before, 1)
        self.assertTrue(sock.closed)
        header, body = sock.output.split(b'\r\n\r\n', 1)
        self.assertIn(('Content-Length: {}'.format(len(body))).encode(), header)
        return header, body

    def test_import_without_ewouldblock(self):
        with patch.dict(web.errno.__dict__):
            web.errno.__dict__.pop('EWOULDBLOCK', None)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.WOULD_BLOCK, (web.errno.EAGAIN, web.errno.EAGAIN))

    def test_routes_and_partial_writes(self):
        header, body = self.request()
        self.assertIn(b'200 OK', header)
        self.assertEqual(body, web.PAGE)
        self.assertIn(b'setTimeout(refresh,500)', body)
        self.assertNotIn(b'<script src=', body)
        self.assertEqual(self.request('/health')[1], b'ok\n')

    def test_status_is_read_only_and_updates(self):
        self.now = 2500
        data = web.json.loads(self.request('/status')[1])
        self.assertEqual(data, dict(self.state, uptime=2))
        self.assertNotIn('uptime', self.state)
        self.state.update(hits=0, misses=0, throws=0, history=[], state='WAIT RELEASE')
        self.assertEqual(web.json.loads(self.request('/status')[1])['history'], [])

    def test_debug_is_small_read_only_and_optional(self):
        self.assertIn(b'404', self.request('/debug')[0])
        snapshot = dict(raw=650, baseline=75, delta=575, grab_threshold=500,
                        release_threshold=300, grabbed=True, hook_contact=False)
        calls = []
        self.server.diagnostics = lambda: calls.append(1) or dict(snapshot)
        before = dict(self.state)
        for _ in range(10):
            header, body = self.request('/debug')
            self.assertIn(b'200', header)
            self.assertEqual(web.json.loads(body), snapshot)
            self.assertLess(len(body), 256)
        self.assertEqual(self.state, before)
        self.assertEqual(len(calls), 10)
        self.assertIn(b'405', self.request('/debug', 'POST')[0])
        self.assertEqual(len(calls), 10)

    def test_large_page_is_shared_without_copy_per_client(self):
        first=self.server._response(b'GET / HTTP/1.1\r\n\r\n')
        second=self.server._response(b'GET / HTTP/1.1\r\n\r\n')
        self.assertIs(first[1],web.PAGE)
        self.assertIs(second[1],web.PAGE)

    def test_ota_requires_key_origin_empty_body_and_safe_game(self):
        calls = []
        self.server.ota = types.SimpleNamespace(authorized=lambda token: token == b'private-test-key')
        self.server.ota_command = lambda action: calls.append(action) or True
        self.server.ota_status = lambda: dict(current_version='v1',update_status='idle')
        def request(extra=b'', method=b'POST'):
            return self.server._response(method+b' /ota/check HTTP/1.1\r\nHost: pico\r\n'+extra+b'\r\n')
        self.assertIn(b'403',request())
        self.assertEqual(calls,[])
        auth=b'X-OTA-Key: private-test-key\r\n'
        self.assertIn(b'405',request(auth,b'GET'))
        self.assertIn(b'403',request(auth+b'Origin: http://evil\r\n'))
        self.assertIn(b'400',request(auth+b'Content-Length: 1\r\n'))
        self.assertEqual(calls,[])
        self.assertIn(b'200',request(auth+b'Origin: http://pico\r\n'))
        self.assertEqual(calls,['check'])
        self.server.ota_command=lambda _:False
        self.assertIn(b'409',request(auth))
        self.assertIn(b'200',self.request('/ota/status')[0])

    def test_reject_mutation_unknown_and_malformed(self):
        self.assertIn(b'405', self.request('/status', 'POST')[0])
        self.assertIn(b'405', self.request('/reset')[0])
        self.assertIn(b'400', self.server._response(b'nonsense\r\n\r\n'))
        self.assertEqual(self.state['throws'], 2)

    def test_post_actions_and_origin(self):
        calls = []
        self.server.action = lambda name: calls.append(name) or True
        self.assertIn(b'200', self.request('/undo', 'POST')[0])
        self.assertIn(b'200', self.request('/reset', 'POST')[0])
        self.assertEqual(calls, ['undo', 'reset'])
        request = b'POST /reset HTTP/1.1\r\nHost: pico\r\nOrigin: http://other\r\n\r\n'
        self.assertIn(b'403', self.server._response(request))
        request = request.replace(b'http://other', b'http://pico')
        self.assertIn(b'200', self.server._response(request))
        self.assertIn(b'400', self.server._response(request.replace(b'\r\n\r\n', b'\r\nContent-Length: 1\r\n\r\nx')))
        self.server.action = lambda _: False
        self.assertIn(b'409', self.request('/undo', 'POST')[0])

    def test_fragmented_and_oversized_headers(self):
        sock = self.attach(b'GET /health HTTP/1.1\r\n')
        self.tick(sock, select.POLLIN)
        self.assertIsNone(self.server.clients[sock][2])
        sock.incoming = b'\r\n'
        self.tick(sock, select.POLLIN)
        self.assertIsNotNone(self.server.clients[sock][2])
        large = self.attach(b'x' * 1600)
        for _ in range(3):
            self.tick(large, select.POLLIN)
        self.assertTrue(large.closed)
        self.assertEqual(large.reads, 3)

    def test_stalled_client_and_tick_wrap(self):
        self.server.last_tick = 65530
        self.now = 4
        sock = self.attach(b'GET ')
        self.server.poll()
        self.assertEqual(self.server.uptime_ms, 10)
        self.now += self.server.CLIENT_TIMEOUT_MS
        self.server.poll()
        self.assertTrue(sock.closed)

    def test_disconnect_and_reconnect(self):
        sock = self.attach(b'GET ')
        self.connected = False
        self.server.poll()
        self.assertTrue(sock.closed)
        self.assertIsNone(self.server.listener)
        self.connected = True
        with patch.object(self.server, '_listen') as listen:
            self.server.poll()
            listen.assert_called_once()

    def test_client_limit_and_would_block(self):
        self.attach(b'GET ')
        self.attach(b'GET ')
        extra = Socket()
        self.server.listener.accept = lambda: (extra, None)
        self.tick(self.server.listener, select.POLLIN)
        self.assertTrue(extra.closed)
        sock = next(iter(self.server.clients))
        with patch.object(sock, 'recv', side_effect=OSError(web.errno.EAGAIN)):
            self.tick(sock, select.POLLIN)
        self.assertFalse(sock.closed)
        with patch.object(sock, 'recv', side_effect=OSError(web.errno.ECONNRESET)):
            self.tick(sock, select.POLLIN)
        self.assertTrue(sock.closed)

    def test_config_connects_once_without_waiting_or_changing_dhcp(self):
        calls = []
        self.wlan.active = lambda value: calls.append(('active', value))
        self.wlan.connect = lambda ssid, password: calls.append(('connect', ssid, password))
        config = types.SimpleNamespace(WIFI_SSID='test', WIFI_PASSWORD='secret')
        self.connected = False
        network = sys.modules['network']
        network.hostname = lambda value: calls.append(('hostname', value))
        network.WLAN = lambda _: calls.append(('interface',)) or self.wlan
        with patch.dict(sys.modules, wifi_config=config):
            server = web.WebServer(lambda: dict(self.state))
            server.poll()
        self.assertEqual(calls, [('hostname', 'ringthebull'), ('interface',), ('active', True), ('connect', 'test', 'secret')])
        self.assertIsNone(server.listener)

    def test_hostname_failure_keeps_ip_server_available(self):
        with patch.object(sys.modules['network'], 'hostname', side_effect=OSError('unsupported')):
            with patch('builtins.print'):
                server = web.WebServer(lambda: dict(self.state))
        self.assertIs(server.wlan, self.wlan)

    def test_listener_hangup_can_recover(self):
        self.tick(self.server.listener, select.POLLHUP)
        self.assertIsNone(self.server.listener)
        with patch.object(self.server, '_listen') as listen:
            self.server.poll()
            listen.assert_called_once()

    def test_network_failure_does_not_escape(self):
        with patch.object(self.server.poller, 'poll', side_effect=OSError('network failed')):
            self.server.poll()
        self.assertIsNone(self.server.listener)


if __name__ == '__main__':
    unittest.main()
