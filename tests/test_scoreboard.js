// Run with node tests/test_scoreboard.js; uses the repo's existing screenshot tools.
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const puppeteer = require('../scripts/node_modules/puppeteer-core');
const jsQR = require('../vendor/jsQR.min.js');
const pageHtml = execFileSync('python3', ['-c', 'import web_server; import sys; sys.stdout.buffer.write(web_server.PAGE)']);
(async () => {
 const browser = await puppeteer.launch({executablePath:process.env.CHROME_PATH || '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
 try {
  const page = await browser.newPage();
  await page.setViewport({width:360,height:640,isMobile:true,deviceScaleFactor:2});
  const calls=[];
  let debugCalls=0;
  const otaCalls=[];
  let otaState={current_version:'v1',available_version:null,update_status:'idle',bench_mode:true};
  let debugData={raw:750,baseline:50,delta:700,grab_threshold:500,release_threshold:300,grabbed:true,hook_contact:false};
  let state={hits:20,misses:1,throws:21,history:[...Array(20).fill(true),false],state:'COMPLETE',complete:true,best:20,longest_streak:20,can_undo:true};
  await page.setRequestInterception(true);
  page.on('request', request => {
   const path = new URL(request.url()).pathname;
   if(path==='/debug')debugCalls++;
   if(path.startsWith('/ota/')&&request.method()==='POST'){
    otaCalls.push({path,key:request.headers()['x-ota-key']});
    otaState={...otaState,available_version:'v2',update_status:path.endsWith('check')?'available':'downloading'};
   }
   if(request.method()==='POST'&&!path.startsWith('/ota/')) {
    calls.push(path);
    if(path==='/undo')state={...state,complete:false,state:'WAIT RELEASE',throws:20,misses:0,history:Array(20).fill(true)};
    if(path==='/reset')state={...state,complete:false,state:'WAIT RELEASE',throws:0,hits:0,history:[],can_undo:false};
   }
   request.respond({status:200,contentType:path==='/'?'text/html':'application/json',body:path==='/'?pageHtml:JSON.stringify(path==='/debug'?debugData:path.startsWith('/ota/')?otaState:state)});
  });
  await page.goto('http://ringthebull.test/');
  await page.waitForFunction(()=>document.getElementById('connection').textContent==='Live');
  assert.equal(await page.$eval('#rate', e=>e.textContent),'95.2%');
  for(const [width,height] of [[320,568],[360,640],[390,844]]){
   await page.setViewport({width,height,isMobile:true,deviceScaleFactor:2});
   const layout=await page.evaluate(()=>{
    const cells=[...document.querySelectorAll('.shot')];
    return {count:cells.length,rows:new Set(cells.map(e=>e.getBoundingClientRect().top)).size,
     columns:new Set(cells.map(e=>e.getBoundingClientRect().left)).size,
     mainBottom:document.getElementById('scores').getBoundingClientRect().bottom,
     controlsBottom:document.querySelector('.controls').getBoundingClientRect().bottom,
     overflow:document.documentElement.scrollWidth>innerWidth};
   });
   assert.equal(layout.count,21);assert.equal(layout.rows,3);assert.equal(layout.columns,7);
   assert.ok(layout.mainBottom<height);assert.ok(layout.controlsBottom<height);assert.equal(layout.overflow,false);
  }
  assert.equal(debugCalls,0);
  await page.click('#debugToggle');
  await page.waitForFunction(()=>document.getElementById('debugValues').textContent.includes('750 us'));
  await new Promise(resolve=>setTimeout(resolve,1050));
  assert.ok(debugCalls>=5&&debugCalls<=8,`debug requests ${debugCalls}`);
  assert.equal(await page.$eval('#debugToggle',e=>e.textContent),'Exit Debug');
  assert.match(await page.$eval('#debugValues',e=>e.textContent),/Grabbed: yes.*Hook contact.*no/);
  // Seed a full window to check bounded history and inspect all three traces.
  await page.evaluate(()=>{
   const now=performance.now();debugSamples.length=0;
   for(let i=0;i<300;i++)debugSamples.push({t:now-59800+i*200,raw:100+600*Math.max(0,Math.sin(i/12)),baseline:50,grab_threshold:500});
   drawSensorGraph();
  });
  await page.waitForFunction(()=>debugSamples.length<=300);
  await page.screenshot({path:'/tmp/ringthebull-debug-phone.png',fullPage:true});
  await page.setViewport({width:1280,height:900,isMobile:true,deviceScaleFactor:1});
  await page.screenshot({path:'/tmp/ringthebull-debug-desktop.png',fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.setViewport({width:390,height:844,isMobile:true,deviceScaleFactor:2});
  await page.evaluate(()=>{
   window.testHidden=true;
   Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.testHidden});
   document.dispatchEvent(new Event('visibilitychange'));
  });
  const paused=debugCalls;await new Promise(resolve=>setTimeout(resolve,500));
  assert.equal(debugCalls,paused,'hidden page must stop diagnostics');
  debugData={...debugData,raw:null,delta:null,grabbed:false,hook_contact:true};
  await page.evaluate(()=>{window.testHidden=false;document.dispatchEvent(new Event('visibilitychange'));});
  await page.waitForFunction(()=>document.getElementById('debugValues').textContent.includes('Raw: unavailable'));
  assert.match(await page.$eval('#debugValues',e=>e.textContent),/Grabbed: no.*Hook contact.*yes/);
  await page.click('#debugToggle');
  const closed=debugCalls;await new Promise(resolve=>setTimeout(resolve,500));
  assert.equal(debugCalls,closed,'closed panel must stop diagnostics');
  assert.equal(await page.$eval('#debugPanel',e=>e.hidden),true);
  assert.equal(await page.$eval('#hits',e=>e.textContent),'20');
  console.log('PASS diagnostics: 5 Hz, cached values, canvas, stop on close/hidden, resume');
  const decodeCanvas=async()=>{
   const image=await page.$eval('#qr', canvas=>({width:canvas.width,height:canvas.height,
    pixels:Array.from(canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data)}));
   return jsQR(new Uint8ClampedArray(image.pixels),image.width,image.height)?.data;
  };
  assert.equal(await decodeCanvas(),'http://ringthebull.test/');
  // Exercise all ten QR versions, including interleaved blocks and version bits.
  for(const length of [10,20,40,60,90,120,140,180,210,250]){
   const payload='http://'+ 'a'.repeat(length-8)+'/';
   await page.evaluate(url=>drawQR(url),payload);
   assert.equal(await decodeCanvas(),payload,`QR payload length ${length}`);
  }
  await page.evaluate(()=>drawQR(location.origin+'/'));
  await page.screenshot({path:'/tmp/ringthebull-mobile.png'});
  await page.screenshot({path:'/tmp/ringthebull-pub-phone.png',fullPage:true});
  assert.match(await page.$eval('#weekly',e=>e.textContent),/synced clock/);
  assert.equal(await page.$eval('.records h2 small',e=>e.textContent),'All time');
  await page.setViewport({width:1280,height:900,deviceScaleFactor:1});
  const desktop=await page.evaluate(()=>({
   overflow:document.documentElement.scrollWidth>innerWidth,
   score:parseFloat(getComputedStyle(document.getElementById('hits')).fontSize),
   controls:document.querySelector('.controls').getBoundingClientRect().bottom,
   columns:getComputedStyle(document.querySelector('.lower')).gridTemplateColumns.split(' ').length
  }));
  assert.equal(desktop.overflow,false);assert.ok(desktop.score>=144);
  assert.ok(desktop.controls<900);assert.equal(desktop.columns,2);
  await page.focus('#reset');
  assert.equal(await page.$eval('#reset',e=>getComputedStyle(e).outlineStyle),'solid');
  await page.screenshot({path:'/tmp/ringthebull-pub-desktop.png',fullPage:true});
  await page.setViewport({width:390,height:844,isMobile:true,deviceScaleFactor:2});
  assert.equal(await page.$$eval('.shot.hit',els=>els.length),20);
  assert.equal(await page.$$eval('.shot.miss',els=>els.length),1);
  assert.equal(await page.$eval('#left',e=>e.textContent),'0');

  await page.evaluate(()=>Object.defineProperty(navigator,'share',{configurable:true,value:async data=>{window.shared=data.text;}}));
  await page.click('#share');
  const text=await page.evaluate(()=>window.shared);
  assert.equal(text, 'Ring the Bull: 20/21\n\n'+'🟩'.repeat(7)+'\n'+'🟩'.repeat(7)+'\n'+'🟩'.repeat(6)+'🟥\n\nhttp://ringthebull.test/');
  await page.evaluate(()=>{
   Object.defineProperty(navigator,'share',{configurable:true,value:undefined});
   Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copied=text;}}});
  });
  await page.click('#share');
  assert.equal(await page.evaluate(()=>window.copied),text);
  await page.evaluate(()=>{
   Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined});
   document.execCommand=()=>false;
   window.prompt=(label,text)=>{window.manualCopy=text;};
  });
  await page.click('#share');
  assert.equal(await page.evaluate(()=>window.manualCopy),text);
  await page.evaluate(()=>window.confirm=()=>false);
  await page.click('#reset');
  assert.deepEqual(calls,[]);
  await page.click('#undo');
  await page.waitForFunction(()=>document.getElementById('throws').textContent==='20');
  assert.equal(await page.$eval('#share',e=>e.disabled),true);
  assert.equal(await page.$eval('#left',e=>e.textContent),'1');
  assert.equal(await page.$$eval('.shot.pending',els=>els.length),1);
  await page.evaluate(()=>window.confirm=()=>true);
  await page.click('#reset');
  await page.waitForFunction(()=>document.getElementById('throws').textContent==='0');
  assert.deepEqual(calls,['/undo','/reset']);
  assert.equal(await page.$$eval('.shot.pending',els=>els.length),21);
  assert.equal(await page.$eval('#left',e=>e.textContent),'21');
  state={...state,last_completed:{hits:20,misses:1,throws:21,history:[...Array(20).fill(true),false]}};
  await page.waitForFunction(()=>document.getElementById('share').textContent==='Share last game');
  await page.click('#share');
  assert.equal(await page.evaluate(()=>window.manualCopy),text);
  assert.equal(await page.$eval('#throws',e=>e.textContent),'0');
  await page.evaluate(()=>{document.getElementById('updates').open=true;window.prompt=()=> 'test-update-key';window.confirm=()=>true;});
  await page.click('#updateCheck');
  await page.waitForFunction(()=>document.getElementById('updateInfo').textContent.includes('Available: v2'));
  assert.match(await page.$eval('#updateInfo',e=>e.textContent),/BENCH: sensors disconnected/);
  await page.click('#updateInstall');
  await page.waitForFunction(()=>document.getElementById('updateInfo').textContent.includes('downloading'));
  assert.deepEqual(otaCalls.map(c=>c.path),['/ota/check','/ota/install']);
  assert.ok(otaCalls.every(c=>c.key==='test-update-key'));
  assert.equal(await page.evaluate(()=>localStorage.length),0);
  console.log('PASS OTA UI: installed/available versions, authenticated check/install, no key in storage');
  console.log('PASS mobile UI: 7x3 grid, phone layouts, QR, sharing last game after rollover/reset');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
