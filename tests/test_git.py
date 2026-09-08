"""Local bare-remote tests. No GitHub, networking, global config, or live repos."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import seedbag_core as core
import seedbag_context as context
import seedbag_git as git
import seedbag


CORE_FILES = list(git.REQUIRED_FILES)


class GitTests(unittest.TestCase):
    def setUp(self):
        work = Path(os.environ.get("SEEDBAG_TEST_WORK", str(Path.cwd() / "work"))).resolve()
        work.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix="seedbag-git-v03-", dir=work))
        self.empty = self.base / "empty-templates"
        self.empty.mkdir()
        self.root = self.base / "project"
        self.remote = self.base / "remote.git"
        seedbag.plant(self.root, "Git fixture", self.remote.as_posix(), use_git=False)
        self.g(self.root, "init", "--initial-branch=main")
        self.configure(self.root)
        self.g(self.root, "add", "--", *CORE_FILES)
        git.gate(self.root)
        self.g(self.root, "commit", "-m", "Initial seed fixture")
        self.initial = self.g(self.root, "rev-parse", "HEAD").strip()
        self.g(self.base, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.g(self.root, "remote", "add", "origin", str(self.remote))
        self.g(self.root, "push", "-u", "origin", "main")

    def g(self, root, *args, allow_failure=False):
        self.assertTrue(Path(root).resolve().is_relative_to(self.base))
        result = subprocess.run(
            ["git", "-c", f"init.templateDir={self.empty}", "-c", "commit.gpgsign=false", "-C", str(root), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if not allow_failure and result.returncode:
            self.fail(f"Git fixture failed: {args}: {result.stderr.decode(errors='replace')}")
        return result if allow_failure else result.stdout.decode("utf-8")

    def configure(self, root):
        self.g(root, "config", "--local", "user.name", "Seedbag Test")
        self.g(root, "config", "--local", "user.email", "seedbag-test@example.invalid")
        self.g(root, "config", "--local", "commit.gpgsign", "false")
        self.g(root, "config", "--local", "core.autocrlf", "false")

    def clone(self, name):
        root = self.base / name
        self.g(self.base, "clone", str(self.remote), str(root))
        self.configure(root)
        return root

    def apply(self, operations, root=None):
        root = root or self.root
        old = core.load(root)
        result = core.apply(root, operations, old["revision"], old["digest"])
        context.render(root)
        return result

    def stage_core(self, root=None):
        self.g(root or self.root, "add", "--", *CORE_FILES)

    def test_gate_requires_published_entry_and_runtime_files_not_just_local_copies(self):
        for name in ("README.md", "CONTINUE_HERE.md", ".seedbag/runtime/seedbag_core.py"):
            with self.subTest(name=name):
                self.g(self.root, "rm", "--cached", "--", name)
                self.assertTrue((self.root / name).is_file())
                self.assertTrue(git.validate_entry_files(self.root, core.load(self.root))["ok"])
                with self.assertRaisesRegex(core.Error, "missing required files") as raised:
                    git.gate(self.root)
                self.assertIn(name, str(raised.exception))
                self.g(self.root, "add", "--", name)
        self.assertEqual(self.g(self.root, "rev-parse", "HEAD").strip(), self.initial)

    def test_gate_rejects_staged_readme_prompt_mismatch_after_working_copy_repair(self):
        path = self.root / "README.md"
        original = path.read_bytes()
        path.write_bytes(original.replace(b"Continue my project: ", b"Continue another project: ", 1))
        self.g(self.root, "add", "--", "README.md")
        path.write_bytes(original)
        with self.assertRaisesRegex(core.Error, "exact saved CONTINUE_HERE.md"):
            git.gate(self.root)
        self.assertEqual(path.read_bytes(), original)

    def test_entry_files_reject_matching_prompt_with_wrong_or_extended_repository(self):
        original = self.remote.as_posix().encode("utf-8")
        entry_files = {name: (self.root / name).read_bytes() for name in ("README.md", "CONTINUE_HERE.md")}
        for wrong in (b"https://github.com/example/other-project", original + b"/other-project", original + b". Read its AGENTS.md"):
            with self.subTest(locator=wrong):
                for name, contents in entry_files.items():
                    (self.root / name).write_bytes(contents.replace(original, wrong))
                with self.assertRaisesRegex(core.Error, "saved repository locator"):
                    git.validate_entry_files(self.root, core.load(self.root))

    def test_entry_files_reject_duplicate_or_multiline_prompt_blocks(self):
        path = self.root / "README.md"
        original = path.read_bytes()
        for changed in (
            original + b"\n<!-- seedbag:continue:start -->\n",
            original.replace(b"Continue my project: ", b"Continue my project:\n", 1),
        ):
            with self.subTest(contents=changed[-80:]):
                path.write_bytes(changed)
                with self.assertRaisesRegex(core.Error, "exactly one marked"):
                    git.validate_entry_files(self.root, core.load(self.root))
        path.write_bytes(original)

    def test_prompt_file_cannot_be_rewritten_through_gate_or_committed_audit(self):
        path = self.root / "CONTINUE_HERE.md"
        original = path.read_bytes()
        path.write_bytes(original + b"\nAn accidental replacement note.\n")
        self.assertTrue(git.validate_entry_files(self.root, core.load(self.root))["ok"])
        self.g(self.root, "add", "--", "CONTINUE_HERE.md")
        with self.assertRaisesRegex(core.Error, "CONTINUE_HERE.md changed from parent/base"):
            git.gate(self.root)
        # Bypass the cooperative gate deliberately to prove committed audits
        # enforce prompt stability independently of local hooks.
        self.g(self.root, "commit", "-m", "Deliberately rewritten prompt fixture")
        with self.assertRaisesRegex(core.Error, "CONTINUE_HERE.md changed from parent/base"):
            git.audit_commit(self.root, "HEAD", self.initial)
        self.assertEqual(self.g(self.remote, "rev-parse", "refs/heads/main").strip(), self.initial)

    def test_publish_preserves_entry_bytes_and_complete_files_in_fresh_clone(self):
        expected = {name: (self.root / name).read_bytes() for name in ("README.md", "CONTINUE_HERE.md")}
        self.apply([{"op": "project.set", "purpose": "Continue the same project after a saved update"}])
        git.publish(self.root, "Preserve permanent entry across update", CORE_FILES)
        fresh = self.clone("entry-reader")
        self.assertTrue(git.validate_entry_files(fresh, core.load(fresh))["ok"])
        for name, contents in expected.items():
            self.assertEqual((fresh / name).read_bytes(), contents)

    def test_gate_validates_index_not_repaired_working_view(self):
        self.apply([{"op": "project.set", "purpose": "Preserve a new purpose"}])
        self.stage_core()
        good = (self.root / "STATE.md").read_bytes()
        (self.root / "STATE.md").write_bytes(b"Manual incorrect staged state\n")
        self.g(self.root, "add", "--", "STATE.md")
        (self.root / "STATE.md").write_bytes(good)
        with self.assertRaisesRegex(core.Error, "STATE.md does not match"):
            git.gate(self.root)
        self.assertEqual((self.root / "STATE.md").read_bytes(), good)

    def test_valid_index_does_not_depend_on_unstaged_corruption(self):
        snapshot = self.apply([{"op": "project.set", "purpose": "Valid staged purpose"}])
        self.stage_core()
        (self.root / ".seedbag/ledger.json").write_text("unfinished edit", encoding="utf-8")
        (self.root / "STATE.md").write_text("unfinished state edit", encoding="utf-8")
        result = git.gate(self.root)
        self.assertEqual(result["digest"], snapshot["digest"])
        self.assertEqual(result["source"], "staged_index")

    def test_rehashed_prior_event_rewrite_is_rejected(self):
        self.apply([{"op": "project.set", "purpose": "Original purpose"}])
        git.publish(self.root, "Original purpose", CORE_FILES)
        ledger = copy.deepcopy(core.load(self.root)["ledger"])
        ledger["events"][0]["operations"][0]["purpose"] = "Silently replaced purpose"
        event = ledger["events"][0]
        event["digest"] = core.digest({k: v for k, v in event.items() if k != "digest"})
        (self.root / git.LEDGER).write_bytes(core.canonical(ledger) + b"\n")
        fake = core.snapshot_from_ledger(ledger)
        for name, text in context.view_texts(fake).items():
            (self.root / name).write_bytes(text.encode())
        self.stage_core()
        with self.assertRaisesRegex(core.Error, "history was removed or rewritten"):
            git.gate(self.root)

    def test_untracked_required_owner_cannot_satisfy_index(self):
        (self.root / "OWNER.md").write_text("Only in working tree", encoding="utf-8")
        self.apply([{"op": "owner.add", "id": "Owner", "path": "OWNER.md", "summary": "Test owner", "tags": [], "requires": []}])
        self.stage_core()
        with self.assertRaises(core.Error):
            git.gate(self.root)
        self.assertEqual((self.root / "OWNER.md").read_text(), "Only in working tree")

    def test_pending_capture_blocks_normal_checkpoint(self):
        self.apply([{"op": "capture.add", "id": "Capture", "text": "Need to keep this fact", "origin": "user", "locator": "fixture conversation"}])
        self.stage_core()
        with self.assertRaisesRegex(core.Error, "Unprocessed capture"):
            git.gate(self.root)

    def test_incomplete_checkpoint_preserves_pending_capture_with_hook(self):
        git.install_hook(self.root)
        self.apply([{"op": "capture.add", "id": "Pending", "text": "Recover this interrupted fact", "origin": "user", "locator": "fixture conversation"}])
        result = git.publish(self.root, "Interrupted capture only", CORE_FILES, incomplete=True)
        self.assertTrue(result["snapshot_only"])
        self.assertTrue(any("Unprocessed capture" in item for item in result["readiness_warnings"]))
        fresh = self.clone("interrupted-reader")
        capture = core.load(fresh)["state"]["captures"]["Pending"]
        self.assertEqual(capture["text"], "Recover this interrupted fact")
        self.assertEqual(capture["disposition"], "pending")
        self.assertNotIn("SEEDBAG_INCOMPLETE_CHECKPOINT", os.environ)

    def test_incomplete_mode_does_not_allow_stale_completed_check(self):
        (self.root / "input.txt").write_text("original", encoding="utf-8")
        self.apply([
            {"op": "check.add", "id": "Check", "argv": [sys.executable, "-c", "print('checked')"], "inputs": ["input.txt"], "timeout": 10},
            {"op": "work.add", "id": "Work", "title": "Checked task", "requires": [], "owners": [], "checks": ["Check"]},
        ])
        core.run_check(self.root, "Check")
        self.apply([{"op": "work.status", "id": "Work", "status": "done", "note": "Recorded check passed"}])
        (self.root / "input.txt").write_text("changed after check", encoding="utf-8")
        self.stage_core()
        self.g(self.root, "add", "--", "input.txt")
        with self.assertRaisesRegex(core.Error, "Stale check inputs"):
            git.gate(self.root, incomplete=True)

    def test_unintended_staged_work_is_preserved(self):
        (self.root / "unrelated.txt").write_text("User-staged content", encoding="utf-8")
        self.g(self.root, "add", "--", "unrelated.txt")
        before = self.g(self.root, "ls-files", "--stage")
        self.apply([{"op": "project.set", "purpose": "Intended change"}])
        with self.assertRaisesRegex(core.Error, "Other files are already staged"):
            git.publish(self.root, "Intended update", CORE_FILES)
        self.assertEqual(self.g(self.root, "ls-files", "--stage"), before)
        self.assertEqual(self.g(self.root, "rev-parse", "HEAD").strip(), self.initial)

    def test_partially_staged_intended_version_is_not_overwritten(self):
        self.apply([{"op": "project.set", "purpose": "First version"}])
        self.stage_core()
        before = self.g(self.root, "ls-files", "--stage")
        self.apply([{"op": "project.set", "purpose": "Second unstaged version"}])
        with self.assertRaisesRegex(core.Error, "index holds a different version"):
            git.publish(self.root, "Do not overwrite index", CORE_FILES)
        self.assertEqual(self.g(self.root, "ls-files", "--stage"), before)

    def test_publish_readback_and_local_status_boundaries(self):
        self.apply([{"op": "project.set", "purpose": "Local saved change"}])
        local = git.status(self.root)
        self.assertEqual(local["local_state"], "dirty")
        self.assertEqual(local["reference_freshness"], "cached_not_rechecked")
        self.stage_core()
        self.g(self.root, "commit", "-m", "Local commit only")
        committed = git.status(self.root)
        self.assertEqual(committed["ahead"], 1)
        self.assertEqual(committed["shared_state"], "ahead")
        fresh_before = self.clone("before-push")
        self.assertEqual(core.load(fresh_before)["revision"], 0)
        shared = git.publish(self.root, "Publish existing checkpoint", CORE_FILES)
        self.assertEqual(shared["state"], "shared_verified")
        fresh_after = self.clone("after-push")
        self.assertEqual(core.load(fresh_after)["digest"], core.load(self.root)["digest"])
        self.assertEqual(git.status(self.root, fetch=True)["shared_state"], "matches_reference")

    def test_candidate_discovery_leaves_default_branch_unchanged(self):
        self.g(self.root, "switch", "-c", "candidate/browser-review")
        self.apply([{"op": "current.set", "summary": "Candidate: browser verification pending; not accepted", "next_work": None}])
        result = git.publish(self.root, "Candidate pending browser review", CORE_FILES)
        fresh = self.clone("candidate-reader")
        before = self.g(fresh, "rev-parse", "HEAD")
        found = git.status(fresh, fetch=True)
        match = [row for row in found["candidate_refs"] if row["ref"] == "refs/remotes/origin/candidate/browser-review"]
        self.assertEqual(match[0]["commit"], result["commit"])
        detail = git.candidate_state(fresh, match[0]["ref"])
        self.assertIn("browser verification pending", detail["state"])
        self.assertEqual(self.g(fresh, "rev-parse", "HEAD"), before)
        self.assertEqual(core.load(fresh)["revision"], 0)

    def test_local_only_status_ignores_parent_repository(self):
        nested = self.root / "new-local-project"
        core.initialize(nested, "Local files only")
        context.render(nested)
        # The parent has a configured remote. Even fetch=True must not contact
        # it on behalf of a nested uninitialized project.
        before = self.g(self.root, "rev-parse", "HEAD")
        result = git.status(nested, fetch=True)
        self.assertEqual(result["git_state"], "not_initialized")
        self.assertEqual(result["local_state"], "local_only")
        self.assertEqual(result["shared_state"], "no_shared_reference")
        self.assertIsNone(result["commit"])
        self.assertEqual(self.g(self.root, "rev-parse", "HEAD"), before)
        self.assertFalse((nested / ".git").exists())

    def test_divergent_publish_refuses_without_discarding_either_writer(self):
        other = self.clone("other-writer")
        self.apply([{"op": "project.set", "purpose": "Writer A decision"}])
        first = git.publish(self.root, "Writer A", CORE_FILES)
        self.apply([{"op": "project.set", "purpose": "Writer B different decision"}], root=other)
        preserved = (other / git.LEDGER).read_bytes()
        (other / "unfinished.txt").write_text("Do not discard", encoding="utf-8")
        with self.assertRaisesRegex(core.Error, "ahead or divergent"):
            git.publish(other, "Writer B checkpoint", CORE_FILES)
        self.assertEqual((other / git.LEDGER).read_bytes(), preserved)
        self.assertEqual((other / "unfinished.txt").read_text(), "Do not discard")
        self.assertNotEqual(self.g(other, "rev-parse", "HEAD").strip(), self.initial)
        self.assertEqual(self.g(self.remote, "rev-parse", "refs/heads/main").strip(), first["commit"])
        self.assertEqual(git.status(other)["shared_state"], "diverged")

    def test_existing_hook_is_never_overwritten(self):
        path = self.root / ".git/hooks/pre-commit"
        path.parent.mkdir(exist_ok=True)
        path.write_text("#!/bin/sh\n# Existing user hook\n", encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaisesRegex(core.Error, "already exists"):
            git.install_hook(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_installed_hook_blocks_stale_staged_view(self):
        git.install_hook(self.root)
        (self.root / "STATE.md").write_text("Manual state edit", encoding="utf-8")
        self.g(self.root, "add", "--", "STATE.md")
        result = self.g(self.root, "commit", "-m", "Invalid view", allow_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.g(self.root, "rev-parse", "HEAD").strip(), self.initial)
        self.assertIn("STATE.md", self.g(self.root, "diff", "--cached", "--name-only"))

    def test_merge_cannot_drop_incoming_ledger_even_if_head_is_preserved(self):
        self.g(self.root, "switch", "-c", "incoming-decisions")
        self.apply([{"op": "project.set", "purpose": "Incoming branch decision"}])
        self.stage_core()
        self.g(self.root, "commit", "-m", "Incoming continuity record")
        incoming = self.g(self.root, "rev-parse", "HEAD").strip()
        self.g(self.root, "switch", "main")
        self.apply([{"op": "project.set", "purpose": "Main branch decision"}])
        self.stage_core()
        self.g(self.root, "commit", "-m", "Main continuity record")
        prior_head = self.g(self.root, "rev-parse", "HEAD").strip()
        merge = self.g(self.root, "merge", "--no-commit", "--no-ff", "incoming-decisions", allow_failure=True)
        self.assertNotEqual(merge.returncode, 0)
        # Simulate an accidental conflict resolution that keeps only HEAD's
        # valid ledger and matching views. The old HEAD-only gate accepted it.
        for name in CORE_FILES:
            (self.root / name).write_bytes(self.g(self.root, "show", f"HEAD:{name}").encode("utf-8"))
        self.stage_core()
        before = self.g(self.root, "ls-files", "--stage")
        with self.assertRaisesRegex(core.Error, "does not preserve parent/base"):
            git.gate(self.root)
        self.assertEqual(self.g(self.root, "ls-files", "--stage"), before)
        self.assertEqual(self.g(self.root, "rev-parse", "HEAD").strip(), prior_head)
        self.assertEqual(self.g(self.root, "rev-parse", "incoming-decisions").strip(), incoming)
        # Deliberately bypass the optional hook in this fixture. A committed
        # snapshot audit must independently catch both actual merge parents.
        self.g(self.root, "commit", "-m", "Intentionally invalid merge fixture")
        with self.assertRaisesRegex(core.Error, "does not preserve parent/base"):
            git.audit_commit(self.root, "HEAD", self.initial)

    def test_merge_with_code_only_branch_preserves_both_parent_ledgers(self):
        self.g(self.root, "switch", "-c", "code-only")
        (self.root / "code.txt").write_text("Independent code-only branch", encoding="utf-8")
        self.g(self.root, "add", "--", "code.txt")
        self.g(self.root, "commit", "-m", "Code only")
        incoming = self.g(self.root, "rev-parse", "HEAD").strip()
        self.g(self.root, "switch", "main")
        self.apply([{"op": "project.set", "purpose": "Main continuity extension"}])
        self.stage_core()
        self.g(self.root, "commit", "-m", "Extend continuity")
        main_parent = self.g(self.root, "rev-parse", "HEAD").strip()
        self.g(self.root, "merge", "--no-commit", "--no-ff", "code-only")
        result = git.gate(self.root)
        self.assertEqual(set(result["checked_parent_ledgers"]), {main_parent, incoming})
        self.assertEqual(self.g(self.root, "rev-parse", "HEAD").strip(), main_parent)
        self.g(self.root, "commit", "-m", "Preserve both compatible parent histories")
        audited = git.audit_commit(self.root, "HEAD", self.initial)
        self.assertEqual(set(audited["parent_commits"]), {main_parent, incoming})
        self.assertEqual(audited["source"], "committed_snapshot")

    def test_committed_audit_ignores_dirty_index_and_working_copy(self):
        self.apply([{"op": "project.set", "purpose": "Committed audited purpose"}])
        self.stage_core()
        self.g(self.root, "commit", "-m", "Valid subject snapshot")
        subject = self.g(self.root, "rev-parse", "HEAD").strip()
        expected = core.load(self.root)["digest"]
        (self.root / "STATE.md").write_text("Incomplete staged change", encoding="utf-8")
        self.g(self.root, "add", "--", "STATE.md")
        (self.root / git.LEDGER).write_text("unfinished local input", encoding="utf-8")
        before_index = self.g(self.root, "ls-files", "--stage")
        result = git.audit_commit(self.root, "HEAD", self.initial)
        self.assertEqual(result["commit"], subject)
        self.assertEqual(result["base_commit"], self.initial)
        self.assertEqual(result["digest"], expected)
        self.assertEqual(self.g(self.root, "ls-files", "--stage"), before_index)
        self.assertEqual((self.root / git.LEDGER).read_text(), "unfinished local input")

    def test_publish_refuses_committed_rollback_against_shared_tip(self):
        self.apply([{"op": "project.set", "purpose": "Published continuity record"}])
        published = git.publish(self.root, "Publish continuity record", CORE_FILES)
        for name in CORE_FILES:
            (self.root / name).write_bytes(self.g(self.root, "show", f"{self.initial}:{name}").encode("utf-8"))
        self.stage_core()
        self.g(self.root, "commit", "-m", "Intentionally bypass gate and roll back ledger")
        outgoing = self.g(self.root, "rev-parse", "HEAD").strip()
        # The index equals HEAD, and Git topology is fast-forward. Only the
        # committed-content comparison against the shared baseline exposes it.
        git.gate(self.root)
        with self.assertRaisesRegex(core.Error, "history was removed or rewritten"):
            git.publish(self.root, "Do not share rolled-back ledger", CORE_FILES)
        self.assertEqual(self.g(self.root, "rev-parse", "HEAD").strip(), outgoing)
        self.assertEqual(self.g(self.remote, "rev-parse", "refs/heads/main").strip(), published["commit"])

    def test_committed_audit_refuses_missing_shallow_parent(self):
        self.apply([{"op": "project.set", "purpose": "Second committed snapshot"}])
        shared = git.publish(self.root, "Extend before shallow clone", CORE_FILES)
        shallow = self.base / "shallow-reader"
        self.g(self.base, "clone", "--no-local", "--depth=1", str(self.remote), str(shallow))
        self.assertEqual(self.g(shallow, "rev-parse", "HEAD").strip(), shared["commit"])
        with self.assertRaisesRegex(core.Error, "Fetch the intended history"):
            git.audit_commit(shallow, "HEAD", "HEAD")


if __name__ == "__main__":
    unittest.main()
