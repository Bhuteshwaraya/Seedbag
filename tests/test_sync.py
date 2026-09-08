"""Real Git synchronization with disposable local bare remotes only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import seedbag
import seedbag_core as core
import seedbag_context as context
import seedbag_git as git
import seedbag_sync as sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        prior_session = os.environ.get("SEEDBAG_SESSION_ID")
        os.environ["SEEDBAG_SESSION_ID"] = "synchronization-test-session"
        def restore_session():
            if prior_session is None:
                os.environ.pop("SEEDBAG_SESSION_ID", None)
            else:
                os.environ["SEEDBAG_SESSION_ID"] = prior_session
        self.addCleanup(restore_session)
        work = Path(os.environ.get("SEEDBAG_TEST_WORK", str(Path.cwd() / "work"))).resolve()
        work.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix="seedbag-sync-", dir=work))
        self.empty = self.base / "empty-templates"
        self.empty.mkdir()
        self.remote = self.base / "remote.git"
        self.g(self.base, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.root = self.base / "project"
        self.plant(self.root)
        self.initial = self.finish_setup(self.root)

    def g(self, root, *args):
        self.assertTrue(Path(root).resolve().is_relative_to(self.base))
        result = subprocess.run(["git", "-c", f"init.templateDir={self.empty}", "-c", "commit.gpgsign=false", "-C", str(root), *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode:
            self.fail(f"Git fixture {args}: {result.stderr.decode(errors='replace')}")
        return result.stdout.decode().strip()

    def identity(self, root):
        self.g(root, "config", "--local", "user.name", "Seedbag Test")
        self.g(root, "config", "--local", "user.email", "seedbag-test@example.invalid")
        self.g(root, "config", "--local", "commit.gpgsign", "false")
        self.g(root, "config", "--local", "core.autocrlf", "false")

    def plant(self, root):
        seedbag.plant(root, "Synchronization fixture", self.remote.as_posix(), use_git=False)
        self.g(root, "init", "--initial-branch=main")
        self.identity(root)
        self.g(root, "remote", "add", "origin", str(self.remote))
        sync.configure(root)

    def finish_setup(self, root):
        result = sync.begin(root, session="setup", setup=True)
        self.assertTrue(result["ready_to_edit"])
        sync.require_ready(root, session="setup")
        result = sync.checkpoint(root, "Save initial project", paths=sync.status(root)["changed_paths"], session="setup")
        self.assertEqual(result["state"], "shared_verified")
        return result["commit"]

    def clone(self, name):
        target = self.base / name
        self.g(self.base, "clone", str(self.remote), str(target))
        self.identity(target)
        return target

    def change(self, root, purpose):
        old = core.load(root)
        core.apply(root, [{"op": "project.set", "purpose": purpose}], old["revision"], old["digest"])
        context.render(root)

    def save(self, root, **kwargs):
        return sync.checkpoint(root, "Save fixture progress", paths=sync.status(root)["changed_paths"] or None, **kwargs)

    def test_equal_begin_grants_session_and_clean_checkpoint_creates_no_project_commit(self):
        result = sync.begin(self.root, session="codex:one")
        self.assertEqual(result["actions"], [])
        self.assertEqual(sync.require_ready(self.root, session="codex:one")["commit"], self.initial)
        result = self.save(self.root, session="codex:one")
        self.assertTrue(result["released"])
        self.assertEqual(result["commit"], self.initial)
        with self.assertRaisesRegex(core.Error, "Synchronization is required"):
            sync.require_ready(self.root)

    def test_remote_ahead_fast_forwards_before_local_mutation(self):
        second = self.clone("cloud")
        sync.begin(second)
        self.change(second, "Progress recorded in the other workspace")
        shared = self.save(second)["commit"]
        self.assertEqual(git._head(self.root), self.initial)
        result = sync.begin(self.root)
        self.assertIn("updated_local_checkpoint", result["actions"])
        self.assertEqual(git._head(self.root), shared)
        self.assertEqual(core.load(self.root)["state"]["project"]["purpose"], "Progress recorded in the other workspace")
        self.change(self.root, "Continue after recovery")

    def test_dirty_active_work_is_allowed_but_new_begin_requires_explicit_paths(self):
        sync.begin(self.root)
        self.change(self.root, "Unsaved intended work")
        sync.require_ready(self.root)
        before = (self.root / git.LEDGER).read_bytes()
        with self.assertRaisesRegex(core.Error, "intended_file_paths_required"):
            sync.begin(self.root)
        self.assertEqual((self.root / git.LEDGER).read_bytes(), before)
        paths = sync.status(self.root)["changed_paths"]
        result = sync.begin(self.root, paths=paths, message="Preserve interrupted work")
        self.assertIn("published_local_checkpoint", result["actions"])
        self.assertEqual(self.g(self.remote, "rev-parse", "refs/heads/main"), git._head(self.root))

    def test_clean_local_ahead_is_audited_and_published(self):
        sync.begin(self.root)
        self.change(self.root, "Locally committed progress")
        self.g(self.root, "add", "--", *sync.status(self.root)["changed_paths"])
        git.gate(self.root)
        self.g(self.root, "commit", "-m", "A local checkpoint")
        local = git._head(self.root)
        with self.assertRaisesRegex(core.Error, "local checkpoint appeared"):
            sync.require_ready(self.root)
        result = sync.begin(self.root)
        self.assertIn("published_local_checkpoint", result["actions"])
        self.assertEqual(result["commit"], local)

    def test_two_workspaces_cannot_hold_writer_claim(self):
        second = self.clone("second")
        sync.begin(self.root)
        with self.assertRaisesRegex(core.Error, "Another workspace has unfinished"):
            sync.begin(second)
        self.assertEqual(git._head(second), self.initial)
        self.save(self.root)
        self.assertTrue(sync.begin(second)["ready_to_edit"])

    def test_same_workspace_distinct_session_cannot_reuse_an_unfinished_claim(self):
        sync.begin(self.root, session="first")
        with self.assertRaisesRegex(core.Error, "Another session owns"):
            sync.begin(self.root, session="second")
        sync.require_ready(self.root, session="first")

    def test_claim_history_is_append_only_and_release_is_not_deletion(self):
        before = self.g(self.remote, "rev-parse", sync.CLAIM_REF)
        sync.begin(self.root)
        active = self.g(self.remote, "rev-parse", sync.CLAIM_REF)
        self.assertEqual(self.g(self.remote, "rev-parse", active + "^"), before)
        self.save(self.root)
        free = self.g(self.remote, "rev-parse", sync.CLAIM_REF)
        self.assertEqual(self.g(self.remote, "rev-parse", free + "^"), active)
        data = json.loads(self.g(self.remote, "show", free + ":claim.json"))
        self.assertEqual(data["state"], "free")
        self.assertNotIn(str(self.root), json.dumps(data))

    def test_unknown_untracked_file_blocks_checkpoint_without_uploading_it(self):
        sync.begin(self.root)
        self.change(self.root, "A useful change")
        before = git._head(self.root)
        (self.root / "private-notes.txt").write_text("not reviewed", encoding="utf-8")
        intended = [p for p in sync.status(self.root)["changed_paths"] if p != "private-notes.txt"]
        with self.assertRaisesRegex(core.Error, "Unreviewed local files"):
            sync.checkpoint(self.root, "Save project", paths=intended)
        self.assertEqual(git._head(self.root), before)
        self.assertEqual((self.root / "private-notes.txt").read_text(), "not reviewed")

    def test_ignored_secret_is_not_a_checkpoint_target(self):
        sync.begin(self.root)
        self.change(self.root, "Intended change")
        (self.root / ".env").write_text("EXAMPLE=private\n", encoding="utf-8")
        with self.assertRaisesRegex(core.Error, "ignored file"):
            sync.checkpoint(self.root, "Save project", paths=sync.status(self.root)["changed_paths"] + [".env"])
        self.assertEqual(git._head(self.root), self.initial)

    def test_incoming_runtime_change_is_not_automatically_adopted(self):
        second = self.clone("runtime-editor")
        path = second / ".seedbag/runtime/seedbag_core.py"
        path.write_bytes(path.read_bytes() + b"\n# Unreviewed replacement fixture\n")
        self.g(second, "add", "--", ".seedbag/runtime/seedbag_core.py")
        self.g(second, "commit", "-m", "Unreviewed runtime change")
        self.g(second, "push", "origin", "main")
        original = (self.root / ".seedbag/runtime/seedbag_core.py").read_bytes()
        with self.assertRaisesRegex(core.Error, "changes installed instructions"):
            sync.begin(self.root)
        self.assertEqual(git._head(self.root), self.initial)
        self.assertEqual((self.root / ".seedbag/runtime/seedbag_core.py").read_bytes(), original)

    def test_setup_cannot_bypass_existing_checkpoint(self):
        with self.assertRaisesRegex(core.Error, "Setup is only"):
            sync.begin(self.root, setup=True)
        self.assertEqual(self.g(self.remote, "rev-parse", "refs/heads/main"), self.initial)

    def test_readme_bootstrap_ancestry_preserved_without_overwriting_planted_files(self):
        self.remote = self.base / "bootstrap.git"
        self.g(self.base, "init", "--bare", "--initial-branch=main", str(self.remote))
        seed = self.base / "bootstrap-writer"
        seed.mkdir()
        self.g(seed, "init", "--initial-branch=main")
        self.identity(seed)
        (seed / "README.md").write_bytes(b"Repository bootstrap\n")
        self.g(seed, "add", "README.md")
        self.g(seed, "commit", "-m", "Create repository")
        bootstrap = git._head(seed)
        self.g(seed, "remote", "add", "origin", str(self.remote))
        self.g(seed, "push", "origin", "main")
        target = self.base / "new-plant"
        self.plant(target)
        before = (target / "README.md").read_bytes()
        begin = sync.begin(target, setup=True)
        self.assertIn("preserved_remote_bootstrap_ancestry", begin["actions"])
        self.assertEqual((target / "README.md").read_bytes(), before)
        result = self.save(target)
        self.assertEqual(self.g(target, "rev-parse", result["commit"] + "^"), bootstrap)
        self.assertEqual((target / "README.md").read_bytes(), before)

    def test_offline_recheck_blocks_mutation_with_files_preserved(self):
        sync.begin(self.root)
        before = (self.root / git.LEDGER).read_bytes()
        actual = git._git
        def denied(root, *args, **kwargs):
            if args and args[0] == "ls-remote":
                raise core.Error("Synthetic network boundary")
            return actual(root, *args, **kwargs)
        with mock.patch.object(git, "_git", side_effect=denied):
            with self.assertRaisesRegex(core.Error, "Synthetic network boundary"):
                self.change(self.root, "Cannot mutate while offline")
        self.assertEqual((self.root / git.LEDGER).read_bytes(), before)

    def test_cached_status_or_cached_permission_does_not_grant_new_work(self):
        sync.begin(self.root)
        self.assertFalse(sync.status(self.root)["ready_to_edit"])
        with self.assertRaisesRegex(core.Error, "cached synchronization receipt"):
            sync.require_ready(self.root, refresh=False)

    def test_incomplete_checkpoint_keeps_pending_capture(self):
        sync.begin(self.root)
        old = core.load(self.root)
        core.apply(self.root, [{"op": "capture.add", "id": "Pending", "text": "Keep this unfinished input", "origin": "user", "locator": "fixture request"}], old["revision"], old["digest"])
        context.render(self.root)
        result = self.save(self.root, incomplete=True)
        self.assertTrue(result["snapshot_only"])
        self.assertEqual(core.load(self.clone("unfinished-reader"))["state"]["captures"]["Pending"]["disposition"], "pending")

    def test_push_success_with_lost_response_recovers_without_duplicate_checkpoint(self):
        sync.begin(self.root)
        self.change(self.root, "One durable change")
        actual = git._git
        def uncertain(root, *args, **kwargs):
            value = actual(root, *args, **kwargs)
            if args and args[0] == "push" and args[-1].endswith(":refs/heads/main"):
                raise core.Error("Synthetic lost publication response")
            return value
        with mock.patch.object(git, "_git", side_effect=uncertain):
            with self.assertRaisesRegex(core.Error, "lost publication response"):
                self.save(self.root)
        saved = git._head(self.root)
        result = sync.checkpoint(self.root, "Inspect prior checkpoint", paths=None)
        self.assertEqual(result["commit"], saved)
        self.assertEqual(core.load(self.root)["revision"], 1)

    def test_local_only_work_does_not_require_git_or_network(self):
        target = self.base / "local-only"
        seedbag.plant(target, "Local fixture", "", use_git=False)
        with mock.patch.object(git, "_git", side_effect=AssertionError("Unexpected Git operation")):
            self.assertTrue(sync.begin(target)["ready_to_edit"])
            self.change(target, "Local-only purpose")

    def test_explicit_same_workspace_recovery_keeps_bytes_and_requires_new_sync(self):
        # Mock session lookup only. Replacing os.environ wholesale can drop
        # inherited empty-valued Git config variables on Windows.
        actual_session = sync._requested_session
        with mock.patch.object(sync, "_requested_session", side_effect=lambda value: actual_session(value or "old-session")):
            sync.begin(self.root)
            self.change(self.root, "Unfinished work survives a closed chat")
        original = (self.root / git.LEDGER).read_bytes()
        recovered = sync.recover_session(self.root, "new-session")
        self.assertFalse(recovered["ready_to_edit"])
        self.assertEqual((self.root / git.LEDGER).read_bytes(), original)
        with self.assertRaisesRegex(core.Error, "Synchronization is required"):
            sync.require_ready(self.root, session="old-session")
        result = sync.begin(self.root, session="new-session", paths=sync.status(self.root)["changed_paths"], message="Preserve prior session")
        self.assertTrue(result["ready_to_edit"])
        self.assertEqual((self.root / git.LEDGER).read_bytes(), original)

    def test_clean_released_checkpoint_can_be_reverified_without_touching_next_writer(self):
        sync.begin(self.root)
        self.save(self.root)
        second = self.clone("next-writer")
        sync.begin(second)
        claim_before = self.g(self.remote, "rev-parse", sync.CLAIM_REF)
        result = sync.checkpoint(self.root, "Verify completed checkpoint")
        self.assertEqual(result["state"], "shared_verified")
        self.assertTrue(result["released"])
        self.assertEqual(self.g(self.remote, "rev-parse", sync.CLAIM_REF), claim_before)

    def test_fresh_permission_uses_one_network_reference_observation(self):
        sync.begin(self.root)
        actual = git._git
        calls = []
        def observed(root, *args, **kwargs):
            if args and args[0] in ("fetch", "ls-remote", "push"):
                calls.append(args)
            return actual(root, *args, **kwargs)
        with mock.patch.object(git, "_git", side_effect=observed):
            sync.require_ready(self.root)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "ls-remote")
        self.assertIn("refs/heads/main", calls[0])
        self.assertIn(sync.CLAIM_REF, calls[0])

    def test_coordination_branch_cannot_be_bound_as_project_branch(self):
        claim = self.g(self.remote, "rev-parse", sync.CLAIM_REF)
        policy = json.loads((self.root / sync.POLICY).read_bytes())
        policy["branch"] = "seedbag-sync-claims"
        (self.root / sync.POLICY).write_bytes(core.canonical(policy) + b"\n")
        self.g(self.root, "branch", "-m", "seedbag-sync-claims")
        with self.assertRaisesRegex(core.Error, "reserved for writer coordination"):
            sync.begin(self.root)
        self.assertEqual(self.g(self.remote, "rev-parse", sync.CLAIM_REF), claim)
        self.assertEqual(self.g(self.remote, "rev-parse", "refs/heads/main"), self.initial)


if __name__ == "__main__":
    unittest.main()
