"""Local workspace execution ownership, inherited atomically across Popen.

The parent closes (never explicitly unlocks) its duplicate after spawn. The
worker holds the same flock until cleanup completes, even if the web process
dies before saving its PID. This is a local-filesystem lock, not an OS sandbox.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


@contextmanager
def execution_lock(store, inherited_fd=None):
    path = Path(store.path).parent / 'execution.lock'
    if inherited_fd is None:
        handle = path.open('a')
    else:
        handle = os.fdopen(inherited_fd, 'a')
        try:
            actual, expected = os.fstat(handle.fileno()), path.stat()
            if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                raise ValueError('Devralınan yürütme kilidi bu çalışma alanına ait değil.')
        except BaseException:
            handle.close()
            raise
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
            return
        yield handle
    finally:
        # LOCK_UN would also release the lock in a surviving inherited worker.
        handle.close()


class WorkerStore:
    """Fence every worker journal write with its immutable claim token."""
    def __init__(self, store, job_id, lease):
        self.store, self.job_id, self.lease = store, job_id, lease

    def update(self, job_id, **fields):
        return self.store.update(job_id, lease=self.lease, **fields)

    def event(self, job_id, kind, data):
        return self.store.event(job_id, kind, data, lease=self.lease)

    def finish(self, job_id, status, result):
        return self.store.finish(job_id, status, result, lease=self.lease)

    def __getattr__(self, name):
        return getattr(self.store, name)
