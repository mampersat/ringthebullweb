#!/usr/bin/env python3
"""Build/sign a fixed application release and serve it on the trusted LAN."""
import argparse
import hashlib
import hmac
import http.server
import json
from pathlib import Path
import secrets

FILES = ('main.py', 'web_server.py', 'records.py')
ROOT = Path(__file__).resolve().parents[1]


def build(version, config_path, output):
    if not 1 <= len(version) <= 48 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in version):
        raise ValueError('Use a short alphanumeric release version')
    config = json.loads(config_path.read_text())
    slot = output / version
    # Versions are immutable; never partially replace a published release.
    if slot.exists():
        raise ValueError('Release version already exists')
    slot.mkdir(parents=True)
    entries = []
    for name in FILES:
        data = (ROOT / name).read_bytes()
        if not 1 <= len(data) <= 128000:
            raise ValueError('Application file too large')
        compile(data, name, 'exec')
        (slot / name).write_bytes(data)
        entries.append(dict(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
    payload = json.dumps(dict(format=1, version=version, files=entries), separators=(',', ':'))
    packet = json.dumps(dict(payload=payload, hmac=hmac.new(config['key'].encode(), payload.encode(), hashlib.sha256).hexdigest()))
    if len(packet.encode()) > 4096:
        raise ValueError('Manifest too large')
    temporary = output / 'manifest.json.tmp'
    temporary.write_text(packet)
    temporary.replace(output / 'manifest.json')
    print('Built', version, 'in', output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'build', 'serve'))
    parser.add_argument('--host', help='Computer IPv4 address reachable by Pico (init only)')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--version')
    parser.add_argument('--config', type=Path, default=ROOT / 'ota_config.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'releases')
    args = parser.parse_args()
    if args.command == 'init':
        if args.config.exists() or not args.host:
            parser.error('init requires --host and a config path that does not exist')
        parts = args.host.split('.')
        if len(parts) != 4 or any(not p.isdigit() or not 0 <= int(p) <= 255 for p in parts):
            parser.error('--host must be IPv4')
        args.config.write_text(json.dumps(dict(host=args.host, port=args.port, key=secrets.token_hex(32)), indent=2)+'\n')
        args.config.chmod(0o600)
        print('Private configuration created:', args.config, '(keep outside release directory)')
    elif args.command == 'build':
        if not args.version:
            parser.error('build requires --version')
        if args.config.resolve().is_relative_to(args.output.resolve()):
            parser.error('Private configuration cannot be inside public release directory')
        build(args.version, args.config, args.output)
    else:
        if args.config.resolve().is_relative_to(args.output.resolve()):
            parser.error('Private configuration cannot be served')
        from functools import partial
        server = http.server.HTTPServer(('0.0.0.0', args.port), partial(http.server.SimpleHTTPRequestHandler, directory=str(args.output)))
        print('Serving releases on trusted LAN port', args.port)
        server.serve_forever()


if __name__ == '__main__':
    main()
