"""Execute shipped native catalog scope, pagination and read ownership."""
import json
import subprocess
import unittest
from test_navigation_controllers import APP, DOM, NODE

SETUP = DOM + r'''
let generation=7,nativeVersion=0,nativeCursor=null,nativeQuery=null,nativeLoading=false;
function showHandoff(){throw Error('Archived read must not review a continuation');}
const calls=[];
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise};};
$('history').open=true;$('history-source').value='current';$('history-search').value='Keep + Café';
const row=(id)=>({id,cwd:'/removed/A',cwdExists:false,name:'Keep + Café '+id});
api=async path=>{calls.push(path);return {data:[row('original-A')],nextCursor:null};};
'''

@unittest.skipUnless(NODE, 'Node is required for catalog controller acceptance')
class NativeArchiveController(unittest.TestCase):
    def check(self, body):
        source=APP.read_text()
        fragments=[source[source.index('function historyPath('):source.index('function projectSummary(')],
                   source[source.index('function nativeRow('):source.index('function fillProfiles(')]]
        script=SETUP+'\n'+'\n'.join(fragments)+'\n(async()=>{'+body+r'''
assert.equal(selected,'active');process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
        result=subprocess.run([NODE,'-e',script],text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout),{'passed':True})

    def test_default_current_is_explicit_and_keeps_existing_actions(self):
        self.check(r'''
api=async path=>{calls.push(path);return {data:[{...row('current'),cwdExists:true}],nextCursor:null};};
await nativeList();const params=new URL(calls[0],'http://local').searchParams;
assert.equal(params.get('archived'),'false');assert.equal(params.get('search'),'Keep + Café');
assert.equal($('native-list').children[0].dataset.nativeSource,'current');
assert.equal($('native-list').querySelectorAll('button').length,3);
assert($('history-summary').textContent.includes('Current native conversations'));
''')

    def test_archived_second_page_exact_read_and_return_only(self):
        self.check(r'''
$('history-source').value='archived';let page=0;
api=async path=>{calls.push(path);return ++page===1?{data:[row('first')],nextCursor:'old+页 /=cursor'}:{data:[row('older')],nextCursor:null};};
await nativeList();await nativeList('old+页 /=cursor');
assert.equal(calls.length,2);assert(calls.every(path=>new URL(path,'http://local').searchParams.get('archived')==='true'));
assert.equal(new URL(calls[1],'http://local').searchParams.get('cursor'),'old+页 /=cursor');
const original=$('native-list').children[1];assert.equal(original.dataset.cursor,'old+页 /=cursor');
assert.equal(original.querySelectorAll('button').length,1);assert(original.textContent.includes('Archived in native Codex history'));
assert(!original.textContent.includes('restore the folder to resume'));
$('history').scrollTop=123;await original.querySelector('.native-read').onclick();
assert.deepEqual(reads[0].result,{thread_id:'older',cwd:'/removed/A'});assert(reads[0].callbacks.valid());
assert.equal(reads[0].callbacks.backLabel,'Back to archived conversations');
$('history').scrollTop=0;reads[0].callbacks.onReturn();assert.equal($('history').scrollTop,123);
assert.equal(document.activeElement,original.querySelector('.native-read'));assert.equal(calls.length,2);
''')

    def test_mode_change_retires_wrong_and_old_cursor(self):
        self.check(r'''
api=async path=>{calls.push(path);return {data:[row('original')],nextCursor:'same-opaque'};};
await nativeList();await nativeList('wrong');assert.equal(calls.length,1);
$('history-source').value='archived';await nativeList('same-opaque');assert.equal(calls.length,1);
await nativeList();assert.equal(calls.length,2);assert.equal($('native-list').children.length,1);
assert.equal(new URL(calls[1],'http://local').searchParams.get('cursor'),null);
assert.equal(new URL(calls[1],'http://local').searchParams.get('archived'),'true');
''')

    def test_held_old_mode_result_cannot_replace_new_mode(self):
        self.check(r'''
const old=deferred();api=async path=>{calls.push(path);return new URL(path,'http://local').searchParams.get('archived')==='false'?old.promise:{data:[row('archived')],nextCursor:null};};
const pending=nativeList();$('history-source').value='archived';await nativeList();
old.resolve({data:[row('old-current')],nextCursor:'old-cursor'});await pending;
assert.equal($('native-list').children.length,1);assert.equal($('native-list').children[0].dataset.thread,'archived');
assert.equal(nativeCursor,null);assert(!$('history-search-submit').disabled);assert(!$('more').disabled);
''')

    def test_source_read_callback_retires_on_mode_query_close_and_owner(self):
        self.check(r'''
$('history-source').value='archived';await nativeList();const button=$('native-list').querySelector('.native-read');await button.onclick();
const callbacks=reads[0].callbacks;assert(callbacks.valid());
$('history-source').value='current';assert(!callbacks.valid());await button.onclick();assert.equal(reads.length,1);
$('history-source').value='archived';$('history-search').value='other';assert(!callbacks.valid());
$('history-search').value='Keep + Café';$('history').open=false;assert(!callbacks.valid());
$('history').open=true;generation++;assert(!callbacks.valid());callbacks.onReturn();assert.notEqual(document.activeElement,button);
''')

    def test_failed_more_retains_archive_origin_and_retry_same_scope(self):
        self.check(r'''
$('history-source').value='archived';let failed=false;
api=async path=>{calls.push(path);if(new URL(path,'http://local').searchParams.has('cursor')&&!failed){failed=true;throw Error('Unavailable archive page');}return {data:[row('A')],nextCursor:'archive-cursor'};};
await nativeList();const first=$('native-list').children[0];await nativeList('archive-cursor');
assert.equal($('native-list').children[0],first);assert.equal(nativeCursor,'archive-cursor');assert(!$('history-error').hidden);
await nativeList('archive-cursor');assert.equal(calls[1],calls[2]);assert.equal($('native-list').children.length,2);
''')

    def test_mode_change_retires_pending_id_home_and_keeps_new_rows(self):
        self.check(r'''
const old=deferred();$('history-id').value='known-A';
api=async path=>path==='/api/native/home'?old.promise:{data:[row('archived')],nextCursor:null};
const pending=readNativeById();$('history-source').value='archived';await nativeList();
old.resolve({home_namespace:'a'.repeat(64)});assert.equal(await pending,false);assert.equal(reads.length,0);
assert.equal($('native-list').children[0].dataset.nativeSource,'archived');assert(!$('history-id-read').disabled);
''')

if __name__=='__main__':unittest.main()
