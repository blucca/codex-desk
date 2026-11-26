#!/usr/bin/env python3
"""Check sample installer navigation and saved preparation in both hosting modes."""
import argparse
import asyncio
import json
from pathlib import Path
from check_browser_preview import static_server

INSTALL='https://github.com/blucca/codex-desk#install-the-preview'
DRAFT='Plan the next retry review.'
SESSION='desk-sample-checkout-thread'

async def check(p,site,evidence,chromium,embedded):
    with static_server(site) as (url,received,escaped):
        browser=await p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=await browser.new_context(viewport={'width':390,'height':844})
        await context.route('https://github.com/**',lambda route:route.fulfill(content_type='text/html',body='<h2>Install the preview</h2>'))
        page=await context.new_page();page.set_default_timeout(10000)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        try:
            await page.goto(url)
            await page.wait_for_function('document.querySelector("#home-list").getAttribute("aria-busy")==="false"')
            await page.locator('#home-list').get_by_role('button',name='Resume conversation',exact=True).first.click()
            await page.locator('#prompt').wait_for()
            await page.locator('#prompt').fill('Verify the retry budget.')
            await page.locator('#prepare-followup').click()
            await page.wait_for_function('document.querySelector("#followup-count").textContent==="1" && !document.querySelector("#prepare-followup").disabled')
            await page.locator('#prompt').fill(DRAFT);await page.locator('#turn-mode').select_option('plan')
            await page.wait_for_function('v=>DeskBrowserPreview.snapshot().drafts[v.id]?.text===v.text',arg={'id':SESSION,'text':DRAFT})
            saved=await page.evaluate('DeskBrowserPreview.snapshot()')
            for control in ('#preview-banner a:has-text("Install for your own work")','#send','#followup-send'):
                if control=='#followup-send' and not await page.locator('#followups').evaluate('n=>n.open'):
                    await page.locator('#followups summary').click()
                if embedded:
                    async with context.expect_page() as info:await page.locator(control).click()
                    popup=await info.value
                    await popup.wait_for_url(INSTALL)
                    assert page.url==url
                    assert await page.evaluate('DeskBrowserPreview.snapshot()')==saved
                    await popup.close()
                    requests=await page.evaluate('DeskBrowserPreview.requests')
                    assert not any(r['path']=='/api/open' and r['data'].get('session')==INSTALL for r in requests), requests
                else:
                    await page.locator(control).click();await page.wait_for_url(INSTALL)
                    await page.go_back();await page.locator('#prompt').wait_for()
                    assert await page.evaluate('DeskBrowserPreview.snapshot()')==saved
            await page.reload();await page.locator('#prompt').wait_for()
            assert await page.evaluate('DeskBrowserPreview.snapshot()')==saved
            assert not errors and not escaped,(errors,escaped)
            result={'passed':True,'embedded':embedded,'controls':3,'saved_state':saved,'javascript_errors':errors,'escaped_api_requests':escaped,'native_model_calls':0}
            (evidence/('embedded-links.json' if embedded else 'direct-links.json')).write_text(json.dumps(result,indent=2)+'\n')
            return result
        finally:await context.close();await browser.close()

async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        result=[await check(p,args.site,args.evidence,args.chromium,False),await check(p,args.embedded_site,args.evidence,args.chromium,True)]
    print(json.dumps({'passed':True,'modes':[r['embedded'] for r in result]}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site',type=Path,required=True)
    parser.add_argument('--embedded-site',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--chromium')
    asyncio.run(main(parser.parse_args()))
