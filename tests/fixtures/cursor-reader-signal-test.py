"""Exercise the compiled reader's shutdown with real PipeWire worker threads.

Usage: python3 tests/fixtures/cursor-reader-signal-test.py /tmp/baseus-cursor-reader
The socket peer intentionally sends no video; no compositor is contacted.
"""
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def check_shutdown(binary):
    peer, remote = socket.socketpair()
    with peer, remote:
        child = subprocess.Popen(
            [binary, str(remote.fileno()), '0'], pass_fds=(remote.fileno(),),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise AssertionError(('Reader exited before shutdown test',
                                          child.returncode, child.communicate()))
                status = Path(f'/proc/{child.pid}/status').read_text()
                mask = next(line.split()[1] for line in status.splitlines()
                            if line.startswith('SigBlk:'))
                threads = list(Path(f'/proc/{child.pid}/task').iterdir())
                if int(mask, 16) & (1 << (signal.SIGTERM - 1)) and len(threads) > 1:
                    break
                time.sleep(0.01)
            else:
                raise AssertionError('Signal handling and worker threads not ready')
            child.terminate()
            output, errors = child.communicate(timeout=3)
            assert child.returncode == 0, (child.returncode, output, errors)
            stats = [json.loads(line) for line in output.splitlines()
                     if json.loads(line).get('event') == 'stats']
            assert len(stats) == 1 and stats[0]['buffers'] == 0, output
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()


check_shutdown(sys.argv[1])
print('Reader shutdown preserves statistics: OK')
