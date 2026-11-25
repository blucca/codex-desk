/* Native tool evidence stays local. Binary payloads and application-private _meta
   are not task text and are never expanded or fetched by this renderer. */
(function(root) {
  function review(value) {
    if(typeof value==='string' && value.toLowerCase().startsWith('data:'))return location(value);
    if(Array.isArray(value))return value.map(review);
    if(value && typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([key])=>key!=='_meta').map(([key,v])=>[key,
      key==='blob' || (key==='data' && ['image','audio'].includes(value.type))?'[Binary payload omitted]':
      ['uri','url','imageUrl','audioUrl'].includes(key) && typeof v==='string'?location(v):review(v)]));
    return value;
  }
  function json(value) {return JSON.stringify(review(value), null, 2) ?? 'null';}
  function location(value) {
    if(typeof value!=='string')return '';
    if(value.toLowerCase().startsWith('data:'))return value.split(';')[0]+' (embedded)';
    try {const u=new URL(value);u.username='';u.password='';u.search='';u.hash='';return u.toString();}catch {return value.split(/[?#]/)[0];}
  }
  function content(block) {
    if(block===null || typeof block!=='object')return json(block);
    if(block.type==='text' || block.type==='inputText')return typeof block.text==='string'?block.text:'[Unavailable text content]';
    if(['image','audio','inputImage','inputAudio'].includes(block.type)) {
      const kind=block.type.toLowerCase().includes('image')?'Image':'Audio';
      return `[${kind}${block.mimeType?' · '+block.mimeType:''}${block.imageUrl || block.audioUrl?' · '+location(block.imageUrl || block.audioUrl):''} · binary omitted]`;
    }
    if(['resource_link','resourceLink'].includes(block.type))return `Resource: ${block.name || block.title || ''}\n${location(block.uri)}${block.description?'\n'+block.description:''}`;
    if(block.type==='resource') {
      const r=block.resource || {};return `Resource: ${location(r.uri)}${r.mimeType?' · '+r.mimeType:''}\n${typeof r.text==='string'?r.text:'[Binary resource omitted]'}`;
    }
    return `[Unsupported content block: ${block.type || 'unknown'}]`;
  }
  function tool(item) {
    const mcp=item.type==='mcpToolCall';
    const title=mcp?`MCP · ${item.server || ''} / ${item.tool || ''}`:`Tool · ${item.namespace?item.namespace+' / ':''}${item.tool || ''}`;
    const lines=[title,`Status: ${item.status || 'unknown'}${item.success===undefined?'':' · success: '+item.success}${item.durationMs==null?'':' · '+item.durationMs+' ms'}`];
    if(item.arguments!==undefined)lines.push('Arguments\n'+json(item.arguments));
    const r=item.result;
    if(mcp && r) {
      if(Array.isArray(r.content))lines.push(...r.content.map(content));
      if(r.structuredContent!=null)lines.push('Structured result\n'+json(r.structuredContent));
      if(r.isError)lines.push('Tool reported an error');
    }
    if(!mcp && Array.isArray(item.contentItems))lines.push(...item.contentItems.map(content));
    if(item.error)lines.push('Error: '+(item.error.message || 'Tool failed'));
    if(Array.isArray(item.progress) && item.progress.length)lines.push('Progress\n'+item.progress.join('\n'));
    return lines.filter(Boolean).join('\n');
  }
  root.DeskEvidence={tool,content};
  if(typeof module!=='undefined')module.exports=root.DeskEvidence;
})(typeof globalThis==='undefined'?this:globalThis);
