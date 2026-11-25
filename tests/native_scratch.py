"""Bounded teardown for native startup writers finishing in runner scratch."""
import errno
import tempfile
import time


class NativeScratch(tempfile.TemporaryDirectory):
    def cleanup(self):
        # A just-closed native backend can have a short-lived git startup child.
        attempt, sharing_deadline = 0, None
        while True:
            try:
                return super().cleanup()
            except OSError as error:
                if isinstance(error, PermissionError) and getattr(error, 'winerror', None) == 32:
                    if sharing_deadline is None:
                        sharing_deadline = time.monotonic() + 5
                    remaining = sharing_deadline - time.monotonic()
                    if remaining <= 0:
                        raise
                    time.sleep(min(0.25, remaining))
                elif error.errno == errno.ENOTEMPTY and attempt < 4:
                    attempt += 1
                    time.sleep(0.05)
                else:
                    raise
