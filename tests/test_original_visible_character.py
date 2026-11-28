"""Literal source UTF16 glyph metadata and fresh visible geometry, without content storage."""
from pathlib import Path
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'codex_desk/static/history_reader.js').read_text()
POINT=SOURCE[SOURCE.index('  function textPoint('):SOURCE.index('  function restoreSelectedText(')]
VISIBLE=SOURCE[SOURCE.index('  function visibleTextClip('):SOURCE.index('  function captureView(')]
HARNESS=r'''
const assert=require('assert/strict'),NodeFilter={SHOW_TEXT:4};
const root={innerWidth:400,innerHeight:400};
let columns=25,lineHeight=20,glyphHeight=18,preTop=30,bodyTop=20;
const text=('A😀B Café e\u0301 项目 '+ 'retained raw native text\n').repeat(130);
const textNodes=[{data:text.slice(0,17)},{data:text.slice(17,400)},{data:text.slice(400)}];
const pre={textContent:text,scrollTop:700,scrollLeft:0,querySelector:()=>null,
 getBoundingClientRect:()=>({top:preTop,bottom:preTop+100,left:40,right:280})};
const body={getBoundingClientRect:()=>({top:bodyTop,bottom:180,left:20,right:300})};
const reader={getBoundingClientRect:()=>({top:0,bottom:250,left:0,right:400})};
const el=id=>id==='body'?body:reader;
const item={open:true,dataset:{windowStart:'50000'},querySelector:()=>pre};
const absolute=(node,offset)=>{let at=offset;for(const n of textNodes){if(n===node)return at;at+=n.data.length;}throw Error('foreign text node');};
function glyph(at){let row=0,col=0;for(let i=0;i<at;){const c=text.codePointAt(i),n=c>0xffff?2:1;
 if(text[i]==='\n'){++row;col=0;}else{++col;if(col===columns){++row;col=0;}}i+=n;}
 const top=preTop+10+row*lineHeight-pre.scrollTop;
 return {top,bottom:top+glyphHeight,left:40+col*7,right:47+col*7};}
let ranges=0;
const document={createTreeWalker:()=>{let i=0;return {nextNode:()=>textNodes[i++]||null};},
 createRange:()=>{++ranges;let at;return {setStart:(node,offset)=>at=absolute(node,offset),setEnd:()=>{},getClientRects:()=>{const r=glyph(at);if(text[at]==='\n')r.right=r.left;return [r];}};}};
'''
@unittest.skipUnless(shutil.which('node'),'Node is required for source glyph units')
class OriginalVisibleCharacterTests(unittest.TestCase):
 def check(self,body):
  p=subprocess.run(['node','-e',HARNESS+POINT+VISIBLE+body],capture_output=True,text=True,timeout=15)
  self.assertEqual(p.returncode,0,p.stdout+p.stderr)
 def test_raw_codepoint_boundaries_across_mark_nodes_and_reflow(self):
  self.check(r'''
const saved=captureVisibleCharacter(item,pre);assert(saved);assert(saved.offset>50000);
assert(text.includes(String.fromCharCode(0x301)));assert(text.includes(String.fromCharCode(10)));
const at=saved.offset-50000;assert(!(/[\uDC00-\uDFFF]/.test(text[at])&&/[\uD800-\uDBFF]/.test(text[at-1])));
assert(ranges<40,'Search remains bounded by the rendered native text window');
const original=characterRect(pre,text,at);assert.equal(original.top-visibleTextClip(pre).top,saved.top);
columns=13;lineHeight=24;glyphHeight=21;bodyTop=60;
assert(restoreVisibleCharacter(item,{start:50000,character:saved}));
const restored=characterRect(pre,text,at),clip=visibleTextClip(pre);
assert.equal(restored.top-clip.top,saved.top);assert(restored.bottom>clip.top && restored.top<clip.bottom);
''')
 def test_half_surrogate_or_missing_offset_never_normalizes_or_hunts_text(self):
  self.check(r'''
const before=pre.scrollTop;const pair=text.indexOf('😀');assert.equal(pair,1);
assert.equal(characterRect(pre,text,pair+1),null);
assert.equal(restoreVisibleCharacter(item,{start:50000,character:{offset:50000+pair+1,top:0}}),false);
assert.equal(restoreVisibleCharacter(item,{start:50000,character:{offset:50000+text.length,top:0}}),false);
assert.equal(restoreVisibleCharacter(item,{start:50000,character:{offset:50000+text.indexOf('\n'),top:0}}),false);
assert.equal(pre.scrollTop,before);
assert(characterRect(pre,text,pair));assert.equal(text,'A😀B Café e\u0301 项目 retained raw native text\n'.repeat(130));
''')
 def test_current_window_and_deliberate_disclosure_must_be_available(self):
  self.check(r'''
const saved=captureVisibleCharacter(item,pre),before=pre.scrollTop;
assert.equal(restoreVisibleCharacter(item,{start:49999,character:saved}),false);assert.equal(pre.scrollTop,before);
item.open=false;assert.equal(captureVisibleCharacter(item,pre),null);assert.equal(restoreVisibleCharacter(item,{start:50000,character:saved}),false);
''')
 def test_legacy_pixels_do_not_create_a_character_or_read_source(self):
  self.check(r'''
const before=pre.scrollTop;document.createRange=()=>{throw Error('Legacy has no glyph target');};
assert(restoreVisibleCharacter(item,{start:50000,scroll:before}));assert.equal(pre.scrollTop,before);
''')
 def test_partially_clipped_glyph_remains_visible_with_smaller_font(self):
  self.check(r'''
const saved=captureVisibleCharacter(item,pre);glyphHeight=12;
assert(restoreVisibleCharacter(item,{start:50000,character:{...saved,top:-17}}));
const rect=characterRect(pre,text,saved.offset-50000),clip=visibleTextClip(pre);
assert.equal(rect.bottom-clip.top,1);
''')
if __name__=='__main__':unittest.main()
