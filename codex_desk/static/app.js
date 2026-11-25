const $ = id => document.getElementById(id);
let state = {profiles: [], sessions: []}, selected = null, after = 0, items = new Map(), requests = new Map();
const nodes = new Map();
async function api(path, data) {
  const r = await fetch(path, data ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)} : {});
  const v = await r.json(); if (!r.ok) throw new Error(v.error || 'Request failed'); return v;
}
function error(e) { $('error').textContent = e.message; $('error').hidden = false; }
function make(tag, text, cls) { const node = document.createElement(tag); if(text) node.textContent=text; if(cls) node.className=cls; return node; }
function draw() {
  $('sessions').replaceChildren();
  for(const s of state.sessions) {
    const b = make('button', '', 'session' + (s.id===selected?' selected':''));
    b.append(make('strong', s.cwd.split(/[\\/]/).filter(Boolean).at(-1)), make('small', `${s.profile} · ${s.status}`));
    b.onclick=()=>open(s.id); $('sessions').append(b);
  }
  const s = state.sessions.find(s=>s.id===selected); if(!s) return;
  $('title').textContent=s.cwd.split(/[\\/]/).filter(Boolean).at(-1);
  $('binding').textContent=`${s.cwd}\n${s.profile} → ${s.provider || 'loading'} / ${s.model || 'native default'}`;
  $('status').textContent=s.status; $('send').disabled=['running','approval','starting'].includes(s.status);
  $('stop').disabled=!['running','approval'].includes(s.status);
  if(s.usage) {
    const u=JSON.parse(s.usage), t=u.total || u;
    $('usage').textContent=`Thread usage · input ${(t.inputTokens || 0).toLocaleString()} (cached ${(t.cachedInputTokens || 0).toLocaleString()}) · output ${(t.outputTokens || 0).toLocaleString()} · latest native cumulative total`;
  } else $('usage').textContent='Usage appears after native Codex reports it.';
  if(s.error && s.status==='failed') error(new Error(s.error));
}
function itemText(i) {
  switch(i.type) {
    case 'userMessage':return (i.content || []).map(c=>c.text || '').join('\n');
    case 'agentMessage':return i.text || '';
    case 'commandExecution':return `$ ${i.command || ''}\n${i.aggregatedOutput || ''}${i.exitCode == null ? '' : '\nExit '+i.exitCode}`;
    case 'fileChange':return (i.changes || []).map(c=>`${c.kind?.type || 'change'} ${c.path}\n${c.diff || ''}`).join('\n');
    case 'reasoning':return [...(i.summary || []), ...(i.content || [])].join('\n');
    default:return i.text || JSON.stringify(i, null, 2);
  }
}
function renderItem(i) {
  items.set(i.id, i); let node=nodes.get(i.id);
  if(!node) {node=make('div', '', 'item '+i.type);nodes.set(i.id,node);$('activity').append(node);}
  node.textContent=itemText(i);
}
function approvals() {
  $('approvals').replaceChildren();
  for(const [id,m] of requests) {
    const p=m.params || {}, box=make('div',`${m.method}\n${p.command || p.reason || 'Native Codex needs your input.'}`, 'approval');
    if(['item/commandExecution/requestApproval','item/fileChange/requestApproval'].includes(m.method)) {
      const buttons=make('div','','actions');
      for(const [label,decision] of [['Allow once','accept'],['Decline','decline']]) {
        const b=make('button',label); b.onclick=async()=>{try{await api('/api/approval',{session:selected,request:id,decision});requests.delete(id);approvals();}catch(e){error(e)}};buttons.append(b);
      } box.append(buttons);
    } else box.append(make('p','Use Stop turn for this interaction; a dedicated UI is not implemented yet.'));
    $('approvals').append(box);
  }
}
function consume(m) {
  const p=m.params || {};
  if(m.id !== undefined && m.method) {requests.set(String(m.id),m);approvals();}
  if(m.method==='serverRequest/resolved') {requests.delete(String(p.requestId));approvals();}
  if(m.method==='item/started' || m.method==='item/completed') renderItem(p.item);
  if(m.method==='item/agentMessage/delta') {
    const i=items.get(p.itemId) || {id:p.itemId,type:'agentMessage',text:''};i.text+=p.delta || '';renderItem(i);
  }
  if(m.method==='item/commandExecution/outputDelta') {
    const i=items.get(p.itemId) || {id:p.itemId,type:'commandExecution',aggregatedOutput:''};i.aggregatedOutput=(i.aggregatedOutput || '')+(p.delta || '');renderItem(i);
  }
  if(m.method==='error') {const n=make('div',p.error?.message || JSON.stringify(p),'item');$('activity').append(n);}
}
async function refresh() {state=await api('/api/state');requests=new Map((state.pending?.[selected] || []).map(m=>[String(m.id),m]));approvals();draw();}
async function open(id) {
  try {
    $('error').hidden=true; await api('/api/open',{session:id});
    selected=id;localStorage.setItem('codex-desk-session',id);after=0;items.clear();nodes.clear();requests.clear();
    $('activity').replaceChildren();$('welcome').hidden=true;$('task').hidden=false;await refresh();
  } catch(e) {error(e);}
}
function profileInfo() {
  const p=state.profiles.find(p=>p.id===$('profile').value);
  $('profile-info').textContent=p?`${p.provider || 'Current default'} / ${p.model || 'Configured model'}${p.endpoint?' · '+p.endpoint:''}`:'';
}
$('new').onclick=()=>{ $('profile').replaceChildren(...state.profiles.map(p=>{const n=make('option',p.name);n.value=p.id;return n;}));profileInfo();$('project').showModal();};
$('profile').onchange=profileInfo;$('cancel').onclick=()=>$('project').close();
$('create').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{const r=await api('/api/sessions',{cwd:$('cwd').value,profile:$('profile').value});$('project').close();await open(r.id);}catch(err){$('project').close();error(err);}finally{b.disabled=false;}};
$('task').onsubmit=async e=>{e.preventDefault();$('error').hidden=true;try{await api('/api/turn',{session:selected,text:$('prompt').value});$('prompt').value='';await refresh();}catch(err){error(err);}};
$('stop').onclick=async()=>{try{await api('/api/stop',{session:selected});requests.clear();approvals();await refresh();}catch(e){error(e);}};
let failures=0;
async function tick(){try{if(selected){const rows=await api(`/api/events?session=${selected}&after=${after}`);for(const r of rows){after=r.seq;consume(r.event);} if(rows.length)await refresh();}failures=0;}catch(e){if(++failures===1)error(new Error('Codex Desk disconnected. Restart it and reopen this session.'));}finally{setTimeout(tick,failures?3000:800)}};
(async()=>{try{await refresh();const last=localStorage.getItem('codex-desk-session');if(state.sessions.some(s=>s.id===last))await open(last);tick();}catch(e){error(e)}})();
