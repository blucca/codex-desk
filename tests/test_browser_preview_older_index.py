"""Static sample truthfully projects the explicit older-index API contract."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(os.environ.get('DESK_PREVIEW_PRODUCT', str(Path(__file__).resolve().parents[1])))
API = Path(os.environ.get('DESK_PREVIEW_API', str(ROOT / 'examples/browser-preview/preview-api.js')))
NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')
spec = importlib.util.spec_from_file_location('preview_older_index_build', ROOT / 'examples/build_browser_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)

HARNESS = r'''
const fs=require('fs'),vm=require('vm');
const seed=JSON.parse(process.argv[3]),threads=JSON.parse(process.argv[2]);
const values=new Map([['codex-desk-browser-preview-v1',JSON.stringify(seed)],
  ['codex-desk-browser-preview-session-v1','desk-sample-checkout-thread']]);
let writes=0,external=0;
global.localStorage={getItem:key=>values.get(key)||null,setItem:(key,value)=>{writes++;values.set(key,value);}};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1'};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={DeskPreviewThreads:threads,open:()=>{},fetch:()=>{external++;throw new Error('Unexpected external request');}};
const evaluate=()=>vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const request=async(path,data)=>{
 const response=await window.fetch(path,data===undefined?{}:{method:'POST',body:JSON.stringify(data)});
 return {status:response.status,data:await response.json(),writes};
};
(async()=>{
 evaluate();
 const initial=await request('/api/history/index');
 const unavailableBefore=await request('/api/history/index',{op:'older'});
 const indexed=await request('/api/history/index',{op:'recent',limit:200});
 const before=window.DeskBrowserPreview.snapshot();
 const legacy=await request('/api/history/index',{});
 const unsupported=[];
 for(const op of ['older','retry','everything',null,0])unsupported.push(await request('/api/history/index',{op}));
 const after=window.DeskBrowserPreview.snapshot();
 const writesBeforeReload=writes;evaluate();const reopened=await request('/api/history/index');
 process.stdout.write(JSON.stringify({initial,unavailableBefore,indexed,legacy,before,after,unsupported,reopened,
   writesBeforeReload,writes,external,selected:values.get('codex-desk-browser-preview-session-v1')}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''


@unittest.skipUnless(NODE, 'Node is needed for sample API controller units')
class BrowserPreviewOlderIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        checkout = preview.sample_threads()[0]
        cls.seed = {'sessions': [{'id': 'desk-sample-checkout-thread', 'thread_id': checkout['id'],
                                 'name': checkout['name'], 'cwd': checkout['cwd'], 'profile': 'default',
                                 'status': 'saved', 'mode': 'native', 'archived': False}],
                    'indexed': False,
                    'drafts': {'desk-sample-checkout-thread': {'text': 'Saved Plan task', 'mode': 'plan', 'revision': 2}},
                    'followups': {'desk-sample-checkout-thread': {'entries': [
                        {'id': f'queued-{i}', 'text': f'Saved Work follow-up {i}', 'mode': 'native',
                         'order': i, 'revision': 1, 'state': 'queued'} for i in (1, 2)], 'reservation': None}},
                    'nextId': 3}
        completed = subprocess.run([NODE, '-e', HARNESS, str(API), json.dumps(preview.sample_threads()),
                                    json.dumps(cls.seed)], capture_output=True, text=True, timeout=10, check=True)
        cls.result = json.loads(completed.stdout)

    def test_four_sample_histories_never_offer_older_or_pending_index_work(self):
        result = self.result
        self.assertEqual(result['initial']['writes'], 0)
        self.assertEqual(result['initial']['data']['job']['status'], 'idle')
        self.assertEqual(result['initial']['data']['projects'], [])
        expected_projects = sorted(thread['cwd'] for thread in preview.sample_threads())
        for response in (result['initial'], result['indexed'], result['legacy'], result['reopened']):
            job = response['data']['job']
            self.assertEqual(response['status'], 200)
            self.assertEqual(job['mode'], 'recent')
            self.assertFalse(job['older_available'])
            self.assertFalse(job['resumable'])
            self.assertEqual(job['retryable_failures'], 0)
            self.assertFalse(job['has_more'])
        for response in (result['indexed'], result['legacy'], result['reopened']):
            self.assertEqual(response['data']['job']['status'], 'completed')
            self.assertEqual((response['data']['job']['seen'], response['data']['job']['indexed']), (4, 4))
            self.assertEqual(response['data']['projects'], expected_projects)
        self.assertEqual(result['writesBeforeReload'], result['writes'])
        self.assertEqual(result['external'], 0)

    def test_unavailable_or_unknown_operations_preserve_saved_preparation_and_selection(self):
        result = self.result
        self.assertEqual(result['unavailableBefore']['status'], 400)
        self.assertEqual(result['unavailableBefore']['writes'], 0)
        for response in result['unsupported']:
            self.assertEqual(response['status'], 400)
            self.assertEqual(response['writes'], 2)
        self.assertEqual(result['before'], result['after'])
        self.assertEqual(result['after']['drafts'], self.seed['drafts'])
        self.assertEqual(result['after']['followups'], self.seed['followups'])
        self.assertEqual(result['selected'], 'desk-sample-checkout-thread')


if __name__ == '__main__':
    unittest.main()
