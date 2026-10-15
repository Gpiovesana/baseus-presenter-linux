"""System contract: unknown installations must never be silently certified."""
import json
from pathlib import Path
import tempfile
import unittest

from app import system_requirements as requirements


class TestSystemRequirements(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.manifest = self.root / 'requirements.json'
        self.manifest.write_text(json.dumps({'schema': 1, 'revision': 1}))
        self.install = self.root / 'install'
        self.install.mkdir()

    def test_installer_records_applied_revision_and_update_accepts_it(self):
        requirements.record(self.manifest, self.install, applied_revision=1)
        requirements.check(self.manifest, self.install)

    def test_unknown_corrupt_and_incompatible_installations_are_rejected(self):
        for state in (None, '{broken', '{}', '{"schema":1,"revision":2}',
                      '{"schema":true,"revision":1}'):
            with self.subTest(state=state):
                path = self.install / '.system-requirements.json'
                path.unlink(missing_ok=True)
                if state is not None:
                    path.write_text(state)
                with self.assertRaises(requirements.RequirementsError):
                    requirements.check(self.manifest, self.install)

    def test_installer_cannot_certify_requirements_it_did_not_apply(self):
        with self.assertRaises(requirements.RequirementsError):
            requirements.record(self.manifest, self.install, applied_revision=2)
        self.assertFalse((self.install / '.system-requirements.json').exists())

    def test_unknown_manifest_schema_or_revision_is_rejected(self):
        for manifest in ({}, {'schema':2,'revision':1}, {'schema':1,'revision':True}):
            self.manifest.write_text(json.dumps(manifest))
            with self.assertRaises(requirements.RequirementsError):
                requirements.record(self.manifest, self.install, applied_revision=1)
