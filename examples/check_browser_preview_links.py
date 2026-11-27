#!/usr/bin/env python3
"""Check sample installer navigation and saved preparation in both hosting modes."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from check_browser_preview import static_server

INSTALL='https://github.com/blucca/codex-desk#install-the-preview'
DRAFT='Plan the next retry review.'
SESSION='desk-sample-checkout-thread'

async def open_app(page, context, url, embedded):
    if embedded:
        host = url + 'sample-frame-host.html'
        await context.route(host, lambda route: route.fulfill(content_type='text/html', body=(
            '<!doctype html><html><head><title>Embedded Desk sample</title>'
            '<style>html,body{margin:0;height:100%;overflow:hidden}iframe{display:block;width:100%;height:100%;border:0}</style>'
            '</head><body><iframe title="Codex Desk sample" src="' + url + '"></iframe></body></html>')))
        await page.goto(host)
        return await (await page.locator('iframe').element_handle()).content_frame()
    await page.goto(url)
    return page.main_frame


async def reload_app(page, embedded):
    await page.reload()
    return await (await page.locator('iframe').element_handle()).content_frame() if embedded else page.main_frame


async def check(p,site,evidence,chromium,embedded,width=390):
    with static_server(site) as (url,received,escaped):
        browser=await p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=await browser.new_context(viewport={'width':width,'height':900 if width==1250 else 844})
        await context.route('https://github.com/**',lambda route:route.fulfill(content_type='text/html',body='<h2>Install the preview</h2>'))
        page=await context.new_page();page.set_default_timeout(10000)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        try:
            app=await open_app(page,context,url,embedded)
            parent_url=page.url
            await app.wait_for_function('document.querySelector("#home-list").getAttribute("aria-busy")==="false"')
            await app.locator('#home-list').get_by_role('button',name='Resume conversation',exact=True).first.click()
            await app.locator('#prompt').wait_for()
            await app.locator('#prompt').fill('Verify the retry budget.')
            await app.locator('#prepare-followup').click()
            await app.wait_for_function('document.querySelector("#followup-count").textContent==="1" && !document.querySelector("#prepare-followup").disabled')
            await app.locator('#prompt').fill(DRAFT);await app.locator('#turn-mode').select_option('plan')
            await app.wait_for_function('v=>DeskBrowserPreview.snapshot().drafts[v.id]?.text===v.text',arg={'id':SESSION,'text':DRAFT})
            saved=await app.evaluate('DeskBrowserPreview.snapshot()')
            for control in ('#preview-banner a:has-text("Install for your own work")','#send','#followup-send'):
                if control=='#followup-send' and not await app.locator('#followups').evaluate('n=>n.open'):
                    await app.locator('#followups summary').click()
                if embedded:
                    async with context.expect_page() as info:await app.locator(control).click()
                    popup=await info.value
                    await popup.wait_for_url(INSTALL)
                    assert page.url==parent_url
                    assert await app.evaluate('DeskBrowserPreview.snapshot()')==saved
                    await popup.close()
                    requests=await app.evaluate('DeskBrowserPreview.requests')
                    assert not any(r['path']=='/api/open' and r['data'].get('session')==INSTALL for r in requests), requests
                else:
                    await app.locator(control).click();await page.wait_for_url(INSTALL)
                    await page.go_back();app=page.main_frame;await app.locator('#prompt').wait_for()
                    assert await app.evaluate('DeskBrowserPreview.snapshot()')==saved
            app=await reload_app(page,embedded);await app.locator('#prompt').wait_for()
            assert await app.evaluate('DeskBrowserPreview.snapshot()')==saved
            assert not errors and not escaped,(errors,escaped)
            result={'passed':True,'embedded':embedded,'actual_iframe':embedded,'width':width,'controls':3,'saved_state':saved,'javascript_errors':errors,'escaped_api_requests':escaped,'native_model_calls':0}
            (evidence/(f'{width}-'+('embedded-links.json' if embedded else 'direct-links.json'))).write_text(json.dumps(result,indent=2)+'\n')
            return result
        finally:await context.close();await browser.close()

async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        result=[await check(p,site,args.evidence,args.chromium,embedded,int(width))
                for site,embedded in ((args.site,False),(args.embedded_site,True)) for width in args.widths.split(',')]
        if args.session_reading:
            from check_browser_preview_session_reading import check as check_reading
            result.extend([await check_reading(p,site,args.evidence,args.chromium,embedded,int(width))
                for site,embedded in ((args.site,False),(args.embedded_site,True)) for width in args.widths.split(',')])
    print(json.dumps({'passed':True,'modes':[r['embedded'] for r in result]}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site',type=Path,required=True)
    parser.add_argument('--embedded-site',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--chromium',default=os.environ.get('DESK_CHROMIUM'))
    parser.add_argument('--widths',default='1250,390')
    parser.add_argument('--session-reading',action='store_true',help='Also check session return and cold reading metadata on fixture builds')
    asyncio.run(main(parser.parse_args()))
