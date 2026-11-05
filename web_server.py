"""Optional Pico W scoreboard. Call poll() once per game iteration."""
import errno
import json
import select
import socket
import time

PAGE = b'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ring the Bull</title><style>
*{box-sizing:border-box}body{font:16px system-ui;background:#111820;color:#f6f8fb;max-width:28rem;margin:auto;padding:14px}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}h1{font-size:1rem;margin:0}#connection{font-size:.75rem;color:#aab9c8;max-width:65%;text-align:right}
#history{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:5px}.shot{height:34px;display:grid;place-items:center;border-radius:5px;font-size:.8rem;font-weight:650;background:#36414d;color:#e1e7ee}
.shot.hit{background:#187343;color:#fff}.shot.miss{background:#a83640;color:#fff}.shot.flying{outline:2px solid #79c6ff;outline-offset:-2px}
#scores{background:#1b2936;border:1px solid #304151;border-radius:12px;padding:14px;margin-top:12px}.counts{display:flex;align-items:center;justify-content:space-between;gap:16px}.remaining{font-size:.85rem;color:#bdcbd8}#left{display:block;font-size:3rem;line-height:1.05;color:#fff;font-weight:750}
.totals{display:flex;gap:18px;text-align:center}.totals strong{display:block;font-size:1.9rem;line-height:1.2}#hits{color:#73dfa4}#misses{color:#ff929a}.totals span{font-size:.8rem;color:#bdcbd8}
#action{font-size:1.1rem;font-weight:650;margin:12px 0 2px}#state{font-size:.7rem;color:#aab9c8;letter-spacing:.06em}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));text-align:center;gap:6px;margin:14px 0}.metrics strong{display:block;font-size:1.3rem}.metrics span{font-size:.72rem;color:#aab9c8}.metrics small{font-size:.75rem;color:#aab9c8}
.controls{display:grid;grid-template-columns:1fr 1.25fr 1fr;gap:8px}button{font:600 .9rem system-ui;min-height:44px;border:1px solid #415364;border-radius:8px;background:#26394b;color:#fff;padding:8px 4px}button:disabled{opacity:.4}#share{background:#225939;border-color:#36784e}
#recordsError,#message{color:#f5bb7b;font-size:.8rem;margin:8px 0}#recordsError:empty,#message:empty{display:none}footer{text-align:center;border-top:1px solid #2c3946;margin-top:18px;padding-top:14px}footer p{font-size:.8rem;color:#aab9c8;margin:0 0 10px}canvas{display:block;margin:auto;max-width:100%;height:auto;image-rendering:pixelated}#pageUrl{display:block;color:#bdcbd8;font-size:.75rem;margin-top:8px;overflow-wrap:anywhere}
</style><header><h1>Ring the Bull</h1><span id="connection" role="status">Connecting...</span></header>
<div id="history" aria-label="21 throws"></div>
<section id="scores" aria-label="Current game"><div class="counts">
<div class="remaining"><strong id="left">21</strong>shots left</div>
<div class="totals"><div><strong id="hits">0</strong><span>hits</span></div><div><strong id="misses">0</strong><span>misses</span></div></div></div>
<p id="action">Waiting for scoreboard</p><span id="state">CONNECTING</span><span id="throws" hidden>0</span></section>
<div class="metrics"><div><strong><b id="best">0</b><small>/21</small></strong><span>High score</span></div>
<div><strong id="longest_streak">0</strong><span>Best streak</span></div><div><strong id="rate">0.0%</strong><span>Accuracy</span></div></div>
<div class="controls"><button id="undo" disabled>Undo</button><button id="reset">Start Over</button><button id="share" disabled>Share</button></div>
<p id="recordsError" role="status"></p><p id="message" role="status"></p>
<footer><p>Scan to open this scoreboard</p><canvas id="qr" role="img" aria-label="QR code for this scoreboard"></canvas><a id="pageUrl"></a></footer>
<script>
const slots=[];
for(let i=0;i<21;i++){const slot=document.createElement('span');slot.className='shot';slot.textContent=i+1;
 document.getElementById('history').appendChild(slot);slots.push(slot);}
const actions={'READY':'Grab the ring','HELD':'Swing and release','IN FLIGHT':'Ring in flight',
 'LANDED':'Take ring off hook','WAIT RESET':'Grab the ring','WAIT RELEASE':'Release ring to continue','COMPLETE':'Game complete - grab for next game'};
let latest=null;
let actionBusy=false;
async function update(){
 const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),2000);
 try{
  const response=await fetch('/status',{cache:'no-store',signal:controller.signal});
  if(!response.ok)throw Error('status');const s=await response.json();
  latest=s;
  for(const key of ['hits','misses','throws','state','best','longest_streak'])document.getElementById(key).textContent=s[key];
  document.getElementById('rate').textContent=(s.throws?100*s.hits/s.throws:0).toFixed(1)+'%';
  document.getElementById('left').textContent=Math.max(0,21-s.history.length);
  document.getElementById('action').textContent=actions[s.state]||s.state;
  slots.forEach((slot,i)=>{
   const result=i<s.history.length?(s.history[i]?'hit':'miss'):'pending';
   slot.className='shot '+result+(i===s.history.length&&s.state==='IN FLIGHT'?' flying':'');
   slot.textContent=(i+1)+(result==='hit'?String.fromCharCode(10003):result==='miss'?String.fromCharCode(215):'');
   slot.setAttribute('aria-label','Throw '+(i+1)+': '+result);
  });
  document.getElementById('connection').textContent='Live';
  document.getElementById('undo').disabled=actionBusy||!s.can_undo;
  document.getElementById('share').disabled=!(s.last_completed||s.complete);
  document.getElementById('share').textContent=s.last_completed&&!s.complete?'Share last game':'Share';
  document.getElementById('recordsError').textContent=s.records_error||'';
 }catch(e){document.getElementById('connection').textContent='Offline - reconnecting...';}
 finally{clearTimeout(timeout);}
}
async function refresh(){await update();setTimeout(refresh,500);}
async function action(name){
 if(actionBusy)return;
 if(name==='reset'&&!confirm('Reset this game? Records will be kept.'))return;
 actionBusy=true;
 for(const id of ['undo','reset'])document.getElementById(id).disabled=true;
 const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),2000);
 try{
  const response=await fetch('/'+name,{method:'POST',signal:controller.signal});
  if(!response.ok)throw Error('Action unavailable');
  document.getElementById('message').textContent='';
 }catch(e){document.getElementById('message').textContent='Could not confirm action. Check the current score.';}
 finally{clearTimeout(timeout);actionBusy=false;document.getElementById('reset').disabled=false;await update();}
}
document.getElementById('undo').onclick=()=>action('undo');
document.getElementById('reset').onclick=()=>action('reset');
document.getElementById('share').onclick=async()=>{
 const result=latest&&(latest.last_completed||(latest.complete?latest:null));
 if(!result)return;
 const rows=[];for(let i=0;i<result.history.length;i+=7){
  rows.push(result.history.slice(i,i+7).map(hit=>String.fromCodePoint(hit?0x1f7e9:0x1f7e5)).join(''));
 }
 const text='Ring the Bull: '+result.hits+'/21'+String.fromCharCode(10,10)+rows.join(String.fromCharCode(10))+
  String.fromCharCode(10,10)+location.origin+'/';
 if(navigator.share){try{await navigator.share({title:'Ring the Bull',text});return;}
  catch(e){if(e.name==='AbortError')return;}}
 try{if(navigator.clipboard){await navigator.clipboard.writeText(text);
  document.getElementById('message').textContent='Results copied';return;}}catch(e){}
 const area=document.createElement('textarea');area.value=text;document.body.appendChild(area);area.select();
 let copied=false;try{copied=document.execCommand('copy');}catch(e){}area.remove();
 if(copied)document.getElementById('message').textContent='Results copied';
 else prompt('Copy results:',text);
};
// Compact byte-mode QR encoder: versions 1-10, level L, mask 0.
// All work runs once in the browser; nothing is generated or stored on the Pico.
function drawQR(url){
 const bytes=new TextEncoder().encode(url);
 const capacity=[0,19,34,55,80,108,136,156,194,232,274];
 const parity=[0,7,10,15,20,26,18,20,24,30,18];
 const groups=[0,1,1,1,1,1,2,2,2,2,4];
 let version=1;while(version<=10&&bytes.length*8+4+(version<10?8:16)>capacity[version]*8)version++;
 if(version>10)throw Error('URL too long');
 const bits=[];const append=(value,count)=>{for(let i=count-1;i>=0;i--)bits.push((value>>>i)&1);};
 append(4,4);append(bytes.length,version<10?8:16);for(const byte of bytes)append(byte,8);
 append(0,Math.min(4,capacity[version]*8-bits.length));while(bits.length%8)bits.push(0);
 const data=[];for(let i=0;i<bits.length;i+=8){let byte=0;for(let j=0;j<8;j++)byte=byte*2+bits[i+j];data.push(byte);}
 for(let pad=0;data.length<capacity[version];pad++)data.push(pad%2?17:236);
 const multiply=(a,b)=>{let product=0;for(;b;b>>>=1){if(b&1)product^=a;a<<=1;if(a&256)a^=285;}return product;};
 const ecc=parity[version];let divisor=[1],root=1;
 for(let i=0;i<ecc;i++){
  const next=Array(divisor.length+1).fill(0);
  divisor.forEach((v,j)=>{next[j]^=v;next[j+1]^=multiply(v,root);});divisor=next;root=multiply(root,2);
 }
 const blocks=[],checks=[];let offset=0;
 for(let block=0;block<groups[version];block++){
  const length=Math.floor(data.length/groups[version])+(block>=groups[version]-data.length%groups[version]?1:0);
  const part=data.slice(offset,offset+length);offset+=length;const remainder=part.concat(Array(ecc).fill(0));
  for(let i=0;i<part.length;i++){const factor=remainder[i];for(let j=0;j<divisor.length;j++)remainder[i+j]^=multiply(divisor[j],factor);}
  blocks.push(part);checks.push(remainder.slice(-ecc));
 }
 const words=[];for(let i=0;i<blocks[blocks.length-1].length;i++)for(const block of blocks)if(i<block.length)words.push(block[i]);
 for(let i=0;i<ecc;i++)for(const check of checks)words.push(check[i]);
 const size=version*4+17,matrix=Array.from({length:size},()=>Array(size).fill(0));
 const reserved=Array.from({length:size},()=>Array(size).fill(false));
 const set=(x,y,value)=>{if(x>=0&&y>=0&&x<size&&y<size){matrix[y][x]=value?1:0;reserved[y][x]=true;}};
 for(let i=0;i<size;i++){set(6,i,i%2===0);set(i,6,i%2===0);}
 for(const [cx,cy] of [[3,3],[size-4,3],[3,size-4]])for(let y=-4;y<=4;y++)for(let x=-4;x<=4;x++){
  const d=Math.max(Math.abs(x),Math.abs(y));set(cx+x,cy+y,d!==2&&d!==4);
 }
 if(version>1){
  const centers=version<7?[6,size-7]:[6,version*2+8,size-7];
  for(const cy of centers)for(const cx of centers){
   if((cx===6&&(cy===6||cy===size-7))||(cx===size-7&&cy===6))continue;
   for(let y=-2;y<=2;y++)for(let x=-2;x<=2;x++)set(cx+x,cy+y,Math.max(Math.abs(x),Math.abs(y))!==1);
  }
 }
 // Format bits: level L (01), mask 000, BCH(15,5), standard XOR mask.
 let remainder=8;for(let i=0;i<10;i++)remainder=(remainder<<1)^((remainder>>>9)*1335);
 const format=((8<<10)|remainder)^21522,bit=(value,i)=>(value>>>i)&1;
 for(let i=0;i<15;i++){
  if(i<6)set(8,i,bit(format,i));else if(i<8)set(8,i+1,bit(format,i));
  else if(i===8)set(7,8,bit(format,i));else set(14-i,8,bit(format,i));
  if(i<8)set(size-1-i,8,bit(format,i));else set(8,size-15+i,bit(format,i));
 }set(8,size-8,1);
 if(version>=7){
  let r=version;for(let i=0;i<12;i++)r=(r<<1)^((r>>>11)*7973);const value=(version<<12)|r;
  for(let i=0;i<18;i++){const a=size-11+i%3,b=Math.floor(i/3);set(a,b,bit(value,i));set(b,a,bit(value,i));}
 }
 let index=0,up=true;
 for(let right=size-1;right>0;right-=2){
  if(right===6)right=5;
  for(let row=0;row<size;row++)for(let column=0;column<2;column++){
   const x=right-column,y=up?size-1-row:row;if(reserved[y][x])continue;
   matrix[y][x]=(index<words.length*8?bit(words[index>>>3],7-index%8):0)^((x+y)%2===0?1:0);index++;
  }up=!up;
 }
 const canvas=document.getElementById('qr'),scale=Math.max(3,Math.floor(192/(size+8)));
 canvas.width=canvas.height=(size+8)*scale;const context=canvas.getContext('2d');
 context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.fillStyle='#000';
 for(let y=0;y<size;y++)for(let x=0;x<size;x++)if(matrix[y][x])context.fillRect((x+4)*scale,(y+4)*scale,scale,scale);
}
const pageUrl=document.getElementById('pageUrl');pageUrl.href=location.origin+'/';pageUrl.textContent=location.origin;
try{drawQR(pageUrl.href);}catch(e){document.getElementById('qr').hidden=true;pageUrl.textContent+=' (QR unavailable)';}

