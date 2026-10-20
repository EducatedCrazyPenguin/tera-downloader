"""Test-only hidden subprocess: crash at an owned synthetic transfer boundary."""
import os
from pathlib import Path
import sys
import time

from queue_manager import QueueManager
from test_delivery_c import Client


def main():
    directory, stage = Path(sys.argv[1]), sys.argv[2]
    assert directory.is_dir() and stage in {'body', 'before_rename', 'after_rename'}
    print(f'Owned crash fixture PID {os.getpid()}; stage {stage}', flush=True)
    Client.gate.set()
    class CrashClient(Client):
        def download(self, video, folder, progress, *, checkpoint=None):
            original_commit, original_finalize = checkpoint.commit, checkpoint.finalize
            def commit(value):
                result = original_commit(value)
                if stage == 'body' and value['offset'] >= 1024 * 1024 and value['phase'] == 'partial':
                    os._exit(23)
                if stage == 'before_rename' and value['phase'] == 'ready':
                    os._exit(24)
                return result
            def finalize():
                result = original_finalize()
                if stage == 'after_rename': os._exit(25)
                return result
            checkpoint.commit, checkpoint.finalize = commit, finalize
            return super().download(video, folder, progress, checkpoint=checkpoint)
    manager = QueueManager(directory / 'state', CrashClient)
    assert manager.ready.wait(3) and not manager.startup_error
    manager.request('review', links=['https://terabox.com/s/1synthetic'], folder=str(directory / 'videos'), profile=None)
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        snapshot = manager.request('snapshot')
        if snapshot['jobs'] and snapshot['jobs'][0]['status'] == 'review':
            manager.request('select', job_ids=[snapshot['jobs'][0]['id']])
            break
        time.sleep(.01)
    while time.monotonic() < deadline:
        time.sleep(.01)
    manager.post('close')
    assert manager.closed.wait(3)
    raise AssertionError('Expected synthetic crash did not occur')


if __name__ == '__main__': main()
