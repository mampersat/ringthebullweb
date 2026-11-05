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
  let state={hits:20,misses:1,throws:21,history:[...Array(20).fill(true),false],state:'COMPLETE',complete:true,best:20,longest_streak:20,can_undo:true};
  await page.setRequestInterception(true);
  page.on('request', request => {
   const path = new URL(request.url()).pathname;
   if(request.method()==='POST') {
    calls.push(path);
    if(path==='/undo')state={...state,complete:false,state:'WAIT RELEASE',throws:20,misses:0,history:Array(20).fill(true)};
    if(path==='/reset')state={...state,complete:false,state:'WAIT RELEASE',throws:0,hits:0,history:[],can_undo:false};
   }
   request.respond({status:200,contentType:path==='/'?'text/html':'application/json',body:path==='/'?pageHtml:JSON.stringify(state)});
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
  console.log('PASS mobile UI: 7x3 grid, phone layouts, QR, sharing last game after rollover/reset');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
