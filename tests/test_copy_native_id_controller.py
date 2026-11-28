"""Header native-ID copying retains the validated source and current reader owner."""
from pathlib import Path
import shutil
import subprocess
import unittest
SOURCE=(Path(__file__).resolve().parents[1]/'codex_desk/static/history_reader.js').read_text()
FUNCTIONS=SOURCE[SOURCE.index('  let nativeIdCopy='):SOURCE.index('  function current(')]
SETUP=r'''
const assert=require('assert/strict'),elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,{disabled:false,textContent:''});return elements.get(id);};
let version=3,loading=false,live=true,source={id:'actual-child/接口?+plain'},requested={thread_id:source.id};
const reading={window:482,page:4,start:50000,scroll:182,find:'second Unicode phrase',range:'exact Café 🌱',backward:true};
const retained=JSON.stringify(reading),copies=[];
let write=async value=>{copies.push(value);};
const root={navigator:{clipboard:{writeText:value=>write(value)}}};
const current=ticket=>ticket===version&&live,available=()=>current(version),preserveChrome=change=>{change();assert.equal(JSON.stringify(reading),retained);};
const held=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
'''

@unittest.skipUnless(shutil.which('node'),'Node is required for native-ID copy checks')
class CopyNativeIdControllerTests(unittest.TestCase):
    def js(self,body):
        r=subprocess.run(['node','-e',SETUP+FUNCTIONS+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});'],text=True,capture_output=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_exact_full_plain_loaded_source_id_not_binding_metadata(self):
        self.js("assert(await copyNativeId());assert.deepEqual(copies,['actual-child/接口?+plain']);assert.equal(el('native-id-status').textContent,'Native conversation ID copied.');assert(!el('copy-native-id').disabled);assert.equal(JSON.stringify(reading),retained);")

    def test_loading_missing_failed_or_mismatched_source_is_unavailable(self):
        self.js("for(const value of [null,{id:'different-source'}]){source=value;nativeIdCopyControls();assert(el('copy-native-id').disabled);assert.equal(await copyNativeId(),false);}source={id:requested.thread_id};loading=true;nativeIdCopyControls();assert(el('copy-native-id').disabled);assert.equal(await copyNativeId(),false);assert.equal(copies.length,0);")

    def test_pending_copy_single_capture_no_double_write(self):
        self.js("const d=held();write=value=>{copies.push(value);return d.promise;};const action=copyNativeId();assert(el('copy-native-id').disabled);assert.equal(await copyNativeId(),false);assert.equal(copies.length,1);d.resolve();assert(await action);assert(!el('copy-native-id').disabled);")

    def test_close_and_new_source_do_not_retarget_late_copy_or_status(self):
        self.js("const d=held();write=value=>{copies.push(value);return d.promise;};const action=copyNativeId();version++;source=null;resetNativeIdCopy();assert(el('copy-native-id').disabled);source={id:'new-native-parent'};requested={thread_id:source.id};nativeIdCopyControls();assert(!el('copy-native-id').disabled);d.resolve();assert.equal(await action,false);assert.deepEqual(copies,['actual-child/接口?+plain']);assert.equal(el('native-id-status').textContent,'');assert(!el('copy-native-id').disabled);")

    def test_failed_copy_can_retry_same_source_without_read_or_mutation(self):
        self.js("write=async()=>{throw Error('permission unavailable');};assert.equal(await copyNativeId(),false);assert(el('native-id-status').textContent.includes('Could not copy'));assert(!el('copy-native-id').disabled);write=async value=>copies.push(value);assert(await copyNativeId());assert.deepEqual(copies,['actual-child/接口?+plain']);")

    def test_ordinary_source_reference_metadata_control_is_unchanged(self):
        # Independent literal format assertions keep this unit portable.
        section=SOURCE[SOURCE.index('  function copyControls('):SOURCE.index('  async function readEmbeddedReference(')]
        self.assertIn("Thread: ${str(source.id)}",section)
        self.assertIn("Turn: ${str(row.turn.id)||'unreported'}",section)
        self.assertIn("Copy source reference",section)
        self.assertEqual(SOURCE.count("id:source.id};nativeIdCopy=request"),1)

if __name__=='__main__':unittest.main()
