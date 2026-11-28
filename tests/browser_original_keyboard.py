"""Original keyboard/selection return over the maintained native HTTP fixture.

Run --help for CLI and environment configuration. The acceptance uses normal
application ticks, real pointer selection and Tab/Enter navigation.
"""
import argparse
import asyncio
import copy
from contextlib import ExitStack
from dataclasses import dataclass
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
import traceback
from unittest.mock import patch
from urllib.parse import quote as encode, urlsplit

ENGINES = ('chromium', 'firefox', 'webkit')


@dataclass(frozen=True)
class RunConfig:
    source: Path
    scratch: Path
    evidence: Path
    engine: str
    widths: tuple[int, ...]
    installed: bool
    installed_root: Path | None
    expect_version: str | None
    executable: Path | None
    browsers_path: Path | None


def viewport(value):
    try:
        width = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError('viewport width must be an integer') from None
    if width < 320:
        raise argparse.ArgumentTypeError('viewport width must be at least 320')
    return width


def parse_config(argv=None, environ=None):
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, default=env.get('DESK_SOURCE', Path(__file__).resolve().parents[1]),
                        help='fixture source checkout (DESK_SOURCE; default: script checkout)')
    parser.add_argument('--scratch', type=Path, default=env.get('DESK_TEST_TEMP'),
                        help='temporary workspace (DESK_TEST_TEMP; default: SOURCE/temp/original-keyboard)')
    parser.add_argument('--evidence', type=Path, default=env.get('DESK_TEST_EVIDENCE'),
                        help='receipts and screenshots (DESK_TEST_EVIDENCE; default: SCRATCH/evidence)')
    parser.add_argument('--engine', choices=ENGINES, default=env.get('DESK_BROWSER_ENGINE', 'chromium').lower(),
                        help='Playwright browser (DESK_BROWSER_ENGINE; default: chromium)')
    parser.add_argument('--widths', type=viewport, nargs='+', default=(1250, 390),
                        help='viewport widths (default: 1250 390)')
    parser.add_argument('--installed', action='store_true', default=env.get('DESK_USE_INSTALLED') == '1',
                        help='check the installed package instead of source (DESK_USE_INSTALLED=1)')
    parser.add_argument('--installed-root', type=Path, default=env.get('DESK_INSTALLED_ROOT'),
                        help='require package beneath this environment (DESK_INSTALLED_ROOT)')
    parser.add_argument('--expect-version', default=env.get('DESK_EXPECT_VERSION'),
                        help='require exact package version (DESK_EXPECT_VERSION)')
    parser.add_argument('--executable', type=Path, default=env.get('DESK_BROWSER_EXECUTABLE'),
                        help='explicit browser executable (DESK_BROWSER_EXECUTABLE)')
    parser.add_argument('--browsers-path', type=Path, default=env.get('PLAYWRIGHT_BROWSERS_PATH'),
                        help='preinstalled browser cache (PLAYWRIGHT_BROWSERS_PATH)')
    args = parser.parse_args(argv)
    if args.engine not in ENGINES:
        parser.error('DESK_BROWSER_ENGINE must be chromium, firefox or webkit')
    if len(set(args.widths)) != len(args.widths):
        parser.error('--widths must not repeat a viewport')
    if args.installed_root and not args.installed:
        parser.error('--installed-root requires --installed or DESK_USE_INSTALLED=1')
    resolve = lambda path: path.expanduser().resolve() if path is not None else None
    source = resolve(args.source)
    helpers = ('check_native_task_evidence.py', 'check_native_find_matches.py', 'check_native_task_response.py')
    if not all((source / 'examples' / name).is_file() for name in helpers):
        parser.error('--source must contain the maintained native task fixture helpers')
    scratch = resolve(args.scratch) or source / 'temp' / 'original-keyboard'
    return RunConfig(source, scratch, resolve(args.evidence) or scratch / 'evidence', args.engine,
                     tuple(args.widths), args.installed, resolve(args.installed_root), args.expect_version,
                     resolve(args.executable), resolve(args.browsers_path))


