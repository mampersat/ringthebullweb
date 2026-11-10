// Offline browser checks for the separately served musical preview.
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const puppeteer=require('../scripts/node_modules/puppeteer-core');
(async()=>{
 const browser=await puppeteer.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setViewport({width:390,height:844,isMobile:true});
  await page.setContent(fs.readFileSync(path.join(__dirname,'../tools/soundboard_preview.html'),'utf8'));
  const base=[261.625565,391.995436,523.251131];
  for(let hit=1;hit<=12;hit++){
   await page.click('#hit');await page.waitForFunction(n=>step===n,{},hit);
   const result=await page.evaluate(()=>({
    hz:lastNote.hz,brass:voices.filter(v=>v.kind==='brass').length,
    drums:voices.filter(v=>v.kind!=='brass').map(v=>({kind:v.kind,pitch:v.pitch,offset:Math.round((v.at-voices[0].at)*100)/100}))
   }));
   if(hit%4){assert.equal(result.hz,base[(hit-1)%4]);assert.equal(result.brass,3);assert.equal(result.drums.length,0);}
   else{
    assert.equal(result.brass,12);assert.equal(result.drums.length,8);
    assert.deepEqual(result.drums,Array.from({length:8},(_,beat)=>({
     kind:'timpani',pitch:beat%2?48.999429:65.406391,offset:Math.round((.15+beat*.5)*100)/100
    })));
    assert.ok(result.drums.every(v=>v.pitch<70));
    await new Promise(r=>setTimeout(r,1100));
    const pitches=await page.evaluate(()=>[...new Set(voices.filter(v=>v.kind==='brass').map(v=>Math.round(v.osc.frequency.value*100)/100))]);
    assert.deepEqual(pitches,hit===4?[261.63,392,523.25,622.25]:hit===8?[261.63,392,523.25,659.26]:[261.63,440,523.25,698.46]);
   }
  }
  assert.equal(await page.$eval('#hit',e=>e.disabled),false);
  for(const [hit,expected,drumCount] of [
   [13,[174.61,261.63,440,698.46],8],
   [14,[196,293.66,493.88,783.99],0],
   [15,[130.81,261.63,392,659.26,1046.5],16]
  ]){
   await page.click('#hit');await page.waitForFunction(n=>step===n,{},hit);
   await new Promise(r=>setTimeout(r,60));
   const final=await page.evaluate(()=>({
    pitches:[...new Set(voices.filter(v=>v.kind==='brass').map(v=>Math.round(v.osc.frequency.value*100)/100))],
    drums:voices.filter(v=>v.kind==='timpani').map(v=>({pitch:v.pitch,offset:Math.round((v.at-voices[0].at)*100)/100}))
   }));
   assert.deepEqual(final.pitches,expected);assert.equal(final.drums.length,drumCount);
   if(hit===13)assert.deepEqual(final.drums.map(v=>v.offset),[2.4,2.9,3.4,3.9,4.4,4.9,5.4,5.9]);
   if(hit===15){
    assert.equal(final.drums[0].offset,.15);
    assert.deepEqual(final.drums.slice(-2),[{pitch:65.406391,offset:3.75},{pitch:130.812783,offset:3.75}]);
   }
  }
  assert.equal(await page.$eval('#hit',e=>e.disabled),true);
  await page.click('#restart');assert.deepEqual(await page.evaluate(()=>({step,voices:voices.length})),{step:0,voices:0});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(errors,[]);
  console.log('PASS 15-hit preview: first 12 unchanged; eight-hit regular fills, F/drums, G, triumphant C/timpani finale; restart cancels audio; mobile layout');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
