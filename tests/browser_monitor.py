"""Controlled local multi-project status and latest-output check; no provider calls."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

if not os.environ.get('DESK_USE_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-monitor-') as folder:
        desk = Desk('not-called', Path(folder) / 'home', Path(folder) / 'state')
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                try:
                    page = await browser.new_page(viewport={'width':390, 'height':844})
                    errors=[]
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    await page.goto(f'http://127.0.0.1:{server.server_port}')
                    await page.wait_for_function('state.profiles.length > 0')
                    result=await page.evaluate('''async () => {
                      const snapshot={profiles:[{id:'default',name:'Current Codex'}],sessions:[
                        {id:'a',name:'Build project A',cwd:'/project/a',profile:'default',status:'running'},
                        {id:'b',name:'Read project B',cwd:'/project/b',profile:'default',status:'ready'}],pending:{}};
                      let rows=[], calls=[];
                      api=async(path,data)=>{
                        calls.push({path,data});
                        if(path==='/api/state')return structuredClone(snapshot);
                        if(path.startsWith('/api/events')){const r=rows;rows=[];return r;}
                        throw Error('Unexpected '+path);
                      };
                      state=structuredClone(snapshot);selected='b';opening=false;
                      $('prompt').value='Unsent task for B';drafts.set('b',$('prompt').value);
                      $('task').hidden=false;draw();
                      $('activity').replaceChildren();items.clear();nodes.clear();
                      for(let i=0;i<35;i++)renderItem({id:'message-'+i,type:'agentMessage',text:'## Step '+i+'\\n\\n'+('Prior result with useful context. '.repeat(12))});
                      window.scrollTo(0,0);statePollAt=0;
                      snapshot.sessions[0].status='approval';await pollActivity();
                      const background={title:document.title,list:$('sessions').textContent,prompt:$('prompt').value,
                        selected,scroll:window.scrollY,requests:[...requests].length};
                      snapshot.sessions[0].status='ready';statePollAt=0;await pollActivity();
                      const completed={title:document.title,list:$('sessions').textContent,selected};
                      rows=[{seq:1,event:{method:'item/completed',params:{item:{id:'new',type:'agentMessage',text:'New useful result'}}}}];
                      await pollActivity();await new Promise(requestAnimationFrame);
                      const reading={scroll:window.scrollY,updates:latestUpdates,label:$('latest-output').textContent};
                      $('latest-output').click();await new Promise(requestAnimationFrame);
                      const jump={near:nearLatest(),updates:latestUpdates};
                      rows=[{seq:2,event:{method:'item/completed',params:{item:{id:'newer',type:'agentMessage',text:'Another new result\\n\\n'+('Long output '.repeat(100))}}}}];
                      await pollActivity();await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
                      const following={near:nearLatest(),updates:latestUpdates,prompt:$('prompt').value};
                      return {background,completed,reading,jump,following,calls,overflow:document.documentElement.scrollWidth>innerWidth,
                        module:typeof DeskActivity,packageUrl:document.querySelector('script[src="/activity.js"]')?.src};
                    }''')
                    assert '1 active' in result['background']['title'], result
                    assert 'approval' in result['background']['list'], result
                    assert result['background']['selected']=='b' and result['background']['requests']==0, result
                    assert result['background']['scroll']==0, result
                    assert result['completed']['title']=='Codex Desk' and 'running' not in result['completed']['list'], result
                    assert result['reading']['scroll']==0 and result['reading']['updates']==1, result
                    assert result['jump']=={'near':True,'updates':0}, result
                    assert result['following']['near'] and result['following']['updates']==0, result
                    assert result['following']['prompt']=='Unsent task for B', result
                    assert not result['overflow'] and not errors, (result,errors)
                    assert not any(c['path'].startswith('/api/turn') or c['path']=='/api/open' for c in result['calls']), result
                    result.update(status='passed',js_errors=errors,native_turns=0,installed_package=__import__('codex_desk.server',fromlist=['x']).__file__)
                    if os.environ.get('DESK_RESULT'):
                        Path(os.environ['DESK_RESULT']).write_text(json.dumps(result,ensure_ascii=False,indent=2))
                    print(json.dumps(result,ensure_ascii=False))
                finally:
                    await browser.close()
        finally:
            server.shutdown();worker.join(timeout=5);server.server_close();desk.close();desk.store.db.close()

if __name__=='__main__':
    asyncio.run(check())
