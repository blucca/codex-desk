const $ = id => document.getElementById(id);
let state = {profiles: [], sessions: []}, selected = null, after = 0, items = new Map(), requests = new Map();
const nodes = new Map();
let modeSelected=null, generation=0, opening=false, refreshVersion=0;
const drafts=new Map(), submitting=new Set();
let projectVersion=0, projectCursor=null, projectQuery=null, projectOpening=false;
let latestUpdates=0, statePollAt=0;
function nearLatest(){return window.scrollY+window.innerHeight >= document.documentElement.scrollHeight-140;}
function latestLabel(){
  $('latest-output').textContent=latestUpdates?`${latestUpdates} new update${latestUpdates===1?'':'s'} · Latest output ↓`:'Latest output ↓';
}
function goLatest(){
  latestUpdates=0;latestLabel();
  window.scrollTo({top:document.documentElement.scrollHeight,behavior:'instant'});
}
$('latest-output').onclick=goLatest;
async function api(path, data) {
  const r = await fetch(path, data ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)} : {});
  const v = await r.json(); if (!r.ok) throw new Error(v.error || 'Request failed'); return v;
}
function error(e) { $('error').textContent = e.message; $('error').hidden = false; }
function make(tag, text, cls) { const node = document.createElement(tag); if(text) node.textContent=text; if(cls) node.className=cls; return node; }
function profileLabel(id){return state.profiles.find(p=>p.id===id || p.legacy_id===id)?.name || id;}
function draw() {
  const list=$('sessions'), left=list.scrollLeft, top=list.scrollTop;
  $('sessions').replaceChildren();
  for(const s of state.sessions) {
    const b = make('button', '', 'session' + (s.id===selected?' selected':''));
    b.title=s.cwd;
    b.append(make('strong', s.name || s.cwd.split(/[\\/]/).filter(Boolean).at(-1)), make('small', `${s.cwd.split(/[\\/]/).filter(Boolean).at(-1) || s.cwd} · ${profileLabel(s.profile)} · ${s.status}`));
    b.onclick=()=>open(s.id); $('sessions').append(b);
  }
  list.scrollLeft=left;list.scrollTop=top;
  const running=state.sessions.filter(s=>['running','approval','starting'].includes(s.status)).length;
  document.title=(running?`(${running} active) `:'')+'Codex Desk';
  $('activity-controls').hidden=!selected;
  const s = state.sessions.find(s=>s.id===selected); if(!s) return;
  $('title').textContent=s.name || s.cwd.split(/[\\/]/).filter(Boolean).at(-1);$('rename').hidden=false;
  $('binding').textContent=`${s.cwd}\n${profileLabel(s.profile)} → ${s.provider || 'loading'} / ${s.model || 'native default'}`;
  if(modeSelected!==selected){$('turn-mode').value=s.mode || 'native';modeSelected=selected;}
  const busy=opening || submitting.has(selected) || ['running','approval','starting'].includes(s.status);
  $('turn-mode').disabled=busy;
  $('status').textContent=opening?'Opening session…':s.status; $('send').disabled=busy;
  $('stop').disabled=opening || !['running','approval'].includes(s.status);
  $('rename').disabled=opening;$('handoff').disabled=opening;
  if(s.usage) {
    const u=JSON.parse(s.usage), t=u.total || u;
    $('usage').textContent=`Thread usage · input ${(t.inputTokens || 0).toLocaleString()} (cached ${(t.cachedInputTokens || 0).toLocaleString()}) · output ${(t.outputTokens || 0).toLocaleString()} · latest native cumulative total`;
  } else $('usage').textContent='Usage appears after native Codex reports it.';
  if(s.error && s.status==='failed' && !opening) error(new Error(s.error));
}
function itemText(i) {
  switch(i.type) {
    case 'userMessage':return (i.content || []).map(c=>c.text || '').join('\n');
    case 'agentMessage':return i.text || '';
    case 'commandExecution':return `$ ${i.command || ''}\n${i.aggregatedOutput || ''}${i.exitCode == null ? '' : '\nExit '+i.exitCode}`;
    case 'fileChange':return (i.changes || []).map(c=>`${c.kind?.type || 'change'} ${c.path}\n${c.diff || ''}`).join('\n');
    case 'reasoning':return (i.summary || []).join('\n');
    case 'mcpToolCall':case 'dynamicToolCall':return DeskEvidence.tool(i);
    default:return i.text || JSON.stringify(i, null, 2);
  }
}
function renderItem(i) {
  const prior=items.get(i.id);if(prior?.progress && !i.progress)i.progress=prior.progress;
  items.set(i.id, i); let node=nodes.get(i.id);const text=itemText(i);
  if(!node) {node=make('div', '', 'item '+i.type);nodes.set(i.id,node);$('activity').append(node);}
  DeskActivity.render(node,i,text);
}
let approvalsSignature='';
function approvals() {
  const signature=JSON.stringify([selected,[...requests]]);
  if(signature===approvalsSignature)return;
  approvalsSignature=signature;
  $('approvals').replaceChildren();
  for(const [id,m] of requests) {
    const session=selected, current=generation;
    const p=m.params || {}, box=make('div',`${m.method}\n${p.command || p.reason || 'Native Codex needs your input.'}`, 'approval');
    if(['item/commandExecution/requestApproval','item/fileChange/requestApproval'].includes(m.method)) {
      const buttons=make('div','','actions');
      for(const [label,decision] of [['Allow once','accept'],['Decline','decline']]) {
        const b=make('button',label); b.onclick=async()=>{try{await api('/api/approval',{session,request:id,decision});if(current===generation){requests.delete(id);approvals();}}catch(e){if(current===generation)error(e)}};buttons.append(b);
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
      form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{const answers=Object.fromEntries([...fields].map(([id,input])=>[id,[input.value]]));await api('/api/answer',{session,request:id,answers});if(current===generation){requests.delete(id);approvals();await refresh();}}catch(e){if(current===generation){error(e);submit.disabled=false;}}};
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
  if(m.method==='item/mcpToolCall/progress') {
    const i=items.get(p.itemId) || {id:p.itemId,type:'mcpToolCall',status:'inProgress'};
    i.progress=[...(i.progress || []),p.message].slice(-50);renderItem(i);
  }
  if(m.method==='error') {const n=make('div',p.error?.message || JSON.stringify(p),'item');$('activity').append(n);}
}
async function refresh() {
  const current=generation, version=++refreshVersion, next=await api('/api/state');
  if(current!==generation || version!==refreshVersion)return;
  state=next;requests=new Map((state.pending?.[selected] || []).map(m=>[String(m.id),m]));approvals();draw();
}
async function open(id) {
  if(selected)drafts.set(selected,$('prompt').value);
  const current=++generation;
  latestUpdates=0;latestLabel();
  selected=id;$('prompt').value=drafts.get(id) || '';opening=true;modeSelected=null;after=0;items.clear();nodes.clear();requests.clear();
  $('error').hidden=true;$('task').hidden=true;$('handoff').hidden=true;
  $('activity').replaceChildren();approvals();draw();
  try {
    const opened=await api('/api/open',{session:id});
    if(current!==generation)return;
    localStorage.setItem('codex-desk-session',id);
    for(const t of opened.thread.turns || [])for(const i of t.items || [])renderItem(i);
    $('prompt').value=drafts.get(id) || '';$('welcome').hidden=true;
    await refresh();
    if(current!==generation)return;
    opening=false;draw();$('task').hidden=false;$('handoff').hidden=false;
    requestAnimationFrame(()=>{if(current===generation)goLatest();});
  } catch(e) {
    if(current===generation){opening=false;draw();error(e);}
  }
}
function profileInfo() {
  const p=state.profiles.find(p=>p.id===$('profile').value);
  $('profile-info').textContent=p?`${p.provider || 'Current default'} / ${p.model || 'Configured model'}${p.endpoint?' · '+p.endpoint:''}`:'';
}
function resetProject() {
  ++projectVersion;projectCursor=null;projectQuery=null;projectOpening=false;
  $('project-list').replaceChildren();$('project-results').hidden=true;$('project-more').hidden=true;
  $('project-error').hidden=true;projectBusy(false);
}
function projectBusy(busy) {
  for(const id of ['cwd','profile','project-search','session-name','project-find','project-more','project-new'])$(id).disabled=busy;
  for(const b of $('project-list').querySelectorAll('button'))b.disabled=busy;
}
function projectFilter() {return {cwd:$('cwd').value,search:$('project-search').value.trim()};}
function projectCurrent(version, query) {
  const current=projectFilter();
  return version===projectVersion && $('project').open && query.cwd===current.cwd && query.search===current.search;
}
function historyPath(search, cwd=null, cursor=null) {
  const params=new URLSearchParams();
  if(search)params.set('search',search);
  if(cwd!==null)params.set('cwd',cwd);
  if(cursor)params.set('cursor',cursor);
  const query=params.toString();return '/api/native'+(query?'?'+query:'');
}
function projectSummary(query) {
  const count=$('project-list').children.length;
  $('project-summary').textContent=count
    ? (query.search?`Saved conversations with titles matching “${query.search}”. `:'')+'Choose a saved conversation to keep its context, or start a new one.'
    : (query.search?`No saved conversation titles match “${query.search}” in this project.`:'No saved conversations in this project.')+' Start a new conversation below.';
}
function projectError(e) {$('project-error').textContent=e.message;$('project-error').hidden=false;}
async function findProject(cursor=null) {
  if(projectOpening)return;
  if(cursor && (!projectQuery || !projectCurrent(projectVersion,projectQuery) || $('project-more').disabled))return;
  if(!cursor)resetProject();
  const current=projectVersion, query=projectFilter();projectQuery=query;
  $('project-error').hidden=true;$('project-find').disabled=true;$('project-more').disabled=true;
  $('project-results').hidden=false;$('project-summary').textContent=query.search?`Searching conversation titles for “${query.search}”…`:'Looking for saved conversations…';
  try {
    const data=await api(historyPath(query.search,query.cwd,cursor));
    if(!projectCurrent(current,query))return;
    for(const t of data.data || [])$('project-list').append(nativeRow(t,
      ()=>openProjectChoice(()=>api('/api/import',{thread:t.id,profile:$('profile').value}),current,query),null,'Resume this conversation'));
    projectCursor=data.nextCursor;$('project-more').hidden=!projectCursor;
    projectSummary(query);
    if(projectOpening)projectBusy(true);
  } catch(e) {
    if(projectCurrent(current,query)){if(!cursor)$('project-results').hidden=true;else projectSummary(query);projectError(e);}
  } finally {
    if(projectCurrent(current,query)){$('project-find').disabled=projectOpening;$('project-more').disabled=projectOpening;}
  }
}
async function openProjectChoice(action, current=projectVersion, query=projectFilter()) {
  if(projectOpening || !projectCurrent(current,query))return;
  projectOpening=true;projectBusy(true);$('project-error').hidden=true;
  try {
    const r=await action();if(!projectCurrent(current,query))return;
    $('project').close();await open(r.id);
  } catch(e) {if(projectCurrent(current,query))projectError(e);}
  finally {if(current===projectVersion){projectOpening=false;projectBusy(false);}}
}
$('new').onclick=()=>{resetProject();fillProfiles($('profile'));profileInfo();$('project').showModal();};
$('profile').onchange=profileInfo;$('cancel').onclick=()=>$('project').close();
$('cwd').oninput=resetProject;$('project-search').oninput=resetProject;
$('project').addEventListener('close',()=>{if(!$('project').open)resetProject();});
$('create').onsubmit=async e=>{e.preventDefault();await findProject();};
$('project-more').onclick=()=>findProject(projectCursor);
$('project-new').onclick=()=>{if($('create').reportValidity())return openProjectChoice(()=>api('/api/sessions',{cwd:$('cwd').value,profile:$('profile').value,name:$('session-name').value.trim() || null}));};
$('prompt').oninput=()=>{if(selected)drafts.set(selected,$('prompt').value);};
$('task').onsubmit=async e=>{
  e.preventDefault();if(!selected || opening || submitting.has(selected) || $('send').disabled)return;
  const id=selected, current=generation, text=$('prompt').value, mode=$('turn-mode').value;
  drafts.set(id,text);submitting.add(id);$('error').hidden=true;draw();
  try {
    await api('/api/turn',{session:id,text,mode});
    if(drafts.get(id)===text)drafts.delete(id);
    if(selected===id && $('prompt').value===text)$('prompt').value='';
    if(current===generation)await refresh();
  } catch(err) {if(current===generation)error(err);}
  finally {submitting.delete(id);draw();}
};
$('stop').onclick=async()=>{if(opening)return;const session=selected,current=generation;try{await api('/api/stop',{session});if(current===generation){requests.clear();approvals();await refresh();}}catch(e){if(current===generation)error(e);}};
let failures=0;
const connectionError='Connection lost. Retrying… If Desk stopped, relaunch it and reopen this URL.';
async function pollActivity(){
  const current=generation;
  if(selected && !opening){
    const rows=await api(`/api/events?session=${selected}&after=${after}`);
    if(current!==generation)return;
    const follow=nearLatest();let changed=0;
    for(const r of rows){
      after=r.seq;consume(r.event);
      if(['item/started','item/completed','item/agentMessage/delta','item/commandExecution/outputDelta','item/mcpToolCall/progress','error'].includes(r.event.method))++changed;
    }
    if(changed){
      if(follow)requestAnimationFrame(()=>{if(current===generation)goLatest();});
      else{latestUpdates+=changed;latestLabel();}
    }
    if(rows.length){await refresh();statePollAt=Date.now();}
  }
  // Other projects can finish or request approval while this conversation is quiet.
  if(Date.now()-statePollAt>=4000){await refresh();statePollAt=Date.now();}
}
async function tick(){
  try{await pollActivity();failures=0;if($('error').textContent===connectionError)$('error').hidden=true;}
  catch(e){if(++failures===1)error(new Error(connectionError));}
  finally{setTimeout(tick,failures?3000:800);}
}
(async()=>{try{await refresh();const last=localStorage.getItem('codex-desk-session');if(state.sessions.some(s=>s.id===last))await open(last);tick();}catch(e){error(e)}})();

let nativeVersion=0,nativeCursor=null,nativeQuery=null,nativeLoading=false;
function nativeRow(t, resume, handoff, label='Resume with current settings') {
  const box=make('div','','native-row');box.append(make('strong',t.name || t.preview || t.id),make('small',`${t.cwd} · ${t.modelProvider}`));
  const actions=make('div','','actions'),view=make('button',label);view.type='button';
  view.onclick=async()=>{
    if(view.disabled)return;
    view.disabled=true;
    try {await resume();} finally {view.disabled=false;}
  };actions.append(view);
  if(handoff){const review=make('button','Review handoff');review.type='button';review.onclick=handoff;actions.append(review);}
  box.append(actions);return box;
}
function resetNative() {
  ++nativeVersion;nativeCursor=null;nativeQuery=null;nativeLoading=false;
  $('native-list').replaceChildren();$('more').hidden=true;$('more').disabled=false;
  $('history-search-submit').disabled=false;$('history-error').hidden=true;
  $('history-summary').textContent='Choose Search titles to find saved conversations. Leave the search blank to list them without a title filter.';
}
function nativeCurrent(version, query) {return version===nativeVersion && $('history').open && query===$('history-search').value.trim();}
function nativeSummary(query) {
  const count=$('native-list').children.length;
  $('history-summary').textContent=count
    ? (query?`Saved conversations with titles matching “${query}”. `:'')+'Resume with current settings, or review a handoff.'
    : query?`No saved conversation titles match “${query}”.`:'No saved conversations found.';
}
async function nativeList(cursor=null) {
  const query=$('history-search').value.trim();
  if(cursor && (nativeLoading || nativeQuery!==query || !nativeCursor))return;
  if(!cursor)resetNative();
  const current=nativeVersion;nativeQuery=query;nativeLoading=true;
  $('history-error').hidden=true;$('history-search-submit').disabled=true;$('more').disabled=true;
  $('history-summary').textContent=query?`Searching conversation titles for “${query}”…`:'Looking for saved conversations…';
  try {
    const data=await api(historyPath(query,null,cursor));
    if(!nativeCurrent(current,query))return;
    for(const t of data.data || []) {
      $('native-list').append(nativeRow(t,async()=>{
        if(!nativeCurrent(current,query))return;
        try {const r=await api('/api/import',{thread:t.id,profile:'default'});if(!nativeCurrent(current,query))return;$('history').close();await open(r.id);}
        catch(e){if(nativeCurrent(current,query)){$('history-error').textContent=e.message;$('history-error').hidden=false;}}
      },()=>{if(nativeCurrent(current,query))showHandoff(t.id,t.cwd,()=>nativeCurrent(current,query));}));
    }
    nativeCursor=data.nextCursor;$('more').hidden=!nativeCursor;nativeSummary(query);
  } catch(e) {
    if(nativeCurrent(current,query)) {
      if(cursor)nativeSummary(query);else $('history-summary').textContent='Could not load saved conversations. Retry Search titles.';
      $('history-error').textContent=e.message;$('history-error').hidden=false;
    }
  } finally {
    if(nativeCurrent(current,query)){nativeLoading=false;$('history-search-submit').disabled=false;$('more').disabled=false;}
  }
}
function fillProfiles(select) {select.replaceChildren(...state.profiles.map(p=>{const n=make('option',p.name);n.value=p.id;return n;}));}
async function showHandoff(thread,cwd,valid=()=>true) {
  const current=generation;
  try {const r=await api('/api/handoff',{thread});if(current!==generation || !valid())return;$('handoff-error').hidden=true;$('handoff-cwd').value=cwd;fillProfiles($('handoff-profile'));$('handoff-text').value=r.text;$('history').close();$('preview').showModal();}catch(e){if(current===generation && valid())error(e);}
}
$('browse').onclick=()=>{$('history').showModal();nativeList();};
$('history-search').oninput=resetNative;
$('history-search-form').onsubmit=e=>{e.preventDefault();nativeList();};
$('history').addEventListener('close',()=>{if(!$('history').open)resetNative();});
$('more').onclick=()=>nativeList(nativeCursor);
$('history-close').onclick=()=>$('history').close();$('preview-close').onclick=()=>$('preview').close();
$('handoff').onclick=()=>{const s=state.sessions.find(s=>s.id===selected);if(s)showHandoff(s.thread_id,s.cwd);};
$('handoff-start').onclick=async()=>{const b=$('handoff-start');b.disabled=true;$('handoff-error').hidden=true;try{const r=await api('/api/handoff/start',{cwd:$('handoff-cwd').value,profile:$('handoff-profile').value,text:$('handoff-text').value,goal:$('handoff-goal').value});$('preview').close();await open(r.id);}catch(e){$('handoff-error').textContent=e.message;$('handoff-error').hidden=false;}finally{b.disabled=false;}};

$('add-provider').onclick=()=>{$('provider-error').hidden=true;$('provider').showModal();};
$('provider-close').onclick=()=>$('provider').close();
$('provider').addEventListener('close',()=>{$('provider-key').value='';});
$('provider-form').onsubmit=async e=>{e.preventDefault();$('provider-save').disabled=true;$('provider-error').hidden=true;try{await api('/api/profiles',{name:$('provider-name').value,endpoint:$('provider-endpoint').value,model:$('provider-model').value,key:$('provider-key').value});$('provider-key').value='';$('provider').close();await refresh();}catch(e){$('provider-error').textContent=e.message;$('provider-error').hidden=false;}finally{$('provider-key').value='';$('provider-save').disabled=false;}};

$('rename').onclick=()=>{const s=state.sessions.find(s=>s.id===selected);if(!s)return;$('rename-name').value=s.name || '';$('rename-error').hidden=true;$('rename-dialog').showModal();$('rename-name').focus();$('rename-name').select();};
$('rename-cancel').onclick=()=>$('rename-dialog').close();
$('rename-form').onsubmit=async e=>{e.preventDefault();const b=$('rename-save');b.disabled=true;try{await api('/api/rename',{session:selected,name:$('rename-name').value});$('rename-dialog').close();await refresh();}catch(e){$('rename-error').textContent=e.message;$('rename-error').hidden=false;await refresh();}finally{b.disabled=false;}};
