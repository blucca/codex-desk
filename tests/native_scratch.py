"""Bounded teardown for native startup writers finishing in runner scratch."""
import errno
import tempfile
import time


class NativeScratch(tempfile.TemporaryDirectory):
    def cleanup(self):
        # A just-closed native backend can have a short-lived git startup child.
        for attempt in range(5):
            try:
                return super().cleanup()
            except OSError as error:
                if error.errno != errno.ENOTEMPTY or attempt == 4:
                    raise
                time.sleep(0.05)
