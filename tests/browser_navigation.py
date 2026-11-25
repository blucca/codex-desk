"""Controlled two-project navigation checks; no native task or provider call.

Run from the repository with a Python environment containing Playwright:
  DESK_TEST_TEMP=/path/to/workspace/temp python tests/browser_navigation.py
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-navigation-') as folder:
        desk = Desk('not-called', Path(folder) / 'home', Path(folder) / 'state')
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                try:
                    page = await browser.new_page(viewport={'width':390, 'height':844})
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    await page.goto(f'http://127.0.0.1:{server.server_port}')
                    await page.wait_for_function('state.profiles.length > 0')
                    navigation = await page.evaluate('''async () => {
                        const original=api, controls={}, calls=[];
                        const snapshot={profiles:[{id:'default',name:'Current Codex'}],sessions:[
                          {id:'a',name:'Project A',cwd:'/project/a',profile:'default',status:'ready'},
                          {id:'b',name:'Project B',cwd:'/project/b',profile:'default',status:'ready'}],pending:{}};
                        state=snapshot;selected='b';$('prompt').value='Unsent B';$('prompt').dispatchEvent(new Event('input'));
                        api=async(path,data)=>{
                          calls.push({path,data});
                          if(path==='/api/open')return new Promise(resolve=>controls[data.session]=resolve);
                          if(path==='/api/state')return snapshot;
                          if(path.startsWith('/api/events'))return [];
                          throw Error('Unexpected '+path);
                        };
                        const first=open('a');
                        const second=open('b');
                        controls.b({thread:{turns:[{items:[{id:'b-item',type:'agentMessage',text:'Only project B'}]}]}});
                        await second;
                        controls.a({thread:{turns:[{items:[{id:'a-item',type:'agentMessage',text:'Only project A'}]}]}});
                        await first;
                        const result={selected,title:$('title').textContent,activity:$('activity').textContent,
                          savedSelection:localStorage.getItem('codex-desk-session'),draftA:drafts.get('a') || '',promptB:$('prompt').value};
                        api=original;return result;
                    }''')
                    # A late successful turn response must never erase Project B's new draft.
                    submission = await page.evaluate('''async () => {
                        const original=api, calls=[], turnResolvers=[];
                        const snapshot={profiles:[{id:'default',name:'Current Codex'}],sessions:[
                          {id:'a',name:'Project A',cwd:'/project/a',profile:'default',status:'ready'},
                          {id:'b',name:'Project B',cwd:'/project/b',profile:'default',status:'ready'}],pending:{}};
                        api=async(path,data)=>{
                          calls.push({path,data});
                          if(path==='/api/open')return {thread:{turns:[]}};
                          if(path==='/api/state')return snapshot;
                          if(path==='/api/turn')return new Promise(resolve=>turnResolvers.push(resolve));
                          if(path.startsWith('/api/events'))return [];
                          throw Error('Unexpected '+path);
                        };
                        state=snapshot;await open('a');$('prompt').value='Task for A';
                        $('prompt').dispatchEvent(new Event('input'));
                        const submit=$('task').onsubmit({preventDefault(){}});
                        const sendDisabledWhilePending=$('send').disabled;
                        // A rapid second submit must not create another native turn.
                        const duplicate=$('task').onsubmit({preventDefault(){}});
                        await open('b');$('prompt').value='Unsent task for B';$('prompt').dispatchEvent(new Event('input'));
                        for(const resolve of turnResolvers)resolve({});await submit;await duplicate;
                        const keptDraft=$('prompt').value;
                        await open('a');const submittedDraft=$('prompt').value;
                        await open('b');const revisitedDraft=$('prompt').value;
                        const result={sendDisabledWhilePending,keptDraft,submittedDraft,revisitedDraft,
                          turnCalls:calls.filter(c=>c.path==='/api/turn')};
                        api=original;return result;
                    }''')
                    retry = await page.evaluate('''async () => {
                        const original=api;let attempts=0;
                        const snapshot={profiles:[{id:'default',name:'Current Codex'}],sessions:[
                          {id:'a',name:'Project A',cwd:'/project/a',profile:'default',status:'failed',error:'Native session could not open'}],pending:{}};
                        state=snapshot;
                        api=async(path)=>{
                          if(path==='/api/open'){
                            if(++attempts===1)throw Error('Fixture initialize rejected');
                            snapshot.sessions[0].status='ready';snapshot.sessions[0].error=null;
                            return {thread:{turns:[]}};
                          }
                          if(path==='/api/state')return snapshot;
                          if(path.startsWith('/api/events'))return [];
                          throw Error('Unexpected '+path);
                        };
                        await open('a');const failedVisible=!$('error').hidden && $('task').hidden;
                        await open('a');const result={failedVisible,retryErrorHidden:$('error').hidden,taskReady:!$('task').hidden&&!$('send').disabled};
                        api=original;return result;
                    }''')
                    approval = await page.evaluate('''async () => {
                        const original=api;let resolveApproval;
                        const snapshot={profiles:[{id:'default',name:'Current Codex'}],sessions:[
                          {id:'a',name:'Project A',cwd:'/project/a',profile:'default',status:'approval'},
                          {id:'b',name:'Project B',cwd:'/project/b',profile:'default',status:'approval'}],pending:{
                          a:[{id:9,method:'item/commandExecution/requestApproval',params:{command:'Verify A'}}],
                          b:[{id:9,method:'item/tool/requestUserInput',params:{questions:[{id:'choice',header:'B',question:'Next task?',isOther:true}]}}]}};
                        state=snapshot;
                        api=async(path)=>{
                          if(path==='/api/open')return {thread:{turns:[]}};
                          if(path==='/api/approval')return new Promise(resolve=>resolveApproval=resolve);
                          if(path==='/api/state')return snapshot;
                          if(path.startsWith('/api/events'))return [];
                          throw Error('Unexpected '+path);
                        };
                        await open('a');const accepted=$('approvals').querySelector('button').onclick();
                        await open('b');$('approvals').querySelector('input').value='Unsent answer for B';
                        resolveApproval({});await accepted;
                        const result={bRequestPreserved:requests.has('9'),bAnswerPreserved:$('approvals').querySelector('input')?.value==='Unsent answer for B'};
                        api=original;return result;
                    }''')
                    result={'navigation':navigation,'submission':submission,'retry':retry,'approval':approval,'javascriptErrors':errors,'nativeTurns':0}
                    print(json.dumps(result, indent=2), flush=True)
                    assert navigation['selected']=='b' and navigation['title']=='Project B' and navigation['activity']=='Only project B' and navigation['savedSelection']=='b', result
                    assert navigation['draftA']=='' and navigation['promptB']=='Unsent B', result
                    assert submission['sendDisabledWhilePending'] and submission['keptDraft']=='Unsent task for B' and submission['revisitedDraft']=='Unsent task for B' and submission['submittedDraft']=='', result
                    assert all(retry.values()) and all(approval.values()), result
                    assert len(submission['turnCalls'])==1 and submission['turnCalls'][0]['data']['session']=='a' and not errors, result
                finally:
                    await browser.close()
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()
            desk.close()
            desk.store.db.close()


if __name__=='__main__':
    asyncio.run(check())
