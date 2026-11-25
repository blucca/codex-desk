"""Observed native-smoke ENOTEMPTY and Windows sharing-violation teardown."""
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

    def test_windows_startup_git_lock_retries_then_deletes_actual_scratch(self):
        folder = NativeScratch(dir=ROOT)
        path = Path(folder.name)
        fetch = path / 'native home' / '.tmp' / 'plugins-clone' / '.git' / 'FETCH_HEAD'
        fetch.parent.mkdir(parents=True)
        fetch.write_text('Native startup git writer')
        sharing = PermissionError(errno.EACCES, 'Used by another process', str(fetch))
        sharing.winerror = 32
        original = tempfile.TemporaryDirectory.cleanup
        calls = []

        def finish(scratch):
            calls.append(scratch.name)
            if len(calls) == 1:
                raise sharing
            return original(scratch)

        try:
            with patch.object(tempfile.TemporaryDirectory, 'cleanup', finish), \
                    patch('native_scratch.time.sleep') as pause:
                folder.cleanup()
            self.assertFalse(path.exists())
            self.assertEqual(len(calls), 2)
            pause.assert_called_once_with(0.25)
        finally:
            folder.cleanup()

    def test_persistent_windows_lock_remains_visible_at_five_second_deadline(self):
        folder = NativeScratch(dir=ROOT)
        sharing = PermissionError(errno.EACCES, 'Still used by another process', 'FETCH_HEAD')
        sharing.winerror = 32
        try:
            with patch.object(tempfile.TemporaryDirectory, 'cleanup', side_effect=sharing) as cleanup, \
                    patch('native_scratch.time.sleep') as pause, \
                    patch('native_scratch.time.monotonic', side_effect=(10, 10, 15)):
                with self.assertRaises(PermissionError) as failure:
                    folder.cleanup()
                self.assertIs(failure.exception, sharing)
                self.assertEqual(cleanup.call_count, 2)
                pause.assert_called_once_with(0.25)
        finally:
            folder.cleanup()

    def test_unrelated_error_propagates_without_retry(self):
        folder = NativeScratch(dir=ROOT)
        denied = PermissionError(errno.EACCES, 'Denied')
        denied.winerror = 5
        try:
            with patch.object(tempfile.TemporaryDirectory, 'cleanup',
                              side_effect=denied) as cleanup, \
                    patch('native_scratch.time.sleep') as pause:
                with self.assertRaises(PermissionError):
                    folder.cleanup()
                cleanup.assert_called_once()
                pause.assert_not_called()
        finally:
            folder.cleanup()


if __name__ == '__main__':
    unittest.main()
