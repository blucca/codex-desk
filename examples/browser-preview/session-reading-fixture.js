/* Opt-in synthetic transport controls for the session-reading acceptance build. */
(()=>{
  'use strict';
  const fixture=window.DeskPreviewReadingFixture,threads=window.DeskPreviewThreads;
  if(!fixture || !Array.isArray(threads))throw Error('Build the session-reading fixture before running its checker.');
  const overrides=window.DeskPreviewReadingOverrides || {},holds=new Map(),entered=[];
  const a=threads[0],prior=a.turns[0],live=a.turns[1];
  if(overrides.freshMcp)prior.items.find(item=>item.id==='sample-checkout-mcp').result.content[0].text+='\nFRESH SAMPLE MCP RESULT supplied for this reload.';
  if(overrides.movedCommand){
    const command=prior.items.find(item=>item.id==='sample-checkout-evidence');
    prior.items=prior.items.filter(item=>item!==command);live.items.push(command);
  }
  function hold(path){if(holds.has(path))throw Error('A sample transport hold already exists.');
    let release;const promise=new Promise(resolve=>{release=resolve;});holds.set(path,{promise,release});}
  if(overrides.namespaceHold)hold('/api/native/home');
  const controls={entered,hold,release:path=>{const held=holds.get(path);if(!held)throw Error('No such sample transport hold.');holds.delete(path);held.release();},
    before:async path=>{const held=holds.get(path);if(held){entered.push(path);await held.promise;}},
    appendOutput:()=>{
      const item={id:'sample-checkout-new-output',type:'agentMessage',text:'New sample output waits below the reviewed original evidence.'};
      live.items.push(item);const events=fixture.events['desk-'+a.id];
      const event={seq:events.at(-1).seq+1,event:{method:'item/started',params:{threadId:a.id,turnId:live.id,item}}};
      events.push(event);return event.seq;
    }};
  fixture.controls=controls;
})();
