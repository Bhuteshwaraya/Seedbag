"""Adversarial synchronization checks with isolated local bare repositories.

No network, user credentials, global Git configuration, or existing projects.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "runtime"))
sys.path.insert(0, str(SOURCE))
import seedbag
import seedbag_core as core
import seedbag_context as context
import seedbag_git as git
import seedbag_sync as sync
import seedbag_hooks as hooks


@contextmanager
def session_environment(**changes):
    """Change only session keys; preserve Windows' existing empty Git env values."""
    previous = {key: os.environ.get(key) for key in changes}
    try:
        for key, value in changes.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class SyncAdversarialTests(unittest.TestCase):
    def setUp(self):
        work = Path(os.environ.get("SEEDBAG_TEST_WORK", str(Path.cwd() / "work"))).resolve()
        work.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix="seedbag-sync-adversarial-", dir=work))
        self.empty = self.base / "empty-templates"
        self.empty.mkdir()
        self.root = self.base / "project"
        self.remote = self.base / "remote.git"
        self.g(self.base, "init", "--bare", "--initial-branch=main", str(self.remote))
        seedbag.plant(self.root, "Sync adversarial fixture", self.remote.as_posix(), use_git=False)
        self.g(self.root, "init", "--initial-branch=main")
        self.configure_git(self.root)
        self.g(self.root, "remote", "add", "origin", str(self.remote))
        sync.configure(self.root)
        self.stage_project(self.root)
        self.g(self.root, "commit", "-m", "Initial isolated synchronization fixture")
        self.g(self.root, "push", "-u", "origin", "main")
        self.initial = self.head(self.root)

    def g(self, root, *args, allow_failure=False):
        self.assertTrue(Path(root).resolve().is_relative_to(self.base))
        result = subprocess.run(
            ["git", "-c", f"init.templateDir={self.empty}", "-c", "commit.gpgsign=false",
             "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30,
        )
        if not allow_failure and result.returncode:
            self.fail(f"Git fixture failed: {args}: {result.stderr.decode(errors='replace')}")
        return result if allow_failure else result.stdout.decode("utf-8")

    def configure_git(self, root):
        for key, value in (("user.name", "Seedbag Test"),
                           ("user.email", "seedbag-test@example.invalid"),
                           ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
            self.g(root, "config", "--local", key, value)

    def stage_project(self, root):
        paths = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                       if p.is_file() and not any(part in (".git", ".seedbag-local", "__pycache__")
                                                  for part in p.relative_to(root).parts))
        self.g(root, "add", "--", *paths)

    def head(self, root=None):
        return self.g(root or self.root, "rev-parse", "HEAD").strip()

    def remote_head(self):
        return self.g(self.remote, "rev-parse", "refs/heads/main").strip()

    def clone(self, name):
        root = self.base / name
        self.g(self.base, "clone", str(self.remote), str(root))
        self.configure_git(root)
        return root

    def advance_uncooperative_remote(self, name="writer", runtime_change=False):
        """Model a writer outside the cooperating gate; never fake remote reads."""
        other = self.clone(name)
        if runtime_change:
            path = other / ".seedbag/runtime/seedbag_core.py"
            path.write_bytes(path.read_bytes() + b"\n# Unreviewed remote runtime change.\n")
        else:
            (other / "other-writer.txt").write_text("Uncoordinated but preserved work.\n", encoding="utf-8")
        self.stage_project(other)
        self.g(other, "commit", "-m", "Uncoordinated remote fixture")
        self.g(other, "push", "origin", "main")
        return self.head(other)

    def test_changed_push_destination_cannot_reuse_ready_receipt(self):
        sync.begin(self.root, session="first-session")
        other_remote = self.base / "unrelated.git"
        self.g(self.base, "init", "--bare", "--initial-branch=main", str(other_remote))
        self.g(self.root, "config", "--local", "remote.origin.pushurl", str(other_remote))
        with self.assertRaisesRegex(core.Error, "destination.*does not match"):
            sync.require_ready(self.root, session="first-session")
        self.assertEqual(self.remote_head(), self.initial)
        self.assertEqual(self.g(other_remote, "show-ref", allow_failure=True).returncode, 1)

    def test_multiple_push_destinations_are_refused_before_claim(self):
        self.g(self.root, "config", "--local", "--add", "remote.origin.pushurl", str(self.remote))
        self.g(self.root, "config", "--local", "--add", "remote.origin.pushurl", str(self.remote))
        with self.assertRaisesRegex(core.Error, "destination.*does not match"):
            sync.begin(self.root, session="ambiguous-push")
        self.assertEqual(self.g(self.remote, "show-ref", "--verify", sync.CLAIM_REF,
                                allow_failure=True).returncode, 128)
        self.assertEqual(self.remote_head(), self.initial)

    def test_ready_receipt_is_blocked_after_uncoordinated_remote_change(self):
        sync.begin(self.root, session="active-session")
        local = self.root / "unfinished.txt"
        local.write_bytes(b"Keep this pending work exactly.\x00\n")
        advanced = self.advance_uncooperative_remote()
        with self.assertRaisesRegex(core.Error, "shared project changed"):
            sync.require_ready(self.root, session="active-session")
        self.assertEqual(local.read_bytes(), b"Keep this pending work exactly.\x00\n")
        self.assertEqual(self.head(), self.initial)
        self.assertEqual(self.remote_head(), advanced)

    def test_network_failure_never_turns_cached_receipt_into_permission(self):
        sync.begin(self.root, session="online-session")
        actual = git._git

        def disconnected(root, *args, **kwargs):
            if args and args[0] in ("fetch", "ls-remote"):
                raise core.Error("Isolated fixture: network unavailable.")
            return actual(root, *args, **kwargs)

        with mock.patch.object(git, "_git", side_effect=disconnected):
            with self.assertRaisesRegex(core.Error, "network unavailable"):
                sync.require_ready(self.root, session="online-session")
        self.assertFalse(sync.status(self.root)["ready_to_edit"])
        with self.assertRaisesRegex(core.Error, "cached"):
            sync.require_ready(self.root, session="online-session", refresh=False)
        self.assertEqual(self.head(), self.initial)
        self.assertEqual(self.remote_head(), self.initial)

    def test_two_competing_claims_admit_exactly_one_writer(self):
        second = self.clone("second-workspace")
        barrier = threading.Barrier(2)
        transition = sync._transition

        def race(root, policy, parent, claim):
            if claim["state"] == "active":
                barrier.wait(timeout=30)
            return transition(root, policy, parent, claim)

        def start(root, session):
            try:
                return sync.begin(root, session=session)
            except core.Error as exc:
                return exc

        with mock.patch.object(sync, "_transition", side_effect=race):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(start, self.root, "racing-one")
                other = executor.submit(start, second, "racing-two")
                results = [first.result(timeout=60), other.result(timeout=60)]
        admitted = [index for index, value in enumerate(results)
                    if isinstance(value, dict) and value.get("ready_to_edit")]
        self.assertEqual(len(admitted), 1, results)
        self.assertIsInstance(results[1 - admitted[0]], core.Error)
        claim = json.loads(self.g(self.remote, "show", f"{sync.CLAIM_REF}:claim.json"))
        winner = self.root if admitted[0] == 0 else second
        receipt = json.loads((winner / sync.RECEIPT).read_bytes())
        self.assertEqual(claim["state"], "active")
        self.assertEqual(claim["token"], receipt["token"])
        self.assertEqual(self.remote_head(), self.initial)
        self.assertTrue(sync.require_ready(winner, session=receipt["session"])["ready_to_edit"])

    def test_failed_connection_before_claim_does_not_strand_next_conversation(self):
        actual = git._git

        def disconnected(root, *args, **kwargs):
            if args and args[0] == "ls-remote":
                raise core.Error("Isolated fixture: first conversation cannot connect.")
            return actual(root, *args, **kwargs)

        with mock.patch.object(git, "_git", side_effect=disconnected):
            with self.assertRaisesRegex(core.Error, "cannot connect"):
                sync.begin(self.root, session="old-disconnected-conversation")
        self.assertEqual(self.g(self.remote, "show-ref", "--verify", sync.CLAIM_REF,
                                allow_failure=True).returncode, 128)
        ready = sync.begin(self.root, session="new-connected-conversation")
        self.assertTrue(ready["ready_to_edit"])
        self.assertEqual(ready["session"], "new-connected-conversation")
        self.assertEqual(self.remote_head(), self.initial)

    def test_lost_release_acknowledgement_is_recoverable_in_next_conversation(self):
        sync.begin(self.root, session="old-saving-conversation")
        transition = sync._transition

        def lost_acknowledgement(root, policy, parent, claim):
            result = transition(root, policy, parent, claim)
            if claim["state"] == "free":
                raise core.Error("Isolated fixture: release response was lost after the actual push.")
            return result

        with mock.patch.object(sync, "_transition", side_effect=lost_acknowledgement):
            with self.assertRaisesRegex(core.Error, "release response was lost"):
                sync.checkpoint(self.root, "Release completed checkpoint", session="old-saving-conversation")
        claim = json.loads(self.g(self.remote, "show", f"{sync.CLAIM_REF}:claim.json"))
        self.assertEqual(claim["state"], "free")
        self.assertEqual(claim["base"], self.initial)
        ready = sync.begin(self.root, session="new-conversation-after-lost-response")
        self.assertTrue(ready["ready_to_edit"])
        self.assertEqual(self.remote_head(), self.initial)
        self.assertEqual(self.head(), self.initial)

    def test_setup_cannot_replace_existing_shared_project(self):
        fresh = self.base / "replacement-attempt"
        seedbag.plant(fresh, "Different new project", self.remote.as_posix(), use_git=False)
        self.g(fresh, "init", "--initial-branch=main")
        self.configure_git(fresh)
        self.g(fresh, "remote", "add", "origin", str(self.remote))
        sync.configure(fresh)
        original = (fresh / git.LEDGER).read_bytes()
        with self.assertRaisesRegex(core.Error, "cannot bypass"):
            sync.begin(fresh, session="incorrect-setup", setup=True)
        self.assertEqual((fresh / git.LEDGER).read_bytes(), original)
        self.assertEqual(self.remote_head(), self.initial)
        self.assertNotEqual(core.load(fresh)["ledger"], core.load(self.root)["ledger"])

    def test_incoming_runtime_change_is_preserved_without_adopting_it(self):
        original = (self.root / ".seedbag/runtime/seedbag_core.py").read_bytes()
        advanced = self.advance_uncooperative_remote(runtime_change=True)
        with self.assertRaisesRegex(core.Error, "incoming checkpoint changes installed"):
            sync.begin(self.root, session="runtime-review")
        self.assertEqual(self.head(), self.initial)
        self.assertEqual((self.root / ".seedbag/runtime/seedbag_core.py").read_bytes(), original)
        self.assertEqual(self.remote_head(), advanced)

    def test_partial_index_and_working_versions_are_both_preserved(self):
        path = self.root / "notes.txt"
        path.write_bytes(b"Keep the staged version.\n")
        self.g(self.root, "add", "--", "notes.txt")
        path.write_bytes(b"Keep the later working version too.\n")
        with self.assertRaisesRegex(core.Error, "index preserves a different version"):
            sync.begin(self.root, session="recover-partial-index", paths=["notes.txt"],
                       message="Attempt to synchronize differing local versions")
        self.assertEqual(self.g(self.root, "show", ":notes.txt"), "Keep the staged version.\n")
        self.assertEqual(path.read_bytes(), b"Keep the later working version too.\n")
        self.assertEqual(self.head(), self.initial)
        self.assertEqual(self.remote_head(), self.initial)

    def test_ignored_secret_cannot_be_added_to_automatic_checkpoint(self):
        secret = self.root / ".env"
        secret.write_bytes(b"TOKEN=synthetic-test-data\n")
        (self.root / "pending.txt").write_text("Intended project work.\n", encoding="utf-8")
        with self.assertRaisesRegex(core.Error, "ignored file"):
            sync.begin(self.root, session="protect-ignored-data", paths=["pending.txt", ".env"],
                       message="Attempt to include ignored data")
        self.assertEqual(secret.read_bytes(), b"TOKEN=synthetic-test-data\n")
        self.assertEqual(self.g(self.root, "ls-files", "--", ".env"), "")
        self.assertEqual(self.remote_head(), self.initial)

    def test_matching_commits_do_not_admit_corrupt_committed_views(self):
        path = self.root / "STATE.md"
        path.write_text("This does not reflect the saved ledger.\n", encoding="utf-8")
        self.g(self.root, "add", "--", "STATE.md")
        self.g(self.root, "commit", "-m", "Deliberately corrupt committed view fixture")
        self.g(self.root, "push", "origin", "main")
        corrupt = self.head()
        with self.assertRaisesRegex(core.Error, "STATE.md does not match"):
            sync.begin(self.root, session="equal-but-invalid")
        self.assertEqual(self.head(), corrupt)
        self.assertEqual(self.remote_head(), corrupt)
        self.assertEqual(path.read_text(encoding="utf-8"), "This does not reflect the saved ledger.\n")

    def test_index_flags_cannot_hide_unpublished_workspace_bytes(self):
        path = self.root / "tracked-notes.txt"
        path.write_bytes(b"Shared notes.\n")
        self.g(self.root, "add", "--", "tracked-notes.txt")
        self.g(self.root, "commit", "-m", "Ordinary tracked domain fixture")
        self.g(self.root, "push", "origin", "main")
        base = self.head()
        for flag, undo in (("--assume-unchanged", "--no-assume-unchanged"),
                           ("--skip-worktree", "--no-skip-worktree")):
            with self.subTest(flag=flag):
                self.g(self.root, "update-index", flag, "--", "tracked-notes.txt")
                path.write_bytes(b"Unpublished work hidden by index flags.\n")
                self.assertEqual(self.g(self.root, "diff", "--name-only"), "")
                with self.assertRaises(core.Error):
                    sync.begin(self.root, session="hidden-work-recovery")
                self.assertEqual(path.read_bytes(), b"Unpublished work hidden by index flags.\n")
                self.assertEqual(self.head(), base)
                self.assertEqual(self.remote_head(), base)
                self.g(self.root, "update-index", undo, "--", "tracked-notes.txt")
                path.write_bytes(b"Shared notes.\n")

    def test_hook_and_normal_cli_share_the_same_host_session_identity(self):
        session = "host-session-id-for-integration"
        with session_environment(CODEX_THREAD_ID=session, SEEDBAG_SESSION_ID=None):
            hooks.handle(self.root, {"hook_event_name": "SessionStart", "session_id": session,
                                     "cwd": str(self.root)})
            receipt = json.loads((self.root / sync.RECEIPT).read_bytes())
            self.assertEqual(receipt["state"], "ready_to_edit")
            old = core.load(self.root)
            changed = core.apply(self.root, [{"op": "project.set", "purpose": "Verified hook-to-runtime session."}],
                                 old["revision"], old["digest"])
        self.assertEqual(changed["revision"], old["revision"] + 1)
        self.assertEqual(self.remote_head(), self.initial)

    def test_unknown_session_cannot_borrow_an_existing_writer_receipt(self):
        sync.begin(self.root, session="known-original-writer")
        with session_environment(CODEX_THREAD_ID=None, SEEDBAG_SESSION_ID=None):
            with self.assertRaises(core.Error):
                sync.require_ready(self.root)
            old = core.load(self.root)
            with self.assertRaises(core.Error):
                core.apply(self.root, [{"op": "project.set", "purpose": "Unidentified caller must not change this."}],
                           old["revision"], old["digest"])
            self.assertEqual(core.load(self.root)["digest"], old["digest"])
        self.assertEqual(self.remote_head(), self.initial)

    def test_public_git_api_cannot_publish_to_another_configured_repository(self):
        unrelated = self.base / "unrelated-publication.git"
        self.g(self.base, "init", "--bare", "--initial-branch=main", str(unrelated))
        self.g(self.root, "remote", "add", "unrelated", str(unrelated))
        with session_environment(CODEX_THREAD_ID="bound-publisher", SEEDBAG_SESSION_ID=None):
            sync.begin(self.root, session="bound-publisher")
            with self.assertRaises(core.Error):
                git.publish(self.root, "Do not copy the project to an unrelated destination",
                            list(git.REQUIRED_FILES), remote="unrelated", branch="main")
        self.assertEqual(self.g(unrelated, "show-ref", allow_failure=True).returncode, 1)
        self.assertEqual(self.remote_head(), self.initial)

    def test_missing_launcher_does_not_disable_installed_core_sync_gate(self):
        with session_environment(CODEX_THREAD_ID="installed-core-session", SEEDBAG_SESSION_ID=None):
            sync.begin(self.root, session="installed-core-session")
            (self.root / "seedbag.py").unlink()
            advanced = self.advance_uncooperative_remote(name="changed-shared-project")
            old = core.load(self.root)
            with self.assertRaises(core.Error):
                core.apply(self.root, [{"op": "project.set", "purpose": "This stale installed core must remain blocked."}],
                           old["revision"], old["digest"])
            self.assertEqual(core.load(self.root)["digest"], old["digest"])
        self.assertEqual(self.remote_head(), advanced)
        self.assertFalse((self.root / "seedbag.py").exists())

    def test_coordination_branch_is_not_presented_as_alternate_project_work(self):
        sync.begin(self.root, session="claim-metadata-session")
        state = git.status(self.root, fetch=True)
        self.assertTrue(self.g(self.root, "show-ref", sync.CLAIM_REF.replace("refs/heads/", "refs/remotes/origin/"),
                               allow_failure=True).returncode == 0)
        self.assertEqual(state["candidate_count"], 0)
        self.assertEqual(state["candidate_refs"], [])


if __name__ == "__main__":
    unittest.main()
