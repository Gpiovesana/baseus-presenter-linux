"""Exercita a transação real com download e ambiente Python locais simulados."""
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestUpdaterShell(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.install = self.root / "installation"
        self.install.mkdir()
        self.status = self.root / "status"
        self.state = self.root / "state"
        self.lock = self.root / "lock"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, BASEUS_INSTALL_DIR=str(self.install),
                        BASEUS_UPDATE_STATE_FILE=str(self.state),
                        BASEUS_UPDATE_LOCK_FILE=str(self.lock),
                        PATH=f"{self.bin}:{os.environ['PATH']}",
                        TEST_UPDATE_ROOT=str(self.root))
        runner = f'''#!{sys.executable}
import os, pathlib, sys
if sys.argv[1:3] == ['-m', 'venv']:
    target = pathlib.Path(sys.argv[-1]) / 'bin'
    target.mkdir(parents=True, exist_ok=True)
    script = target / 'python'
    script.write_text(pathlib.Path(__file__).read_text())
    script.chmod(0o755)
    entry = target / 'entrypoint'
    entry.write_text('#!' + str(script) + '\\nprint("ok")\\n')
    entry.chmod(0o755)
    sys.exit(0)
if sys.argv[1:3] == ['-m', 'pip']:
    sys.exit(17 if os.environ.get('FAIL_PIP') else 0)
os.execv({sys.executable!r}, [{sys.executable!r}] + sys.argv[1:])
'''
        self.executable(self.bin / "python3", runner)
        old_python = self.install / ".venv/bin/python"
        old_python.parent.mkdir(parents=True)
        self.executable(old_python, runner)
        (self.install / "version").write_text("1.0.0\n")
        (self.install / "baseus_app.py").write_text(
            "import os, pathlib\npathlib.Path(os.environ['TEST_UPDATE_ROOT'], 'rollback').write_text('restarted')\n")
        self.executable(self.bin / "curl", '''#!/bin/sh
if [ -n "$FAIL_DOWNLOAD" ]; then exit 22; fi
while [ "$#" -gt 0 ]; do
    if [ "$1" = '-o' ]; then shift; cp "$FAKE_RELEASE" "$1"; exit; fi
    shift
done
exit 1
''')
        self.release = self.root / "release"
        (self.release / "app").mkdir(parents=True)
        (self.release / "app/__init__.py").write_text("")
        (self.release / "version").write_text("2.0.0\n")
        (self.release / "requirements.txt").write_text("")
        (self.release / "updater.sh").write_text("#!/bin/bash\n")
        self.payload = '''import os, pathlib, time
root = pathlib.Path(os.environ['TEST_UPDATE_ROOT'])
if os.environ.get('FAIL_STARTUP'):
    raise SystemExit(23)
assert pathlib.Path(str(root / 'installation') + '_backup').is_dir()
pathlib.Path(os.environ['BASEUS_UPDATE_READY_FILE']).write_text(str(os.getpid()))
(root / 'started').write_text('ready')
time.sleep(1)
'''

    def executable(self, path, text):
        path.write_text(text)
        path.chmod(0o755)

    def run_update(self, pid="99999999"):
        (self.release / "baseus_app.py").write_text(self.payload)
        archive = self.root / "release.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            output.add(self.release, arcname="release")
        self.env["FAKE_RELEASE"] = str(archive)
        return subprocess.run(
            ["bash", str(ROOT / "updater.sh"), "2.0.0", pid, str(self.status)],
            env=self.env, text=True, capture_output=True, timeout=15)

    def test_download_failure_preserves_installation(self):
        self.env["FAIL_DOWNLOAD"] = "1"
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.install / "version").read_text(), "1.0.0\n")
        self.assertEqual(self.status.read_text().strip(), "ERROR")

    def test_pip_failure_preserves_installation_before_ready(self):
        self.env["FAIL_PIP"] = "1"
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.install / "version").read_text(), "1.0.0\n")
        self.assertEqual(self.status.read_text().strip(), "ERROR")
        self.assertFalse(Path(str(self.install) + "_backup").exists())

    def test_success_keeps_backup_until_startup_confirmation(self):
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.install / "version").read_text(), "2.0.0\n")
        self.assertTrue((self.root / "started").exists())
        entry = self.install / ".venv/bin/entrypoint"
        self.assertTrue(entry.read_text().startswith("#!" + str(self.install / ".venv/bin/python")))
        self.assertNotIn("_staging", entry.read_text())
        launched = subprocess.run([str(entry)], env=self.env, capture_output=True,
                                  text=True, timeout=5)
        self.assertEqual(launched.returncode, 0, launched.stderr)
        self.assertEqual(launched.stdout.strip(), "ok")
        self.assertFalse(Path(str(self.install) + "_backup").exists())
        self.assertFalse(self.state.exists())

    def test_startup_failure_restores_and_restarts_previous_version(self):
        self.env["FAIL_STARTUP"] = "1"
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.install / "version").read_text(), "1.0.0\n")
        # O filho restaurado pode ainda estar recebendo CPU após a saída do shell.
        import time
        deadline = time.monotonic() + 2
        while not (self.root / "rollback").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue((self.root / "rollback").exists(), result.stdout + result.stderr)
        self.assertFalse(self.state.exists())

    def test_lock_rejects_concurrent_update(self):
        import fcntl
        with self.lock.open('w') as locked:
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("andamento", result.stdout)
        self.assertEqual((self.install / "version").read_text(), "1.0.0\n")

    def test_recovery_does_not_touch_running_installation(self):
        # Falha antes do READY, com backup/estado pré-existentes e app vivo.
        backup = Path(str(self.install) + "_backup")
        backup.mkdir()
        (backup / "version").write_text("0.9.0\n")
        self.state.write_text("pending\n")
        self.env["FAIL_DOWNLOAD"] = "1"
        result = self.run_update(str(os.getpid()))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.install / "version").read_text(), "1.0.0\n")
        self.assertTrue(backup.exists())
