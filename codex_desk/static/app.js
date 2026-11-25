const $ = id => document.getElementById(id);
let state = {profiles: [], sessions: []}, selected = null, after = 0, items = new Map(), requests = new Map();
const nodes = new Map();
let modeSelected=null, generation=0;
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
    b.title=s.cwd;
    b.append(make('strong', s.name || s.cwd.split(/[\\/]/).filter(Boolean).at(-1)), make('small', `${s.cwd.split(/[\\/]/).filter(Boolean).at(-1) || s.cwd} · ${s.profile} · ${s.status}`));
    b.onclick=()=>open(s.id); $('sessions').append(b);
  }
  const s = state.sessions.find(s=>s.id===selected); if(!s) return;
  $('title').textContent=s.name || s.cwd.split(/[\\/]/).filter(Boolean).at(-1);$('rename').hidden=false;
  $('binding').textContent=`${s.cwd}\n${s.profile} → ${s.provider || 'loading'} / ${s.model || 'native default'}`;
  if(modeSelected!==selected){$('turn-mode').value=s.mode || 'native';modeSelected=selected;}
  $('turn-mode').disabled=['running','approval','starting'].includes(s.status);
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
    case 'reasoning':return (i.summary || []).join('\n');
    default:return i.text || JSON.stringify(i, null, 2);
  }
}
function renderItem(i) {
  items.set(i.id, i); let node=nodes.get(i.id);
  if(!node) {node=make('div', '', 'item '+i.type);nodes.set(i.id,node);$('activity').append(node);}
  node.textContent=itemText(i);
}
let approvalsSignature='';
function approvals() {
  const signature=JSON.stringify([selected,[...requests]]);
  if(signature===approvalsSignature)return;
  approvalsSignature=signature;
  $('approvals').replaceChildren();
  for(const [id,m] of requests) {
    const p=m.params || {}, box=make('div',`${m.method}\n${p.command || p.reason || 'Native Codex needs your input.'}`, 'approval');
    if(['item/commandExecution/requestApproval','item/fileChange/requestApproval'].includes(m.method)) {
      const buttons=make('div','','actions');
      for(const [label,decision] of [['Allow once','accept'],['Decline','decline']]) {
        const b=make('button',label); b.onclick=async()=>{try{await api('/api/approval',{session:selected,request:id,decision});requests.delete(id);approvals();}catch(e){error(e)}};buttons.append(b);
      } box.append(buttons);
    } else if(m.method==='item/tool/requestUserInput') {
      const form=make('form'), fields=new Map();
      for(const q of p.questions || []) {
        const label=make('label',q.header+' — '+q.question);
        const input=make(q.options?.length && !q.isOther?'select':'input');
        if(input.tagName==='SELECT') for(const o of q.options) {const option=make('option',o.label+' — '+o.description);option.value=o.label;input.append(option);}
        else {input.type=q.isSecret?'password':'text';input.required=true;input.autocomplete='off';if(q.options?.length)input.placeholder=q.options.map(o=>o.label).join(' / ');}
        label.append(input);form.append(label);fields.set(q.id,input);
      }
      const submit=make('button','Send answers');form.append(submit);
      form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{const answers=Object.fromEntries([...fields].map(([id,input])=>[id,[input.value]]));await api('/api/answer',{session:selected,request:id,answers});requests.delete(id);approvals();await refresh();}catch(e){error(e);submit.disabled=false;}};
      box.append(form);
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
    $('error').hidden=true; const opened=await api('/api/open',{session:id});
    selected=id;modeSelected=null;generation++;$('task').hidden=true;localStorage.setItem('codex-desk-session',id);after=0;items.clear();nodes.clear();requests.clear();
    $('activity').replaceChildren();for(const t of opened.thread.turns || [])for(const i of t.items || [])renderItem(i);$('welcome').hidden=true;await refresh();$('task').hidden=false;$('handoff').hidden=false;
  } catch(e) {error(e);}
}
function profileInfo() {
  const p=state.profiles.find(p=>p.id===$('profile').value);
  $('profile-info').textContent=p?`${p.provider || 'Current default'} / ${p.model || 'Configured model'}${p.endpoint?' · '+p.endpoint:''}`:'';
}
$('new').onclick=()=>{ $('profile').replaceChildren(...state.profiles.map(p=>{const n=make('option',p.name);n.value=p.id;return n;}));profileInfo();$('project').showModal();};
$('profile').onchange=profileInfo;$('cancel').onclick=()=>$('project').close();
$('create').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{const r=await api('/api/sessions',{cwd:$('cwd').value,profile:$('profile').value,name:$('session-name').value.trim() || null});$('project').close();await open(r.id);}catch(err){$('project').close();error(err);}finally{b.disabled=false;}};
$('task').onsubmit=async e=>{e.preventDefault();$('error').hidden=true;try{await api('/api/turn',{session:selected,text:$('prompt').value,mode:$('turn-mode').value});$('prompt').value='';await refresh();}catch(err){error(err);}};
$('stop').onclick=async()=>{try{await api('/api/stop',{session:selected});requests.clear();approvals();await refresh();}catch(e){error(e);}};
let failures=0;
async function tick(){try{if(selected){const current=generation;const rows=await api(`/api/events?session=${selected}&after=${after}`);if(current!==generation)return;for(const r of rows){after=r.seq;consume(r.event);} if(rows.length)await refresh();}failures=0;}catch(e){if(++failures===1)error(new Error('Codex Desk disconnected. Restart it and reopen this session.'));}finally{setTimeout(tick,failures?3000:800)}};
(async()=>{try{await refresh();const last=localStorage.getItem('codex-desk-session');if(state.sessions.some(s=>s.id===last))await open(last);tick();}catch(e){error(e)}})();

