"""Testa o instalador sem sudo, rede ou alterações fora de diretórios temporários."""
import json
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestInstaller(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.install = self.root / "installation"
        self.install.mkdir()
        (self.install / "version").write_text("1.0.0\n")
        (self.install / "baseus_app.py").write_text("")
        (self.install / ".venv").mkdir()
        (self.install / ".venv/old-environment").write_text("preserved")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "runtime").mkdir()
        self.calls = self.root / "curl-calls"
        self.env = dict(
            os.environ,
            BASEUS_INSTALL_DIR=str(self.install),
            BASEUS_UPDATE_LOCK_FILE=str(self.root / "update-lock"),
            PATH=f"{self.bin}:{os.environ['PATH']}",
            TEST_INSTALL_ROOT=str(self.root),
            CURL_CALLS=str(self.calls),
            XDG_DATA_HOME=str(self.root / "data"),
            XDG_CONFIG_HOME=str(self.root / "config"),
            XDG_RUNTIME_DIR=str(self.root / "runtime"),
        )
        self.executable(self.bin / "sudo", """#!/bin/sh
if [ "$1" = tee ]; then cat >/dev/null; fi
exit 0
""")
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
    raise SystemExit(0)
if sys.argv[1:3] == ['-m', 'pip']:
    raise SystemExit(19 if os.environ.get('FAIL_PIP') else 0)
