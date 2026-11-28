"""README is also the installed PyPI description: links must survive that surface."""
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / 'README.md'
LINKS = re.compile(r'(!?)\[([^\]]*)\]\(([^)]+)\)')


class ReadmeLinksTests(unittest.TestCase):
    def test_readme_links_work_without_repository_relative_resolution(self):
        links = LINKS.findall(README.read_text(encoding='utf-8'))
        self.assertTrue(links)
        for image, label, target in links:
            with self.subTest(label=label, target=target):
                if target.startswith('#'):
                    continue
                parsed = urlsplit(target)
                self.assertIn(parsed.scheme, ('http', 'https'))
                self.assertTrue(parsed.netloc)
                if parsed.netloc == 'github.com' and parsed.path.startswith('/blucca/codex-desk/blob/'):
                    path = unquote(parsed.path.split('/', 5)[5])
                    self.assertTrue((ROOT / path).is_file(), path)

    def test_readme_images_use_retained_repository_assets(self):
        images = [target for image, label, target in LINKS.findall(README.read_text(encoding='utf-8')) if image]
        self.assertTrue(images)
        for target in images:
            with self.subTest(target=target):
                parsed = urlsplit(target)
                self.assertEqual(parsed.netloc, 'raw.githubusercontent.com')
                owner, repo, commit, path = parsed.path.lstrip('/').split('/', 3)
                self.assertEqual((owner, repo), ('blucca', 'codex-desk'))
                self.assertRegex(commit, r'^[0-9a-f]{40}$')
                self.assertTrue((ROOT / unquote(path)).is_file())


if __name__ == '__main__':
    unittest.main()
