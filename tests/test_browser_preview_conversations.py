"""Sample grouped recall shares exact source/query/page semantics, not new storage."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import test_browser_preview_task_review as base

class BrowserPreviewConversationTests(unittest.TestCase):
    run_js=base.BrowserPreviewTaskReviewTests.run_js

    def test_four_builds_preserve_default_sources_and_offer_deliberate_fixture_only(self):
        folder=Path(os.environ.get('DESK_TEST_TEMP',base.ROOT/'temp'));folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder,prefix='grouped-sample-build-') as tmp:
            for rich in (False,True):
                for embedded in (False,True):
                    out=base.preview.build(Path(tmp)/f'{rich}-{embedded}',embedded=embedded,session_reading_fixture=rich)
                    self.assertEqual((out/'index.html').read_text().count('id="preview-group-prepare"'),1)
                    threads=base.preview.reading_fixture()[0] if rich else base.preview.sample_threads()
                    self.assertEqual(len(threads),4);self.assertEqual(sum(len(t['items']) for h in threads for t in h['turns']),15 if rich else 13)
                    self.assertEqual((out/'recall.js').read_bytes(),(base.ROOT/'codex_desk/static/recall.js').read_bytes())

    def test_shallow_source_mount_does_not_evaluate_historical_parent_default(self):
        source=(base.ROOT/'examples/build_browser_preview.py').read_text().replace('ROOT = Path(__file__).resolve().parents[1]',"ROOT = Path('/source')")
        script="import sys;sys.argv=['build_browser_preview.py','--help'];exec("+repr(source)+")"
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('--out',result.stdout)

    @unittest.skipUnless(base.NODE,'Node required')
    def test_group_source_paging_unicode_item_counts_and_no_extra_native_reads(self):
        self.run_js(r'''
const B=(await request('/api/import',{thread:'sample-docs-thread'})).id;
await request('/api/draft',{session:B,text:'Existing B Plan',mode:'plan',revision:0});for(const mode of ['native','plan'])await request('/api/followups',{session:B,text:'Existing '+mode,mode});
const before=window.DeskBrowserPreview.snapshot(),raw=Object.fromEntries(stored),calls=window.DeskBrowserPreview.requests.length;
const f=window.DeskBrowserPreview.groupFixture;assert.equal(f.prepare(),true);assert.equal(f.prepare(),false);
assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);assert.deepEqual(Object.fromEntries(stored),raw);assert.equal(window.DeskBrowserPreview.requests.length,calls);
await request('/api/history/index',{});const q=encodeURIComponent('Retry discovery Cafe\u0301 项目 😀');
const plain=await request('/api/recall?q='+q);assert.equal(plain.total,66);assert.equal(plain.results.length,30);assert(plain.results.every(r=>r.thread_id===f.source));
const groups=await request('/api/recall?q='+q+'&view=conversations');assert.equal(groups.total,2);assert.equal(groups.item_total,66);assert.deepEqual(groups.results.map(r=>r.match_count),[65,1]);
const own=await request('/api/recall?q='+q+'&source_thread='+f.other);assert.equal(own.total,1);assert.equal(own.results.length,1);assert.equal(own.results[0].match_text,f.query);
const page=await request('/api/recall?q='+q+'&source_thread='+f.source+'&offset=30');assert.equal(page.total,65);assert.equal(page.results.length,30);assert(page.results.every(r=>r.thread_id===f.source));
assert(!window.DeskBrowserPreview.requests.some(r=>r.path.startsWith('/api/native/thread')));assert.equal(external,0);
''')

    @unittest.skipUnless(base.NODE,'Node required')
    def test_bound_archived_and_preparation_sources_share_exact_scope(self):
        self.run_js(r'''
const f=window.DeskBrowserPreview.groupFixture;f.prepare();const A=(await request('/api/import',{thread:f.source})).id;
await request('/api/history/index',{});await request('/api/draft',{session:A,text:f.query+' local draft',mode:'plan',revision:0});
const q=encodeURIComponent(f.query),groups=await request('/api/recall?q='+q+'&view=conversations');
assert.equal(groups.item_total,67);assert.equal(groups.results.find(r=>r.group_id===A).match_count,66);
assert.equal((await request('/api/recall?q='+q+'&source_thread='+f.source)).total,0);
assert.equal((await request('/api/recall?q='+q+'&source_session='+A)).total,66);
await request('/api/archive',{session:A,archived:true});assert.equal((await request('/api/recall?q='+q+'&source_session='+A)).total,0);
assert.equal((await request('/api/recall?q='+q+'&source_session='+A+'&archived=true')).total,66);
for(const suffix of ['&view=bad','&view=items&view=conversations','&source_thread=','&source_session='+A+'&source_thread='+f.other])assert.equal((await window.fetch('/api/recall?q='+q+suffix)).status,400);
const before=window.DeskBrowserPreview.snapshot();load('sample-data.js');load('preview-api.js');assert.equal(count(),13);assert(!window.DeskBrowserPreview.groupFixture.prepared);assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);
''')

if __name__=='__main__':unittest.main()