os.execv({sys.executable!r}, [{sys.executable!r}] + sys.argv[1:])
'''
        self.executable(self.bin / "python3", runner)
        self.executable(self.bin / "curl", """#!/bin/sh
url=''
output=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) shift; output="$1" ;;
        http*) url="$1" ;;
    esac
    shift
done
printf '%s\n' "$url" >> "$CURL_CALLS"
if [ -n "$FAIL_DOWNLOAD" ]; then exit 22; fi
case "$url" in
    */releases/latest) cp "$FAKE_API" "$output" ;;
    */archive/refs/tags/*) cp "$FAKE_RELEASE" "$output" ;;
    *) exit 2 ;;
esac
""")
        self.api = self.root / "release.json"
        self.api.write_text(json.dumps({
            "tag_name": "v2.0.0", "draft": False, "prerelease": False,
        }))
        release = self.root / "release"
        (release / "app").mkdir(parents=True)
        (release / "app/__init__.py").write_text("")
        (release / "app/uninstall.py").write_text("""import os, pathlib, sys
if len(sys.argv) == 3 and sys.argv[1] == '--register-desktop':
    destination = pathlib.Path(os.environ['XDG_DATA_HOME']) / 'applications'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'baseus-presenter-uninstall.desktop').write_text(
        '[Desktop Entry]\\nType=Application\\nName=Uninstall\\n'
        'Exec=/bin/bash \\\"' + str(pathlib.Path(sys.argv[2]) / 'uninstall.sh') + '\\\"\\n'
        'Terminal=true\\n')
""")
        (release / "baseus_app.py").write_text("")
        (release / "requirements.txt").write_text("")
        (release / "version").write_text("2.0.0\n")
        (release / "updater.sh").write_text("#!/bin/bash\n")
        (release / "uninstall.sh").write_text("#!/bin/bash\n")
        archive = self.root / "release.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            output.add(release, arcname="baseus-presenter-linux-2.0.0")
        self.env.update(FAKE_API=str(self.api), FAKE_RELEASE=str(archive))

    @staticmethod
    def executable(path, contents):
        path.write_text(contents)
        path.chmod(0o755)

    def run_installer(self, *args):
        return subprocess.run(
            ["bash", str(ROOT / "install.sh"), *args],
            env=self.env, text=True, capture_output=True, timeout=15,
        )

    def run_piped_installer(self, answers):
        command = f"cat {shlex.quote(str(ROOT / 'install.sh'))} | bash"
        return subprocess.run(
            ["script", "-qefc", command, "/dev/null"],
            input=answers, env=self.env, text=True, capture_output=True,
            timeout=15,
        )

    def assert_old_install_preserved(self):
        self.assertEqual((self.install / "version").read_text(), "1.0.0\n")
        self.assertEqual((self.install / ".venv/old-environment").read_text(), "preserved")

    def test_success_uses_latest_tag_and_creates_working_environment(self):
        for tag in ("v2.0.0", "2.0.0"):
            with self.subTest(tag=tag):
                self.api.write_text(json.dumps({"tag_name": tag, "draft": False, "prerelease": False}))
                result = self.run_installer("--autostart")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((self.install / "version").read_text(), "2.0.0\n")
                self.assertIn("/releases/latest", self.calls.read_text())
                self.assertIn(f"/archive/refs/tags/{tag}.tar.gz", self.calls.read_text())
                entrypoint = self.install / ".venv/bin/entrypoint"
                launched = subprocess.run([str(entrypoint)], capture_output=True, text=True, timeout=5)
                self.assertEqual(launched.returncode, 0, launched.stderr)
                self.assertEqual(launched.stdout.strip(), "ok")
                desktop = self.root / "data/applications/baseus-presenter.desktop"
                self.assertIn(str(self.install / ".venv/bin/python"), desktop.read_text())
                self.assertTrue((self.root / "config/autostart/baseus-presenter.desktop").exists())
                uninstall = self.root / "data/applications/baseus-presenter-uninstall.desktop"
                self.assertTrue(uninstall.exists())
                self.assertIn(str(self.install / "uninstall.sh"), uninstall.read_text())
                self.assertFalse(any(self.root.glob("installation.backup.*")))
                self.assertFalse(any(self.root.glob("installation.prepare.*")))

    def test_first_install_and_no_autostart(self):
        destination = self.root / "fresh-installation"
        self.env["BASEUS_INSTALL_DIR"] = str(destination)
        result = self.run_installer("--no-autostart")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((destination / "version").read_text(), "2.0.0\n")
        self.assertFalse((self.root / "config/autostart/baseus-presenter.desktop").exists())

    def test_piped_install_accepts_uppercase_no(self):
        result = self.run_piped_installer("N\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "config/autostart/baseus-presenter.desktop").exists())

    def test_piped_install_accepts_lowercase_no(self):
        result = self.run_piped_installer("n\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "config/autostart/baseus-presenter.desktop").exists())

    def test_piped_install_accepts_lowercase_yes(self):
        result = self.run_piped_installer("y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "config/autostart/baseus-presenter.desktop").exists())

    def test_piped_install_reprompts_until_yes_or_no(self):
        result = self.run_piped_installer("\nindefinido\nY\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "config/autostart/baseus-presenter.desktop").exists())
        self.assertGreaterEqual(result.stdout.count("[y/n]"), 3)

    def test_install_without_terminal_requires_explicit_autostart_choice(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assert_old_install_preserved()
        self.assertIn("--autostart", result.stdout + result.stderr)
        self.assertIn("--no-autostart", result.stdout + result.stderr)

    def test_activation_failure_restores_old_code_and_environment(self):
        import shutil
        real_mv = shutil.which("mv")
        self.executable(self.bin / "mv", f'''#!/bin/sh
if [ "$1" = -- ]; then shift; fi
case "$1" in *.prepare.*/staging) exit 19 ;; esac
exec "{real_mv}" "$@"
''')
        result = self.run_installer("--no-autostart")
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_install_preserved()
        self.assertFalse(any(self.root.glob("installation.backup.*")))
        self.assertFalse((self.root / "data/applications/baseus-presenter-uninstall.desktop").exists())

    def test_launcher_failure_rolls_back_after_activation(self):
        import shutil
        real_cp = shutil.which("cp")
        self.executable(self.bin / "cp", f'''#!/bin/sh
for argument in "$@"; do
    case "$argument" in */applications/baseus-presenter.desktop) exit 20 ;; esac
