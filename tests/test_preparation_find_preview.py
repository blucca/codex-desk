"""Maintained sample saved-work lookup carries exact owners and original Unicode."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('find_preview',ROOT/'examples/build_browser_preview.py')
preview=importlib.util.module_from_spec(spec);spec.loader.exec_module(preview)
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')

@unittest.skipUnless(NODE,'Node required for sample API')
class PreparationFindPreviewTests(unittest.TestCase):
    def test_current_sample_query_pages_original_sources_without_saving(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            output=preview.build(Path(tmp)/'sample')
            script=r'''
const fs=require('fs'),vm=require('vm');
const text='Prefix '+('unrelated '.repeat(80))+'Straße café🙂 ＦＩＸ retained evidence. Tail';
const saved={sessions:[{id:'a',name:'Task a',cwd:'/sample/a',profile:'default',status:'saved',updated:2},{id:'b',name:'Task b',cwd:'/sample/b',profile:'default',status:'saved',updated:1,archived:true}],drafts:{a:{text,mode:'plan',revision:1},b:{text,mode:'native',revision:3}},followups:{b:{entries:[{id:'entry',text:'Revised retry evidence',mode:'native',revision:4,state:'queued',order:0}],reservation:{entry_id:'entry',text:'Captured retry evidence',token:'token',mode:'plan',revision:2,state:'reserved'}}},indexed:false,nextId:1};
let stored=JSON.stringify(saved),writes=0;
global.localStorage={getItem:()=>stored,setItem:(_key,value)=>{writes++;stored=value;}};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1'};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={open:()=>{},fetch:()=>{throw Error('External request');}};
vm.runInThisContext(fs.readFileSync(process.argv[1]+'/sample-data.js','utf8'));
vm.runInThisContext(fs.readFileSync(process.argv[1]+'/preview-api.js','utf8'));
(async()=>{
 const get=async path=>{const r=await window.fetch(path);return {status:r.status,body:await r.json()};};
 const q=encodeURIComponent('STRASSE CAFÉ🙂 fix');
 const all=await get('/api/preparation?q='+q+'&archived=true&limit=1');
 const later=await get('/api/preparation?q='+q+'&archived=true&limit=1&offset=1');
 const scoped=await get('/api/preparation?q='+q+'&cwd='+encodeURIComponent('/sample/a'));
 const lifecycle=await get('/api/preparation?q=retry%20evidence&archived=true');
 const missing=await get('/api/preparation?q=absent');
 const invalid=await get('/api/preparation?q=one&q=two');
 process.stdout.write(JSON.stringify({all,later,scoped,lifecycle,missing,invalid,writes,preserved:JSON.parse(stored)}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
            r=subprocess.run([NODE,'-e',script,str(output)],text=True,capture_output=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stderr);data=json.loads(r.stdout)
            for key in ('all','later','scoped','lifecycle','missing'):self.assertEqual(data[key]['status'],200)
            first=data['all']['body']['lookup'];second=data['later']['body']['lookup']
            self.assertEqual(first['total'],2);self.assertTrue(first['has_more']);self.assertFalse(second['has_more'])
            self.assertEqual([first['results'][0]['session_id'],second['results'][0]['session_id']],['a','b'])
            for hit in (first['results'][0],second['results'][0]):
                self.assertEqual(hit['match_text'],'Straße café🙂 ＦＩＸ');self.assertLessEqual(len(hit['snippet']),422)
            self.assertEqual(data['scoped']['body']['lookup']['total'],1)
            hits=data['lifecycle']['body']['lookup']['results']
            self.assertEqual([(x['kind'],x['revision'],x['mode']) for x in hits],[('followup',4,'native'),('reservation',2,'plan')])
            self.assertEqual(data['missing']['body']['lookup']['total'],0)
            self.assertEqual(data['invalid']['status'],400)
            self.assertEqual(data['writes'],0)
            self.assertEqual(data['preserved']['drafts']['b']['revision'],3)
            self.assertIn('./preparation-find.js',(output/'index.html').read_text())
