"""Reproduce the observed macOS native-smoke ENOTEMPTY teardown race."""
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native_scratch import NativeScratch

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class NativeScratchTests(unittest.TestCase):
    def test_startup_writer_race_retries_then_deletes_actual_scratch(self):
        folder = NativeScratch(dir=ROOT)
        path = Path(folder.name)
        (path / '.git').mkdir()
        original = tempfile.TemporaryDirectory.cleanup
        calls = []

        def finish(scratch):
            calls.append(scratch.name)
            if len(calls) == 1:
                raise OSError(errno.ENOTEMPTY, 'Directory not empty', '.git')
            return original(scratch)

        with patch.object(tempfile.TemporaryDirectory, 'cleanup', finish), \
                patch('native_scratch.time.sleep') as pause:
            folder.cleanup()
        self.assertFalse(path.exists())
        self.assertEqual(len(calls), 2)
        pause.assert_called_once_with(0.05)

    def test_persistent_writer_error_remains_visible_after_bounded_retries(self):
        folder = NativeScratch(dir=ROOT)
        try:
            with patch.object(tempfile.TemporaryDirectory, 'cleanup',
                              side_effect=OSError(errno.ENOTEMPTY, 'Still writing', '.git')) as cleanup, \
                    patch('native_scratch.time.sleep') as pause:
                with self.assertRaises(OSError) as failure:
                    folder.cleanup()
                self.assertEqual(failure.exception.errno, errno.ENOTEMPTY)
                self.assertEqual(cleanup.call_count, 5)
                self.assertEqual(pause.call_count, 4)
        finally:
            folder.cleanup()

    def test_unrelated_error_propagates_without_retry(self):
        folder = NativeScratch(dir=ROOT)
        try:
            with patch.object(tempfile.TemporaryDirectory, 'cleanup',
                              side_effect=PermissionError(errno.EACCES, 'Denied')) as cleanup, \
                    patch('native_scratch.time.sleep') as pause:
                with self.assertRaises(PermissionError):
                    folder.cleanup()
                cleanup.assert_called_once()
                pause.assert_not_called()
        finally:
            folder.cleanup()


if __name__ == '__main__':
    unittest.main()
