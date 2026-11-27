#!/usr/bin/env python3
"""Reproduce the static sample workflow in isolated desktop and mobile browsers.

Build with examples/build_browser_preview.py, then run this checker with a
Playwright Python environment. --site selects the generated demo directory;
--evidence keeps screenshots and a JSON receipt. No Desk backend is started.
"""
import argparse
import asyncio
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit


THREAD = "sample-checkout-thread"
SESSION = "desk-" + THREAD
TURN = "sample-checkout-turn"
ITEM = "sample-checkout-answer"
QUERY = "retry budget"
FIRST = "Review the retry budget before changing timeout handling."
SECOND = "Verify checkout retry behavior and record the result."
DRAFT = "Plan the next timeout review; keep this draft unsent."
REUSED_DRAFT = DRAFT + "\n\n" + FIRST


def check_preparation_api():
    """Exercise browser-local preparation against the maintained three histories."""
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('browser_preview_build', root / 'examples/build_browser_preview.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    node = os.environ.get('DESK_TEST_NODE') or shutil.which('node')
    assert node, 'Node is required for the local preparation API check'
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const fixture=JSON.parse(process.argv[2]),stored=new Map();let external=0;
global.localStorage={getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value),removeItem:key=>stored.delete(key)};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1',assign:()=>{throw Error('Unexpected installer navigation');}};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={DeskPreviewThreads:fixture.threads,DeskPreviewCasefold:fixture.casefold,open:()=>{throw Error('Unexpected installer popup');},fetch:()=>{++external;throw Error('Unexpected HTTP request');}};
const source=fs.readFileSync(process.argv[1],'utf8');
function load(){vm.runInThisContext(source);}
async function request(path,data){const response=await window.fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});return {status:response.status,body:await response.json()};}
(async()=>{
 load();assert.equal(fixture.threads.length,3);
 const pristine=window.DeskBrowserPreview.snapshot();
 const home=(await request('/api/native/home')).body.home_namespace;assert.match(home,/^[a-f0-9]{64}$/);
 const original=fixture.threads[0],turn=original.turns[0];
 const read=(await request('/api/native/task-response?thread='+original.id+'&turn='+turn.id));assert.equal(read.status,200);
 assert.deepEqual(read.body.thread,original);assert.equal(read.body.response.item_id,turn.items.at(-1).id);
 assert.equal(read.body.response.phase,null);assert.equal(read.body.response.selection,'last_assistant_message');
 const source=await request('/api/native/evidence-source?home='+home+'&thread='+original.id);
 assert.equal(source.status,200);assert.deepEqual(source.body.thread,original);assert.equal(source.body.home_namespace,home);
 for(const bad of ['/api/native/home?x=1','/api/native/task-response?thread='+original.id+'&turn='+turn.id+'&turn=other',
   '/api/native/task-response?thread='+original.id,'/api/native/task-response?thread='+original.id+'&turn=+',
   '/api/native/evidence-source?home='+('0'.repeat(64))+'&thread='+original.id,
   '/api/native/evidence-source?home='+home+'&thread=missing'])assert.equal((await request(bad)).status,400,bad);
 for(const endpoint of ['/api/native','/api/native/thread?id='+original.id,'/api/native/home','/api/native/task-response?thread='+original.id+'&turn='+turn.id,'/api/native/evidence-source?home='+home+'&thread='+original.id])assert.equal((await request(endpoint,{})).status,400);
 assert.equal((await request('/api/native/task-response?thread='+original.id+'&turn=missing')).body.response.status,'turn_unavailable');
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),pristine,'Native sample reads changed preparation');
 load();assert.equal((await request('/api/native/home')).body.home_namespace,home);
 const imported=await request('/api/import',{thread:fixture.thread});assert.equal(imported.status,200);const id=imported.body.id;
 const initial=window.DeskBrowserPreview.snapshot();
 assert.equal((await request('/api/turn/request?session='+encodeURIComponent(id))).status,404);
 assert.equal((await request('/api/turn/request?session='+encodeURIComponent(id)+'&token=00000000-0000-4000-8000-000000000000')).status,404);
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),initial,'Read-only missing Run receipt mutated sample storage');
 await request('/api/draft',{session:id,text:fixture.draft,mode:'plan',revision:0,writer:'sample-page',sequence:1});
 for(const [text,mode] of [[fixture.first,'plan'],[fixture.second,'native']])assert.equal((await request('/api/followups',{session:id,text,mode})).status,200);
 const before=window.DeskBrowserPreview.snapshot();const overview=await request('/api/preparation?archived=false');
 assert.equal(overview.status,200);assert.equal(overview.body.sessions.length,1);
 const row=overview.body.sessions[0];assert.equal(row.id,id);assert.equal(row.draft.text,fixture.draft);assert.equal(row.draft.mode,'plan');
 assert.deepEqual(row.followups,before.followups[id]);assert.equal(row.followups.reservation,null);assert.equal(typeof row.updated,'number');
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),before,'Overview mutated storage');
 assert.equal((await request('/api/preparation?archived=false&cwd='+encodeURIComponent(row.cwd))).body.sessions.length,1);
 assert.equal((await request('/api/preparation?archived=false&cwd='+encodeURIComponent(fixture.threads[1].cwd))).body.sessions.length,0);
 await request('/api/archive',{session:id,archived:true});assert.equal((await request('/api/preparation?archived=false')).body.sessions.length,0);
 assert.equal((await request('/api/preparation?archived=true')).body.sessions.length,1);await request('/api/archive',{session:id,archived:false});
 const reused=fixture.draft+'\n\n'+row.followups.entries[0].text;
 const saved=await request('/api/draft',{session:id,text:reused,mode:'plan',revision:row.draft.revision,writer:'sample-modal',sequence:1});assert.equal(saved.status,200);
 assert.deepEqual(window.DeskBrowserPreview.snapshot().followups[id],before.followups[id],'Reuse changed the source queue');
 const conflict=await request('/api/draft',{session:id,text:'Other sample page',mode:'native',revision:row.draft.revision,writer:'sample-page',sequence:2});
 assert.equal(conflict.status,409);assert.deepEqual(conflict.body.current,saved.body);
 const duplicate=await request('/api/draft',{session:id,text:reused,mode:'plan',revision:row.draft.revision,writer:'sample-modal',sequence:1});
 assert.deepEqual(duplicate.body,saved.body);assert.equal(duplicate.status,200);
 const latest=await request('/api/draft',{session:id,text:reused+'\nReviewed once more.',mode:'plan',revision:row.draft.revision,writer:'sample-modal',sequence:2});
 assert.equal(latest.status,200);assert.equal(latest.body.revision,saved.body.revision+1);
 const preserved=window.DeskBrowserPreview.snapshot(),requests=window.DeskBrowserPreview.requests;
 load();assert.deepEqual(window.DeskBrowserPreview.snapshot(),preserved);
 const restored=(await request('/api/preparation?archived=false')).body.sessions[0];
 assert.deepEqual(restored.draft,latest.body);assert.deepEqual(restored.followups,before.followups[id]);
 // The sample uses the same normalized, literal lookup contract as installed Desk.
 await request('/api/draft',{session:id,text:'Checkout '+fixture.literal,mode:'plan',revision:latest.body.revision});
 const docs=(await request('/api/import',{thread:fixture.threads[1].id})).body.id;
 const mobile=(await request('/api/import',{thread:fixture.threads[2].id})).body.id;
 await request('/api/draft',{session:docs,text:'Documentation '+fixture.literal,mode:'plan',revision:0});
 await request('/api/draft',{session:mobile,text:'Independent mobile preparation',mode:'plan',revision:0});
 const lookupBaseline=window.DeskBrowserPreview.snapshot();
 const phrase=encodeURIComponent(fixture.query),found=await request('/api/preparation?q='+phrase+'&limit=30&offset=0');
 assert.equal(found.status,200);assert.equal(found.body.lookup.total,2);assert.equal(found.body.sessions.length,3);
 assert.deepEqual(new Set(found.body.lookup.results.map(x=>x.session_id)),new Set([id,docs]));
 assert(found.body.lookup.results.every(x=>x.match_text===fixture.literal && x.kind==='draft' && x.control==='draft'));
 assert.equal((await request('/api/preparation?q='+phrase+'&cwd='+encodeURIComponent(fixture.threads[1].cwd))).body.lookup.total,1);
 assert.equal((await request('/api/preparation?q='+encodeURIComponent('.*[missing]'))).body.lookup.total,0);
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),lookupBaseline,'Literal or scoped lookup wrote storage');
 for(const bad of ['q=x','q='+('x'.repeat(201)),'q='+phrase+'&q='+phrase,'q='+phrase+'&limit=0',
   'q='+phrase+'&limit=51','q='+phrase+'&offset=01','q='+phrase+'&other=1','limit=30','q='+phrase+'&cwd=a&cwd=b'])
   assert.equal((await request('/api/preparation?'+bad)).status,400,bad);
 assert.equal((await request('/api/preparation?q=+')).body.lookup.total,0);
 await request('/api/archive',{session:id,archived:true});
 assert.equal((await request('/api/preparation?q='+phrase)).body.lookup.total,1);
 assert.equal((await request('/api/preparation?q='+phrase+'&archived=true')).body.lookup.total,2);
 await request('/api/archive',{session:id,archived:false});
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),lookupBaseline);
 assert(!requests.some(r=>/\/api\/(turn|followups\/send)$/.test(r.path)));assert.equal(external,0);
 console.log(JSON.stringify({passed:true,sample_histories:3,overview_sessions:1,prepared_followups:2,
   overview_read_only:true,exact_project_scope:true,archive_scope:true,literal_unicode_lookup:true,lookup_owners:3,duplicate_phrase_owners:2,lookup_read_only:true,source_queue_unchanged:true,
   reload_preserved:true,conflict_status:409,same_page_sequence_recovery:true,native_model_calls:0,external_http_requests:external}));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    fixture = {'threads': build.sample_threads(), 'thread': THREAD,
               'draft': DRAFT, 'first': FIRST, 'second': SECOND,
               'literal': 'Straße café🙂 ＦＩＸ .*[retry]', 'query': 'strasse café🙂 fix .*[retry]',
               'casefold': {chr(n): chr(n).casefold() for n in range(0x110000)
                            if chr(n).casefold() != chr(n).lower()}}
    result = subprocess.run([node, '-e', script, str(root / 'examples/browser-preview/preview-api.js'),
                             json.dumps(fixture)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@contextmanager
def static_server(site):
    """Fail visibly if any application API escapes the browser fixture."""
    received, escaped_api = [], []

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            received.append({"path": self.path, "method": "GET"})
            if "/api/" in path:
                escaped_api.append(self.path)
                self.send_error(502, "Application API escaped browser fixture")
            else:
                super().do_GET()

        def do_POST(self):
            escaped_api.append(self.path)
            received.append({"path": self.path, "method": "POST"})
            self.send_error(502, "Static preview cannot execute application requests")

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(site.parent)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/{site.name}/", received, escaped_api
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def normalized_request(record):
    address = record.get("path", record.get("url", ""))
    parsed = urlsplit(address)
    data = record.get("data", record.get("body", {})) or {}
    if isinstance(data, str):
        data = json.loads(data)
    return {"path": parsed.path, "method": record.get("method", "GET").upper(),
            "query": parse_qs(parsed.query), "data": data}


async def check(playwright, site, evidence, width, chromium, public_url=None):
    errors, console_errors, external, failures, phases, captured = [], [], [], [], [], []
    with static_server(site) as (url, received, escaped_api):
        url = public_url or url
        browser = await playwright.chromium.launch(executable_path=chromium,
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(viewport={"width": width, "height": 900 if width > 390 else 844})
        # Clipboard is isolated to this checker; no system clipboard/account is used.
        await context.add_init_script("""Object.defineProperty(navigator, 'clipboard', {configurable:true,
            value:{async writeText(text){(window.__deskSampleCopies ||= []).push(text);}}});""")
        page = await context.new_page()
        page.set_default_timeout(10_000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("requestfailed", lambda request: failures.append({"url": request.url, "error": request.failure}))

        async def isolated(route):
            parsed = urlsplit(route.request.url)
            if parsed.netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", isolated)

        async def snapshot():
            return await page.evaluate("DeskBrowserPreview.snapshot()")

        async def log():
            return [normalized_request(row) for row in await page.evaluate("DeskBrowserPreview.requests")]

        async def checkpoint(name):
            assert not errors and not console_errors, (errors, console_errors)
            assert not external and not escaped_api and not failures, (external, escaped_api, failures)
            assert await page.evaluate("""() => document.documentElement.scrollWidth <= innerWidth &&
                [...document.querySelectorAll('dialog[open]')].every(n => n.scrollWidth <= n.clientWidth)"""), name + " horizontal overflow"
            phases.append(name)
            await page.screenshot(path=str(evidence / f"{width}-{name}.png"))

        async def wait_saved(text, mode):
            await page.wait_for_function("""v => {
                const drafts=DeskBrowserPreview.snapshot().drafts;
                const d=drafts && drafts[v.id];
                return d && d.text===v.text && d.mode===v.mode;
            }""", arg={"id": SESSION, "text": text, "mode": mode})

        async def followups():
            return await page.locator("#followup-list .followup-entry").evaluate_all("""rows => rows.map(n => ({
                id:n.dataset.followup, heading:n.querySelector('h3').textContent, text:n.querySelector('pre').textContent}))""")

        try:
            await page.goto(url)
            await page.wait_for_function("document.querySelector('#home-list').getAttribute('aria-busy') === 'false'")
            assert await page.locator("#home-list .native-row").count() == 3
            assert "Sample" in await page.locator("#home-list").inner_text()
            banner = page.locator("#preview-banner")
            assert await banner.is_visible()
            starter = await page.locator("#preview-start").bounding_box()
            assert starter and starter["y"] + starter["height"] < await page.evaluate("innerHeight"), "Sample action is below the first viewport"
            provenance = (await banner.inner_text()).lower()
            assert "preview" in provenance and "sample" in provenance
            install_links = await banner.locator("a").evaluate_all("nodes => nodes.map(n => ({text:n.textContent,href:n.href}))")
            assert any("install" in link["text"].lower() and "github.com/blucca/codex-desk" in link["href"] for link in install_links), install_links
            assert (await snapshot())["sessions"] == []
            assert not any(row["path"] == "/api/history/index" and row["method"] == "POST" for row in await log())
            await checkpoint("home")

            await page.locator("#preview-start").click()
            assert await page.locator("#recall-query").input_value() == QUERY
            await page.wait_for_function("!document.querySelector('#recall-index').disabled")
            await page.locator("#recall-query").fill(QUERY)
            await page.locator("#recall-search").click()
            await page.wait_for_function("!document.querySelector('#recall-search').disabled")
            assert await page.locator(".recall-result").count() == 0, "History was indexed without explicit action"
            assert (await snapshot())["sessions"] == []
            assert "not indexed yet" in await page.locator("#recall-summary").inner_text()
            assert await page.locator("#recall-index").count() == 1
            assert await page.locator("#recall-index").evaluate("n => n.parentElement.id === 'recall-actions'")
            assert await page.locator("#recall-index").evaluate("""n => {
                const button=n.getBoundingClientRect(),modal=document.querySelector('#recall').getBoundingClientRect();
                return button.top >= modal.top && button.bottom <= Math.min(modal.bottom,innerHeight) &&
                    button.left >= modal.left && button.right <= modal.right;
            }"""), "Explicit first-use index action is clipped outside the visible search dialog"
            await checkpoint("literal-search")

            before = sum(row["path"] == "/api/recall" for row in await log())
            await page.locator("#recall-index").click()
            row = page.locator(f'.recall-result[data-thread="{THREAD}"][data-item="{ITEM}"]')
            await row.wait_for()
            await page.wait_for_function("!document.querySelector('#recall-search').disabled")
            assert await page.locator("#recall-query").input_value() == QUERY
            assert "scan completed" in await page.locator("#recall-index-status").inner_text()
            assert await page.locator("#recall-index").evaluate("n => n.parentElement.id === 'recall-index-actions'")
            requests = await log()
            assert sum(r["path"] == "/api/recall" for r in requests) == before + 1, "Explicit index did not refresh unchanged query exactly once"
            assert sum(r["path"] == "/api/history/index" and r["method"] == "POST" for r in requests) == 1
            assert all(r["query"].get("q") == [QUERY] for r in requests if r["path"] == "/api/recall")
            await checkpoint("indexed-search")

            await row.locator(".recall-read").click()
            await page.wait_for_function("document.querySelector('#history-reader-body').getAttribute('aria-busy') === 'false'")
            assert THREAD in await page.locator("#history-reader-binding").inner_text()
            matched = page.locator(".history-reader-target")
            assert await matched.get_attribute("data-turn-id") == TURN
            assert await matched.get_attribute("data-item-id") == ITEM
            assert QUERY in (await matched.inner_text()).lower()
            assert (await snapshot())["sessions"] == [], "Read imported or resumed the sample"
            reads = [r for r in await log() if r["path"] == "/api/native/thread"]
            assert reads and reads[-1]["query"].get("id") == [THREAD], reads
            await checkpoint("read-original")
            await page.locator("#history-reader-back").click()

            await row.locator(".recall-open").click()
            await page.wait_for_function("!document.querySelector('#task').hidden && !document.querySelector('#recall').open")
            sessions = (await snapshot())["sessions"]
            assert len(sessions) == 1 and sessions[0]["id"] == SESSION and sessions[0]["thread_id"] == THREAD, sessions
            assert await page.locator("#activity .recall-target").get_attribute("data-item-id") == ITEM
            imports = [r for r in await log() if r["path"] == "/api/import"]
            assert len(imports) == 1 and imports[0]["data"]["thread"] == THREAD, imports
            await checkpoint("continue-same-thread")
            await page.wait_for_function("!$('native-outcome').hidden")
            await page.locator('#native-outcome > summary').click()
            boundary = len(await log())
            await page.locator('#read-task-response').click()
            await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            assert await page.locator('.history-reader-target').get_attribute('data-turn-id') == TURN
            assert await page.locator('.history-reader-target').get_attribute('data-item-id') == ITEM
            response_reads = (await log())[boundary:]
            assert len([r for r in response_reads if r['path']=='/api/native/task-response']) == 1
            assert all(r['method']=='GET' for r in response_reads)
            await page.locator('#history-reader-back').click()
            await checkpoint('read-exact-sample-task-response')

            for count, text, mode in ((1, FIRST, "plan"), (2, SECOND, "native")):
                await page.locator("#prompt").fill(text)
                await page.locator("#turn-mode").select_option(mode)
                await page.locator("#prepare-followup").click()
                await page.wait_for_function("v => document.querySelector('#followup-count').textContent === String(v) && !document.querySelector('#prepare-followup').disabled", arg=count)
            rows = await followups()
            assert [r["text"] for r in rows] == [FIRST, SECOND], rows
            assert rows[0]["heading"].startswith("1. Plan") and rows[1]["heading"].startswith("2. Work")
            await page.locator(".followup-entry").nth(1).get_by_role("button", name="Move up", exact=True).click()
            await page.wait_for_function("v => document.querySelector('#followup-list pre').textContent === v", arg=SECOND)
            rows = await followups()
            assert [r["text"] for r in rows] == [SECOND, FIRST]
            assert rows[0]["heading"].startswith("1. Work") and rows[1]["heading"].startswith("2. Plan")
            await page.locator("#prompt").fill(DRAFT)
            await page.locator("#turn-mode").select_option("plan")
            await wait_saved(DRAFT, "plan")
            saved = await snapshot()
            queued_ids = [r["id"] for r in rows]
            await checkpoint("plan-and-followups")

            # Exercise the shipped query-free entry without native open/resume.
            before_review = await log()
            await page.locator("#show-preparation").click()
            await page.wait_for_function("document.querySelector('#preparation-list').getAttribute('aria-busy') === 'false'")
            prepared = page.locator(f'.preparation-session[data-session="{SESSION}"]')
            assert await prepared.count() == 1
            await prepared.locator('button[aria-label^="Review preparation in "]').click()
            assert await page.locator("#preparation-text").input_value() == DRAFT
            assert await page.locator("#preparation-mode").input_value() == "plan"
            assert await page.locator("#prompt").input_value() == DRAFT
            await page.locator("#preparation-copy").click()
            await page.wait_for_function("v => window.__deskSampleCopies?.at(-1) === v", arg=DRAFT)
            source = page.locator(f'.preparation-followup[data-followup="{queued_ids[1]}"]')
            await source.get_by_role("button", name="Use in this session draft", exact=True).click()
            assert await page.locator("#preparation-reuse").is_visible()
            assert await page.locator("#preparation-text").input_value() == DRAFT, "Reuse overwrote the draft without a choice"
            await page.locator("#preparation-append").click()
            assert await page.locator("#preparation-text").input_value() == REUSED_DRAFT
            assert await page.locator("#preparation-mode").input_value() == "plan"
            assert await page.locator("#prompt").input_value() == DRAFT, "Local review changed the active draft before Save"
            assert (await snapshot())["drafts"][SESSION]["text"] == DRAFT
            assert (await snapshot())["followups"][SESSION] == saved["followups"][SESSION]
            await source.get_by_role("button", name="Copy instruction", exact=True).click()
            await page.wait_for_function("v => window.__deskSampleCopies?.at(-1) === v", arg=FIRST)
            await page.locator("#preparation-save").click()
            await wait_saved(REUSED_DRAFT, "plan")
            await page.wait_for_function("!document.querySelector('#preparation-save').disabled")
            assert (await snapshot())["followups"][SESSION] == saved["followups"][SESSION], "Explicit reuse changed source order or instructions"
            review_requests = (await log())[len(before_review):]
            assert any(r["path"] == "/api/preparation" and r["method"] == "GET" for r in review_requests)
            assert not any(r["method"] == "POST" and r["path"] in {"/api/import", "/api/open", "/api/turn", "/api/followups", "/api/followups/send"} for r in review_requests)
            copied = await page.evaluate("window.__deskSampleCopies")
            before_open = len(await log())
            await page.locator("#preparation-save-open").click()
            await page.wait_for_function("!document.querySelector('#preparation').open && !document.querySelector('#task').hidden")
            assert await page.locator("#prompt").input_value() == REUSED_DRAFT
            assert await page.locator("#turn-mode").input_value() == "plan"
            assert (await snapshot())["followups"][SESSION] == saved["followups"][SESSION]
            opens = [r for r in (await log())[before_open:] if r["path"] == "/api/open"]
            assert len(opens) == 1 and opens[0]["data"]["session"] == SESSION
            saved = await snapshot()
            await checkpoint("prepared-work-reuse")
            captured.extend(await log())

            await page.reload()
            await page.wait_for_function("!document.querySelector('#task').hidden")
            await page.wait_for_function("document.querySelector('#followup-count').textContent === '2'")
            assert await page.locator("#prompt").input_value() == REUSED_DRAFT
            assert await page.locator("#turn-mode").input_value() == "plan"
            rows = await followups()
            assert [r["text"] for r in rows] == [SECOND, FIRST]
            assert [r["id"] for r in rows] == queued_ids
            preserved = await snapshot()
            assert preserved == saved, "Reload altered local sample preparation"
            await page.locator("#show-preparation").click()
            await page.wait_for_function("document.querySelector('#preparation-list').getAttribute('aria-busy') === 'false'")
            await page.locator(f'.preparation-session[data-session="{SESSION}"]').locator('button[aria-label^="Review preparation in "]').click()
            assert await page.locator("#preparation-text").input_value() == REUSED_DRAFT
            assert await page.locator("#preparation-mode").input_value() == "plan"
            assert await page.locator("#preparation-followups .preparation-followup").count() == 2
            assert await snapshot() == preserved, "Overview reread mutated restored preparation"
            await page.locator("#preparation-close").click()
            await page.locator("#followups summary").click()
            await checkpoint("preserved-after-reload")

            # Reviewed original A -> different existing unsent B -> exact A.
            destination_thread = "sample-docs-thread"
            destination = "desk-" + destination_thread
            destination_draft = "Plan tomorrow's installation check; retain this unsent task."
            quote = "Retry only transient failures; preserve the original timeout result."
            await page.locator("#browse").click()
            await page.locator('#native-list .native-row').filter(has_text='Sample documentation review').get_by_role('button', name='Resume with current settings', exact=True).click()
            await page.wait_for_function("id => selected===id && !opening", arg=destination)
            await page.locator("#prompt").fill(destination_draft)
            await page.locator("#turn-mode").select_option("plan")
            await page.wait_for_function("v => DeskBrowserPreview.snapshot().drafts[v.id]?.text===v.text && DeskBrowserPreview.snapshot().drafts[v.id]?.mode==='plan'", arg={"id": destination, "text": destination_draft})
            for text in ("Check the installation command first.", "Review configuration after the launch command."):
                await page.locator("#prompt").fill(text)
                await page.locator("#prepare-followup").click()
                await page.wait_for_function("!$('prepare-followup').disabled")
            await page.locator("#prompt").fill(destination_draft)
            await page.wait_for_function("v => DeskBrowserPreview.snapshot().drafts[v.id]?.text===v.text", arg={"id": destination, "text": destination_draft})
            before_evidence = await snapshot()
            await page.locator("#browse").click()
            await page.locator('#native-list .native-row').filter(has_text='Sample checkout retry decision').locator('.native-read').click()
            await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            original_item = page.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"]')
            await original_item.locator('pre').evaluate("""(n,quote) => {
                const walker=document.createTreeWalker(n,NodeFilter.SHOW_TEXT);let node;
                while(node=walker.nextNode()){const at=node.textContent.indexOf(quote);if(at<0)continue;
                    const r=document.createRange();r.setStart(node,at);r.setEnd(node,at+quote.length);
                    const selection=getSelection();selection.removeAllRanges();selection.addRange(r);return;}
                throw Error('Sample original quote missing');
            }""", quote)
            await original_item.locator('.history-reader-review-evidence').click()
            await page.wait_for_function("$('evidence-preparation').open && !DeskEvidencePreparation.state().pending")
            reviewed = await page.evaluate("DeskEvidencePreparation.state()")
            assert reviewed['reference']['quote'] == quote and reviewed['reference']['thread_id'] == THREAD
            assert reviewed['reference']['turn_id'] == TURN and reviewed['reference']['item_id'] == ITEM
            assert len(reviewed['reference']['native_home']) == 64
            assert reviewed['destination']['session'] == destination and reviewed['destination']['mode'] == 'plan'
            assert await snapshot() == before_evidence, 'Review wrote sample storage'
            await page.locator('#evidence-preparation-note').fill('Use the retained retry rule in the next installation check.')
            await page.locator('#evidence-preparation-append').click()
            await page.wait_for_function("!$('evidence-preparation').open && DeskEvidencePreparation.parse($('prompt').value).length===1")
            await page.locator('#history-reader-back').click()
            await page.locator('#history-close').click()
            evidence_saved = await snapshot()
            assert evidence_saved['drafts'][destination]['text'].startswith(destination_draft + '\n\nNext-step note:')
            assert evidence_saved['drafts'][destination]['mode'] == 'plan'
            assert evidence_saved['followups'] == before_evidence['followups']
            assert evidence_saved['drafts'][SESSION] == before_evidence['drafts'][SESSION]
            await checkpoint('review-original-A-append-unsent-B')
            captured.extend(await log())
            await page.reload()
            await page.wait_for_function("id => selected===id && !opening && DeskEvidencePreparation.parse($('prompt').value).length===1", arg=destination)
            await page.wait_for_function("$('followup-count').textContent==='2'")
            assert await snapshot() == evidence_saved
            if not await page.locator('#draft-evidence').evaluate('n=>n.open'):
                await page.locator('#draft-evidence > summary').click()
            await page.locator('#draft-evidence-list button').scroll_into_view_if_needed()
            await page.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(5,16,'backward')}")
            owner = await page.evaluate("({selected,text:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection})")
            boundary = len(await log())
            await page.locator('#draft-evidence-list button').focus()
            await page.locator('#draft-evidence-list button').press('Enter')
            await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            exact = page.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"]')
            assert await exact.locator('mark').text_content() == quote
            assert await page.locator('#history-reader-saved-evidence-quote').text_content() == quote
            assert await snapshot() == evidence_saved
            source_reads = (await log())[boundary:]
            assert len([r for r in source_reads if r['path']=='/api/native/evidence-source']) == 1
            assert all(r['method']=='GET' for r in source_reads), source_reads
            await page.locator('#history-reader-back').click()
            restored = await page.evaluate("({selected,text:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection})")
            assert restored == owner, (owner, restored)
            assert await snapshot() == evidence_saved
            await checkpoint('cold-saved-B-read-exact-A-return')
            captured.extend(await log())

            # Reset is scoped; unrelated same-origin browser state survives.
            await page.evaluate("window.localStorage.setItem('preview-check-unrelated', 'keep')")
            await page.locator("#prompt").fill("Discard this pending sample draft on reset.")
            await page.locator("#preview-reset").click()
            await page.wait_for_function("document.querySelector('#welcome')?.hidden === false && document.querySelector('#home-list')?.getAttribute('aria-busy') === 'false'")
            cleared = await snapshot()
            assert cleared["sessions"] == [] and cleared["drafts"] == {} and cleared["followups"] == {}, cleared
            assert not cleared["indexed"]
            assert await page.locator("#task").is_hidden()
            assert await page.evaluate("window.localStorage.getItem(DeskBrowserPreview.sessionKey)") is None
            assert await page.evaluate("window.localStorage.getItem('preview-check-unrelated')") == "keep"
            await checkpoint("reset")
            captured.extend(await log())

            allowed_posts = {"/api/history/index", "/api/import", "/api/open", "/api/draft", "/api/followups", "/api/followups/reorder"}
            assert all(r["method"] != "POST" or r["path"] in allowed_posts for r in captured), captured
            receipt = {"viewport": width, "passed": True, "phases": phases,
                "source": str(site), "provenance": provenance, "install_links": install_links,
                "thread_id": THREAD, "matched_turn_id": TURN, "matched_item_id": ITEM,
                "preserved": preserved, "reset": cleared, "simulated_api_requests": captured,
                "static_http_requests": received, "escaped_api_requests": escaped_api,
                "native_model_calls": 0, "external_requests": external, "javascript_errors": errors,
                "console_errors": console_errors, "failed_requests": failures, "horizontal_overflow": False,
                "unrelated_storage_preserved": True}
            receipt['evidence_preparation'] = {'source': reviewed['reference'], 'destination': destination, 'cold_exact_return': True, 'read_only_source': True, 'queues_unchanged': True}
            receipt['prepared_work'] = {'query_free_entry': 'show-preparation', 'reviewed_session': SESSION,
                'copied_texts': copied, 'explicit_append': True, 'saved_mode': 'plan', 'source_queue_unchanged': True,
                'overview_after_reload': True, 'no_native_open_on_review': True, 'explicit_save_and_open_exact_unsent_plan': True}
            (evidence / f"receipt-{width}.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps({"viewport": width, "passed": True, "phases": phases}), flush=True)
            return receipt
        except Exception:
            try:
                await page.screenshot(path=str(evidence / f"failure-{width}.png"))
                captured.extend(await log())
                diagnostic = {"phases": phases, "errors": errors, "console": console_errors,
                    "external": external, "escaped_api": escaped_api, "failures": failures,
                    "snapshot": await snapshot(), "api_requests": captured, "body": await page.locator("body").inner_text()}
                (evidence / f"failure-{width}.json").write_text(json.dumps(diagnostic, indent=2) + "\n")
            except Exception:
                pass
            raise
        finally:
            await context.close()
            await browser.close()


async def main(args):
    from playwright.async_api import async_playwright
    site, evidence = args.site.resolve(), args.evidence.resolve()
    assert (site / "index.html").is_file(), f"Build the preview first: {site}"
    evidence.mkdir(parents=True, exist_ok=True)
    from check_browser_preview_lookup import check as check_lookup
    lookup_evidence = evidence / "prepared-lookup"
    lookup_evidence.mkdir(parents=True, exist_ok=True)
    embedded = 'data-preview-embedded="true"' in (site / "index.html").read_text()
    async with async_playwright() as playwright:
        results = [await check(playwright, site, evidence, int(width), args.chromium, args.url) for width in args.widths.split(",")]
        lookup_results = [await check_lookup(playwright, site, lookup_evidence, int(width), args.chromium, embedded, args.url)
                          for width in args.widths.split(",")]
    (evidence / "acceptance.json").write_text(json.dumps({"passed": True, "viewports": results,
        "prepared_lookup": lookup_results}, indent=2) + "\n")


if __name__ == "__main__":
    workspace = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=workspace / "temp/round122-preview/site/demo")
    parser.add_argument("--evidence", type=Path, default=workspace / "temp/round122-preview/browser-evidence")
    parser.add_argument("--url", help="Verify the same sample flow at an already-deployed URL")
    parser.add_argument("--widths", default="1250,390")
    parser.add_argument("--chromium", default=os.environ.get("DESK_CHROMIUM"))
    parser.add_argument("--api-only", action="store_true", help="Check local sample preparation API with Node; no browser or generated site")
    args = parser.parse_args()
    if args.api_only:
        print(json.dumps(check_preparation_api(), indent=2))
    else:
        asyncio.run(main(args))
