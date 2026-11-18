/* Exercise registered modes through their rendered controls, with a deterministic clock.
   Only the browser DOM, animation/timer scheduler and xterm output boundary are faked. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

function fixture(mode,{demo=false,cmd='ab',reduced=false}={}) {
  const nodes=new Map();
  class Element {
    constructor(tag='div') {this.tagName=tag;this.children=[];this.hidden=false;this.style={};this.dataset={};this.value='';this.textContent='';this.classList={add(){},remove(){}};}
    setAttribute(k,v) {this[k]=String(v);if(k==='id')nodes.set(v,this);}
    append(...ns) {this.children.push(...ns);}
    appendChild(n) {this.append(n);return n;}
    set innerHTML(v) {this.children=[];this.html=v;}
    get innerHTML() {return this.html||'';}
    remove() {nodes.delete(this.id);}
  }
  for(const id of ['list','example','title','terminal-status','extra','slider','stepinfo','paneltitle','output','panel','simcmd','simhint','edit','reset','play','next','setupbox','figures','code','simterm','simbar','pagelink','editor']) {
    const n=new Element();n.setAttribute('id',id);
  }
  const controls=new Element(),cols=new Element();
  let now=0,next=0,modeAPI,raf=new Map(),timers=new Map(),output='',onIntersect;
  class Terminal {
    constructor() {this.options={};}
    open() {} dispose() {} reset() {output='';} write(s) {output+=s;}
  }
  const document={getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),
    querySelector:s=>s.includes('.controls')?controls:cols,querySelectorAll:()=>[],
    body:{dataset:{},classList:{add(){}}},documentElement:{dataset:{}}};
  const window={Terminal,CVIZ_VIEWER:{esc:s=>String(s)},addEventListener(){},
    matchMedia:()=>({matches:reduced,addEventListener(){},removeEventListener(){}}),
    CVIZ_MODES:{register:(name,api)=>{assert.equal(name,mode);modeAPI=api;}}};
  const context={window,document,location:{search:''},URLSearchParams,performance:{now:()=>now},
    requestAnimationFrame:fn=>{raf.set(++next,fn);return next;},cancelAnimationFrame:id=>raf.delete(id),
    setTimeout:(fn,ms)=>{timers.set(++next,{fn,at:now+ms});return next;},clearTimeout:id=>timers.delete(id),
    IntersectionObserver:class {constructor(fn) {onIntersect=fn;} observe() {} disconnect() {}},
    fetch:async()=>({ok:true,text:async()=>[{version:2,duration:20},[1,'o','recorded \x1b[32moutput\x1b[0m'],[2,'m','Raw marker']].map(x=>JSON.stringify(x)).join('\n')})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,`../viewer/mode-${mode}.js`),'utf8'),context);
  const sess={title:'Playback fixture',demo,markers:[{step:0,title:'First',note:'Start here'}],steps:[{cmd,cast:[[0.2,'first'],[0.7,'second']],output:'firstsecond',exit:0,state:{}}]};
  return {api:modeAPI,el:id=>nodes.get(id),output:()=>output,
    enterViewport:()=>onIntersect?.([{isIntersecting:true}]),
    show:()=>modeAPI.show({id:'fixture',meta:{},params:new URLSearchParams(),fetchJson:async()=>sess}),
    frame(ms) {now+=ms;const batch=[...raf.values()];raf.clear();batch.forEach(fn=>fn(now));},
    async advance(ms) {
      const end=now+ms;
      for(;;) {
        const due=[...timers].filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
        if(!due)break;
        now=due[1].at;timers.delete(due[0]);due[1].fn();
        for(let i=0;i<5;i++)await Promise.resolve();
      }
      now=end;for(let i=0;i<5;i++)await Promise.resolve();
    }};
}

const rates=[0.1,0.25,0.5,0.75,1,2,4,16];
function select(n,value) {n.value=value;n.onchange();}
function end(f) {return Number(f.el('terminal-seek').max);}
test('Terminal demos stay paused in view until Play is pressed',async()=>{
  const f=fixture('terminal',{demo:true});await f.show();
  f.enterViewport();f.frame(500);assert.equal(f.api.pos(),0);
  const play=f.el('terminal-play');assert.equal(play.textContent,'Play');
  play.onclick();f.frame(500);assert.equal(f.api.pos(),0.5);assert.equal(play.textContent,'Pause');
  play.onclick();f.frame(500);assert.equal(f.api.pos(),0.5);
});
test('Terminal demos reveal whole lines, with a small per-line premium, without replacing the transcript',async()=>{
  const f=fixture('terminal',{demo:true,cmd:'ab\r\ncd'});await f.show();
  const pacing=f.el('terminal-pacing'),screen=f.el('terminal-screen'),lineDuration=end(f);
  assert.equal(pacing?.value,'line');
  assert.equal(screen.textContent,'$ ');
  f.api.go(0.2);assert.equal(screen.textContent,'$ ab\n');
  f.api.go(0.3);assert.equal(screen.textContent,'$ ab\ncd');
  select(pacing,'character');
  f.api.go(0.05);assert.equal(screen.textContent,'$ a');
  assert(Math.abs(lineDuration-end(f)-0.18)<=0.002);
  f.api.go(end(f));assert.equal(screen.textContent,'$ ab\ncd\nfirstsecond\n');
  assert.equal(f.el('terminal-note').textContent,'Start here');
  assert.equal(f.el('terminal-transcript').textContent,'recorded output');
});
test('Terminal does not retime a raw cast, and Instant completes playback',async()=>{
  const f=fixture('terminal');await f.show();
  assert.equal(f.el('terminal-pacing'),undefined);
  f.api.go(0.99);assert.equal(f.el('terminal-screen').textContent,'');
  f.api.go(1);assert.equal(f.el('terminal-screen').textContent,'recorded output');
  f.api.go(2);assert.equal(f.el('terminal-note').textContent,'Start here');
  select(f.el('terminal-speed'),'0');f.api.go('+1');assert.equal(f.api.pos(),20);
});
test('Terminal reduced motion stays at the end when command pacing changes',async()=>{
  const f=fixture('terminal',{demo:true,reduced:true});await f.show();
  assert(f.el('terminal-play').disabled);assert.equal(f.api.pos(),end(f));
  assert.equal(f.el('terminal-pacing')?.value,'line');
  select(f.el('terminal-pacing'),'character');assert.equal(f.api.pos(),end(f));
  assert.equal(f.el('terminal-screen').textContent,'$ ab\nfirstsecond\n');
});
test('Terminal offers fractional speeds and retains the default and faster choices',async()=>{
  const f=fixture('terminal');await f.show();
  assert.deepEqual(f.el('terminal-speed').children.map(n=>Number(n.value)),[...rates,0]);
  assert.equal(Number(f.el('terminal-speed').value),1);
});
for(const rate of rates) test(`Terminal ${rate}x selection scales elapsed playback and preserves pause, resume and seek`,async()=>{
  const f=fixture('terminal');await f.show();const select=f.el('terminal-speed');
  assert(select.children.some(n=>Number(n.value)===rate),`missing selectable ${rate}x`);
  select.value=String(rate);select.onchange();f.el('terminal-play').onclick();f.frame(1000);
  assert.equal(f.api.pos(),rate);
  f.el('terminal-play').onclick();f.frame(5000);assert.equal(f.api.pos(),rate);
  f.el('terminal-play').onclick();f.frame(100);assert(Math.abs(f.api.pos()-rate*1.1)<1e-10);
  f.el('terminal-seek').value='1';f.el('terminal-seek').oninput();f.frame(5000);assert.equal(f.api.pos(),1);
  f.el('terminal-play').onclick();f.frame(100);assert(Math.abs(f.api.pos()-(1+rate*0.1))<1e-10);
  select.value='0.5';select.onchange();f.frame(200);assert(Math.abs(f.api.pos()-(1+rate*0.1+0.1))<1e-10);
  f.api.go(20);assert.equal(f.el('terminal-status').textContent,'Playback complete');
  f.el('terminal-play').onclick();f.frame(1000);assert.equal(f.api.pos(),0.5);
});

function speedButton(f,label) {const b=f.el('extra').children.find(n=>n.textContent===label);assert(b,`missing ${label} speed control`);return b;}
test('Simulate opens idle with an explicit Next command control',async()=>{
  const f=fixture('simulate');await f.show();await f.advance(2000);
  assert.equal(f.api.pos(),-1);assert(!f.output().includes('ab'));
  assert.equal(f.el('next').textContent,'Next command');
  f.api.go('+1');assert.equal(f.el('next').textContent,'Finish command');
  f.api.go('+1');assert.equal(f.el('next').textContent,'Next command');assert.equal(f.api.pos(),0);
});
test('Simulate retains default 1x and offers clearly labeled Slow alongside fast and instant',async()=>{
  const f=fixture('simulate');await f.show();
  assert.deepEqual(f.el('extra').children.slice(0,4).map(n=>n.textContent),['0.5x (Slow)','1x','fast','instant']);
  assert.equal(speedButton(f,'1x').className,'on');
});
for(const [label,factor] of [['0.5x (Slow)',0.5],['1x',1],['fast',4]]) test(`Simulate ${label} paces typed command and recorded output`,async()=>{
  const f=fixture('simulate');await f.show();speedButton(f,label).onclick();select(f.el('simulate-pacing'),'character');
  assert.equal(speedButton(f,label).className,'on');f.api.go('+1');
  assert(f.output().endsWith('a'));await f.advance(35/factor-0.01);assert(!f.output().endsWith('ab'));
  await f.advance(0.01);assert(f.output().endsWith('ab'));
  await f.advance((35+200)/factor-0.01);assert(!f.output().includes('first'));
  await f.advance(0.01);assert(f.output().includes('first'));assert.equal(f.api.pos(),-1);
  await f.advance(500/factor);assert(f.output().includes('second'));assert.equal(f.api.pos(),0);
});
for(const [label,factor] of [['0.5x (Slow)',0.5],['1x',1],['fast',4]]) test(`Simulate ${label} reveals whole lines and scales the per-line premium`,async()=>{
  const f=fixture('simulate',{cmd:'ab\r\ncd'});await f.show();speedButton(f,label).onclick();
  assert.equal(f.el('simulate-pacing')?.value,'line');
  f.api.go('+1');assert(f.output().endsWith('ab\r\n'));
  await f.advance(230/factor-0.01);assert(f.output().endsWith('ab\r\n'));
  await f.advance(0.01);assert(f.output().endsWith('ab\r\ncd'));
  await f.advance(360/factor-0.01);assert(!f.output().includes('first'));
  await f.advance(0.02);assert(f.output().endsWith('ab\r\ncd\r\nfirst'));
  await f.advance(500/factor);assert.equal(f.api.pos(),0);
  const animated=f.output();f.api.go('-1');speedButton(f,'instant').onclick();f.api.go('+1');
  assert.equal(f.output(),animated,'animation preserves command and output bytes');
});
test('Simulate reduced motion completes without animated input or output',async()=>{
  const f=fixture('simulate',{reduced:true});await f.show();f.api.go('+1');
  assert.equal(f.api.pos(),0);assert(f.output().includes('ab\r\nfirstsecond'));
});
test('Simulate Slow preserves Next-to-finish, Back, seek, cancellation and next-command speed semantics',async()=>{
  const f=fixture('simulate');await f.show();speedButton(f,'0.5x (Slow)').onclick();select(f.el('simulate-pacing'),'character');f.api.go('+1');
  speedButton(f,'instant').onclick();await f.advance(70);assert(f.output().endsWith('ab'),'changing speed does not interrupt current command');
  f.api.go('+1');assert.equal(f.api.pos(),0);const finished=f.output();await f.advance(2000);assert.equal(f.output(),finished);
  f.api.go('-1');assert.equal(f.api.pos(),-1);f.api.go('+1');assert.equal(f.api.pos(),0,'instant takes effect on next command');
  f.api.go('0');speedButton(f,'0.5x (Slow)').onclick();f.api.go('+1');f.api.go('0');const before=f.output();
  await f.advance(2000);assert.equal(f.output(),before);assert.equal(f.api.pos(),-1);
  f.api.go('+1');f.api.hide();const hidden=f.output();await f.advance(2000);assert.equal(f.output(),hidden);
});