let nativeCursor=null;
async function nativeList(cursor=null) {
  const data=await api('/api/native'+(cursor?'?cursor='+encodeURIComponent(cursor):''));
  if(!cursor)$('native-list').replaceChildren();
  for(const t of data.data || []) {
    const box=make('div','','native-row');box.append(make('strong',t.name || t.preview || t.id),make('small',`${t.cwd} · ${t.modelProvider}`));
    const action=make('div','','actions'),view=make('button','Resume with current settings'),handoff=make('button','Review handoff');
    view.onclick=async()=>{try{const r=await api('/api/import',{thread:t.id,profile:'default'});$('history').close();await open(r.id);}catch(e){error(e);}};
    handoff.onclick=()=>showHandoff(t.id,t.cwd);action.append(view,handoff);box.append(action);$('native-list').append(box);
  }
  nativeCursor=data.nextCursor;$('more').hidden=!nativeCursor;
}
function fillProfiles(select) {select.replaceChildren(...state.profiles.map(p=>{const n=make('option',p.name);n.value=p.id;return n;}));}
async function showHandoff(thread,cwd) {
  try {const r=await api('/api/handoff',{thread});$('handoff-cwd').value=cwd;fillProfiles($('handoff-profile'));$('handoff-text').value=r.text;$('history').close();$('preview').showModal();}catch(e){error(e);}
}
$('browse').onclick=async()=>{try{$('history').showModal();await nativeList();}catch(e){$('history').close();error(e);}};
$('more').onclick=async()=>{try{await nativeList(nativeCursor);}catch(e){error(e);}};
$('history-close').onclick=()=>$('history').close();$('preview-close').onclick=()=>$('preview').close();
$('handoff').onclick=()=>{const s=state.sessions.find(s=>s.id===selected);if(s)showHandoff(s.thread_id,s.cwd);};
$('handoff-start').onclick=async()=>{const b=$('handoff-start');b.disabled=true;try{const r=await api('/api/handoff/start',{cwd:$('handoff-cwd').value,profile:$('handoff-profile').value,text:$('handoff-text').value,goal:$('handoff-goal').value});$('preview').close();await open(r.id);}catch(e){error(e);}finally{b.disabled=false;}};

$('add-provider').onclick=()=>$('provider').showModal();
$('provider-close').onclick=()=>{$('provider-key').value='';$('provider').close();};
$('provider-form').onsubmit=async e=>{e.preventDefault();$('provider-save').disabled=true;try{await api('/api/profiles',{name:$('provider-name').value,endpoint:$('provider-endpoint').value,model:$('provider-model').value,key:$('provider-key').value});$('provider-key').value='';$('provider').close();await refresh();}catch(e){$('provider').close();error(e);}finally{$('provider-key').value='';$('provider-save').disabled=false;}};

$('rename').onclick=()=>{const s=state.sessions.find(s=>s.id===selected);if(!s)return;$('rename-name').value=s.name || '';$('rename-error').hidden=true;$('rename-dialog').showModal();$('rename-name').focus();$('rename-name').select();};
$('rename-cancel').onclick=()=>$('rename-dialog').close();
$('rename-form').onsubmit=async e=>{e.preventDefault();const b=$('rename-save');b.disabled=true;try{await api('/api/rename',{session:selected,name:$('rename-name').value});$('rename-dialog').close();await refresh();}catch(e){$('rename-error').textContent=e.message;$('rename-error').hidden=false;await refresh();}finally{b.disabled=false;}};
