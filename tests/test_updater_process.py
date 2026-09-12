import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import updater


class FakeTimer:
    def __init__(self, parent=None):
        self.callback = None
        self.started = False

    def setInterval(self, interval):
        self.interval = interval

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    class _Timeout:
        def __init__(self, owner):
            self.owner = owner

        def connect(self, callback):
            self.owner.callback = callback

    @property
    def timeout(self):
        return self._Timeout(self)


class UpdateProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.install = Path(temporary.name)
        (self.install / "updater.sh").touch()
        patcher = mock.patch.object(updater, "__file__", str(self.install / "app/updater.py"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_checkout_and_worktree_are_blocked_before_starting_process(self):
        for kind in ("directory", "file", "ancestor"):
            with self.subTest(kind=kind):
                git = self.install / ".git"
                if kind == "directory":
                    git.mkdir()
                    (git / "HEAD").write_text("ref: refs/heads/dev")
                else:
                    git.write_text("gitdir: /some/worktree")
                if kind == "ancestor":
                    (self.install / "nested").mkdir()
                    updater.__file__ = str(self.install / "nested/app/updater.py")
                with mock.patch.object(updater.QMessageBox, "warning") as warning, \
                     mock.patch.object(updater.subprocess, "Popen") as popen:
                    self.assertFalse(updater.start_update_process("v2.3.0"))
                popen.assert_not_called()
                self.assertIn("checkout", warning.call_args.args[2])
                if git.is_dir():
                    (git / "HEAD").unlink()
                    git.rmdir()
                else:
                    git.unlink()

    def test_waits_for_ready_before_quitting(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / "status"
            log_file = Path(directory) / "log"
            status.touch()
            log_file.touch()
            descriptors = iter((os.open(status, os.O_RDWR), os.open(log_file, os.O_RDWR)))
            process = mock.Mock()
            process.poll.return_value = None
            app = mock.Mock()
            app._baseus_update_process = None
            timer = FakeTimer()

            with mock.patch.object(updater.tempfile, "mkstemp", side_effect=lambda **kw: (
                next(descriptors), str(status if "status" in kw["prefix"] else log_file)
            )), mock.patch.object(updater.QApplication, "instance", return_value=app), \
                 mock.patch.object(updater, "QTimer", return_value=timer), \
                 mock.patch.object(updater.QMessageBox, "warning") as warning, \
                 mock.patch.object(updater.subprocess, "Popen", return_value=process) as popen:
                self.assertTrue(updater.start_update_process("v2.3.0", autostart=False), warning.call_args)
                self.assertTrue(timer.started)
                app.quit.assert_not_called()
                status.write_text("READY\n", encoding="utf-8")
                timer.callback()

            app.quit.assert_called_once_with()
            self.assertEqual(popen.call_args.args[0][-2], str(status))
            self.assertEqual(popen.call_args.args[0][-1], "disable")
            self.assertEqual(popen.call_args.args[0][2], "v2.3.0")

    def test_rejects_invalid_version(self):
        with mock.patch.object(updater.QMessageBox, "warning") as warning, \
             mock.patch.object(updater.subprocess, "Popen") as popen:
            self.assertFalse(updater.start_update_process("v2.0; touch /tmp/no"))
        popen.assert_not_called()
        warning.assert_called_once()

    def test_preparation_failure_keeps_app_open_and_shows_log(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / "status"
            log_file = Path(directory) / "log"
            status.touch()
            log_file.touch()
            descriptors = iter((os.open(status, os.O_RDWR), os.open(log_file, os.O_RDWR)))
            process = mock.Mock()
            process.poll.return_value = 22
            app = mock.Mock()
            app._baseus_update_process = None
            timer = FakeTimer()

            with mock.patch.object(updater.tempfile, "mkstemp", side_effect=lambda **kw: (
                next(descriptors), str(status if "status" in kw["prefix"] else log_file)
            )), mock.patch.object(updater.QApplication, "instance", return_value=app), \
                 mock.patch.object(updater, "QTimer", return_value=timer), \
                 mock.patch.object(updater.subprocess, "Popen", return_value=process), \
                 mock.patch.object(updater.QMessageBox, "warning") as warning:
                self.assertTrue(updater.start_update_process("2.3.0"), warning.call_args)
                status.write_text("ERROR\n", encoding="utf-8")
                log_file.write_text("download recusado", encoding="utf-8")
                timer.callback()

            app.quit.assert_not_called()
            self.assertIn("download recusado", warning.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
