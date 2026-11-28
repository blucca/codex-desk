"""Execute the actual ordinary-browser direct-ID controller with owned transport."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'codex_desk/static/app.js').read_text()
CONTROLLER = APP[APP.index('let nativeIdVersion=0;'):APP.index('function resetNative() {')]
SETUP = r'''
const assert=require('assert/strict');
let selected='B',generation=3;
const form={open:true,scrollTop:122,contains:node=>node===input||node===button};
const input={value:'native-A',selectionStart:2,selectionEnd:5,selectionDirection:'backward',isConnected:true,
 focus(){document.activeElement=this;},setSelectionRange(start,end,direction){Object.assign(this,{selectionStart:start,selectionEnd:end,selectionDirection:direction});}};
const button={disabled:false,isConnected:true,focus(){document.activeElement=this;}};
const status={textContent:''},els={'history':form,'history-id':input,'history-id-read':button,'history-id-status':status};
const $=id=>{assert(els[id]);return els[id];},document={activeElement:input};
const retained={draft:'B unsent Plan',mode:'plan',queue:['B Work','B Plan'],titles:{query:'Keep + Café',rows:['row31'],page:2}};
const before=JSON.stringify(retained),calls=[],shown=[];
let home='a'.repeat(64),readError=null;
let transport=async path=>path==='/api/native/home'?{home_namespace:home}:
 {home_namespace:home,thread:{id:new URL(path,'http://local').searchParams.get('thread'),turns:[]}};
const api=async path=>{calls.push(path);return transport(path);};
let reader=async(target,options)=>{shown.push({target,options});try{await options.loadOriginal();return options.valid();}catch(error){readError=error;return false;}};
const DeskHistoryReader={show:(...args)=>reader(...args)};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise};};
'''

class OriginalById(unittest.TestCase):
    def check(self, body):
        script = SETUP + CONTROLLER + '\n(async()=>{' + body + r'''
assert.equal(JSON.stringify(retained),before);
assert(calls.every(path=>path==='/api/native/home' || path.startsWith('/api/native/evidence-source?home=')));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_direct_exact_id_reads_scoped_original_without_title_lookup(self):
        self.check(r'''
input.value='  native-A/接口?+  ';assert(await readNativeById());assert.equal(calls.length,2);
assert.equal(shown[0].target.thread_id,'native-A/接口?+');
assert.deepEqual(Object.fromEntries(new URL(calls[1],'http://local').searchParams),{home:'a'.repeat(64),thread:'native-A/接口?+'});
assert.equal(shown[0].options.backLabel,'Back to conversation ID');assert.equal(button.disabled,false);
form.scrollTop=600;input.selectionStart=0;shown[0].options.onReturn();
assert.equal(form.scrollTop,122);assert.equal(input.selectionStart,2);assert.equal(input.selectionDirection,'backward');assert.equal(document.activeElement,input);
''')

    def test_blank_overlimit_and_whole_reference_do_not_read(self):
        self.check(r'''
for(const invalid of ['  ','x'.repeat(201),'Thread: native-A']){input.value=invalid;assert.equal(await readNativeById(),false);}
assert.equal(calls.length,0);assert.equal(shown.length,0);assert.equal(document.activeElement,input);
''')

    def test_held_home_cannot_open_after_newer_selection(self):
        self.check(r'''
const held=deferred();transport=()=>held.promise;const pending=readNativeById();await Promise.resolve();
selected='C';generation++;held.resolve({home_namespace:home});assert.equal(await pending,false);assert.equal(shown.length,0);assert.equal(calls.length,1);
''')

    def test_closed_browser_or_new_id_supersedes_held_home(self):
        self.check(r'''
const held=deferred();transport=()=>held.promise;const pending=readNativeById();await Promise.resolve();
input.value='new-ID';resetNativeId();form.open=false;held.resolve({home_namespace:home});
assert.equal(await pending,false);assert.equal(shown.length,0);assert.equal(button.disabled,false);
''')

    def test_held_native_read_cannot_adopt_new_target(self):
        self.check(r'''
const held=deferred();transport=path=>path==='/api/native/home'?Promise.resolve({home_namespace:home}):held.promise;
const pending=readNativeById();await new Promise(r=>setImmediate(r));assert.equal(calls.length,2);input.value='new-ID';resetNativeId();
held.resolve({home_namespace:home,thread:{id:'native-A',turns:[]}});assert.equal(await pending,false);
assert.equal(shown.length,1);assert.equal(shown[0].options.valid(),false);assert.equal(status.textContent,'');
''')

    def test_retry_and_refresh_use_same_captured_home_and_id(self):
        self.check(r'''
const ordinary=transport;transport=async path=>{if(path!=='/api/native/home')throw Error('Controlled native unavailable');return ordinary(path);};
assert.equal(await readNativeById(),false);assert.equal(readError.message,'Controlled native unavailable');
transport=ordinary;const fresh=await shown[0].options.loadOriginal();assert.equal(fresh.id,'native-A');assert.equal(calls[1],calls[2]);
home='b'.repeat(64);await assert.rejects(shown[0].options.loadOriginal(),/different native home/);assert.equal(calls[1],calls[3]);
''')

    def test_return_retires_held_read_and_reenables_same_id_action(self):
        self.check(r'''
const held=deferred();transport=path=>path==='/api/native/home'?Promise.resolve({home_namespace:home}):held.promise;
const pending=readNativeById();await new Promise(r=>setImmediate(r));assert.equal(calls.length,2);
shown[0].options.onReturn();assert.equal(button.disabled,false);assert.equal(shown[0].options.valid(),false);
held.resolve({home_namespace:home,thread:{id:'native-A',turns:[]}});assert.equal(await pending,false);
assert.equal(status.textContent,'');
''')

    def test_invalid_namespace_and_wrong_original_never_succeed(self):
        self.check(r'''
transport=async()=>({home_namespace:'invalid'});assert.equal(await readNativeById(),false);assert.equal(shown.length,0);
transport=async path=>path==='/api/native/home'?{home_namespace:home}:{home_namespace:home,thread:{id:'other',turns:[]}};
assert.equal(await readNativeById(),false);assert.match(readError.message,/did not supply this original/);
''')

    def test_late_return_does_not_change_current_editor_or_focus(self):
        self.check(r'''
assert(await readNativeById());selected='C';generation++;form.scrollTop=800;document.activeElement=button;
shown[0].options.onReturn();assert.equal(form.scrollTop,800);assert.equal(document.activeElement,button);
await assert.rejects(shown[0].options.loadOriginal(),/target changed/);assert.equal(calls.length,2);
''')

if __name__ == '__main__':
    unittest.main()
