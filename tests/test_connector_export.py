"""Initial connector exports use committed bytes; no network or account access."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import seedbag
import seedbag_core as core
import seedbag_git as git


class ConnectorExportTests(unittest.TestCase):
    def setUp(self):
        work = Path(os.environ.get("SEEDBAG_TEST_WORK", str(Path.cwd() / "work"))).resolve()
        work.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix="seedbag-connector-", dir=work))
        self.empty = self.base / "empty-templates"
        self.empty.mkdir()
        self.root = self.base / "project"
        self.output = self.base / "initial-export.json"
        self.plant("https://github.com/example/project")

    def g(self, *args, input_bytes=None, env=None):
        result = subprocess.run(
            ["git", "-c", f"init.templateDir={self.empty}", "-c", "commit.gpgsign=false", "-C", str(self.root), *args],
            input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout

    def plant(self, locator):
        seedbag.plant(self.root, "Connector fixture", locator, use_git=False)
        self.g("init", "--initial-branch=main")
        self.g("config", "--local", "user.name", "Seedbag Test")
        self.g("config", "--local", "user.email", "seedbag-test@example.invalid")
        self.g("config", "--local", "core.autocrlf", "false")
        self.binary = b"\x00\xff\x80\r\nexact bytes\x00\n"
        (self.root / "sample.bin").write_bytes(self.binary)
        self.g("add", "--", *git.REQUIRED_FILES, "sample.bin")
        self.g("update-index", "--chmod=+x", "sample.bin")
        self.g("commit", "-m", "Initial project fixture")
        self.initial = self.g("rev-parse", "HEAD").decode().strip()

    def export(self, output=None):
        result = git.connector_export(self.root, self.initial, output or self.output)
        return result, json.loads(Path(result["output"]).read_bytes())

    def amend(self):
        self.g("commit", "--amend", "--no-edit")
        self.initial = self.g("rev-parse", "HEAD").decode().strip()

    def test_export_reconstructs_exact_tree_and_binary_bytes_with_modes(self):
        before = self.g("status", "--porcelain=v1", "-z")
        result, export = self.export()
        binary = next(item for item in export["files"] if item["path"] == "sample.bin")
        self.assertEqual(base64.b64decode(binary["content"], validate=True), self.binary)
        self.assertEqual(binary["mode"], "100755")
        self.assertEqual(binary["size"], len(self.binary))
        alternate_index = dict(os.environ, GIT_INDEX_FILE=str(self.base / "verify.index"))
        records = b""
        for item in export["files"]:
            data = base64.b64decode(item["content"], validate=True)
            oid = self.g("hash-object", "--stdin", input_bytes=data).decode().strip()
            self.assertEqual(oid, item["sha"])
            records += f"{item['mode']} {oid}\t{item['path']}".encode() + b"\0"
        self.g("update-index", "-z", "--index-info", input_bytes=records, env=alternate_index)
        rebuilt_tree = self.g("write-tree", env=alternate_index).decode().strip()
        self.assertEqual(rebuilt_tree, export["source"]["tree"])
        self.assertEqual(result["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(result["state"], "prepared_not_shared")
        self.assertFalse(export["shared"])
        self.assertEqual(export["repository"]["privacy"], "unverified")
        self.assertIn("README-only bootstrap", export["boundary"])
        self.assertEqual(export["source"]["parent_commits"], [])
        self.assertEqual(self.g("rev-parse", "HEAD").decode().strip(), self.initial)
        self.assertEqual(self.g("remote"), b"")
        self.assertEqual(self.g("status", "--porcelain=v1", "-z"), before)

    def test_staged_and_working_changes_do_not_change_selected_export(self):
        _, original = self.export()
        (self.root / "sample.bin").write_bytes(b"new staged bytes")
        (self.root / "STATE.md").write_bytes(b"invalid staged view")
        self.g("add", "--", "sample.bin", "STATE.md")
        (self.root / ".seedbag/ledger.json").write_bytes(b"invalid working ledger")
        (self.root / "STATE.md").write_bytes(b"different working view")
        before = self.g("status", "--porcelain=v1", "-z")
        _, after = self.export(self.base / "second-export.json")
        self.assertEqual(after, original)
        self.assertEqual(before, self.g("status", "--porcelain=v1", "-z"))

    def test_repaired_working_view_cannot_hide_invalid_committed_snapshot(self):
        state = self.root / "STATE.md"
        original = state.read_bytes()
        state.write_bytes(b"corrupt committed view")
        self.g("add", "--", "STATE.md")
        self.amend()
        state.write_bytes(original)
        with self.assertRaisesRegex(core.Error, "STATE.md does not match"):
            self.export()
        self.assertFalse(self.output.exists())

    def test_child_commit_is_refused_even_when_snapshot_is_valid(self):
        self.g("commit", "--allow-empty", "-m", "Later checkpoint")
        with self.assertRaisesRegex(core.Error, "first parentless"):
            git.connector_export(self.root, "HEAD", self.output)
        self.assertFalse(self.output.exists())

    def test_link_entry_is_refused_without_using_working_copy(self):
        oid = self.g("hash-object", "-w", "--stdin", input_bytes=b"sample.bin").decode().strip()
        self.g("update-index", "--add", "--cacheinfo", f"120000,{oid},linked.bin")
        self.amend()
        with self.assertRaisesRegex(core.Error, "link or submodule"):
            self.export()
        self.assertFalse(self.output.exists())

    def test_non_github_and_ambiguous_repository_locators_are_refused(self):
        for number, locator in enumerate(("", "C:/project", "git@github.com:example/project.git",
                                          "https://github.com/example/project?token=unexpected",
                                          "https://other.example/example/project", "https://github.com/example/..")):
            with self.subTest(locator=locator):
                self.root = self.base / f"locator-{number}"
                self.plant(locator)
                with self.assertRaisesRegex(core.Error, "plain HTTPS GitHub"):
                    self.export()
                self.assertFalse(self.output.exists())

    def test_output_cannot_replace_files_or_enter_shared_project_paths(self):
        for target in (self.root / "export.json", self.root / ".seedbag/runtime/export.json", self.root / ".seedbag-local"):
            with self.subTest(target=target):
                existed = target.exists()
                with self.assertRaisesRegex(core.Error, "outside the project"):
                    self.export(target)
                self.assertEqual(target.exists(), existed)
        self.output.write_bytes(b"keep existing evidence")
        with self.assertRaisesRegex(core.Error, "already exists"):
            self.export()
        self.assertEqual(self.output.read_bytes(), b"keep existing evidence")
        result, _ = self.export(self.root / ".seedbag-local/export.json")
        self.assertEqual(result["state"], "prepared_not_shared")
        self.assertEqual(self.g("status", "--porcelain=v1", "-z"), b"")

    def test_snapshot_cannot_include_prior_exports_or_local_scratch(self):
        scratch = self.root / ".seedbag-local"
        scratch.mkdir(exist_ok=True)
        (scratch / "previous-export.json").write_bytes(b"prior private scratch")
        self.g("add", "--force", "--", ".seedbag-local/previous-export.json")
        self.amend()
        with self.assertRaisesRegex(core.Error, "local scratch files"):
            self.export()
        self.assertFalse(self.output.exists())

    def test_installed_cli_exports_without_claiming_publication(self):
        result = subprocess.run(
            [sys.executable, "-B", str(self.root / "seedbag.py"), "--root", str(self.root),
             "connector-export", "--commit", "HEAD", "--output", str(self.output)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        report = json.loads(result.stdout)
        self.assertEqual(report["commit"], self.initial)
        self.assertEqual(report["state"], "prepared_not_shared")
        self.assertFalse(report["shared"])
        self.assertIn("No upload", report["boundary"])
        self.assertTrue(self.output.is_file())


if __name__ == "__main__":
    unittest.main()
