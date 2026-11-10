"""Cooperative LAN application updater; fixed IPv4, bounded buffers, no DNS/TLS."""
import errno
import hashlib
import json
import os
import select
import socket
import time
from ota_recovery import FILES, STATE, activate, load_state


def digest(data):
    return hashlib.sha256(data).digest()


def hex_digest(data):
    import binascii
    return binascii.hexlify(data).decode()


def mac(key, data):
    if len(key) > 64:
        key = digest(key)
    key += b'\0' * (64 - len(key))
    return digest(bytes(v ^ 0x5c for v in key) + digest(bytes(v ^ 0x36 for v in key) + data))


def equal(a, b):
    if len(a) != len(b):
        return False
    difference = 0
    for x, y in zip(a, b):
        difference |= x ^ y
    return difference == 0


def manifest(packet, key):
    envelope = json.loads(packet)
    payload = envelope['payload'].encode()
    if not equal(hex_digest(mac(key, payload)).encode(), envelope['hmac'].encode()):
        raise ValueError('Release authentication failed')
    data = json.loads(payload)
    version = data['version']
    if (data.get('format') != 1 or not isinstance(version, str) or not 1 <= len(version) <= 48
            or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in version)):
        raise ValueError('Invalid release version')
    entries = data['files']
    if len(entries) != len(FILES) or set(entry['name'] for entry in entries) != set(FILES):
        raise ValueError('Invalid application files')
    for entry in entries:
        size, sha = entry['size'], entry['sha256']
        if (type(size) is not int or not 1 <= size <= 128000 or len(sha) != 64
                or any(c not in '0123456789abcdef' for c in sha)):
            raise ValueError('Invalid release file')
    return data


