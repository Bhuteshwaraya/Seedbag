"""Black-box installed CLI exercise in fresh disposable projects and local Git.

No direct core calls, existing example projects, external remotes, user Git
configuration, or domain-system effects participate in these tests.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PACKAGE = Path(__file__).resolve().parents[1]
SEED_FILES = [
    "seedbag.py", "seedbag_setup.py", "FIRST_RUN.md", "SEEDBAG_LICENSE.txt", "AGENTS.md", "PROJECT.md", "STATE.md", "CONTINUE_HERE.md",
    ".gitignore", ".gitattributes", ".seedbag/ledger.json",
    ".seedbag/runtime/seedbag_core.py", ".seedbag/runtime/seedbag_context.py",
    ".seedbag/runtime/seedbag_git.py",
]


class InstalledCliTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(os.environ.get("SEEDBAG_TEST_WORK", Path.cwd() / "work")).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="seedbag-cli-new-", dir=workspace)
        self.base = Path(self.temp.name).resolve()
        self.assertTrue(self.base.is_relative_to(workspace))
        self.addCleanup(self.temp.cleanup)
        self.root = self.base / "project"
        self.remote = self.base / "remote.git"
        empty = self.base / "empty-git-templates"
        empty.mkdir()
        self.env = os.environ.copy()
        self.env.update({
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "init.templateDir",
            "GIT_CONFIG_VALUE_0": str(empty), "GIT_CONFIG_KEY_1": "commit.gpgsign",
            "GIT_CONFIG_VALUE_1": "false", "PYTHONDONTWRITEBYTECODE": "1",
        })
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "SEEDBAG_INCOMPLETE_CHECKPOINT"):
            self.env.pop(name, None)
        planted, _ = self.cli("init", str(self.root), "--name", "Disposable offline index", "--repository", self.remote.as_posix(), package=True)
        self.assertTrue(planted["git_initialized"])
        self.assertFalse(planted["shared"])
        self.assertFalse(planted["remote_configured"])
        self.assertEqual((self.root / "SEEDBAG_LICENSE.txt").read_bytes(), (PACKAGE / "LICENSE").read_bytes())
        for support in ("seedbag_setup.py", "FIRST_RUN.md"):
            self.assertEqual((self.root / support).read_bytes(), (PACKAGE / support).read_bytes())
        self.g(self.root, "config", "--local", "user.name", "Seedbag CLI Fixture")
        self.g(self.root, "config", "--local", "user.email", "fixture@example.invalid")
        hook = (self.root / ".git/hooks/pre-commit").read_text(encoding="utf-8")
        self.assertIn(str(self.root).replace("\\", "/"), hook.replace("\\", "/"))
        self.assertNotIn(str(PACKAGE / "runtime").replace("\\", "/"), hook.replace("\\", "/"))
        self.g(self.base, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.g(self.root, "remote", "add", "origin", str(self.remote))
        self.apply_number = 0

    def cli(self, *args, root=None, package=False, expected=0):
        root = root or self.root
        script = PACKAGE / "seedbag.py" if package else root / "seedbag.py"
        command = [sys.executable, "-B", str(script)]
        if not package:
            command.extend(["--root", str(root)])
        result = subprocess.run(command + list(args), cwd=self.base, env=self.env,
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, expected,
                         f"CLI {args}: {result.stdout.decode('utf-8', 'replace')} {result.stderr.decode('utf-8', 'replace')}")
        self.assertFalse(result.stderr, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout), result.stdout

    def g(self, root, *args, expected=0):
        self.assertTrue(Path(root).resolve().is_relative_to(self.base))
        result = subprocess.run(["git", "-C", str(root), *args], cwd=self.base, env=self.env,
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, expected,
                         f"Git {args}: {result.stderr.decode('utf-8', 'replace')}")
        return result.stdout.decode("utf-8")

    def file(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        return target

    def capture(self, identifier, text):
        path = self.base / (identifier + ".txt")
        path.write_text(text, encoding="utf-8")
        outcome, _ = self.cli("capture", "--file", str(path), "--id", identifier,
                              "--origin", "user", "--locator", "fixture:" + identifier)
        self.assertEqual(outcome["saved"], "local")
        self.assertEqual(outcome["disposition"], "pending")

    def apply(self, *operations):
        before, _ = self.cli("inspect")
        self.apply_number += 1
        path = self.base / f"transaction-{self.apply_number}.json"
        path.write_text(json.dumps({"expected_revision": before["revision"],
                                    "expected_digest": before["digest"],
                                    "operations": operations}, ensure_ascii=False), encoding="utf-8")
        outcome, _ = self.cli("apply", "--file", str(path))
        self.assertEqual(outcome["saved"], "local")
        return outcome

    def test_capture_rewrite_verification_publish_and_fresh_clone_use_installed_runtime(self):
        permanent_prompt = (self.root / 'CONTINUE_HERE.md').read_bytes()
        self.assertIn(self.remote.as_posix().encode('utf-8'), permanent_prompt)
        self.assertNotIn(b'python seedbag.py', permanent_prompt)
        self.capture("request", "Build an offline alphabetic index. Start with cards. Printing can wait until paper copies are requested.")
        pending, _ = self.cli("doctor", expected=2)
        self.assertFalse(pending["ready"])
        self.file("domain/display.md", "Current display contract: case-insensitive alphabetic unique entries, as plain list lines.\n")
        self.file("entries.json", '["Pear", "apple", "Pear"]\n')
        self.file("indexer.py", "import json\nfrom pathlib import Path\n\ndef render(entries):\n    rows = sorted(set(entries), key=str.casefold)\n    return ''.join('- ' + row + '\\n' for row in rows)\n\nif __name__ == '__main__':\n    Path('index.txt').write_text(render(json.loads(Path('entries.json').read_text())), encoding='utf-8')\n")
        self.file("check_indexer.py", "import json\nfrom pathlib import Path\nfrom indexer import render\n\nassert render(['Pear', 'apple', 'Pear']) == '- apple\\n- Pear\\n'\nassert render([]) == ''\nassert render(['éclair', 'Zebra']) == '- Zebra\\n- éclair\\n'\nassert Path('index.txt').read_text(encoding='utf-8') == render(json.loads(Path('entries.json').read_text()))\nassert 'plain list' in Path('domain/display.md').read_text()\nprint('Alphabetic order, uniqueness, empty input, Unicode and saved artifact verified')\n")
        self.apply(
            {"op": "project.set", "purpose": "Produce a useful offline index from a small local list."},
            {"op": "item.add", "id": "offline", "kind": "requirement", "text": "The index must work offline.", "status": "accepted", "sources": ["request"]},
            {"op": "item.add", "id": "cards", "kind": "decision", "text": "Start with a card presentation.", "status": "accepted", "sources": ["request"]},
            {"op": "item.add", "id": "printing", "kind": "idea", "text": "Support printing later.", "status": "deferred", "trigger": "Paper copies are requested", "sources": ["request"]},
            {"op": "owner.add", "id": "display", "path": "domain/display.md", "summary": "Exact currently intended output behavior", "tags": ["display"], "requires": []},
            {"op": "check.add", "id": "verify_index", "argv": [sys.executable, "check_indexer.py"], "inputs": ["indexer.py", "check_indexer.py", "entries.json", "index.txt", "domain/display.md"], "timeout": 10},
            {"op": "work.add", "id": "build_index", "title": "Create and verify the index", "requires": ["offline"], "owners": ["display"], "checks": ["verify_index"]},
            {"op": "current.set", "summary": "The initial display plan needs review before completion.", "next_work": "build_index"},
            {"op": "capture.resolve", "id": "request", "items": ["offline", "cards", "printing"], "reason": "Preserved requirement, initial direction and deferred trigger"},
        )
        self.capture("correction", "Use a plain list instead of cards. Keep the offline requirement and printing trigger.")
        self.apply(
            {"op": "item.add", "id": "list", "kind": "decision", "text": "Use plain list lines.", "status": "accepted", "sources": ["correction"], "owner": "display"},
            {"op": "item.status", "id": "cards", "status": "superseded", "source": "correction", "reason": "User selected a plain list", "replacement": "list"},
            {"op": "capture.resolve", "id": "correction", "items": ["cards", "list"], "reason": "Explicitly replaced the old display direction"},
            {"op": "work.status", "id": "build_index", "status": "in_progress", "note": "Implement the corrected display and retain constraints"},
            {"op": "current.set", "summary": "Plain list implementation is ready for verification.", "next_work": "build_index"},
        )
        built = subprocess.run([sys.executable, "-B", "indexer.py"], cwd=self.root,
                               env=self.env, capture_output=True, timeout=10)
        self.assertEqual(built.returncode, 0, built.stderr)
        verified_artifact_bytes = (self.root / "index.txt").read_bytes()
        check, _ = self.cli("check", "verify_index")
        self.assertEqual(check["code"], 0)
        self.apply(
            {"op": "current.set", "summary": "Offline plain-list artifact completed and locally tested; printing remains deferred.", "next_work": None},
            {"op": "work.status", "id": "build_index", "status": "done", "note": "Meaningful output and saved-artifact checks passed"},
        )
        self.cli("render")
        before, raw = self.cli("context")
        self.assertEqual(before["bytes"], len(raw))
        self.assertIn("The index must work offline", before["brief"])
        self.assertIn("Paper copies are requested", before["brief"])
        self.assertIn("Replaced by: list", before["brief"])
        self.assertNotIn("Start with a card presentation", before["brief"])
        self.assertIn("Use plain list lines", before["brief"])
        paths = SEED_FILES + ["domain/display.md", "entries.json", "indexer.py", "check_indexer.py", "index.txt"]
        publication, _ = self.cli("publish", "--message", "Verified corrected offline index", "--paths", *paths)
        remote_tip = self.g(self.base, "--git-dir", str(self.remote), "rev-parse", "refs/heads/main").strip()
        self.assertEqual(remote_tip, self.g(self.root, "rev-parse", "HEAD").strip())
        self.assertIn(remote_tip, json.dumps(publication))
        fresh = self.base / "new-reader"
        self.g(self.base, "clone", str(self.remote), str(fresh))
        self.assertEqual((fresh / "SEEDBAG_LICENSE.txt").read_bytes(), (PACKAGE / "LICENSE").read_bytes())
        self.assertEqual((fresh / "index.txt").read_text(), "- apple\n- Pear\n")
        self.assertEqual((fresh / "index.txt").read_bytes(), verified_artifact_bytes)
        after, after_raw = self.cli("context", root=fresh)
        self.assertEqual(after, before)
        self.assertEqual(after_raw, raw)
        self.assertEqual((fresh / 'CONTINUE_HERE.md').read_bytes(), permanent_prompt)
        for support in ("seedbag_setup.py", "FIRST_RUN.md"):
            self.assertEqual((fresh / support).read_bytes(), (PACKAGE / support).read_bytes())
        probe = subprocess.run([sys.executable, "-B", str(fresh / "seedbag_setup.py"), "--offline"],
                               cwd=self.base, env=self.env, capture_output=True, timeout=30)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        probe_report = json.loads(probe.stdout)
        self.assertEqual(probe_report["mode"], "offline")
        self.assertEqual(probe_report["probes"]["github_api"]["status"], "not_inspected")
        self.cli("install-hook", root=fresh)
        installed_hook = (fresh / ".git/hooks/pre-commit").read_text(encoding="utf-8")
        self.assertIn(str(fresh).replace("\\", "/"), installed_hook.replace("\\", "/"))
        self.assertNotIn(str(PACKAGE / "runtime").replace("\\", "/"), installed_hook.replace("\\", "/"))
        current, _ = self.cli("doctor", root=fresh)
        self.assertTrue(current["ready"])

    def test_actual_commit_hook_refuses_manual_generated_view_without_creating_commit(self):
        publication, _ = self.cli("publish", "--message", "Initial fresh seed", "--paths", *SEED_FILES)
        before = self.g(self.root, "rev-parse", "HEAD").strip()
        state_path = self.root / "STATE.md"
        state_path.write_bytes(state_path.read_bytes() + b"\nHandwritten claim: all work accepted.\n")
        self.g(self.root, "add", "--", "STATE.md")
        refused = subprocess.run(["git", "-C", str(self.root), "commit", "-m", "Attempt handwritten state"],
                                 cwd=self.base, env=self.env, capture_output=True, timeout=60)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn(b"STATE.md", refused.stdout + refused.stderr)
        self.assertEqual(self.g(self.root, "rev-parse", "HEAD").strip(), before)
        self.assertIn(b"Handwritten claim", state_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