def load_fixture(config):
    global tasks, base, SOURCE, TURN, ITEM, QUOTE, QUERY
    os.environ.update(DESK_SOURCE=str(config.source), DESK_USE_INSTALLED='1' if config.installed else '0',
                      DESK_TEST_TEMP=str(config.scratch), DESK_TEST_EVIDENCE=str(config.evidence),
                      TMPDIR=str(config.scratch))
    for name, value in (('DESK_INSTALLED_ROOT', config.installed_root), ('DESK_EXPECT_VERSION', config.expect_version),
                        ('PLAYWRIGHT_BROWSERS_PATH', config.browsers_path)):
        if value is not None:
            os.environ[name] = str(value)
    spec = importlib.util.spec_from_file_location('keyboard_tasks', config.source / 'examples/check_native_task_evidence.py')
    tasks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tasks)
    base = tasks.base
    SOURCE, TURN, ITEM, QUOTE, QUERY = tasks.SOURCE, tasks.TURN, tasks.COMMAND, tasks.PHRASE, tasks.QUERY


# Independent DOM prefix lengths work across PRE/MARK text nodes and surrogate pairs.
VIEW = r"""(item, at) => {
 const pre=item.querySelector('pre'),s=getSelection(),start=Number(item.dataset.windowStart);
 const prefix=(node,offset)=>{if(!node||!pre.contains(node))return null;const r=document.createRange();r.selectNodeContents(pre);r.setEnd(node,offset);return start+r.toString().length;};
 const anchor=prefix(s.anchorNode,s.anchorOffset),focus=prefix(s.focusNode,s.focusOffset);
 const br=document.getElementById('history-reader-body').getBoundingClientRect(),rr=document.getElementById('history-reader').getBoundingClientRect(),pr=pre.getBoundingClientRect();
 const clip={top:Math.max(pr.top,br.top,rr.top,0),bottom:Math.min(pr.bottom,br.bottom,rr.bottom,innerHeight),left:Math.max(pr.left,br.left,rr.left,0),right:Math.min(pr.right,br.right,rr.right,innerWidth)};
 const seen=r=>r.width>0&&r.height>0&&r.right>clip.left&&r.left<clip.right&&r.bottom>clip.top&&r.top<clip.bottom;
 const nodes=[],walk=document.createTreeWalker(pre,NodeFilter.SHOW_TEXT);let node,offset=0;
 while(node=walk.nextNode()){nodes.push({node,start:offset,end:offset+node.data.length});offset+=node.data.length;}
 const point=(n,right=false)=>{for(const q of nodes)if(n<q.end||!right&&n===q.end)return[q.node,n-q.start];};
 const rectangles=(a,b)=>{const first=point(a,true),last=point(b);if(!first||!last)return[];const r=document.createRange();r.setStart(...first);r.setEnd(...last);return [...r.getClientRects()];};
 const character=n=>{const r=rectangles(n,n+(pre.textContent.codePointAt(n)>0xffff?2:1)).find(seen);return r?{offset:start+n,character:String.fromCodePoint(pre.textContent.codePointAt(n)),top:r.top-clip.top}:null;};
 let glyph=at===null?null:character(at-start);
 if(at===null){outer:for(const line of pre.textContent.matchAll(/[^\n\r]+/g)){
  if(!rectangles(line.index,line.index+line[0].length).some(seen))continue;
  let n=line.index;for(const char of line[0]){glyph=character(n);if(glyph)break outer;n+=char.length;}
 }}
 return {turn:item.dataset.turnId,item:item.dataset.itemId,window:start,query:document.getElementById('history-reader-find-query').value,status:document.getElementById('history-reader-find-status').textContent,
  text:s.toString(),anchor,focus,backward:anchor!==null&&focus!==null&&anchor>focus,same_node:s.anchorNode===s.focusNode,glyph};
}"""
EDITOR = "n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop,window:scrollY})"
STATE = "({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})"
SETTLE = "n=>new Promise(resolve=>{let previous=n.scrollTop,stable=0;function frame(){const value=n.scrollTop;stable=value===previous?stable+1:0;previous=value;if(stable>=5)resolve();else requestAnimationFrame(frame);}requestAnimationFrame(frame);})"


def utf16(text):
    return len(text.encode('utf-16-le')) // 2