class Updater:
    CHUNK = 512
    MANIFEST_LIMIT = 4096
    TIMEOUT_MS = 15000

    def __init__(self, config, checkpoint, reboot):
        self.config = config
        self.key = config['key'].encode()
        if len(self.key) < 32:
            raise ValueError('OTA key too short')
        # Numeric IPv4 only: socket.connect never invokes a hostname lookup.
        parts = config['host'].split('.')
        if len(parts) != 4 or any(not p.isdigit() or not 0 <= int(p) <= 255 for p in parts):
            raise ValueError('OTA server requires IPv4 address')
        self.checkpoint, self.reboot = checkpoint, reboot
        self.boot = load_state()
        self.release = None
        self.phase = 'idle'
        self.error = self.boot.get('error')
        self.sock = self.output = None
        self.poller = select.poll()
        self.packet = b''
        self.headers = b''
        self.index = self.received = self.total = 0
        self.mode = None

    def authorized(self, token):
        return equal(token, self.key)

    def status(self):
        return dict(current_version=self.boot['version'],
                    available_version=self.release['version'] if self.release else None,
                    update_status=self.phase, update_error=self.error,
                    update_bytes=self.received, update_total=self.total,
                    trial=self.boot['phase'] == 'trial')

    def _close(self):
        if self.sock is not None:
            try:
                self.poller.unregister(self.sock)
            except (OSError, KeyError):
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        if self.output is not None:
            try:
                self.output.close()
            except OSError:
                pass
            self.output = None

    def _fail(self, error):
        self._close()
        self.phase, self.error = 'error', str(error)[:120]

    def command(self, action, safe):
        if not safe or self.boot['phase'] != 'stable' or self.phase not in ('idle', 'available', 'error', 'paused'):
            return False
        try:
            self.error = None
            if action == 'check':
                self.release = None
                self.mode = 'manifest'
                self._request('/manifest.json')
            elif action == 'install' and self.release and self.release['version'] != self.boot['version']:
                # Restart interrupted files from byte zero; the active slot is untouched.
                self._stage()
            else:
                return False
            return True
        except Exception as exc:
            self._fail(exc)
            return False

    def _request(self, path):
        self._close()
        self.headers, self.packet = b'', b''
        self.length = None
        self.received = 0
        self.started = time.ticks_ms()
        self.sock = socket.socket()
        self.sock.setblocking(False)
        self.poller.register(self.sock, select.POLLIN | select.POLLOUT)
        try:
            self.sock.connect((self.config['host'], self.config.get('port', 8765)))
        except OSError as exc:
            if exc.args[0] not in (errno.EINPROGRESS, errno.EAGAIN, getattr(errno, 'EALREADY', 114)):
                raise
        self.request = ('GET {} HTTP/1.0\r\nHost: {}\r\nConnection: close\r\n\r\n'.format(path, self.config['host'])).encode()
        self.sent = 0
        self.phase = 'connecting'

    def _stage(self):
        self.slot = 'ota_b' if self.boot['active'] == 'ota_a' else 'ota_a'
        needed = sum(entry['size'] for entry in self.release['files']) + 16384
        stats = os.statvfs('.')
        # Count reusable inactive files as well as free space.
        reusable = 0
        for name in FILES:
            try:
                reusable += os.stat(self.slot + '/' + name)[6]
            except OSError:
                pass
        if stats[0] * stats[3] + reusable < needed:
            raise ValueError('Not enough free flash')
        try:
            os.mkdir(self.slot)
        except OSError:
            if not os.stat(self.slot)[0] & 0x4000:
                raise
        self.index = 0
        self.mode = 'file'
        self._next_file()

    def _next_file(self):
        entry = self.release['files'][self.index]
        self._request('/' + self.release['version'] + '/' + entry['name'])
        self.output = open(self.slot + '/' + entry['name'], 'wb')
        self.hasher = hashlib.sha256()
        self.total = entry['size']

    def _body(self, chunk):
        if self.mode == 'manifest':
            if len(self.packet) + len(chunk) > self.MANIFEST_LIMIT:
                raise ValueError('Manifest too large')
            self.packet += chunk
        else:
            if self.received + len(chunk) > self.total:
                raise ValueError('File too large')
            self.output.write(chunk)
            self.hasher.update(chunk)
        self.received += len(chunk)

    def _finished(self):
        if self.received != self.length:
            raise ValueError('Incomplete download')
        if self.mode == 'manifest':
            self.release = manifest(self.packet, self.key)
            self._close()
            self.phase = 'available' if self.release['version'] != self.boot['version'] else 'idle'
        else:
            entry = self.release['files'][self.index]
            if self.received != entry['size'] or hex_digest(self.hasher.digest()) != entry['sha256']:
                raise ValueError('File hash mismatch')
            self.output.flush()
            self.output.close()
            self.output = None
            self._close()
            if hasattr(os, 'sync'):
                os.sync()
            self.index += 1
            if self.index == len(FILES):
                self.index = 0
                self.phase = 'verifying'
            else:
                self._next_file()

    def _verify_step(self):
        entry = self.release['files'][self.index]
        if self.output is None:
            self.output = open(self.slot + '/' + entry['name'], 'rb')
            self.hasher = hashlib.sha256()
            self.received, self.total = 0, entry['size']
        chunk = self.output.read(self.CHUNK)
        if chunk:
            self.hasher.update(chunk)
            self.received += len(chunk)
            if self.received > self.total:
                raise ValueError('Staged file too large')
            return
        if self.received != self.total or hex_digest(self.hasher.digest()) != entry['sha256']:
            raise ValueError('Staged file hash mismatch')
        self.output.close()
        self.output = None
        self.index += 1
        if self.index == len(FILES):
            self.phase = 'ready'

    def poll(self, safe):
        if self.phase in ('idle', 'available', 'error', 'paused'):
            return
        if not safe:
            self._close()
            self.phase = 'paused'
            self.error = 'Game started; check/install again between games'
            return
        try:
            if self.phase == 'verifying':
                self._verify_step()
                return
            if self.phase == 'ready':
                # All inactive files are closed, synced and verified before pointer update.
                self.checkpoint()
                activate(self.slot, self.release['version'])
                self.reboot()
                self.phase = 'restarting'
                return
            if time.ticks_diff(time.ticks_ms(), self.started) > self.TIMEOUT_MS:
                raise ValueError('Update download timed out')
            events = self.poller.poll(0)
            if not events:
                return
            flags = events[0][1]
            if flags & select.POLLERR:
                raise OSError('Update socket error')
            if self.sent < len(self.request):
                if flags & select.POLLOUT:
                    sent = self.sock.send(self.request[self.sent:])
                    if sent:
                        self.sent += sent
                    if self.sent == len(self.request):
                        self.poller.modify(self.sock, select.POLLIN)
                        self.phase = 'downloading'
                return
            chunk = self.sock.recv(self.CHUNK)
            if not chunk:
                raise ValueError('Truncated response')
            if self.length is None:
                self.headers += chunk
                if len(self.headers) > 2048:
                    raise ValueError('Response headers too large')
                if b'\r\n\r\n' not in self.headers:
                    return
                header, chunk = self.headers.split(b'\r\n\r\n', 1)
                if not header.split(b'\r\n')[0].startswith(b'HTTP/1.0 200 ') and not header.split(b'\r\n')[0].startswith(b'HTTP/1.1 200 '):
                    raise ValueError('Release server rejected request')
                fields = {}
                for line in header.split(b'\r\n')[1:]:
                    if b':' in line:
                        key, value = line.split(b':', 1)
                        fields[key.lower()] = value.strip()
                self.length = int(fields[b'content-length'])
                if b'transfer-encoding' in fields or b'content-encoding' in fields:
                    raise ValueError('Encoded responses unsupported')
                expected = self.total if self.mode == 'file' else self.MANIFEST_LIMIT
                if not 0 < self.length <= expected or (self.mode == 'file' and self.length != expected):
                    raise ValueError('Unexpected download size')
                self.headers = b''
            self._body(chunk)
            if self.received >= self.length:
                self._finished()
        except OSError as exc:
            if exc.args and exc.args[0] in (errno.EAGAIN, getattr(errno, 'EWOULDBLOCK', errno.EAGAIN)):
                return
            self._fail(exc)
        except Exception as exc:
            self._fail(exc)
