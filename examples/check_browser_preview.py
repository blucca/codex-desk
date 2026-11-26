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
            captured.extend(await log())

            await page.reload()
            await page.wait_for_function("!document.querySelector('#task').hidden")
            await page.wait_for_function("document.querySelector('#followup-count').textContent === '2'")
            assert await page.locator("#prompt").input_value() == DRAFT
            assert await page.locator("#turn-mode").input_value() == "plan"
            rows = await followups()
            assert [r["text"] for r in rows] == [SECOND, FIRST]
            assert [r["id"] for r in rows] == queued_ids
            preserved = await snapshot()
            assert preserved == saved, "Reload altered local sample preparation"
            await page.locator("#followups summary").click()
            await checkpoint("preserved-after-reload")

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
    async with async_playwright() as playwright:
        results = [await check(playwright, site, evidence, int(width), args.chromium, args.url) for width in args.widths.split(",")]
    (evidence / "acceptance.json").write_text(json.dumps({"passed": True, "viewports": results}, indent=2) + "\n")


if __name__ == "__main__":
    workspace = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=workspace / "temp/round122-preview/site/demo")
    parser.add_argument("--evidence", type=Path, default=workspace / "temp/round122-preview/browser-evidence")
    parser.add_argument("--url", help="Verify the same sample flow at an already-deployed URL")
    parser.add_argument("--widths", default="1250,390")
    parser.add_argument("--chromium", default=os.environ.get("DESK_CHROMIUM"))
    asyncio.run(main(parser.parse_args()))