done
exec "{real_cp}" "$@"
''')
        result = self.run_installer("--no-autostart")
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_install_preserved()
        self.assertFalse((self.root / "data/applications/baseus-presenter-uninstall.desktop").exists())

    def test_network_failure_preserves_existing_installation(self):
        self.env["FAIL_DOWNLOAD"] = "1"
        result = self.run_installer("--no-autostart")
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_install_preserved()

    def test_pip_failure_preserves_existing_installation_and_exact_tag_url(self):
        self.env["FAIL_PIP"] = "1"
        result = self.run_installer("--no-autostart")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_old_install_preserved()
        self.assertIn("/archive/refs/tags/v2.0.0.tar.gz", self.calls.read_text())
        self.assertFalse(any(self.root.glob("installation.backup.*")))

    def test_success_activates_release_and_relocates_venv_entrypoint(self):
        result = self.run_installer("--no-autostart")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.install / "version").read_text(), "2.0.0\n")
        entrypoint = self.install / ".venv/bin/entrypoint"
        self.assertTrue(entrypoint.read_text().startswith(
            "#!" + str(self.install / ".venv/bin/python")))
        self.assertNotIn(".prepare.", entrypoint.read_text())
        desktop = self.root / "data/applications/baseus-presenter.desktop"
        self.assertIn(str(self.install), desktop.read_text())
        self.assertFalse((self.root / "config/autostart/baseus-presenter.desktop").exists())

    def test_failure_after_activation_rolls_back_previous_installation(self):
        # Faz a criação do diretório XDG falhar somente após a troca do app.
        blocked = self.root / "blocked-data"
        blocked.write_text("not a directory")
        self.env["XDG_DATA_HOME"] = str(blocked)
        result = self.run_installer("--no-autostart")
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_install_preserved()
        self.assertIn("restaurada", result.stdout)

    def test_rejects_invalid_or_unstable_release_metadata(self):
        cases = [
            {"tag_name": "main", "draft": False, "prerelease": False},
            {"tag_name": "v2.0.0", "draft": True, "prerelease": False},
            {"tag_name": "v2.0.0", "draft": False, "prerelease": True},
            {},
            [],
            None,
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                self.api.write_text(json.dumps(metadata))
                result = self.run_installer("--no-autostart")
                self.assertNotEqual(result.returncode, 0)
                self.assert_old_install_preserved()

    def test_rejects_package_version_different_from_tag(self):
        self.api.write_text(json.dumps({
            "tag_name": "2.1.0", "draft": False, "prerelease": False,
        }))
        result = self.run_installer("--no-autostart")
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_install_preserved()
        self.assertIn("não confere", result.stdout)

    def test_rejects_git_checkout_for_directory_and_worktree_file(self):
        for worktree in (False, True):
            git = self.install / ".git"
            if worktree:
                git.write_text("gitdir: elsewhere\n")
            else:
                git.mkdir()
                (git / "HEAD").write_text("ref: refs/heads/main\n")
            result = self.run_installer("--no-autostart")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checkout Git", result.stdout)
            if worktree:
                git.unlink()
            else:
                import shutil
                shutil.rmtree(git)

    def test_shared_lock_rejects_concurrent_operation(self):
        import fcntl
        lock = Path(self.env["BASEUS_UPDATE_LOCK_FILE"])
        with lock.open("w") as locked:
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_installer("--no-autostart")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("andamento", result.stdout)
        self.assert_old_install_preserved()

    def test_running_app_prevents_replacement(self):
        import fcntl
        lock = self.root / "runtime/baseus_presenter.lock"
        with lock.open("w") as locked:
            fcntl.lockf(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_installer("--no-autostart")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("trava do aplicativo", result.stdout + result.stderr)
        self.assert_old_install_preserved()
        self.assertFalse(any(self.root.glob("installation.backup.*")))

    def test_app_lock_is_held_during_activation_and_released_afterwards(self):
        import fcntl
        import shutil
        real_mv = shutil.which("mv")
        self.executable(self.bin / "mv", f'''#!{sys.executable}
import fcntl, os, subprocess, sys
with open(os.path.join(os.environ['XDG_RUNTIME_DIR'], 'baseus_presenter.lock'), 'a+') as lock:
    try:
        fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        raise SystemExit('A instalação está sendo movida sem a trava do app!')
raise SystemExit(subprocess.call([{real_mv!r}] + sys.argv[1:]))
''')
        result = self.run_installer("--no-autostart")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with (self.root / "runtime/baseus_presenter.lock").open("a+") as lock:
            fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


if __name__ == "__main__":
    unittest.main()
