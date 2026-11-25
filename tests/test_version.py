from pathlib import Path
import tomllib
import unittest

from codex_desk import __version__


class VersionTests(unittest.TestCase):
    def test_build_metadata_uses_the_canonical_package_attribute(self):
        metadata = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())
        self.assertNotIn('version', metadata['project'])
        self.assertEqual(metadata['project']['dynamic'], ['version'])
        self.assertEqual(metadata['tool']['setuptools']['dynamic']['version'],
                         {'attr': 'codex_desk.__version__'})
        self.assertIsInstance(__version__, str)
        self.assertTrue(__version__)


if __name__ == '__main__':
    unittest.main()