async def run_case(browser, width, scratch, evidence):
    result = {'result': 'RUNNING', 'width': width, 'browser': browser.version, 'checks': [], 'selections': []}
    phase = 'setup'
    with tempfile.TemporaryDirectory(dir=scratch, prefix='original-keyboard-') as temporary, ExitStack() as cleanup:
        fixture = base.Fixture(Path(temporary))
        cleanup.callback(fixture.stop)
        fixture.threads[SOURCE] = tasks.make_tasks(Path(temporary))
        turn = next(turn for turn in fixture.threads[SOURCE]['turns'] if turn['id'] == TURN)
        command = next(item for item in turn['items'] if item and item.get('id') == ITEM)
        projection = 'Command\n' + command['command'] + '\nStatus: completed\nExit: 0\n' + command['aggregatedOutput']
        point = projection.index(QUOTE)
        span = {'start': utf16(projection[:point]), 'end': utf16(projection[:point]) + utf16(QUOTE)}
        base.save_draft(fixture.desk.store, base.ORIGINAL, 'B exact unsent Plan — 保持\n' + 'Use reviewed original evidence.\n' * 12, 'plan', 1)
        requests, errors = [], []
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
        page = await context.new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append((request.method, urlsplit(request.url))))
        target = page.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"]')
        async def frames():
            await base.frames(page)
        async def key(control):
            await control.evaluate('n=>n.focus({preventScroll:true})')
            await page.keyboard.press('Enter')
            await frames()
        async def find(total):
            await page.locator('#history-reader-find-query').fill(QUERY)
            await page.locator('#history-reader-find-query').press('Enter')
            await page.wait_for_function('n=>$(' + '"history-reader-find-status"' + ').textContent.includes("Match 1 of "+n)', arg=total)
            await frames()
        async def selected(name):
            view = await target.evaluate(VIEW, None)
            assert view['text'] == QUOTE and view['anchor'] == span['end'] and view['focus'] == span['start'] and view['backward'], view
            result['selections'].append({'phase': name, **view})
            return view
        async def drag():
            boxes = await target.locator('mark').evaluate('n=>[...n.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
            first, last = boxes[0], boxes[-1]
            await page.mouse.move(last['right']-.5, (last['top']+last['bottom'])/2)
            await page.mouse.down()
            await page.mouse.move(first['left']+.5, (first['top']+first['bottom'])/2, steps=12)
            await page.mouse.up()
            return await selected('real-pointer-drag')
        async def review():
            for count in range(16):
                await page.keyboard.press('Tab')
                if await page.evaluate("document.activeElement.classList.contains('history-reader-review-evidence')"):
                    break
            else:
                raise AssertionError('Tab did not reach the selected item’s Review control')
            await page.keyboard.press('Enter')
            await page.wait_for_function("$('evidence-preparation').open&&!$('evidence-preparation-append').disabled")
            reference = await page.evaluate('DeskEvidencePreparation.state().reference')
            assert reference['quote'] == QUOTE and reference['thread_id'] == SOURCE and reference['turn_id'] == TURN and reference['item_id'] == ITEM
            output_point = command['aggregatedOutput'].index(QUOTE)
            assert reference['projection'] == 'history-reader-command-output/v1'
            assert (reference['quote_start'], reference['quote_end']) == (output_point, output_point + len(QUOTE))
            await page.locator('#evidence-preparation-cancel').click()
            await frames()
            await selected('keyboard-Review-Cancel-return')
            result.setdefault('Tab_counts', []).append(count+1)
        async def check(name):
            nonlocal phase
            phase = name
            assert fixture.sql() == sql and fixture.prepared() == preparation and fixture.opens == opened
            assert fixture.threads == original and await page.evaluate(STATE) == state
            assert not errors and all(url.hostname == '127.0.0.1' for _, url in requests)
            assert sum(method == 'POST' for method, _ in requests) == posts
            assert len(fixture.calls) == reads
            assert {p: p.read_bytes() for p in fixture.protected} == fixture.protected
            assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            result['checks'].append(name)
            await page.screenshot(path=str(evidence / f'{width}-{name}.png'))
        try:
            phase = 'known-ID-global-Find-late-Unicode-backward-pointer'
            with patch.object(base.product, '_NativeReader', fixture.reader_type), patch.object(base.product, 'Runtime', side_effect=AssertionError('Unexpected native admission')):
                await page.goto(f'http://127.0.0.1:{fixture.server.server_port}')
                await page.locator(f'.session-row[data-session="{base.ORIGINAL}"] .session').click()
                await page.wait_for_function('id=>selected===id&&!opening', arg=base.ORIGINAL)
                await page.locator('#prompt').click()
                await page.keyboard.press('Control+Home')
                for _ in range(27): await page.keyboard.press('ArrowRight')
                for _ in range(19): await page.keyboard.press('Shift+ArrowLeft')
                await page.mouse.wheel(0, 40)
                await frames()
                await page.mouse.click(8, 8)  # Page margin: Ctrl+Home scrolls the document, not the draft.
                await page.keyboard.press('Control+Home')
                page_scroll = await page.evaluate('scrollY')
                if page_scroll:
                    await page.mouse.wheel(0, -page_scroll - 900)
                await page.wait_for_function('scrollY===0')
                editor = await page.locator('#prompt').evaluate(EDITOR)
                result['editor_baseline'] = {key:value for key,value in editor.items() if key!='text'}
                result['setup_page_scroll_before_wheel'] = page_scroll
                assert (editor['start'], editor['end'], editor['direction']) == (8, 27, 'backward'), editor
                sql, preparation, opened = fixture.sql(), fixture.prepared(), list(fixture.opens)
                original, state = copy.deepcopy(fixture.threads), await page.evaluate(STATE)
                posts = sum(method == 'POST' for method, _ in requests)
                await page.locator('#browse').click()
                await page.wait_for_function("!$('history-search-submit').disabled")
                await page.locator('#history-id').fill(SOURCE)
                await page.locator('#history-id').press('Enter')
                await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
                reads = len(fixture.calls)
                await find(3)
                await page.locator('#history-reader-find-next').click()
                await frames()
                await drag()
                await check('known-ID-global-Find-late-Unicode-backward-pointer')
                phase = 'pointer-clear-and-global-keyboard-Review-Cancel'
                await page.keyboard.press('Tab')
                await target.locator('.history-reader-identity').click()
                await target.locator('.history-reader-review-evidence').click()
                await frames()
                assert not await page.locator('#evidence-preparation').evaluate('n=>n.open')
                assert 'Select up to 8,000 characters' in await target.locator('.history-reader-copy-status').text_content()
                await target.locator('mark').scroll_into_view_if_needed()
                await drag()
                await review()
                await check('pointer-clear-and-global-keyboard-Review-Cancel')
                phase = 'chosen-task-paged-evidence-task-only-Find'
                control = page.locator('#history-reader-task-overview-show')
                box = await control.bounding_box()
                if box['y'] < 12:
                    reader = await page.locator('#history-reader').bounding_box()
                    await page.mouse.move(reader['x']+reader['width']-8, reader['y']+80)
                    await page.mouse.wheel(0, box['y']-24)
                    await page.locator('#history-reader').evaluate(SETTLE)
                boxes = await target.locator('mark').evaluate('n=>[...n.getClientRects()].map(r=>r.bottom)')
                excess = max(boxes) - (900 if width > 390 else 844) + 50
                if excess > 0:
                    pre = await target.locator('pre').bounding_box()
                    await page.mouse.move(pre['x']+pre['width']/2, min(pre['y']+60, 750))
                    await page.mouse.wheel(0, excess)
                    await target.locator('pre').evaluate(SETTLE)
                passage = await selected('visible-original-passage-baseline')
                assert passage['glyph'] and passage['window'] > 20000
                await control.click()
                for _ in range(2): await key(page.locator('[data-task-action="overview-next"]'))
                assert await page.locator('.history-reader-task-overview-row').count() == 20
                await key(page.locator(f'[data-task-action="overview-context:{TURN}"]'))
                await key(page.locator('[data-task-action="evidence-open"]'))
                for _ in range(2): await key(page.locator('[data-task-action="evidence-next"]'))
                action = 'evidence-item:' + encode(json.dumps([TURN, ITEM], separators=(',', ':')), safe='')
                await key(page.locator(f'[data-task-action="{action}"]'))
                await find(1)
                await drag()
                await check('chosen-task-paged-evidence-task-only-Find')
                phase = 'scoped-keyboard-Review-Cancel'
                await review()
                await check('scoped-keyboard-Review-Cancel')
                phase = 'original-Find-Range-native-glyph-return'
                await page.locator('#history-reader-task-evidence-return').click()
                assert await page.locator('.history-reader-task-evidence-row').first.get_attribute('data-item-index') == '40'
                await page.locator('#history-reader-task-overview-return').click()
                assert await page.locator('.history-reader-task-overview-row').first.get_attribute('data-task-index') == '40'
                await key(page.locator('#history-reader-task-passage'))
                restored = await selected('original-passage-return')
                assert (restored['query'], restored['status'], restored['window']) == (passage['query'], passage['status'], passage['window'])
                glyph = (await target.evaluate(VIEW, passage['glyph']['offset']))['glyph']
                assert glyph and glyph['offset'] == passage['glyph']['offset'] and glyph['character'] == passage['glyph']['character'] and abs(glyph['top']-passage['glyph']['top']) < 2
                result['source_glyph_return'] = {'before': passage['glyph'], 'after': glyph}
                await check('original-Find-Range-native-glyph-return')
                phase = 'exact-B-Plan-caret-direction-scroll-return'
                await page.locator('#history-reader-back').click()
                await page.wait_for_function("!$('history-reader').open")
                await page.locator('#history-close').click()
                await frames()
                after = await page.locator('#prompt').evaluate(EDITOR)
                assert after == editor, (editor, after)
                result['editor_return'] = {'exact': True, **{key: value for key, value in after.items() if key != 'text'}}
                await check('exact-B-Plan-caret-direction-scroll-return')
                result.update(result='PASS',metadata=base.codex_desk.__version__,SQL_source_twoqueues_exact=True,navigation_POSTs=0,navigation_native_reads=0,native_admissions=0,JS_errors=0)
        except Exception as error:
            result.update(result='FAIL',phase=phase,error=str(error),traceback=traceback.format_exc())
            try:
                await page.screenshot(path=str(evidence / f'{width}-failure.png'))
            except Exception as capture_error:
                result['screenshot_error'] = str(capture_error)
        finally:
            try:
                await context.close()
                cleanup.close()
                result['cleanup'] = {'browser_context_closed': True, 'fixture_worker_stopped': not fixture.worker.is_alive()}
            finally:
                (evidence / f'{width}-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


async def run(config):
    load_fixture(config)
    from playwright.async_api import async_playwright

    options = {'headless': True}
    if config.engine == 'chromium':
        options['args'] = ['--no-sandbox', '--disable-dev-shm-usage']
    if config.executable:
        options['executable_path'] = str(config.executable)
    async with async_playwright() as playwright:
        browser = await getattr(playwright, config.engine).launch(**options)
        version = browser.version
        try:
            rows = [await run_case(browser, width, config.scratch, config.evidence) for width in config.widths]
        finally:
            await browser.close()
    return {'result': 'PASS' if all(row['result'] == 'PASS' for row in rows) else 'FAIL',
            'engine': config.engine, 'browser': version, 'metadata': base.codex_desk.__version__,
            'python': sys.version.split()[0], 'playwright': importlib.metadata.version('playwright'),
            'source': str(config.source), 'package': str(base.PACKAGE),
            'widths': list(config.widths), 'installed': config.installed,
            'groups': sum(len(row['checks']) for row in rows),
            'cases': [{'width': row['width'], 'result': row['result'], 'groups': len(row['checks']),
                       'receipt': f"{row['width']}-receipt.json"} for row in rows],
            'browser_closed': True}


def main(argv=None):
    config = parse_config(argv)
    os.umask(0o077)
    config.scratch.mkdir(parents=True, exist_ok=True)
    config.evidence.mkdir(parents=True, exist_ok=True)
    try:
        summary = asyncio.run(run(config))
    except Exception as error:
        summary = {'result': 'FAIL', 'engine': config.engine, 'widths': list(config.widths),
                   'installed': config.installed, 'phase': 'harness',
                   'error': str(error), 'traceback': traceback.format_exc()}
    (config.evidence / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary['result'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
