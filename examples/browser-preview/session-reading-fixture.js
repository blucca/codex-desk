/* Opt-in synthetic transport controls for the session-reading acceptance build. */
(()=>{
  'use strict';
  const fixture=window.DeskPreviewReadingFixture,threads=window.DeskPreviewThreads;
  if(!fixture || !Array.isArray(threads))throw Error('Build the session-reading fixture before running its checker.');
  const overrides=window.DeskPreviewReadingOverrides || {},holds=new Map(),responseHolds=new Map(),entered=[],responsesEntered=[];
  const a=threads[0],prior=a.turns[0],live=a.turns[1];
  const events=fixture.events['desk-'+a.id],copy=value=>JSON.parse(JSON.stringify(value));
  function applySource(event){
    const p=event.params || {};if(p.threadId!==a.id)return;
    const turn=a.turns.find(turn=>turn.id===p.turnId);if(!turn)return;
    if(event.method==='item/commandExecution/outputDelta'){
      const item=turn.items.find(item=>item.id===p.itemId);if(item?.type==='commandExecution')item.aggregatedOutput+=p.delta;
    }else if(['item/started','item/completed'].includes(event.method) && p.item){
      const index=turn.items.findIndex(item=>item.id===p.item.id);
      if(index<0)turn.items.push(copy(p.item));else turn.items[index]=copy(p.item);
    }
  }
  // Fresh sample reads and cached replay are distinct, even across a cold reload.
  for(const row of overrides.activityRows || []){events.push(copy(row));applySource(row.event);}
  if(overrides.freshMcp)prior.items.find(item=>item.id==='sample-checkout-mcp').result.content[0].text+='\nFRESH SAMPLE MCP RESULT supplied for this reload.';
  if(overrides.movedCommand){
    const command=prior.items.find(item=>item.id==='sample-checkout-evidence');
    prior.items=prior.items.filter(item=>item!==command);live.items.push(command);
  }
  function hold(path){if(holds.has(path))throw Error('A sample transport hold already exists.');
    let release;const promise=new Promise(resolve=>{release=resolve;});holds.set(path,{promise,release});}
  function emit(event){applySource(event);const row={seq:(events.at(-1)?.seq || 0)+1,event};events.push(row);return row.seq;}
  if(overrides.namespaceHold)hold('/api/native/home');
  const controls={entered,hold,release:path=>{const held=holds.get(path);if(!held)throw Error('No such sample transport hold.');holds.delete(path);held.release();},
    before:async path=>{const held=holds.get(path);if(held){entered.push(path);await held.promise;}},
    responsesEntered,
    holdResponse:path=>{if(responseHolds.has(path))throw Error('A sample response hold already exists.');let release;const promise=new Promise(resolve=>{release=resolve;});responseHolds.set(path,{promise,release});},
    releaseResponse:path=>{const held=responseHolds.get(path);if(!held)throw Error('No such sample response hold.');responseHolds.delete(path);held.release();},
    after:async path=>{const held=responseHolds.get(path);if(held){responsesEntered.push(path);await held.promise;}},
    activityRows:()=>copy(events.filter(row=>row.seq>3)),
    updateCommand:()=>{
      const item=copy(prior.items.find(item=>item.id==='sample-checkout-evidence'));
      item.aggregatedOutput+='\nNEW SAMPLE COMMAND MATERIAL remains in its exact earlier native item.';
      return emit({method:'item/completed',params:{threadId:a.id,turnId:prior.id,item}});
    },
    updateLinkedOriginal:()=>{
      const item=copy(prior.items.find(item=>item.id==='sample-checkout-collaboration'));
      item.agentsStates['sample-child-thread'].message+='\nNew parent-reported linked result retains its exact original source.';
      return emit({method:'item/completed',params:{threadId:a.id,turnId:prior.id,item}});
    },
    appendIgnored:()=>{
      emit({method:'thread/tokenUsage/updated',params:{threadId:a.id,tokenUsage:{total:99}}});
      emit({method:'item/agentMessage/delta',params:{threadId:'sample-child-thread',turnId:prior.id,itemId:'sample-child-output',delta:'Child-only sample output.'}});
      return emit({method:'item/plan/delta',params:{threadId:a.id,turnId:prior.id,itemId:'sample-dropped-plan',delta:'Not accepted by the current native plan renderer.'}});
    },
    appendOutput:()=>{
      const item={id:'sample-checkout-new-output',type:'agentMessage',text:'New sample output waits below the reviewed original evidence.'};
      return emit({method:'item/started',params:{threadId:a.id,turnId:live.id,item}});
    }};
  fixture.controls=controls;
})();
