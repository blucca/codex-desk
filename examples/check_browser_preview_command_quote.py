"""Saved exact command-output quote through completion and normal sample reload."""
import json
from check_browser_preview_links import reload_app
from check_browser_preview_following_original import VISIBLE
from original_character_oracle import CHARACTER_RANGE,probe_character,utf16_character,assert_responsive_character

QUOTE='HEADER OUTPUT PASSAGE — café🙂 项目.'

async def saved_output_quote(page,app,embedded,evidence,prefix):
    checks=[]
    def item():return app.locator('.history-reader-item[data-turn-id="sample-child-turn"][data-item-id="sample-child-evidence"]')
    async def frames():await app.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    async def ready():
        await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await frames()
    async def close_reader():
        await app.locator('#history-reader-back').click();await app.wait_for_function("!$('history-reader').open")
        if await app.locator('#history').evaluate('n=>n.open'):await app.locator('#history-close').click()
        await frames()
    async def checkpoint(name):
        checks.append(name);await page.screenshot(path=str(evidence/f'{prefix}-{name}.png'))
    def untouched(before,after):
        # Only B's normal revisioned draft changes in this rehearsal.
        before=json.loads(json.dumps(before));after=json.loads(json.dumps(after));before.pop('drafts');after.pop('drafts');assert before==after
    async def owner():return await app.evaluate("({selected,nativeThreadId,text:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop})")
    before=await app.evaluate('DeskBrowserPreview.snapshot()')
    await app.locator('#preview-header-prepare').click()
    if await app.evaluate('DeskBrowserPreview.headerFixture.command().status')!='inProgress':await app.locator('#preview-header-toggle').click()
    raw=await app.evaluate('DeskBrowserPreview.headerFixture.command().aggregatedOutput')
    await app.locator('#browse').click();await app.wait_for_function("!$('history-search-submit').disabled")
    await app.locator('#history-id').fill('sample-child-thread');await app.locator('#history-id').press('Enter');await ready()
    await app.locator('#history-reader-find-query').fill(QUOTE);await app.locator('#history-reader-find-query').press('Enter')
    await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')");await frames()
    # Backwards physical pointer selection survives the Review keyboard route too.
    rects=await item().locator('mark').evaluate('n=>[...n.getClientRects()].filter(r=>r.width&&r.height).map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
    first,last=rects[0],rects[-1];a=(last['right']-.5,(last['top']+last['bottom'])/2);b=(first['left']+.5,(first['top']+first['bottom'])/2)
    if embedded:
        box=await page.locator('iframe').bounding_box();a=(a[0]+box['x'],a[1]+box['y']);b=(b[0]+box['x'],b[1]+box['y'])
    await page.mouse.move(*a);await page.mouse.down();await page.mouse.move(*b,steps=12);await page.mouse.up()
    assert await app.evaluate('getSelection().toString()')==QUOTE
    await item().locator('.history-reader-review-evidence').click();await app.wait_for_function("$('evidence-preparation').open&&!DeskEvidencePreparation.state().pending")
    reference=await app.evaluate('DeskEvidencePreparation.state().reference')
    assert reference['projection']=='history-reader-command-output/v1' and reference['quote_start']==raw.index(QUOTE)
    assert reference['status']=='inProgress' and reference['quote']==QUOTE
    boundary=await app.evaluate('DeskBrowserPreview.requests.length')
    await app.locator('#evidence-preparation-append').click();await app.wait_for_function("!$('evidence-preparation').open")
    await frames();await close_reader();saved=await app.evaluate('DeskBrowserPreview.snapshot()');untouched(before,saved)
    assert [r['path'] for r in await app.evaluate('n=>DeskBrowserPreview.requests.slice(n)',boundary) if r['method']=='POST']==['/api/draft']
    assert await app.evaluate("DeskEvidencePreparation.parse($('prompt').value)[0].reference")==reference
    await checkpoint('output-only-quote-appended-once-to-B-Plan-two-queues-intact')
    await app.locator('#preview-header-toggle').click();assert await app.evaluate('DeskBrowserPreview.headerFixture.command().aggregatedOutput')==raw
    app=await reload_app(page,embedded);await app.locator('#prompt').wait_for();await app.wait_for_function('!opening&&!sessionReadingPending');await frames()
    assert await app.evaluate('DeskBrowserPreview.snapshot()')==saved
    assert not await app.locator('#history-reader').evaluate('n=>n.open')
    assert not await app.evaluate("DeskBrowserPreview.requests.some(r=>['/api/native/thread','/api/native/evidence-source','/api/native/task-response'].includes(r.path.split('?')[0]))")
    assert await app.evaluate("DeskEvidencePreparation.parse($('prompt').value)[0].reference")==reference
    await checkpoint('saved-readable-output-reference-survives-reload-without-original-read')
    # The sample-only completion control resets on reload. Deliberately complete
    # the same supplied command before reading the saved reference.
    await app.locator('#preview-header-prepare').click();await app.locator('#preview-header-toggle').click()
    assert await app.evaluate('DeskBrowserPreview.headerFixture.command().aggregatedOutput')==raw
    if not await app.locator('#draft-evidence').evaluate('n=>n.open'):await app.locator('#draft-evidence > summary').click()
    await app.locator('#draft-evidence-list button').scroll_into_view_if_needed()
    await app.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(10,22,'backward');n.scrollTop=25}");await frames();editor=await owner();boundary=await app.evaluate('DeskBrowserPreview.requests.length')
    await app.locator('#draft-evidence-list button').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#draft-evidence-list button').press('Enter');await ready()
    assert await item().locator('mark').text_content()==QUOTE
    assert 'still at this exact' in await app.locator('#history-reader-response').inner_text()
    assert await app.locator('#history-reader-saved-evidence-quote').text_content()==QUOTE
    assert await app.evaluate('DeskBrowserPreview.snapshot()')==saved
    requests=await app.evaluate('n=>DeskBrowserPreview.requests.slice(n)',boundary)
    assert len([r for r in requests if r['path'].startswith('/api/native/evidence-source')])==1
    assert not [r for r in requests if r['method']=='POST' or r['path'].startswith('/api/native/thread')]
    await checkpoint('completed-command-reopens-exact-saved-output-span-read-only')
    await item().locator('mark').evaluate("n=>{const r=document.createRange();r.selectNodeContents(n);const s=getSelection();s.removeAllRanges();s.addRange(r)}")
    old_start=int(await item().get_attribute('data-window-start'))
    await app.locator('#preview-header-reader-toggle').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#preview-header-reader-toggle').press('Enter');await app.locator('#history-reader-refresh').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#history-reader-refresh').press('Enter')
    await app.wait_for_function("!$('history-reader-refresh').disabled&&$('history-reader-status').textContent.startsWith('Original refreshed.')");await frames()
    assert await item().locator('mark').text_content()==QUOTE and await app.evaluate('getSelection().toString()')==QUOTE, await item().evaluate("n=>({mark:n.querySelector('mark')?.textContent,selection:getSelection().toString(),start:n.dataset.windowStart})")
    assert int(await item().get_attribute('data-window-start'))==old_start+12
    assert 'still at this exact' in await app.locator('#history-reader-response').inner_text()
    assert await app.evaluate('DeskBrowserPreview.snapshot()')==saved
    await checkpoint('saved-output-Refresh-retains-exact-quote-window-and-Range-across-header')
    # Physical pointer activation can reveal a control before onclick captures
    # reading intent. Remember the independently observed source glyph at that
    # actual action boundary, including the reader's documented 1px visibility floor.
    visible=VISIBLE.replace('Child source line ', 'H').replace('Child decisive evidence — café🙂 项目 exact source.',QUOTE)
    projection=await app.evaluate(r"""()=>{const c=DeskBrowserPreview.headerFixture.command();return ('Command\n'+c.command+'\nStatus: '+c.status+'\nExit: '+(typeof c.exitCode==='number'?c.exitCode:'not reported')+'\n').length}""")
    control=item().get_by_role('button',name='Read containing task',exact=True)
    await control.evaluate("""(button,oracles)=>button.addEventListener('pointerdown',()=>{
      const item=button.closest('.history-reader-item'),view=(0,eval)('('+oracles.visible+')')(item);
      const glyph=view.first_visible;if(!glyph)throw Error('No source glyph at pointer action');
      const character=(0,eval)('('+oracles.range+')')(item,{offset:glyph.offset,size:glyph.char.length});
      globalThis.__commandQuotePointer={view,character};
    },{once:true})""",{'visible':visible,'range':CHARACTER_RANGE})
    pointer_calls=await app.evaluate('DeskBrowserPreview.requests.length')
    await control.click();captured=await app.evaluate('__commandQuotePointer')
    before_character=captured['character'];offset=before_character['native_offset']-projection
    expected,size=utf16_character(raw,offset)
    assert before_character['character']==expected and before_character['visible']
    before_character.update(source_offset=offset,projection_offset=projection,expected_character=expected)
    await app.locator('#history-reader-task-passage').click();await frames()
    after_character=await probe_character(item(),raw,offset,projection)
    assert_responsive_character(before_character,after_character)
    assert after_character['clip_relative_top']+after_character['glyph_height']>=1
    after=await item().evaluate(visible)
    assert captured['view']['window_start']==after['window_start']
    assert after['query']==QUOTE and after['selection']==QUOTE and await item().locator('mark').text_content()==QUOTE
    assert await app.evaluate('DeskBrowserPreview.snapshot()')==saved
    assert not [r for r in await app.evaluate('n=>DeskBrowserPreview.requests.slice(n)',pointer_calls) if r['method']=='POST' or r['path'].startswith('/api/native/')]
    (evidence/f'{prefix}-pointer-source-character.json').write_text(json.dumps({'before':captured,'after':after,'before_character':before_character,'after_character':after_character},indent=2))
    await checkpoint('saved-output-pointer-containing-task-return-keeps-action-source-glyph')
    # Reveal the action and move a clipped source glyph into its ordinary
    # interior before genuine Tab/Enter. Strict raw passage equality remains
    # appropriate for this unchanged viewport; the pointer case above retains
    # the original clipped-edge action and its documented visibility floor.
    task=item().get_by_role('button',name='Read containing task',exact=True)
    await task.scroll_into_view_if_needed();await frames()
    clipped=await item().evaluate("n=>n.querySelector('pre').getBoundingClientRect().top<$('history-reader-body').getBoundingClientRect().top")
    if clipped:
        # Playwright bounding_box is already main-frame-relative for iframes.
        box=await task.bounding_box();x=box['x']+box['width']/2;y=box['y']+box['height']/2
        body_scroll=await app.evaluate("$('history-reader-body').scrollTop")
        await page.mouse.move(x,y);await page.mouse.wheel(0,-8)
        await app.wait_for_function("n=>$('history-reader-body').scrollTop<n",arg=body_scroll);await frames()
    await item().get_by_role('button',name='Copy source reference',exact=True).focus()
    await page.keyboard.press('Tab');await frames()
    assert await task.evaluate('n=>n===document.activeElement')
    passage=await item().evaluate("n=>({start:n.dataset.windowStart,text:n.querySelector('mark').textContent,scroll:n.querySelector('pre').scrollTop})")
    await page.keyboard.press('Enter');await app.locator('#history-reader-task-passage').click();await frames()
    assert await item().evaluate("n=>({start:n.dataset.windowStart,text:n.querySelector('mark').textContent,scroll:n.querySelector('pre').scrollTop})")==passage
    await checkpoint('saved-output-containing-task-return-keeps-original-passage')
    await close_reader();assert await owner()==editor
    await checkpoint('completed-output-source-return-keeps-same-unsent-editor')
    return app,{'checks':checks,'reference':reference,'editor':editor,'unchanged_output':True}
