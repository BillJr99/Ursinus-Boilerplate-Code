/* Terminal: local asciicast v2 playback. No shell commands execute in the browser.
   Supports line-oriented output, SGR removal, CR and backspace, not cursor-addressed TUIs.
   The selectable transcript is always available when clipboard access is unavailable. */
(function () {
  'use strict';
  const el = id => document.getElementById(id);
  const S = {id:null,time:0,duration:0,playing:false,speed:1,frame:0,events:[],markers:[],sess:null,epoch:0};
  let saved=[];
  function plain(raw) {
    raw=raw.replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g,'').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'');
    const lines=['']; let row=0,col=0;
    for(const c of raw) {
      if(c==='\n') {row++;lines[row]='';col=0;}
      else if(c==='\r') col=0;
      else if(c==='\b') col=Math.max(0,col-1);
      else if(c==='\t') {const n=8-col%8;lines[row]+=' '.repeat(n);col+=n;}
      else if(c>=' ') {const line=lines[row];lines[row]=line.slice(0,col).padEnd(col,' ')+c+line.slice(col+1);col++;}
    }
    return lines.join('\n');
  }
  function pause() {S.playing=false;cancelAnimationFrame(S.frame);if(el('terminal-play')) el('terminal-play').textContent='Play';}
  function draw() {
    if(!el('terminal-player')) return;
    el('terminal-screen').textContent=plain(S.events.filter(e=>e[1]==='o'&&e[0]<=S.time).map(e=>e[2]).join(''));
    el('terminal-screen').scrollTop=el('terminal-screen').scrollHeight;
    el('terminal-seek').value=S.time;
    el('terminal-status').textContent=S.time>=S.duration?'Recording complete':'Recorded output';
    let active=-1;
    S.markers.forEach((m,i)=>{if(m.at<=S.time) active=i;});
    el('terminal-note').textContent=active>=0?S.markers[active].note:S.sess.description||'';
    document.querySelectorAll('.terminal-marker').forEach((b,i)=>{b.setAttribute('aria-current',String(i===active));});
  }
  function seek(t) {pause();S.time=Math.max(0,Math.min(Number(t)||0,S.duration));draw();}
  function play() {
    if(S.playing) return pause();
    if(S.time>=S.duration) S.time=0;
    S.playing=true;el('terminal-play').textContent='Pause';S.epoch=performance.now();
    const tick=now=>{
      if(!S.playing) return;
      S.time=Math.min(S.duration,S.time+(now-S.epoch)/1000*S.speed);S.epoch=now;draw();
      if(S.time>=S.duration) pause();else S.frame=requestAnimationFrame(tick);
    };
    S.frame=requestAnimationFrame(tick);
  }
  function node(tag,attrs={},text='') {
    const n=document.createElement(tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);n.textContent=text;return n;
  }
  async function show(ctx) {
    pause(); const epoch=++S.loadEpoch;
    const [sess,response]=await Promise.all([ctx.fetchJson('sessions/'+encodeURIComponent(ctx.id)+'.json.gz'),fetch('terminals/'+encodeURIComponent(ctx.id)+'.cast')]);
    if(!response.ok) throw new Error('Terminal recording missing');
    const rows=(await response.text()).trim().split('\n').map(x=>JSON.parse(x)),header=rows.shift();
    if(header.version!==2||!rows.every(e=>Array.isArray(e)&&e.length===3&&Number.isFinite(e[0])&&e[0]>=0&&typeof e[2]==='string')) throw new Error('Invalid asciicast v2 recording');
    if(epoch!==S.loadEpoch) return;
    S.id=ctx.id;S.sess=sess;S.events=rows;
    S.duration=Math.max(Number(header.duration)||0,...rows.map(e=>e[0]));
    const castMarkers=rows.filter(e=>e[1]==='m');
    S.markers=(sess.markers||[]).slice().sort((a,b)=>a.step-b.step).map((m,i)=>({...m,at:castMarkers[i]?castMarkers[i][0]:0}));
    S.time=Math.min(S.duration,Math.max(0,ctx.pos||0));
    el('list').hidden=true;el('example').hidden=false;el('title').textContent=sess.title||ctx.id;
    saved=[];
    for(const selector of ['#example > .controls','#example > .cols']) {
      const n=document.querySelector(selector);saved.push([n,n.hidden]);n.hidden=true;
    }
    const panel=node('div',{id:'terminal-player'}),bar=node('div',{class:'terminal-controls'});
    const toggle=node('button',{id:'terminal-play',type:'button'},'Play');toggle.onclick=play;bar.append(toggle);
    const label=node('label',{},'Speed '),speed=node('select',{id:'terminal-speed','aria-label':'Playback speed'});
    [1,2,4,16].forEach(n=>speed.append(node('option',{value:n},n+'x')));speed.value=S.speed;
    speed.onchange=()=>{S.speed=Number(speed.value);S.epoch=performance.now();};label.append(speed);bar.append(label);
    const theme=node('select',{id:'terminal-theme','aria-label':'Terminal theme'});
    ['system','light','dark'].forEach(x=>theme.append(node('option',{value:x},x)));
    theme.onchange=()=>{if(theme.value==='system')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=theme.value;};bar.append(theme);
    const copy=node('button',{id:'terminal-copy',type:'button'},'Copy transcript');
    copy.onclick=async()=>{try{await navigator.clipboard.writeText(el('terminal-transcript').textContent);copy.textContent='Copied';}catch(e){el('terminal-transcript-details').open=true;const range=document.createRange();range.selectNodeContents(el('terminal-transcript'));const selection=getSelection();selection.removeAllRanges();selection.addRange(range);copy.textContent='Select and copy transcript';}};bar.append(copy);
    const seekbar=node('input',{id:'terminal-seek',type:'range',min:0,max:S.duration,step:'0.001',value:S.time,'aria-label':'Recording position'});seekbar.oninput=()=>seek(seekbar.value);bar.append(seekbar);
    bar.append(node('span',{id:'terminal-status','aria-live':'polite'}));panel.append(bar);
    panel.append(node('pre',{id:'terminal-screen',tabindex:0,'aria-label':'Recorded terminal output'}));
    const notes=node('div',{class:'terminal-notes'}),markers=node('div',{class:'terminal-markers','aria-label':'Recording markers'});
    S.markers.forEach(m=>{const b=node('button',{class:'terminal-marker',type:'button'},m.title);b.onclick=()=>seek(m.at);markers.append(b);});notes.append(markers,node('p',{id:'terminal-note','aria-live':'polite'}));panel.append(notes);
    const details=node('details',{id:'terminal-transcript-details'});details.append(node('summary',{},'Selectable transcript'),node('pre',{id:'terminal-transcript',tabindex:0},plain(rows.filter(e=>e[1]==='o').map(e=>e[2]).join(''))));panel.append(details);
    el('example').append(panel);draw();
  }
  S.loadEpoch=0;
  window.CVIZ_MODES.register('terminal',{
    label:'Terminal',show,
    go(to){if(to==='+1')play();else if(to==='-1')seek(S.time-5);else seek(to);},
    pos(){return S.time;},url(){return {s:Math.round(S.time*1000)/1000};},
    hide(){pause();S.loadEpoch++;const n=el('terminal-player');if(n)n.remove();saved.forEach(([n,h])=>{n.hidden=h;});saved=[];}
  });
  if(new URLSearchParams(location.search).has('embed'))document.body.classList.add('terminal-embed');
})();
