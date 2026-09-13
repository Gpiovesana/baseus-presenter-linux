"""Safety and transaction tests for the standalone uninstaller."""
import fcntl
import io
import os
import subprocess
import shutil
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import uninstall


class TestUninstall(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(os.chdir, Path.cwd())
        self.root = Path(temporary.name)
        rule = mock.patch.object(uninstall, "UDEV_RULE", self.root / "udev.rules")
        rule.start()
        self.addCleanup(rule.stop)
        self.install = self.root / "Baseus Presenter % 100"
        (self.install / "app").mkdir(parents=True)
        (self.install / "app/uninstall.py").write_text("", encoding="utf-8")
        (self.install / "baseus_app.py").write_text("", encoding="utf-8")
        (self.install / "version").write_text("1.0.0\n", encoding="utf-8")
        (self.install / "uninstall.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        self.data = self.root / "xdg-data"
        self.config = self.root / "xdg-config"
        self.runtime = self.root / "runtime"
        self.data.mkdir()
        self.config.mkdir()
        self.runtime.mkdir()
        self.env = mock.patch.dict(os.environ, {
            "XDG_DATA_HOME": str(self.data),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "BASEUS_UPDATE_LOCK_FILE": str(self.root / "update.lock"),
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_confirmation_cancel_and_eof_never_remove(self):
        for answer in ("", "no", "sim", "desinstala", "desinstalar agora"):
            with self.subTest(answer=answer), \
                    mock.patch("builtins.input", return_value=answer), \
                    mock.patch.object(uninstall, "remove_installation") as remove:
                self.assertEqual(uninstall.main([str(self.install)]), 0)
                remove.assert_not_called()

        with mock.patch("builtins.input", side_effect=EOFError), \
                mock.patch.object(uninstall, "remove_installation") as remove:
            self.assertEqual(uninstall.main([str(self.install)]), 1)
            remove.assert_not_called()

    def test_explicit_confirmation_calls_removal(self):
        for answer in ("DESINSTALAR", "desinstalar", "Desinstalar", "dEsInStAlAr"):
            with self.subTest(answer=answer), \
                    mock.patch("builtins.input", return_value=answer), \
                    mock.patch.object(uninstall, "UninstallProgress") as progress_type, \
                    mock.patch.object(uninstall, "remove_installation") as remove:
                self.assertEqual(uninstall.main([str(self.install)]), 0)
                remove.assert_called_once_with(str(self.install), progress=progress_type.return_value.update)
                progress_type.return_value.close.assert_called_once()

    def test_validation_rejects_root_home_symlink_and_invalid_directories(self):
        with self.assertRaises(ValueError):
            uninstall.validate_installation("/")
        with mock.patch.object(uninstall.Path, "home", return_value=self.root):
            with self.assertRaises(ValueError):
                uninstall.validate_installation(self.root)

        link = self.root / "link"
        link.symlink_to(self.install, target_is_directory=True)
        with self.assertRaises(ValueError):
            uninstall.validate_installation(link)

        for invalid in (self.root / "missing", self.root / "empty"):
            invalid.mkdir(exist_ok=True)
            with self.assertRaises(ValueError):
                uninstall.validate_installation(invalid)

    def test_validation_rejects_checkout_ancestor(self):
        (self.install / ".git").mkdir()
        (self.install / ".git/HEAD").write_text("ref: refs/heads/main\n")
        with self.assertRaises(ValueError):
            uninstall.validate_installation(self.install)

    def test_register_desktop_quotes_spaces_and_percent_and_is_terminal(self):
        launcher = uninstall.register_desktop(self.install)
        content = launcher.read_text(encoding="utf-8")
        self.assertIn("Terminal=true", content)
        self.assertNotIn("DESINSTALAR", content)
        self.assertNotIn("--yes", content)
        self.assertIn("Exec=/bin/bash", content)
        self.assertIn("Baseus Presenter", content)
        self.assertIn("%%", content)

    def test_register_materializes_missing_wrapper(self):
        wrapper = self.install / "uninstall.sh"
        wrapper.unlink()
        uninstall.register_desktop(self.install)
        self.assertTrue(wrapper.is_file())
        self.assertIn("app/uninstall.py", wrapper.read_text(encoding="utf-8"))

    def test_wrapper_real_abre_aviso_e_enter_cancela(self):
        shutil.copyfile(uninstall.__file__, self.install / "app/uninstall.py")
        from app import i18n
        shutil.copyfile(i18n.__file__, self.install / "app/i18n.py")
        shutil.copytree(i18n.TRANSLATIONS, self.install / "app/translations")
        (self.install / "uninstall.sh").write_text(uninstall.WRAPPER)
        result = subprocess.run(
            ["bash", str(self.install / "uninstall.sh")], input="\n",
            text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AVISO", result.stdout)
        self.assertIn("Enter cancela", result.stdout)
        self.assertTrue(self.install.exists())

    @unittest.skipUnless(shutil.which("desktop-file-validate"), "validador não instalado")
    def test_desktop_valido(self):
        launcher = uninstall.register_desktop(self.install)
        result = subprocess.run(["desktop-file-validate", str(launcher)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_falha_sudo_preserva_instalacao(self):
        uninstall.UDEV_RULE.write_text("regra de teste")
        with mock.patch.object(uninstall.os, "geteuid", return_value=1000), \
                mock.patch.object(uninstall, "stop_application"), \
                mock.patch.object(uninstall.subprocess, "run",
                                  side_effect=subprocess.CalledProcessError(1, "sudo")), \
                self.assertRaises(subprocess.CalledProcessError):
            uninstall.remove_installation(self.install)
        self.assertTrue(self.install.exists())

    def test_trava_livre_nao_envia_sinal(self):
        with uninstall.open_lock(self.runtime / "app.lock") as lock, \
                mock.patch.object(uninstall.os, "kill") as kill:
            uninstall.stop_application(self.install, lock)
        kill.assert_not_called()

    def test_aguarda_encerramento_de_processo_da_instalacao(self):
        script = self.install / "baseus_app.py"
        script.write_text(
            "import fcntl, os, pathlib, signal, time\n"
            f"lock = open({str(self.runtime / 'app.lock')!r}, 'w+')\n"
            "fcntl.lockf(lock, fcntl.LOCK_EX)\n"
            "lock.write(str(os.getpid())); lock.flush()\n"
            f"marker = pathlib.Path({str(self.root / 'closed')!r})\n"
            "def stop(*args):\n"
            "    marker.write_text('devices released')\n"
            "    raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            f"pathlib.Path({str(self.root / 'ready')!r}).touch()\n"
            "while True: time.sleep(0.01)\n")
        process = subprocess.Popen([sys.executable, str(script)])
        try:
            deadline = time.monotonic() + 5
            while not (self.root / "ready").exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    self.fail("O processo de teste não iniciou")
                time.sleep(0.01)
            with uninstall.open_lock(self.runtime / "app.lock") as lock:
                uninstall.stop_application(self.install, lock)
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual((self.root / "closed").read_text(), "devices released")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_remove_only_installation_and_shortcuts_preserving_external_data(self):
        (self.data / "applications").mkdir()
        (self.config / "autostart").mkdir()
        for path in (
            self.data / "applications/baseus-presenter.desktop",
            self.data / "applications/baseus-presenter-uninstall.desktop",
            self.config / "autostart/baseus-presenter.desktop",
        ):
            path.write_text("desktop", encoding="utf-8")
        external = self.root / "profiles/model transcript"
        external.mkdir(parents=True)
        (external / "keep.dat").write_text("keep", encoding="utf-8")

        stages = []
        with mock.patch.object(uninstall.os, "geteuid", return_value=1000), \
                mock.patch.object(uninstall, "stop_application"), \
                mock.patch.object(uninstall, "app_lock_path", return_value=self.runtime / "app.lock"), \
                mock.patch.object(uninstall.subprocess, "run") as run:
            uninstall.remove_installation(self.install, progress=lambda message: stages.append(message))

        self.assertFalse(self.install.exists())
        self.assertFalse((self.data / "applications/baseus-presenter.desktop").exists())
        self.assertFalse((self.data / "applications/baseus-presenter-uninstall.desktop").exists())
        self.assertFalse((self.config / "autostart/baseus-presenter.desktop").exists())
        self.assertTrue((external / "keep.dat").exists())
        run.assert_not_called()
        self.assertTrue(any("Encerrando" in message for message in stages))
        self.assertTrue(any("arquivos" in message for message in stages))
        self.assertTrue(any("atalhos" in message for message in stages))

    def test_progress_window_reports_steps_and_closes(self):
        process = mock.Mock()
        process.stdin = io.StringIO()
        process.poll.return_value = None
        with mock.patch.object(uninstall.shutil, "which", return_value="/usr/bin/zenity"), \
                mock.patch.object(uninstall.subprocess, "Popen", return_value=process):
            progress = uninstall.UninstallProgress()
            progress.update("Removendo arquivos…")
            self.assertIn("Removendo arquivos", process.stdin.getvalue())
            progress.close()
            process.wait.assert_called_once()

    def test_progress_unavailable_keeps_terminal_feedback(self):
        with mock.patch.object(uninstall.shutil, "which", return_value=None), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            progress = uninstall.UninstallProgress()
            progress.update("Removendo arquivos…")
            progress.close()
            self.assertIn("Removendo arquivos", output.getvalue())

    def test_update_lock_contention_aborts_before_removal(self):
        update_lock = Path(os.environ["BASEUS_UPDATE_LOCK_FILE"])
        with update_lock.open("w+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch.object(uninstall.os, "geteuid", return_value=1000), \
                    mock.patch.object(uninstall, "stop_application") as stop, \
                    self.assertRaises(RuntimeError):
                uninstall.remove_installation(self.install)
        self.assertTrue(self.install.exists())
        stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
