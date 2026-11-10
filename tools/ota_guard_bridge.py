#!/usr/bin/env python3
"""One-time signed bridge from 2026.11.09.4's over-sensitive staging gate.

The small trial verifies/copies the previous slot into its own slot, changing only
OTA gate/poll code. It never writes the previous slot or root recovery/config/data.
A reset during expansion rolls back normally. After confirmation both slots remain
independent, so the next full release can overwrite the previous slot safely.
"""
import hashlib
import hmac
import json
from pathlib import Path
from ota_release import ROOT, FILES

BASE='2026.11.09.4'
VERSION='2026.11.09.6-bridge'

BOOTSTRAP='''import os,json,hashlib,binascii
from ota_recovery import load_state
_s=load_state()
assert _s['phase']=='trial' and _s['previous_version']==%(base)r
_a,_b=_s['active'],_s['previous']
assert _a!=_b and _b in ('ota_a','ota_b')
_m=%(metadata)r
_g=%(gate)r
_p=%(poll)r
def _hash(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  while True:
   b=f.read(512)
   if not b:break
   h.update(b);ota_watchdog.feed()
 return binascii.hexlify(h.digest()).decode()
for n,v in _m.items():assert _hash(_b+'/'+n)==v[0]
_st=os.statvfs('.')
assert _st[0]*_st[3]+sum(os.stat(_a+'/'+n)[6] for n in _m)>sum(v[2] for v in _m.values())+16384
for n,v in _m.items():
 if n=='main.py':
  with open(_b+'/'+n) as f:t=f.read()
  i=t.index('\\ndef ota_safe():');j=t.index('\\ndef ota_checkpoint():',i)
  t=t[:i]+_g+t[j:]
  assert t.count('        updater.poll(ota_safe())')==1
  t=t.replace('        updater.poll(ota_safe())',_p)
  with open(_a+'/'+n,'w') as f:f.write(t);f.flush()
  del t
 else:
  with open(_b+'/'+n,'rb') as r,open(_a+'/'+n,'wb') as w:
   while True:
    b=r.read(512)
    if not b:break
    w.write(b);ota_watchdog.feed()
   w.flush()
 os.sync()
 assert _hash(_a+'/'+n)==v[1]
with open(_a+'/main.py') as f:_code=compile(f.read(),_a+'/main.py','exec')
del _m,_g,_p
exec(_code,globals())
'''


def sources(root=ROOT):
    current=(root/'main.py').read_text()
    gate=current[current.index('\ndef ota_idle():'):current.index('\ndef ota_checkpoint():')]
    # Exclude comments/empty lines from the transport, retaining readable source here.
    gate='\n'+'\n'.join(line for line in gate.splitlines() if line.strip() and not line.lstrip().startswith('#'))+'\n\n'
    poll="        idle = ota_idle()\n        if not idle or updater.phase != 'ready' or ota_safe():\n            updater.poll(idle)"
    metadata={};expanded={}
    for name in FILES:
        original=(root/'releases'/BASE/name).read_bytes()
        data=original
        if name=='main.py':
            text=original.decode();a=text.index('\ndef ota_safe():');b=text.index('\ndef ota_checkpoint():',a)
            text=text[:a]+gate+text[b:]
            assert text.count('        updater.poll(ota_safe())')==1
            data=text.replace('        updater.poll(ota_safe())',poll).encode()
        compile(data,name,'exec')
        expanded[name]=data
        metadata[name]=(hashlib.sha256(original).hexdigest(),hashlib.sha256(data).hexdigest(),len(data))
    bootstrap=(BOOTSTRAP%dict(base=BASE,metadata=metadata,gate=gate,poll=poll)).encode()
    compile(bootstrap,'main.py','exec')
    return {'main.py':bootstrap,'web_server.py':b"raise RuntimeError('Bridge incomplete')\n",'records.py':b"raise RuntimeError('Bridge incomplete')\n"},expanded


def build():
    files,_=sources();output=ROOT/'releases';folder=output/VERSION
    folder.mkdir()
    entries=[]
    for name,data in files.items():
        (folder/name).write_bytes(data)
        entries.append(dict(name=name,size=len(data),sha256=hashlib.sha256(data).hexdigest()))
    key=json.loads((ROOT/'ota_config.json').read_text())['key'].encode()
    payload=json.dumps(dict(format=1,version=VERSION,files=entries),separators=(',',':'))
    packet=json.dumps(dict(payload=payload,hmac=hmac.new(key,payload.encode(),hashlib.sha256).hexdigest()))
    temporary=output/'manifest.json.tmp';temporary.write_text(packet);temporary.replace(output/'manifest.json')
    print('Built signed bridge',VERSION,'bytes',sum(map(len,files.values())))


if __name__=='__main__':build()
