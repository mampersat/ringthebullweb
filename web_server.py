"""Optional Pico W scoreboard. Call poll() once per game iteration."""
import errno
import json
import select
import socket
import time

PAGE = b'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ring the Bull</title><style>
:root{color-scheme:dark;--wood:#2b1d17;--screen:#121510;--brass:#b7934b;--cream:#f3e7c6;--green:#79b886;--red:#ce7969}
*{box-sizing:border-box}body{margin:0;background:#1a120e;color:var(--cream);font:16px Georgia,'Times New Roman',serif;padding:12px}main{max-width:740px;margin:auto;background:var(--wood);border:2px solid #684a2f;box-shadow:0 0 0 3px #110e0b,inset 0 0 0 3px #35281c;padding:12px}
header{text-align:center;border:3px double var(--brass);padding:8px 6px;margin-bottom:10px}h1{margin:0;font-size:clamp(1.7rem,7vw,3.2rem);letter-spacing:.04em;line-height:1;text-shadow:2px 2px #080a07}
.playfield{background:var(--screen);border:1px solid #8e733f;box-shadow:inset 0 0 0 4px #080a07;padding:10px}.statusline{display:flex;justify-content:space-between;gap:10px;font:12px 'Courier New',monospace;color:#c4b792}.statusline span:last-child{text-align:right}#connection{color:var(--green)}
#scores{margin-top:8px}.counts{display:grid;grid-template-columns:1fr 1fr;align-items:end;gap:8px}.live-score{border-right:1px solid #4d482f}.score-label{display:block;font-size:.9rem;color:#c4b792}#hits{display:block;font:900 clamp(4.5rem,20vw,8.5rem)/.95 'Courier New',monospace;letter-spacing:-.09em;color:var(--cream);text-shadow:2px 2px #5e4f2c}
.shot-count{text-align:right;padding-bottom:3px}.shot-count strong{font:700 clamp(2rem,9vw,3rem)/1 'Courier New',monospace}.shot-count small{font:1rem 'Courier New',monospace;color:#aa9f7d}.results{display:flex;justify-content:space-between;gap:8px;margin-top:8px;font:14px 'Courier New',monospace;color:#c4b792}.results b{color:var(--cream)}#misses{color:var(--red)}
#action{margin:8px 0 0;padding:6px 0;border-top:1px solid #4d482f;font-size:1.2rem;line-height:1.2;font-weight:bold;color:var(--green)}#state{display:block;color:#a89d7d;font:11px 'Courier New',monospace;letter-spacing:.04em;margin-bottom:6px}
#history{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px}.shot{display:grid;place-items:center;min-width:0;height:26px;background:#252920;border:1px solid #494e3e;color:#b4b6a3;font:700 13px 'Courier New',monospace;box-shadow:inset 0 -3px #161a14}.shot.hit{background:#285439;border-color:var(--green);color:#edffe5}.shot.miss{background:#622d24;border-color:var(--red);color:#ffe6d5}.shot.flying{outline:2px solid var(--cream);outline-offset:-3px}
.records{margin-top:12px}.records h2{display:flex;justify-content:space-between;align-items:baseline;font-size:1.2rem;color:var(--brass);margin:0 0 6px}.records h2 small{font-size:.75rem;font-weight:normal;color:#c7b28a}table{width:100%;border-collapse:collapse;font:14px 'Courier New',monospace}th,td{padding:6px 0;border-bottom:1px solid #5c452e}th{text-align:left;font-weight:normal}td{text-align:right;color:var(--cream);font-weight:bold;font-size:1.1rem}#weekly{font:12px/1.35 'Courier New',monospace;color:#c7b28a;margin:8px 0 0}
.controls{display:grid;grid-template-columns:1fr 1.3fr 1.2fr;gap:7px;margin-top:12px}button{min-height:44px;border:1px solid #d2ae62;border-bottom:4px solid #745624;border-radius:2px;background:#b7934b;color:#17130d;font:700 14px Georgia,'Times New Roman',serif;padding:8px 3px}button:active{transform:translateY(2px);border-bottom-width:2px}button:disabled{background:#3c3223;border-color:#6d5838;color:#a99977;transform:none}button:focus-visible,a:focus-visible{outline:3px solid var(--cream);outline-offset:3px}
#recordsError,#message{font:13px/1.4 'Courier New',monospace;color:#f3b49d;margin:10px 0}#recordsError:empty,#message:empty{display:none}footer{border-top:3px double #8e733f;text-align:center;margin-top:16px;padding-top:12px}footer p{font-size:.85rem;color:#c7b28a;margin:0 0 10px}canvas{display:block;margin:auto;max-width:100%;height:auto;image-rendering:pixelated}#pageUrl{display:block;color:var(--brass);font:12px 'Courier New',monospace;overflow-wrap:anywhere;margin-top:8px}
@media(min-width:650px){body{padding:28px}main{padding:22px}header{padding:18px}.playfield{padding:20px}.counts{grid-template-columns:1.2fr 1fr}#hits{font-size:10rem}.shot-count strong{font-size:4rem}#action{font-size:1.6rem}.shot{height:38px;font-size:16px}.statusline,.results{font-size:16px}.records h2{font-size:1.5rem}table{font-size:16px}.lower{display:grid;grid-template-columns:1fr 190px;gap:28px;align-items:start}.controls{margin-top:16px}footer{margin-top:16px;padding-top:12px}footer canvas{max-width:150px}button{font-size:16px}}
@media(max-width:350px){body{padding:7px}main{padding:7px}header{padding:8px 6px}#hits{font-size:4.5rem}#history{gap:4px}.shot{height:24px}#action{margin-top:8px;padding:6px 0}#state{margin-bottom:6px}.playfield{padding:10px}.records{margin-top:9px}.records h2{font-size:1.1rem}th,td{padding:4px 0}#weekly{font-size:11px}.controls{margin-top:9px}.results{font-size:12px}#action{font-size:1.05rem}}
#debugPanel{margin-top:14px;border-top:1px solid var(--brass);padding-top:10px}#debugToggle{margin-top:12px;width:100%}#debugValues{font:13px/1.6 'Courier New',monospace}#sensorGraph{width:100%;height:180px;background:var(--screen);image-rendering:auto}#debugPanel[hidden]{display:none}#debugNote{font:12px/1.4 'Courier New',monospace;color:#c7b28a}
</style><main><header><h1>Ring the Bull</h1></header>
<div class="playfield"><div class="statusline"><span>21-shot game</span><span id="connection" role="status">Connecting...</span></div>
<section id="scores" aria-label="Current game"><div class="counts"><div class="live-score"><span class="score-label">Score</span><strong id="hits">0</strong></div>
<div class="shot-count"><span class="score-label">Shots taken</span><strong id="throws">0</strong><small> / 21</small></div></div>
<div class="results"><span><b id="left">21</b> shots left</span><span>Misses <b id="misses">0</b></span></div>
<p id="action">Waiting for scoreboard</p><span id="state">CONNECTING</span></section>
<div id="history" aria-label="21 throws"></div></div>
<div class="lower"><div><section class="records" aria-label="High scores"><h2>House records <small>All time</small></h2>
<table aria-label="All-time high scores"><tbody><tr><th scope="row">High score</th><td><span id="best">0</span> / 21</td></tr>
<tr><th scope="row">Best hit streak</th><td id="longest_streak">0</td></tr>
<tr><th scope="row">Game accuracy</th><td id="rate">0.0%</td></tr></tbody></table>
<p id="weekly">Weekly scores need a synced clock.</p></section>
<div class="controls"><button id="undo" disabled>Undo</button><button id="reset">Start Over</button><button id="share" disabled>Share</button></div>
<p id="recordsError" role="status"></p><p id="message" role="status"></p></div>
<footer><p>Scan to join the game</p><canvas id="qr" role="img" aria-label="QR code for this scoreboard"></canvas><a id="pageUrl"></a></footer></div>
<button id="debugToggle" aria-expanded="false" aria-controls="debugPanel">Enter Debug</button>
<section id="debugPanel" hidden aria-label="Sensor diagnostics"><h2>Sensor diagnostics</h2>
<div id="debugValues">Waiting for sensor readings...</div>
<canvas id="sensorGraph" width="640" height="180" role="img" aria-label="Last 60 seconds: raw capacitance, idle baseline and grab threshold"></canvas>
<p id="debugNote">Raw: cream / idle baseline: green / grab threshold: gold. Readings in microseconds, not farads. Baseline is an observed idle estimate, not scoring calibration. Gaps mean timeout or sensing skipped on hook.</p></section>
<details id="updates"><summary>Application updates</summary>
<p id="updateInfo">Loading version...</p><button id="updateCheck">Check for update</button>
<button id="updateInstall" disabled>Install between games</button>
<p>Trusted LAN only. Updates briefly restart the Pico. Your saved results are retained.</p></details></main>
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
// The update key stays only in memory; never in URLs or browser storage.
let updateKey=null;
async function updateInfo(){
 try{const response=await fetch('/ota/status',{cache:'no-store'});if(!response.ok)return;
  const s=await response.json();
  document.getElementById('updateInfo').textContent='Installed: '+s.current_version+
   ' | Available: '+(s.available_version||'unchecked')+' | '+s.update_status+(s.trial?' (trial)':'')+
   (s.bench_mode?' | BENCH: sensors disconnected':'')+
   (s.update_error?' | '+s.update_error:'');
  document.getElementById('updateInstall').disabled=!['available','paused','error'].includes(s.update_status)||!s.available_version;
 }catch(e){document.getElementById('updateInfo').textContent='Update status unavailable';}
}
async function updateCommand(name){
 if(!updateKey)updateKey=prompt('Private OTA key (trusted LAN only):');if(!updateKey)return;
 if(name==='install'&&!confirm('Install this release and restart between games?'))return;
 try{const response=await fetch('/ota/'+name,{method:'POST',headers:{'X-OTA-Key':updateKey}});
  if(!response.ok){if(response.status===403)updateKey=null;throw Error(response.status===409?'Game active or updater busy':'Update request rejected');}
  await updateInfo();
 }catch(e){document.getElementById('updateInfo').textContent=e.message;}
}
document.getElementById('updateCheck').onclick=()=>updateCommand('check');
document.getElementById('updateInstall').onclick=()=>updateCommand('install');
async function refreshUpdateInfo(){if(!document.hidden)await updateInfo();setTimeout(refreshUpdateInfo,2000);}
refreshUpdateInfo();
// Diagnostics: one request in flight, 5 Hz maximum, 300 browser-only samples.
let debugOpen=false, debugTimer=null, debugRequest=null, debugGeneration=0;
const debugSamples=[];
function drawSensorGraph(){
 const canvas=document.getElementById('sensorGraph'),ctx=canvas.getContext('2d');
 const w=canvas.width,h=canvas.height,now=performance.now();
 while(debugSamples.length&&now-debugSamples[0].t>60000)debugSamples.shift();
 ctx.clearRect(0,0,w,h);
 let maximum=600;
 for(const s of debugSamples)for(const key of ['raw','baseline','grab_threshold'])
  if(Number.isFinite(s[key]))maximum=Math.max(maximum,s[key]*1.1);
 ctx.font='12px monospace';ctx.fillStyle='#c7b28a';
 ctx.fillText(Math.ceil(maximum)+' us',4,13);ctx.fillText('-60s',4,h-3);ctx.fillText('now',w-28,h-3);
 for(const [key,color] of [['raw','#f3e7c6'],['baseline','#79b886'],['grab_threshold','#b7934b']]){
  ctx.strokeStyle=color;ctx.beginPath();let pen=false,lastTime=null;
  for(const s of debugSamples){
   if(!Number.isFinite(s[key])){pen=false;continue;}
   const x=w-(now-s.t)/60000*w,y=h-18-s[key]/maximum*(h-36);
   if(pen&&s.t-lastTime<1000)ctx.lineTo(x,y);else ctx.moveTo(x,y);
   pen=true;lastTime=s.t;
  }ctx.stroke();
 }
}
function stopDebug(){
 debugGeneration++;clearTimeout(debugTimer);debugTimer=null;
 if(debugRequest)debugRequest.abort();
}
async function pollDebug(){
 if(!debugOpen||document.hidden||debugRequest)return;
 const generation=debugGeneration,controller=new AbortController();debugRequest=controller;
 const timeout=setTimeout(()=>controller.abort(),1500),started=performance.now();
 try{
  const response=await fetch('/debug',{cache:'no-store',signal:controller.signal});
  if(!response.ok)throw Error('debug');const s=await response.json();
  if(generation!==debugGeneration||!debugOpen||document.hidden)return;
  const value=n=>Number.isFinite(n)?Math.round(n*10)/10+' us':'unavailable';
  document.getElementById('debugValues').textContent='Raw: '+value(s.raw)+' | Baseline (idle): '+value(s.baseline)+
   ' | Delta: '+value(s.delta)+' | Grab threshold: '+value(s.grab_threshold)+
   ' | Grabbed: '+(s.grabbed?'yes':'no')+' | Hook contact (electrical): '+(s.hook_contact?'yes':'no');
  debugSamples.push({...s,t:performance.now()});if(debugSamples.length>300)debugSamples.shift();drawSensorGraph();
 }catch(e){if(generation===debugGeneration&&debugOpen&&!document.hidden)
  document.getElementById('debugValues').textContent='Sensor diagnostics unavailable - retrying';}
 finally{
  clearTimeout(timeout);debugRequest=null;
  if(debugOpen&&!document.hidden)debugTimer=setTimeout(pollDebug,Math.max(0,200-(performance.now()-started)));
 }
}
document.getElementById('debugToggle').onclick=()=>{
 debugOpen=!debugOpen;stopDebug();
 document.getElementById('debugPanel').hidden=!debugOpen;
 document.getElementById('debugToggle').textContent=debugOpen?'Exit Debug':'Enter Debug';
 document.getElementById('debugToggle').setAttribute('aria-expanded',String(debugOpen));
 if(debugOpen)pollDebug();
};
document.addEventListener('visibilitychange',()=>{stopDebug();if(!document.hidden&&debugOpen)pollDebug();});
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

    def __init__(self, status, port=80, action=None, diagnostics=None, ota=None, ota_command=None, ota_status=None):
        self.status = status
        self.diagnostics = diagnostics
        self.ota, self.ota_command, self.ota_status = ota, ota_command, ota_status
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
        elif line[1] in (b'/ota/check', b'/ota/install'):
            if line[0] != b'POST':
                code, body = '405 Method Not Allowed', b'Use POST\n'
            else:
                fields = {}
                for row in request.split(b'\r\n')[1:]:
                    if b':' in row:
                        key, value = row.split(b':', 1)
                        fields[key.lower()] = value.strip()
                origin = fields.get(b'origin')
                token = fields.get(b'x-ota-key', b'')
                if self.ota is None or not self.ota.authorized(token):
                    code, body = '403 Forbidden', b'Update authentication required\n'
                elif origin is not None and origin != b'http://' + fields.get(b'host', b''):
                    code, body = '403 Forbidden', b'Origin mismatch\n'
                elif fields.get(b'content-length', b'0') != b'0' or b'transfer-encoding' in fields:
                    code, body = '400 Bad Request', b'Empty body required\n'
                elif self.ota_command is None or not self.ota_command(line[1].split(b'/')[-1].decode()):
                    code, body = '409 Conflict', b'Update unavailable or game active\n'
                else:
                    kind, body = 'application/json', json.dumps(self.ota_status()).encode()
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
        elif line[1] == b'/debug' and self.diagnostics is not None:
            kind, body = 'application/json', json.dumps(self.diagnostics()).encode()
        elif line[1] == b'/ota/status' and self.ota_status is not None:
            kind, body = 'application/json', json.dumps(self.ota_status()).encode()
        elif line[1] == b'/health':
            body = b'ok\n'
        else:
            code, body = '404 Not Found', b'Not found\n'
        allow = 'POST' if len(line) == 3 and line[1] in (b'/undo', b'/reset', b'/ota/check', b'/ota/install') else 'GET'
        header = ('HTTP/1.1 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n'
                  'Cache-Control: no-store\r\nConnection: close\r\n'
                  'Allow: {}\r\n\r\n').format(code, kind, len(body), allow).encode()
        return (header, body) if body is PAGE else header + body

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
            response = client[2]
            if isinstance(response, tuple):
                header, body = response
                total = len(header) + len(body)
                part = (memoryview(header)[start:start + self.CHUNK] if start < len(header)
                        else memoryview(body)[start - len(header):start - len(header) + self.CHUNK])
            else:
                total = len(response)
                part = memoryview(response)[start:start + self.CHUNK]
            sent = sock.send(part)
            if sent is None:
                return
            if sent <= 0:
                self._close(sock)
                return
            client[3] += sent
            if client[3] == total:
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
