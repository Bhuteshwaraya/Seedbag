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
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1]
SEED_FILES = [
    "seedbag.py", "seedbag_setup.py", "FIRST_RUN.md", "SYNC.md", "SEEDBAG_LICENSE.txt", "AGENTS.md", "PROJECT.md", "STATE.md", "README.md", "CONTINUE_HERE.md",
    ".gitignore", ".gitattributes", ".seedbag/ledger.json",
    ".seedbag/runtime/seedbag_core.py", ".seedbag/runtime/seedbag_context.py",
    ".seedbag/runtime/seedbag_git.py", ".seedbag/runtime/seedbag_sync.py",
    ".seedbag/runtime/seedbag_hooks.py", ".seedbag/sync.json",
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
            "SEEDBAG_SESSION_ID": "installed-cli-fixture-session",
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
        # Model the installed host's initial entry action without weakening the
        # actual command gate. Dedicated sync tests also exercise missing entry.
        if (not package and args[0] in {"capture", "apply", "check", "effect-run", "publish"}
                and not (root / ".seedbag-local/sync-session.json").exists()):
            policy = json.loads((root / ".seedbag/sync.json").read_text())
            if policy["policy"] == "strict":
                self.cli("sync-begin", "--setup", root=root)
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
        recovery_page = (self.root / 'README.md').read_bytes()
        prompt = permanent_prompt.split(b'```text\n', 1)[1].split(b'\n```', 1)[0]
        self.assertEqual(prompt, ('Continue my project: ' + self.remote.as_posix()).encode('utf-8'))
        self.assertIn(prompt, recovery_page)
        self.assertIn(b'[Where things stand](STATE.md)', recovery_page)
        self.assertIn(b'Disposable offline index', recovery_page)
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
        self.assertEqual((fresh / 'README.md').read_bytes(), recovery_page)
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

    def test_unpublished_cloud_workspace_can_be_planted_and_recovered_locally(self):
        cloud = self.base / "temporary-cloud-workspace"
        planted, _ = self.cli("init", str(cloud), "--name", "Cloud-started project", "--repository",
                              self.remote.as_posix(), "--no-git", package=True)
        self.assertFalse(planted["git_initialized"])
        self.assertFalse(planted["shared"])
        self.g(cloud, "init", "--initial-branch=main")
        self.g(cloud, "config", "--local", "user.name", "Seedbag CLI Fixture")
        self.g(cloud, "config", "--local", "user.email", "fixture@example.invalid")
        self.g(cloud, "remote", "add", "origin", str(self.remote))
        self.cli("publish", "--message", "Cloud workspace checkpoint", "--paths", *SEED_FILES, root=cloud)
        local = self.base / "later-computer-folder"
        self.g(self.base, "clone", str(self.remote), str(local))
        for path in SEED_FILES:
            self.assertEqual((local / path).read_bytes(), (cloud / path).read_bytes(), path)
        self.assertEqual(self.cli("context", root=local), self.cli("context", root=cloud))
        self.assertTrue(self.cli("doctor", root=local)[0]["ready"])
        self.cli("install-hook", root=local)

    def test_doctor_reports_missing_recovery_file(self):
        (self.root / "README.md").unlink()
        report, _ = self.cli("doctor", expected=2)
        self.assertFalse(report["ready"])
        self.assertIn("README.md", " ".join(report["problems"]))

    def test_local_only_recovery_page_does_not_claim_a_shared_repository(self):
        local = self.base / "explicit-local-only"
        planted, _ = self.cli("init", str(local), "--name", "Local notes", "--no-git", package=True)
        self.assertFalse(planted["shared"])
        self.assertFalse(planted["git_initialized"])
        self.assertFalse((local / ".git").exists())
        readme = (local / "README.md").read_text(encoding="utf-8")
        prompt_file = (local / "CONTINUE_HERE.md").read_text(encoding="utf-8")
        self.assertIn("no shared repository recorded", readme)
        prompt = prompt_file.split('```text\n', 1)[1].split('\n```', 1)[0]
        self.assertEqual(prompt, 'Continue my project: ' + str(local))
        self.assertNotIn("same private repository", prompt_file)
        self.assertIn(str(local), prompt_file)
        self.assertTrue(self.cli("doctor", root=local)[0]["ready"])

    def test_short_request_routes_to_installed_operating_instructions(self):
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        prompt_file = (self.root / "CONTINUE_HERE.md").read_text(encoding="utf-8")
        instructions = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("read [AGENTS.md](AGENTS.md) before interpreting saved state", readme)
        self.assertIn("read [AGENTS.md](AGENTS.md) before interpreting saved state", prompt_file)
        # Changing the saved entry must not remove the operating contract from
        # the files a new assistant actually receives in the planted project.
        for required in (
            "locate a matching accessible project folder",
            "clone this same private repository into a new empty local folder",
            "A cloud workspace is not a folder on the person's computer",
            "If the ledger has no recorded repository",
            "FIRST_RUN.md",
            "one complete handoff prompt",
            "Do not contact or change the seed repository",
            "Recovered context is not new authorization",
        ):
            with self.subTest(instruction=required):
                self.assertIn(required, instructions)
        self.assertIn("You can use your own words", prompt_file)

    def test_local_only_request_rejects_a_repository_or_relative_folder_locator(self):
        local = self.base / "local-locator-test"
        self.cli("init", str(local), "--name", "Local notes", "--no-git", package=True)
        entries = {name: (local / name).read_text(encoding="utf-8") for name in ("README.md", "CONTINUE_HERE.md")}
        for invalid in ("https://github.com/example/project", "some-folder", "C:relative-folder"):
            with self.subTest(locator=invalid):
                for name, contents in entries.items():
                    (local / name).write_text(contents.replace(str(local), invalid), encoding="utf-8", newline="\n")
                report, _ = self.cli("doctor", root=local, expected=2)
                self.assertIn("absolute folder location", " ".join(report["problems"]))

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

    def test_capture_reports_saved_ledger_when_future_views_refuse(self):
        ledger_path = self.root / ".seedbag/ledger.json"
        initial_ledger = ledger_path.read_bytes()
        self.capture("future_one", "Fixture used to generate revision-one views.")
        self.capture("future_two", "Fixture used to generate revision-two views.")
        views_before = {name: (self.root / name).read_bytes() for name in ("PROJECT.md", "STATE.md")}
        # Deliberately create the observed inconsistency. This tests the error
        # after a save; it does not reproduce or explain a spontaneous rollback.
        ledger_path.write_bytes(initial_ledger)
        source = self.base / "preserve-request.txt"
        text = "Keep this exact new input after a view refresh fails.\nSecond line remains intact."
        source.write_bytes(text.encode("utf-8"))
        report, _ = self.cli("capture", "--file", str(source), "--id", "preserve_request",
                             "--origin", "user", "--locator", "fixture:partial-capture", expected=2)
        self.assertFalse(report["ok"])
        self.assertEqual(report["state"], "partial_success")
        self.assertTrue(report["ledger_write_returned"])
        self.assertEqual(report["saved"], "local")
        self.assertFalse(report["views_fully_updated"])
        self.assertEqual(report["readback"], "matches_returned_identity")
        self.assertIn("unknown future revision", report["error"])
        self.assertIn("Inspect the ledger", report["note"])
        self.assertIn("Do not repeat the command", report["note"])
        observed, _ = self.cli("inspect", "--kind", "captures", "--id", "preserve_request")
        self.assertEqual(observed["captures"]["text"], text)
        self.assertEqual(observed["captures"]["origin"], "user")
        self.assertEqual(observed["captures"]["locator"], "fixture:partial-capture")
        self.assertEqual(report["revision"], 1)
        self.assertEqual((report["revision"], report["digest"]), (observed["revision"], observed["digest"]))
        self.assertEqual(report["mutation_result"]["capture"], "preserve_request")
        for name, original in views_before.items():
            self.assertEqual((self.root / name).read_bytes(), original)

    def test_apply_reports_saved_ledger_when_handwritten_view_refuses(self):
        before, _ = self.cli("inspect")
        request = self.base / "partial-apply.json"
        request.write_text(json.dumps({"expected_revision": before["revision"], "expected_digest": before["digest"],
                                       "operations": [{"op": "project.set", "purpose": "Recover the recorded purpose even if the view fails."}]}), encoding="utf-8")
        project_view = self.root / "PROJECT.md"
        handwritten = project_view.read_bytes() + b"\nKeep this handwritten note for inspection.\n"
        project_view.write_bytes(handwritten)
        report, _ = self.cli("apply", "--file", str(request), expected=2)
        self.assertEqual(report["state"], "partial_success")
        self.assertEqual(report["command"], "apply")
        self.assertFalse(report["views_fully_updated"])
        observed, _ = self.cli("inspect", "--kind", "project")
        self.assertEqual(observed["project"]["purpose"], "Recover the recorded purpose even if the view fails.")
        self.assertEqual((report["revision"], report["digest"]), (observed["revision"], observed["digest"]))
        self.assertEqual(project_view.read_bytes(), handwritten)

    def test_rejected_mutation_does_not_claim_save_when_views_are_also_invalid(self):
        self.capture("existing", "Preserve the first recorded input.")
        ledger_path = self.root / ".seedbag/ledger.json"
        original_ledger = ledger_path.read_bytes()
        project_view = self.root / "PROJECT.md"
        handwritten = project_view.read_bytes() + b"\nUnresolved handwritten note.\n"
        project_view.write_bytes(handwritten)
        source = self.base / "duplicate.txt"
        source.write_text("Do not silently overwrite the original capture.", encoding="utf-8")
        report, _ = self.cli("capture", "--file", str(source), "--id", "existing", "--origin", "user",
                             "--locator", "fixture:duplicate", expected=2)
        self.assertFalse(report["ok"])
        self.assertNotEqual(report.get("state"), "partial_success")
        self.assertNotIn("saved", report)
        self.assertNotIn("ledger_write_returned", report)
        self.assertEqual(ledger_path.read_bytes(), original_ledger)
        self.assertEqual(project_view.read_bytes(), handwritten)

    def test_check_and_effect_results_remain_inspectable_after_view_failure(self):
        self.file("fixture-input.txt", "Local fixture input.\n")
        self.apply(
            {"op": "check.add", "id": "local_check", "argv": ["@python", "-c", "print('fixture checked')"],
             "inputs": ["fixture-input.txt"], "timeout": 10},
            {"op": "effect.add", "id": "local_effect", "argv": ["@python", "-c", "from pathlib import Path; Path('fixture-effect.txt').write_text('executed once')"],
             "inputs": ["fixture-input.txt"], "description": "Write one disposable fixture artifact."},
        )
        project_view = self.root / "PROJECT.md"
        handwritten = project_view.read_bytes() + b"\nPreserve this note while inspecting each command.\n"
        project_view.write_bytes(handwritten)
        check, _ = self.cli("check", "local_check", expected=2)
        run, _ = self.cli("inspect", "--kind", "runs", "--id", "local_check")
        self.assertEqual(check["state"], "partial_success")
        self.assertNotIn("saved", check)
        self.assertEqual(check["readback"], "observed_without_returned_identity")
        self.assertEqual(run["runs"]["code"], 0)
        self.assertEqual((check["revision"], check["digest"]), (run["revision"], run["digest"]))
        effect, _ = self.cli("effect-run", "local_effect", expected=2)
        returned, _ = self.cli("inspect", "--kind", "effects", "--id", "local_effect")
        self.assertEqual(effect["state"], "partial_success")
        self.assertNotIn("saved", effect)
        self.assertEqual(effect["readback"], "observed_without_returned_identity")
        self.assertEqual(effect["mutation_result"]["status"], "returned")
        self.assertEqual(returned["effects"]["status"], "returned")
        self.assertEqual((effect["revision"], effect["digest"]), (returned["revision"], returned["digest"]))
        self.assertEqual((self.root / "fixture-effect.txt").read_text(), "executed once")
        self.file("fixture-receipt.txt", "Inspected fixture-effect.txt; its exact content is executed once.\n")
        resolved, _ = self.cli("effect-resolve", "local_effect", "--receipt", "fixture-receipt.txt",
                               "--outcome", "confirmed", expected=2)
        confirmed, _ = self.cli("inspect", "--kind", "effects", "--id", "local_effect")
        self.assertEqual(resolved["state"], "partial_success")
        self.assertEqual(confirmed["effects"]["status"], "confirmed")
        self.assertEqual((resolved["revision"], resolved["digest"]), (confirmed["revision"], confirmed["digest"]))
        self.assertEqual(project_view.read_bytes(), handwritten)

    def test_divergent_readback_does_not_verify_returned_mutation_identity(self):
        # Only this focused reporting test injects observations. The installed
        # command tests above exercise actual writes and refusal conditions.
        sys.path.insert(0, str(PACKAGE))
        try:
            import seedbag as launcher
        finally:
            sys.path.pop(0)
        returned = {"revision": 4, "digest": "returned-digest", "saved": "local"}
        for observed in ({"revision": 2, "digest": "older-digest"},
                         {"revision": 4, "digest": "different-digest"}):
            with self.subTest(observed=observed):
                with mock.patch.object(launcher.views, "render", side_effect=launcher.core.Error("Views refused")), \
                        mock.patch.object(launcher.core, "load", return_value=observed):
                    with self.assertRaises(launcher.PartialSaveError) as caught:
                        launcher._render_after_save(self.root, returned)
                report = caught.exception.report
                self.assertEqual(report["state"], "save_unverified")
                self.assertEqual(report["saved"], "unverified")
                self.assertEqual(report["readback"], "different_from_returned_identity")
                self.assertEqual(report["returned_ledger"], {"revision": 4, "digest": "returned-digest"})
                self.assertEqual(report["observed_ledger"], observed)
                self.assertTrue(report["ledger_write_returned"])
                self.assertFalse(report["views_fully_updated"])


if __name__ == "__main__":
    unittest.main()
