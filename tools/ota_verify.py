#!/usr/bin/env python3
"""Authenticated end-to-end LAN update check. Run only between games/on bench."""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://ringthebull.local')
    parser.add_argument('--config',type=Path,default=ROOT/'ota_config.json')
    parser.add_argument('--version',required=True)
    parser.add_argument('--poll-interval',type=float,default=.5,help='Status interval; use 5 for a quiet transfer on the legacy sensing gate')
    args=parser.parse_args()
    if not .2<=args.poll_interval<=10:parser.error('poll interval must be 0.2–10 seconds')
    key=json.loads(args.config.read_text())['key']
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path,auth=False,post=False):
        headers={'X-OTA-Key':key} if auth else {}
        req=urllib.request.Request(args.url.rstrip('/')+path,headers=headers,method='POST' if post else 'GET')
        with opener.open(req,timeout=3) as response:
            body=response.read()
            return json.loads(body) if response.headers.get_content_type()=='application/json' else body
    before=request('/status')
    assert before['state'] in ('READY','WAIT RELEASE','COMPLETE') and not before['hook'],before
    assert not before['history'] or len(before['history'])==21,before
    assert request('/health')==b'ok\n'
    try:request('/ota/check',post=True)
    except urllib.error.HTTPError as exc:assert exc.code==403
    else:raise AssertionError('Unauthenticated update accepted')
    print('PASS health and unauthenticated update rejection',flush=True)
    request('/ota/check',auth=True,post=True)
    time.sleep(args.poll_interval)
    end=time.monotonic()+25
    while time.monotonic()<end:
        status=request('/ota/status')
        if status['update_status'] in ('error','paused'):raise RuntimeError(status.get('update_error'))
        if status['update_status']=='available':break
        time.sleep(args.poll_interval)
    else:raise RuntimeError('No release available')
    assert status['available_version']==args.version,status
    print('PASS authenticated manifest check:',args.version,flush=True)
    request('/ota/install',auth=True,post=True)
    time.sleep(args.poll_interval)
    end=time.monotonic()+110
    last=None
    while time.monotonic()<end:
        try:
            status=request('/ota/status')
            state=(status.get('current_version'),status.get('update_status'),status.get('trial'))
            if state!=last:print('UPDATE',state,flush=True);last=state
            if 'rolled back' in (status.get('update_error') or ''):
                raise RuntimeError(status['update_error'])
            if status.get('update_status') in ('error','paused'):
                raise RuntimeError(status.get('update_error'))
            if status['current_version']==args.version and not status.get('trial'):
                break
        except (OSError,urllib.error.URLError):
            pass  # Expected while rebooting; bounded by overall deadline.
        time.sleep(args.poll_interval)
    else:raise RuntimeError('Update did not confirm: '+str(last))
    after=request('/status')
    for field in ('best','longest_streak','hits','misses','throws','history','last_completed'):
        assert after[field]==before[field],(field,before[field],after[field])
    assert request('/health')==b'ok\n'
    assert b'Enter Debug' in request('/')
    print('PASS OTA activation, restart, trial confirmation, scoreboard, diagnostics UI and preserved records/results',flush=True)
    print('FINAL',json.dumps(status),flush=True)


if __name__=='__main__':main()
