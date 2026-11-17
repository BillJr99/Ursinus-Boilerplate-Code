/* Exercise registered modes through their rendered controls, with a deterministic clock.
   Only the browser DOM, animation/timer scheduler and xterm output boundary are faked. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

function fixture(mode) {
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
  for(const id of ['list','example','title','terminal-status','extra','slider','stepinfo','paneltitle','output','panel','simcmd','simhint','edit','reset','play','setupbox','figures','code','simterm','simbar','pagelink','editor']) {
    const n=new Element();n.setAttribute('id',id);
  }
  const controls=new Element(),cols=new Element();
  let now=0,next=0,modeAPI,raf=new Map(),timers=new Map(),output='';
  class Terminal {
    constructor() {this.options={};}
    open() {} dispose() {} reset() {output='';} write(s) {output+=s;}
  }
  const document={getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),
    querySelector:s=>s.includes('.controls')?controls:cols,querySelectorAll:()=>[],
    body:{dataset:{},classList:{add(){}}},documentElement:{dataset:{}}};
  const window={Terminal,CVIZ_VIEWER:{esc:s=>String(s)},addEventListener(){},
    matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){}}),
    CVIZ_MODES:{register:(name,api)=>{assert.equal(name,mode);modeAPI=api;}}};
  const context={window,document,location:{search:''},URLSearchParams,performance:{now:()=>now},
    requestAnimationFrame:fn=>{raf.set(++next,fn);return next;},cancelAnimationFrame:id=>raf.delete(id),
    setTimeout:(fn,ms)=>{timers.set(++next,{fn,at:now+ms});return next;},clearTimeout:id=>timers.delete(id),
    fetch:async()=>({ok:true,text:async()=>JSON.stringify({version:2,duration:20})+'\n'+JSON.stringify([1,'o','recorded output'])})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,`../viewer/mode-${mode}.js`),'utf8'),context);
  const sess={title:'Synthetic playback fixture',steps:[{cmd:'ab',cast:[[0.2,'first'],[0.7,'second']],output:'firstsecond',exit:0,state:{}}]};
  return {api:modeAPI,el:id=>nodes.get(id),output:()=>output,
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
test('Terminal offers fractional speeds and retains the default and faster choices',async()=>{
  const f=fixture('terminal');await f.show();
  assert.deepEqual(f.el('terminal-speed').children.map(n=>Number(n.value)),rates);
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
test('Simulate retains default 1x and offers clearly labeled Slow alongside fast and instant',async()=>{
  const f=fixture('simulate');await f.show();
  assert.deepEqual(f.el('extra').children.map(n=>n.textContent),['0.5x (Slow)','1x','fast','instant']);
  assert.equal(speedButton(f,'1x').className,'on');
});
for(const [label,factor] of [['0.5x (Slow)',0.5],['1x',1],['fast',4]]) test(`Simulate ${label} paces typed command and recorded output`,async()=>{
  const f=fixture('simulate');await f.show();speedButton(f,label).onclick();
  assert.equal(speedButton(f,label).className,'on');f.api.go('+1');
  assert(f.output().endsWith('a'));await f.advance(35/factor-0.01);assert(!f.output().endsWith('ab'));
  await f.advance(0.01);assert(f.output().endsWith('ab'));
  await f.advance((35+200)/factor-0.01);assert(!f.output().includes('first'));
  await f.advance(0.01);assert(f.output().includes('first'));assert.equal(f.api.pos(),-1);
  await f.advance(500/factor);assert(f.output().includes('second'));assert.equal(f.api.pos(),0);
});
test('Simulate Slow preserves Next-to-finish, Back, seek, cancellation and next-command speed semantics',async()=>{
  const f=fixture('simulate');await f.show();speedButton(f,'0.5x (Slow)').onclick();f.api.go('+1');
  speedButton(f,'instant').onclick();await f.advance(70);assert(f.output().endsWith('ab'),'changing speed does not interrupt current command');
  f.api.go('+1');assert.equal(f.api.pos(),0);const finished=f.output();await f.advance(2000);assert.equal(f.output(),finished);
  f.api.go('-1');assert.equal(f.api.pos(),-1);f.api.go('+1');assert.equal(f.api.pos(),0,'instant takes effect on next command');
  f.api.go('0');speedButton(f,'0.5x (Slow)').onclick();f.api.go('+1');f.api.go('0');const before=f.output();
  await f.advance(2000);assert.equal(f.output(),before);assert.equal(f.api.pos(),-1);
  f.api.go('+1');f.api.hide();const hidden=f.output();await f.advance(2000);assert.equal(f.output(),hidden);
});
