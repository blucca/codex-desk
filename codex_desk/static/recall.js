/* Literal recall of retained Desk evidence and preparation; navigation never sends. */
const DeskRecall=(()=>{
  const el=id=>document.getElementById(id), rowData=new WeakMap();
  let options, searchVersion=0, openVersion=0, navigationVersion=0;
  let searching=false, resultOpening=false, projectSignature='', target=null, pendingNavigation=null;
  const query=()=>({q:el('recall-query').value.trim(),cwd:el('recall-project').value,archived:el('recall-archived').checked});
  const sameQuery=(a,b)=>a.q===b.q && a.cwd===b.cwd && a.archived===b.archived;
  const current=(version,scope)=>version===searchVersion && el('recall').open && sameQuery(scope,query());
  const make=(tag,text,cls)=>options.make(tag,text,cls);
  function clearTarget(){if(target){target.node.classList.remove('recall-target');if(target.addedTabindex)target.node.removeAttribute('tabindex');target=null;}}
  function selectionChanged(){clearTarget();++navigationVersion;pendingNavigation=null;}
  function projects(){
    if(!options)return;
    const values=[...new Set(options.state().sessions.map(s=>s.cwd).filter(Boolean))].sort();
    const selected=el('recall-project').value, signature=JSON.stringify(values);
    if(signature===projectSignature)return;projectSignature=signature;
    const all=make('option','All saved Desk projects');all.value='';
    const rows=values.map(cwd=>{const folder=cwd.split(/[\\/]/).filter(Boolean).at(-1) || cwd;
      const row=make('option',folder+' — '+cwd);row.value=cwd;return row;});
    // A background state change must not silently broaden an exact saved scope.
    if(selected && !values.includes(selected)){const row=make('option',selected+' — saved scope');row.value=selected;rows.push(row);}
    el('recall-project').replaceChildren(all,...rows);el('recall-project').value=selected;
  }
  function stateChanged(){projects();if(target && (target.session!==options.selected() || target.generation!==options.generation()))clearTarget();}
  function buttons(){
    el('recall-search').disabled=searching;
    el('recall-results').setAttribute('aria-busy',String(searching || resultOpening));
    for(const b of el('recall-results').querySelectorAll('.recall-open'))b.disabled=resultOpening;
  }
  function invalidate(){
    ++searchVersion;++openVersion;++navigationVersion;searching=false;resultOpening=false;pendingNavigation=null;
    el('recall-error').hidden=true;el('recall-results').replaceChildren();
    el('recall-summary').textContent='Query changed. Choose Search to update saved content.';buttons();
  }
  function snippet(text,match){
    const node=make('pre','','recall-snippet'), value=String(text || ''), needle=String(match || '');
    const at=needle?value.indexOf(needle):-1;
    if(at<0){node.textContent=value;return node;}
    node.append(document.createTextNode(value.slice(0,at)),make('mark',value.slice(at,at+needle.length)),document.createTextNode(value.slice(at+needle.length)));
    return node;
  }
  function coverage(value){
    const counts=[];
    for(const [key,label] of [['sessions','Desk sessions'],['activity_items','cached activity items'],['drafts','saved drafts'],['followups','prepared follow-ups']]){
      if(Number.isFinite(value?.[key]))counts.push(value[key]+' '+label);
    }
    el('recall-coverage').textContent=[typeof value==='string'?value:value?.text,counts.join(' · ')].filter(Boolean).join('\n');
  }
  function resultRow(result,version,scope){
    const row=make('article','','recall-result');rowData.set(row,result);row.dataset.session=result.session_id;row.dataset.kind=result.kind;
    if(result.item_id)row.dataset.item=result.item_id;if(result.followup_id)row.dataset.followup=result.followup_id;
    const name=result.session_name || result.cwd || 'Saved conversation';
    const kind={activity:'Cached activity',draft:'Saved draft',followup:'Prepared follow-up'}[result.kind] || 'Saved content';
    row.append(make('h3',name),make('p',kind+(result.archived?' · Archived locally':''),'recall-kind'),
      make('p',`${result.cwd || ''}\n${options.profileLabel(result.profile)}`,'recall-binding'),snippet(result.snippet,result.match_text));
    if(Number.isFinite(result.updated) && result.updated>0){
      const date=new Date(result.updated*1000);
      if(!Number.isNaN(date.getTime())){const time=make('time',date.toLocaleString(),'recall-updated');time.dateTime=date.toISOString();row.append(time);}
    }
    const action=make('button',{activity:'Open matching activity',draft:'Go to saved draft',followup:'Go to prepared follow-up'}[result.kind] || 'Open saved content','recall-open');action.type='button';
    action.setAttribute('aria-label',action.textContent+' in '+name);
    const notice=make('p','','recall-result-status');notice.setAttribute('role','status');notice.hidden=true;
    action.onclick=()=>reveal(result,row,notice,version,scope);row.append(action,notice);return row;
  }
  async function search(){
    if(!options)return;
    const scope=query();
    if(scope.q.length<2 || scope.q.length>200){
      el('recall-error').textContent='Enter 2–200 characters from a saved message, tool result or prepared task.';
      el('recall-error').hidden=false;el('recall-query').focus();return;
    }
    const version=++searchVersion;++openVersion;++navigationVersion;pendingNavigation=null;resultOpening=false;searching=true;
    el('recall-error').hidden=true;el('recall-results').replaceChildren();
    el('recall-summary').textContent='Searching saved content…';buttons();
    const params=new URLSearchParams({q:scope.q,archived:String(scope.archived),limit:'30'});
    if(scope.cwd)params.set('cwd',scope.cwd);
    try{
      const data=await options.api('/api/recall?'+params);
      if(!current(version,scope))return;
      const rows=Array.isArray(data.results)?data.results:[];
      el('recall-results').replaceChildren(...rows.map(result=>resultRow(result,version,scope)));
      const total=Number.isFinite(data.total)?data.total:rows.length;
      el('recall-summary').textContent=rows.length
        ? `Showing ${rows.length} of ${total} matching item${total===1?'':'s'}.`+(data.truncated?' More matches exist — narrow the query or project.':'')
        : 'No saved content matches this query in the selected scope.';
      coverage(data.coverage);
    }catch(error){if(current(version,scope)){
      el('recall-summary').textContent='Saved content could not be searched. Choose Search to retry.';
      el('recall-error').textContent=error.message;el('recall-error').hidden=false;
    }}finally{if(current(version,scope)){searching=false;buttons();}}
  }
  function targetFor(result){
    const matches=node=>node && typeof result.match_text==='string' && result.match_text &&
      (['INPUT','TEXTAREA'].includes(node.tagName)?node.value:node.textContent).includes(result.match_text);
    if(result.kind==='activity'){
      const node=options.itemNode(result.item_id), turn=options.itemTurn(result.item_id);
      if(!node?.isConnected || node.hidden || !matches(node) || (result.turn_id && turn && turn!==result.turn_id))return null;
      return node;
    }
    if(result.kind==='draft')return el('task').hidden || !matches(el('prompt'))?null:el('prompt');
    if(result.kind==='followup'){
      // Match IDs as data, not as a selector assembled from untrusted content.
      const row=[...el('followup-list').children].find(node=>node.dataset.followup===result.followup_id);
      const node=row?.querySelector('textarea, pre');return matches(node)?node:null;
    }
    return null;
  }
  function expand(node,result){
    if(result.kind==='followup')el('followups').open=true;
    for(const details of node.querySelectorAll('details'))details.open=true;
    for(let parent=node.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
  }
  function focusMatch(nav){
    if(nav.version!==navigationVersion || el('recall').open || nav.session!==options.selected() || nav.generation!==options.generation() || !nav.node.isConnected)return;
    clearTarget();const node=nav.node, addedTabindex=!node.hasAttribute('tabindex') && !['INPUT','TEXTAREA','BUTTON','SELECT'].includes(node.tagName);
    if(addedTabindex)node.tabIndex=-1;
    node.classList.add('recall-target');target={...nav,addedTabindex};node.focus({preventScroll:true});node.scrollIntoView({block:'center',behavior:'instant'});
    // Long command/MCP evidence can itself scroll. Reveal the matching line
    // without rewriting Markdown, changing selection or inserting source HTML.
    if(nav.result.kind==='activity' && nav.result.match_text){
      const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT);
      let textNode;while((textNode=walker.nextNode())){
        const at=textNode.data.indexOf(nav.result.match_text);if(at<0)continue;
        const pre=textNode.parentElement.closest('pre');if(!pre)break;
        const range=document.createRange();range.setStart(textNode,at);range.setEnd(textNode,at+nav.result.match_text.length);
        const rect=range.getBoundingClientRect(), box=pre.getBoundingClientRect();
        pre.scrollTop+=rect.top-box.top-pre.clientHeight/2;break;
      }
    }
  }
  async function reveal(result,row,notice,version,scope){
    if(resultOpening || !current(version,scope))return;
    const ticket=++openVersion;resultOpening=true;notice.hidden=false;notice.textContent='Opening saved work…';buttons();
    const valid=()=>ticket===openVersion && current(version,scope) && row.isConnected;
    let expectedGeneration=options.generation();
    try{
      const saved=options.state().sessions.find(s=>s.id===result.session_id);
      if(!saved)throw new Error('This session is no longer in Desk. Its search result is kept here.');
      if(saved.archived){
        await options.api('/api/archive',{session:result.session_id,archived:false});
        if(!valid())return;
        await options.refresh();if(!valid())return;
      }
      if(expectedGeneration!==options.generation())throw new Error('The selected conversation changed. Choose this result again to open it.');
      if(options.selected()!==result.session_id || !options.loaded()){
        const opening=options.open(result.session_id,{revealLatest:false});expectedGeneration=options.generation();await opening;
        if(!valid())return;
      }
      if(expectedGeneration!==options.generation())throw new Error('The selected conversation changed before this result could be shown. Choose it again.');
      if(options.selected()!==result.session_id || !options.loaded())throw new Error('This session could not be opened. Its search result is kept here; check the session error and retry.');
      if(result.kind==='followup'){await options.refreshFollowups(result.session_id);if(!valid())return;}
      if(expectedGeneration!==options.generation() || options.selected()!==result.session_id || !options.loaded())throw new Error('The selected conversation changed before the matching preparation could be shown. Choose this result again.');
      const node=targetFor(result);
      if(!node){
        notice.textContent=result.kind==='activity'
          ? 'The saved match is not in the freshly loaded native activity. This cached result is kept here; no task or handoff was started.'
          : 'The saved phrase is no longer in the current preparation. Your current text and this search result are kept; search again to refresh the match.';
        return;
      }
      expand(node,result);notice.textContent='Opened saved content. Nothing was sent.';
      pendingNavigation={node,result,session:result.session_id,generation:expectedGeneration,version:++navigationVersion};
      el('recall').close();
    }catch(error){if(valid()){notice.textContent=error.message;notice.hidden=false;}}
    finally{if(ticket===openVersion){resultOpening=false;buttons();}}
  }
  function show(){
    ++navigationVersion;pendingNavigation=null;projects();
    const version=searchVersion,scope=query();
    for(const row of el('recall-results').children){const result=rowData.get(row);
      if(result)row.querySelector('.recall-open').onclick=()=>reveal(result,row,row.querySelector('.recall-result-status'),version,scope);
    }
    el('recall').showModal();el('recall-query').focus();
  }
  function configure(value){
    options=value;projects();
    el('search-saved-content').onclick=show;
    el('recall-form').onsubmit=event=>{event.preventDefault();search();};
    el('recall-query').oninput=invalidate;el('recall-project').onchange=invalidate;el('recall-archived').onchange=invalidate;
    el('recall-close').onclick=()=>el('recall').close();
    el('recall').addEventListener('close',()=>{
      const nav=pendingNavigation;pendingNavigation=null;++searchVersion;++openVersion;
      if(searching)el('recall-summary').textContent='Search canceled. Choose Search to try again.';
      searching=false;resultOpening=false;buttons();
      // show() rebinds retained results to the next dialog generation.
      if(nav)requestAnimationFrame(()=>focusMatch(nav));
    });
    el('recall').addEventListener('cancel',()=>{pendingNavigation=null;++navigationVersion;});
  }
  return {configure,stateChanged,selectionChanged};
})();