refresh();
</script></html>'''

WOULD_BLOCK = (errno.EAGAIN, getattr(errno, "EWOULDBLOCK", errno.EAGAIN))


class WebServer:
    MAX_CLIENTS = 2
    REQUEST_LIMIT = 1024
    CHUNK = 512
    CLIENT_TIMEOUT_MS = 5000
    RETRY_MS = 30000

    def __init__(self, status, port=80, action=None):
        self.status = status
        self.action = action
        self.port = port
        self.listener = None
        self.clients = {}
        self.poller = select.poll()
        self.wlan = None
        self.last_retry = None
        self.last_tick = time.ticks_ms()
        self.uptime_ms = 0
        # No scans, DNS, static IP changes, or waits for association/DHCP.
        import network
        # DHCP and built-in mDNS take the name when the interface starts.
        try:
            network.hostname('ringthebull')
        except (AttributeError, OSError, ValueError):
            print('Hostname unavailable; use the DHCP IP address')
        self.wlan = network.WLAN(network.STA_IF)
        try:
            import wifi_config
        except ImportError:
            wifi_config = None
        if wifi_config is not None:
            self.wlan.active(True)
            if not self.wlan.isconnected():
                self.wlan.connect(wifi_config.WIFI_SSID, wifi_config.WIFI_PASSWORD)

    def _close(self, sock):
        try:
            self.poller.unregister(sock)
        except (OSError, KeyError):
            pass
        sock.close()
        self.clients.pop(sock, None)

    def close(self):
        for sock in list(self.clients):
            self._close(sock)
        if self.listener is not None:
            self._close(self.listener)
            self.listener = None

    def _listen(self):
        sock = socket.socket()
        try:
            sock.setblocking(False)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', self.port))
            sock.listen(self.MAX_CLIENTS)
            self.poller.register(sock, select.POLLIN)
        except Exception:
            sock.close()
            raise
        self.listener = sock
        print('Scoreboard: http://{}/'.format(self.wlan.ifconfig()[0]))

    def _response(self, request):
        line = request.split(b'\r\n', 1)[0].split()
        code, kind = '200 OK', 'text/plain; charset=utf-8'
        if len(line) != 3 or line[2] not in (b'HTTP/1.0', b'HTTP/1.1'):
            code, body = '400 Bad Request', b'Bad request\n'
        elif line[1] in (b'/undo', b'/reset'):
            if line[0] != b'POST':
                code, body = '405 Method Not Allowed', b'Use POST\n'
            else:
                headers = {}
                for header_line in request.split(b'\r\n')[1:]:
                    if b':' in header_line:
                        key, value = header_line.split(b':', 1)
                        headers[key.lower()] = value.strip()
                origin = headers.get(b'origin')
                if origin is not None and origin != b'http://' + headers.get(b'host', b''):
                    code, body = '403 Forbidden', b'Origin mismatch\n'
                elif headers.get(b'content-length', b'0') != b'0' or b'transfer-encoding' in headers:
                    code, body = '400 Bad Request', b'Empty body required\n'
                elif self.action is None or not self.action(line[1][1:].decode()):
                    code, body = '409 Conflict', b'Action unavailable\n'
                else:
                    kind, body = 'application/json', json.dumps(self.status()).encode()
        elif line[0] != b'GET':
            code, body = '405 Method Not Allowed', b'Use GET\n'
        elif line[1] == b'/':
            kind, body = 'text/html; charset=utf-8', PAGE
        elif line[1] == b'/status':
            data = self.status()
            data['uptime'] = self.uptime_ms // 1000
            kind, body = 'application/json', json.dumps(data).encode()
        elif line[1] == b'/health':
            body = b'ok\n'
        else:
            code, body = '404 Not Found', b'Not found\n'
        allow = 'POST' if len(line) == 3 and line[1] in (b'/undo', b'/reset') else 'GET'
        header = ('HTTP/1.1 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n'
                  'Cache-Control: no-store\r\nConnection: close\r\n'
                  'Allow: {}\r\n\r\n').format(code, kind, len(body), allow).encode()
        return header + body

    def _service(self, sock, flags, now):
        if flags & (select.POLLERR | select.POLLHUP):
            if sock is self.listener:
                self.close()
            else:
                self._close(sock)
            return
        if sock is self.listener:
            if flags & select.POLLIN:
                client, _ = sock.accept()  # At most one accept per iteration.
                client.setblocking(False)
                if len(self.clients) >= self.MAX_CLIENTS:
                    client.close()
                else:
                    self.clients[client] = [now, b'', None, 0]
                    try:
                        self.poller.register(client, select.POLLIN)
                    except Exception:
                        self._close(client)
                        raise
            return
        client = self.clients.get(sock)
        if client is None:
            return
        if flags & select.POLLIN and client[2] is None:
            chunk = sock.recv(self.CHUNK)
            if not chunk:
                self._close(sock)
                return
            client[1] += chunk
            if len(client[1]) > self.REQUEST_LIMIT:
                self._close(sock)
            elif b'\r\n\r\n' in client[1]:
                client[2] = self._response(client[1])
                client[1] = b''
                self.poller.modify(sock, select.POLLOUT)
        elif flags & select.POLLOUT and client[2] is not None:
            start = client[3]
            sent = sock.send(memoryview(client[2])[start:start + self.CHUNK])
            if sent is None:
                return
            if sent <= 0:
                self._close(sock)
                return
            client[3] += sent
            if client[3] == len(client[2]):
                self._close(sock)

    def poll(self):
        now = time.ticks_ms()
        self.uptime_ms += time.ticks_diff(now, self.last_tick)
        self.last_tick = now
        try:
            if not self.wlan.isconnected():
                self.close()
                return
            if self.listener is None:
                if self.last_retry is not None and time.ticks_diff(now, self.last_retry) < self.RETRY_MS:
                    return
                self.last_retry = now
                self._listen()
            for sock, client in list(self.clients.items()):
                if time.ticks_diff(now, client[0]) >= self.CLIENT_TIMEOUT_MS:
                    self._close(sock)
            # Zero wait; at most MAX_CLIENTS + one listener are registered.
            for event in self.poller.poll(0):
                sock, flags = event[0], event[1]
                try:
                    self._service(sock, flags, now)
                except OSError as exc:
                    if exc.args[0] not in WOULD_BLOCK:
                        if sock is self.listener:
                            self.close()
                        else:
                            self._close(sock)
        except Exception:
            # A network failure must never stop the game.
            self.close()
            self.last_retry = now
