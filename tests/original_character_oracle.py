"""Independent literal-source UTF16 glyph and responsive clip-geometry oracle."""

# No reader controller, stored checkpoint or clipboard supplies the expected glyph.
CHARACTER_RANGE = r"""(item,target)=>{
 const pre=item.querySelector('pre'),body=document.querySelector('#history-reader-body'),reader=document.querySelector('#history-reader');
 const text=pre.textContent,start=Number(item.dataset.windowStart),at=target.offset-start;
 const result={native_offset:target.offset,window_start:start,character:text.slice(at,at+target.size),visible:false,
   font:getComputedStyle(pre).font,line_height:getComputedStyle(pre).lineHeight};
 if(at<0||at+target.size>text.length)return result;
 const walker=document.createTreeWalker(pre,NodeFilter.SHOW_TEXT),nodes=[];let node,offset=0;
 while(node=walker.nextNode()){nodes.push({node,start:offset,end:offset+node.data.length});offset+=node.data.length;}
 function point(pos,right){for(const n of nodes)if(pos<n.end||!right&&pos===n.end)return [n.node,pos-n.start];return null;}
 const first=point(at,true),last=point(at+target.size,false);if(!first||!last)return result;
 const range=document.createRange();range.setStart(...first);range.setEnd(...last);
 const p=pre.getBoundingClientRect(),b=body.getBoundingClientRect(),r=reader.getBoundingClientRect();
 const clip={left:Math.max(p.left,b.left,r.left,0),right:Math.min(p.right,b.right,r.right,innerWidth),
   top:Math.max(p.top,b.top,r.top,0),bottom:Math.min(p.bottom,b.bottom,r.bottom,innerHeight)};
 const boxes=[...range.getClientRects()].map(x=>({left:x.left,right:x.right,top:x.top,bottom:x.bottom,width:x.width,height:x.height}));
 const inside=x=>x.width>0&&x.height>0&&x.right>clip.left&&x.left<clip.right&&x.bottom>clip.top&&x.top<clip.bottom;
 const rect=boxes.find(inside)||boxes[0];
 return {...result,clip,rects:boxes,visible:boxes.some(inside),clip_relative_top:rect?rect.top-clip.top:null,
   glyph_height:rect?.height,clip_height:clip.bottom-clip.top};
}"""


def utf16_character(text,offset):
    raw=text.encode('utf-16-le'); first=raw[offset*2:offset*2+2]
    assert len(first)==2,offset
    value=int.from_bytes(first,'little');assert not 0xdc00<=value<=0xdfff,offset
    size=2 if 0xd800<=value<=0xdbff else 1
    return raw[offset*2:(offset+size)*2].decode('utf-16-le'),size


async def probe_character(locator,source_text,source_offset,projection_offset=0):
    expected,size=utf16_character(source_text,source_offset)
    observed=await locator.evaluate(CHARACTER_RANGE,{'offset':source_offset+projection_offset,'size':size})
    assert observed['character']==expected,(expected,observed)
    assert observed['visible'],observed
    observed.update(source_offset=source_offset,projection_offset=projection_offset,expected_character=expected)
    return observed


def assert_responsive_character(before,after):
    assert before['source_offset']==after['source_offset'] and before['expected_character']==after['expected_character'],(before,after)
    assert before['visible'] and after['visible'],(before,after)
    assert before['window_start']-before['projection_offset']==after['window_start']-after['projection_offset'],(before,after)
    expected_top=min(max(before['clip_relative_top'],1-after['glyph_height']),after['clip_height']-1)
    assert abs(after['clip_relative_top']-expected_top)<=2,(expected_top,before,after)
