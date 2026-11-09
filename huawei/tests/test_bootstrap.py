import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

MODULE_PATH = Path(__file__).parents[1] / "bootstrap.py"
SPEC = importlib.util.spec_from_file_location("bootstrap", MODULE_PATH)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "android"
        self.manifest = self.source / ".repo" / "manifests"
        self.manifest.mkdir(parents=True)
        self.selector = self.source / ".repo" / "manifest.xml"
        self.selector.write_text('<manifest><include name="default.xml"/></manifest>\n')
        self.default = self.manifest / "default.xml"
        self.default.write_text('<manifest><include name="extra.xml"/></manifest>\n')
        (self.manifest / "extra.xml").write_text('<manifest><project name="platform/a" path="a"/></manifest>\n')
        self.git("init", "-q")
        self.git("add", "default.xml", "extra.xml")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        self.plan = json.loads(bootstrap.PLAN.read_text())
        self.plan["manifest"]["revision"] = self.git("rev-parse", "HEAD")
        self.plan["manifest"]["default_xml_sha256"] = hashlib.sha256(self.default.read_bytes()).hexdigest()
        for index, project in enumerate(self.plan["projects"], start=1):
            project["revision"] = str(index) * 40

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.manifest,
                                       text=True, stderr=subprocess.DEVNULL).strip()

    def save_plan(self, plan):
        location = self.root / "plan.json"
        location.write_text(json.dumps(plan))
        return location

    def test_unresolved_pin_stops_before_any_command(self):
        self.plan["projects"][0]["revision"] = "PENDING_BLANC_HEAD"
        with mock.patch.object(bootstrap.subprocess, "run") as command:
            with self.assertRaisesRegex(bootstrap.PreparationError, "Unresolved"):
                bootstrap.load_plan(self.save_plan(self.plan))
            command.assert_not_called()

    def test_tracked_overlay_matches_its_only_editable_source(self):
        plan = bootstrap.load_plan(bootstrap.PLAN)
        expected = bootstrap.preparation_overlay(plan, bootstrap.PLAN)
        self.assertEqual(bootstrap.PLAN.with_name(bootstrap.OVERLAY).read_text(), expected)

    def test_duplicate_and_unsafe_paths_are_rejected(self):
        for path in (self.plan["projects"][0]["path"], "../outside", "/outside", "."):
            plan = copy.deepcopy(self.plan)
            plan["projects"][1]["path"] = path
            with self.subTest(path=path), self.assertRaises(bootstrap.PreparationError):
                bootstrap.load_plan(self.save_plan(plan))

    def test_pinned_overlay_is_correct_and_idempotent(self):
        plan = bootstrap.load_plan(self.save_plan(self.plan))
        self.assertEqual(bootstrap.install_overlay(self.source, plan), "created")
        location = self.source / ".repo" / "local_manifests" / bootstrap.OVERLAY
        original = location.read_bytes()
        projects = ET.fromstring(original).findall("project")
        self.assertEqual(len(projects), 4)
        self.assertEqual([(p.attrib["path"], p.attrib["revision"]) for p in projects],
                         [(p["path"], p["revision"]) for p in plan["projects"]])
        self.assertEqual(bootstrap.install_overlay(self.source, plan), "unchanged")
        self.assertEqual(location.read_bytes(), original)

    def test_modified_overlay_is_not_overwritten(self):
        bootstrap.install_overlay(self.source, self.plan)
        location = self.source / ".repo" / "local_manifests" / bootstrap.OVERLAY
        location.write_text("a deliberate local change\n")
        with self.assertRaisesRegex(bootstrap.PreparationError, "will not be overwritten"):
            bootstrap.install_overlay(self.source, self.plan)
        self.assertEqual(location.read_text(), "a deliberate local change\n")

    def test_other_local_manifest_blocks_overlay(self):
        directory = self.source / ".repo" / "local_manifests"
        directory.mkdir()
        (directory / "roomservice.xml").write_text("<manifest/>\n")
        with self.assertRaisesRegex(bootstrap.PreparationError, "Other local manifests"):
            bootstrap.install_overlay(self.source, self.plan)
        self.assertFalse((directory / bootstrap.OVERLAY).exists())

    def test_included_project_conflict_is_rejected(self):
        self.plan["projects"][0]["path"] = "a"
        with self.assertRaisesRegex(bootstrap.PreparationError, "conflicts"):
            bootstrap.install_overlay(self.source, self.plan)

    def test_dirty_manifest_and_wrong_head_are_rejected(self):
        with self.default.open("a") as handle:
            handle.write("<!-- local change -->\n")
        with self.assertRaisesRegex(bootstrap.PreparationError, "dirty"):
            bootstrap.verify_manifest(self.source, self.plan)
        self.plan["manifest"]["revision"] = "0" * 40
        with self.assertRaisesRegex(bootstrap.PreparationError, "expected the pinned"):
            bootstrap.verify_manifest(self.source, self.plan)

    def test_active_manifest_must_select_only_default(self):
        selectors = (
            '<manifest><include name="extra.xml"/></manifest>',
            '<manifest><include name="default.xml"/><project name="unexpected"/></manifest>',
            '<manifest><include name="default.xml" groups="restricted"/></manifest>',
        )
        for contents in selectors:
            with self.subTest(contents=contents):
                self.selector.write_text(contents)
                with self.assertRaisesRegex(bootstrap.PreparationError, "Active repo manifest"):
                    bootstrap.verify_manifest(self.source, self.plan)

    def test_legacy_manifest_symlink_must_select_default(self):
        self.selector.unlink()
        self.selector.symlink_to("manifests/default.xml")
        self.assertEqual(bootstrap.verify_manifest(self.source, self.plan), self.manifest)
        self.selector.unlink()
        self.selector.symlink_to("manifests/extra.xml")
        with self.assertRaisesRegex(bootstrap.PreparationError, "Active repo manifest"):
            bootstrap.verify_manifest(self.source, self.plan)

    def test_init_preserves_nonempty_and_preparation_directories(self):
        preparation = self.root / "preparation"
        preparation.mkdir()
        existing = self.root / "existing"
        existing.mkdir()
        note = existing / "important.txt"
        note.write_text("keep me")
        with mock.patch.object(bootstrap.subprocess, "run") as command:
            for location in (existing, preparation / "nested"):
                with self.subTest(location=location), self.assertRaises(bootstrap.PreparationError):
                    bootstrap.initialize(location, self.plan, preparation)
            command.assert_not_called()
        self.assertEqual(note.read_text(), "keep me")


if __name__ == "__main__":
    unittest.main()
