import http.client
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from codex_desk import server as desk_server

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class PageAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.scripts.append(attrs['src'])
        elif tag == 'link' and attrs.get('rel') == 'stylesheet' and attrs.get('href'):
            self.styles.append(attrs['href'])


class AssetsTests(unittest.TestCase):
    def test_index_referenced_packaged_assets_are_served_with_correct_mime(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder, patch.object(desk_server, 'Runtime') as native:
            path = Path(folder)
            desk = desk_server.Desk('unused-native-binary', path / 'home', path / 'state')
            server = ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()

            def get(asset):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    connection.request('GET', asset)
                    response = connection.getresponse()
                    return response.status, response.getheader('Content-Type'), response.read()
                finally:
                    connection.close()

            try:
                status, mime, body = get('/')
                self.assertEqual(status, 200)
                self.assertEqual(mime, 'text/html; charset=utf-8')
                page = PageAssets()
                page.feed(body.decode('utf-8'))
                self.assertIn('/app.js', page.scripts)
                self.assertIn('/evidence.js', page.scripts)
                self.assertIn('/activity.js', page.scripts)
                self.assertIn('/followups.js', page.scripts)
                self.assertIn('/native-state.js', page.scripts)
                self.assertIn('/recall.js', page.scripts)
                self.assertIn('/style.css', page.styles)
                static = Path(desk_server.__file__).parent / 'static'
                for asset, expected in ([(a, 'text/javascript; charset=utf-8') for a in page.scripts]
                                        + [(a, 'text/css; charset=utf-8') for a in page.styles]):
                    with self.subTest(asset=asset):
                        address = urlsplit(asset)
                        self.assertFalse(address.scheme or address.netloc)
                        status, mime, body = get(asset)
                        self.assertEqual(status, 200)
                        self.assertEqual(mime, expected)
                        self.assertEqual(body, (static / address.path.lstrip('/')).read_bytes())
                        self.assertTrue(body)
                native.assert_not_called()
            finally:
                server.shutdown()
                worker.join(timeout=5)
                server.server_close()
                desk.close()
                desk.store.db.close()


if __name__ == '__main__':
    unittest.main()
