"""Codex wire-contract, gate bypass, and isolated project-hook preparation tests."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "runtime"))
import seedbag_core as core
import seedbag_hooks as hooks
import seedbag_git as git


@contextmanager
def scoped_environment(updates, remove=()):
    """Only touch test-owned keys; Windows empty inherited values stay intact."""
    keys = set(updates) | set(remove)
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in remove:
            os.environ.pop(key, None)
        os.environ.update(updates)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class HookTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(os.environ.get("SEEDBAG_TEST_WORK", Path.cwd() / "work")).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="seedbag-hooks-new-", dir=workspace)
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(workspace))
        self.addCleanup(self.temp.cleanup)
        self.runtime = mock.Mock()
        self.runtime.begin.return_value = {"state": "ready_to_edit", "commit": "a" * 40}
        self.runtime.require_ready.return_value = {"state": "ready_to_edit"}
        self.runtime.checkpoint.return_value = {"state": "shared_verified", "shared": True, "released": True}
        self.runtime.status.return_value = {"state": "not_rechecked"}
        patcher = mock.patch.object(hooks, "_sync", return_value=self.runtime)
        patcher.start()
        self.addCleanup(patcher.stop)

    def event(self, name, **extra):
        return {"hook_event_name": name, "session_id": "test-session", "turn_id": "test-turn",
                "cwd": str(self.root), **extra}

    def call(self, name, **extra):
        return hooks.handle(self.root, self.event(name, **extra))

    def assert_denied(self, result):
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertNotIn("continue", result)

    def block(self):
        self.runtime.begin.side_effect = core.Error("remote_unavailable")
        self.runtime.require_ready.side_effect = core.Error("remote_unavailable")

    def shell(self, command, **data):
        return self.call("PreToolUse", tool_name="Bash", tool_input={"command": command, **data})

    def test_entry_refreshes_before_context_and_forwards_host_identity(self):
        for name in ("SessionStart", "UserPromptSubmit"):
            result = self.call(name)
            self.assertEqual(result["hookSpecificOutput"]["hookEventName"], name)
            self.assertIn("shared starting point", result["hookSpecificOutput"]["additionalContext"])
        self.runtime.begin.assert_called_with(self.root, session="test-session")

    def test_other_workspace_cannot_acquire_writer_or_admit_a_tool(self):
        for cwd in (str(self.root.parent), "relative/project", None):
            with self.subTest(cwd=cwd):
                result = self.call("SessionStart", cwd=cwd)
                self.assertIn("wrong_workspace", json.dumps(result))
                self.assert_denied(self.call("PreToolUse", cwd=cwd, tool_name="apply_patch",
                                             tool_input={"command": "patch"}))
        self.runtime.begin.assert_not_called()
        self.runtime.require_ready.assert_not_called()

    def test_project_subdirectory_keeps_the_same_gate(self):
        result = self.call("SessionStart", cwd=str(self.root / "src"))
        self.assertIn("shared starting point", json.dumps(result))
        self.runtime.begin.assert_called_once_with(self.root, session="test-session")

    def test_failed_entry_preserves_prompt_for_recovery_without_leaking_error(self):
        self.runtime.begin.side_effect = core.Error("remote_unavailable https://token:secret@example.invalid")
        result = self.call("UserPromptSubmit")
        text = json.dumps(result)
        self.assertNotIn("secret", text)
        self.assertNotIn("decision", result)
        self.assertIn("Pause new project changes", text)

    def test_writes_require_fresh_ready_state_even_after_entry(self):
        self.call("SessionStart")
        result = self.call("PreToolUse", tool_name="apply_patch", tool_input={"command": "patch"})
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertIn("freshly verified", result["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("permissionDecision", result["hookSpecificOutput"])
        self.runtime.require_ready.assert_called_once_with(self.root, session="test-session", refresh=True)
        self.block()
        self.assert_denied(self.call("PreToolUse", tool_name="apply_patch", tool_input={"command": "patch"}))

    def test_unverified_runtime_result_is_not_permission(self):
        for outcome in ({"state": "offline"}, {"ok": True}, None):
            self.runtime.require_ready.return_value = outcome
            self.assert_denied(self.shell("python arbitrary.py"))

    def test_missing_session_identity_blocks_tools(self):
        self.assert_denied(hooks.handle(self.root, {"hook_event_name": "PreToolUse", "tool_name": "apply_patch"}))
        self.runtime.require_ready.assert_not_called()

    def test_unexpected_runtime_failure_emits_valid_deny_not_hook_failure(self):
        self.runtime.require_ready.side_effect = RuntimeError("private diagnostic")
        result = self.shell("python arbitrary.py")
        self.assert_denied(result)
        self.assertNotIn("private diagnostic", json.dumps(result))

    def test_local_only_has_no_shared_claim_or_stop_publication(self):
        result = {"state": "local_only", "ready_to_edit": True, "shared": False}
        self.runtime.begin.return_value = result
        self.runtime.require_ready.return_value = result
        self.runtime.status.return_value = result
        self.assertIn("local work only", json.dumps(self.call("SessionStart")))
        self.assertEqual(self.shell("python ordinary.py"), {})
        self.assertEqual(self.call("Stop"), {})
        self.runtime.checkpoint.assert_not_called()

    def test_dedicated_read_and_permission_tools_remain_available(self):
        self.block()
        for name in ("read_file", "view_image", "request_permissions", "request_user_input", "request_user_input_async",
                     "mcp__codex_app__list_threads", "mcp__codex_app__read_thread"):
            self.assertEqual(self.call("PreToolUse", tool_name=name, tool_input={}), {})
        self.assert_denied(self.call("PreToolUse", tool_name="mcp__unknown__read_and_delete", tool_input={}))
        self.assert_denied(self.call("PreToolUse", tool_name="mcp__codex_app__send_message_to_thread", tool_input={}))

    def test_opaque_code_wrapper_is_not_assumed_to_provide_safe_recovery(self):
        self.block()
        result = self.call("PreToolUse", tool_name="functions.exec", tool_input={"code": "await tools.exec_command(...)"})
        self.assert_denied(result)
        self.assertIn("blocked code wrapper", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_exact_installed_recovery_commands_are_allowed(self):
        self.block()
        for command in (
            "python -B seedbag.py sync-status",
            "python3 seedbag.py sync-begin --paths PROJECT.md STATE.md --message 'Preserve work'",
            f"& '{sys.executable}' -B '{self.root / 'seedbag.py'}' --root '{self.root}' sync-checkpoint --paths 'draft.md' --incomplete",
            "python seedbag.py context",
            "python seedbag.py render",
            "python seedbag.py effect-resolve prior-operation --outcome confirmed --receipt 'Observed the actual destination'",
            "python seedbag.py --session test-session sync-status",
            f"python seedbag.py --session test-session --root '{self.root}' sync-recover",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.shell(command), {})
        self.runtime.require_ready.assert_not_called()

    def test_shell_syntax_or_arbitrary_script_cannot_bypass(self):
        self.block()
        for command in (
            "python seedbag.py sync-status; echo changed > draft.md",
            "python seedbag.py sync-status && python evil.py",
            "python seedbag.py sync-status | sh",
            "python seedbag.py sync-status > notes.txt",
            "python seedbag.py sync-status\npython evil.py",
            "python seedbag.py sync-status $(python evil.py)",
            "python seedbag.py sync-status `python evil.py`",
            "python seedbag.py sync-status %EXTRA_COMMAND%",
            "python seedbag.py sync-status !EXTRA_COMMAND!",
            "python -c 'print(1)' seedbag.py sync-status",
            "python other.py sync-status",
            "python seedbag.py capture --file notes.txt --id fabricated",
            "python seedbag.py effect-run prior-operation",
            "python seedbag.py sync-status --root ../another-project",
            "python seedbag.py --root ../another-project sync-status",
            "python seedbag.py sync-status --root=../another-project",
            "python seedbag.py --session another-session sync-status",
            "python seedbag.py sync-status --message 'quoted;command'",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.shell(command))

    def test_recovery_from_subdirectory_needs_explicit_matching_root(self):
        self.block()
        subdirectory = self.root / "nested"
        subdirectory.mkdir()
        self.assert_denied(self.shell("python ../seedbag.py sync-status", workdir=str(subdirectory)))
        self.assertEqual(self.shell(f"python '{self.root / 'seedbag.py'}' --root '{self.root}' sync-status",
                                    workdir=str(subdirectory)), {})
        self.assert_denied(self.shell("python seedbag.py sync-status", workdir=str(self.root.parent)))

    def test_exact_setup_diagnostics_allow_connection_recovery_without_shell_escape(self):
        self.block()
        for command in (
            "python -B seedbag_setup.py --offline",
            "python seedbag_setup.py --network --repository https://github.com/example/project --timeout 12",
            "whoami",
        ):
            self.assertEqual(self.shell(command), {})
        for command in (
            "python seedbag_setup.py --network",
            "python seedbag_setup.py --network --repository https://attacker.invalid/repo",
            "python seedbag_setup.py --offline --network --repository https://github.com/example/project",
            "python seedbag_setup.py --timeout 99999",
            "python seedbag_setup.py --login",
            "python ../seedbag_setup.py --offline",
            "python seedbag_setup.py --offline; python arbitrary.py",
            "whoami; python arbitrary.py",
        ):
            self.assert_denied(self.shell(command))

    def test_exact_read_commands_inspect_untracked_files_without_general_shell_bypass(self):
        self.block()
        (self.root / "AGENTS.md").write_text("Existing project instructions", encoding="utf-8")
        (self.root / "untracked notes.txt").write_text("Review before sharing", encoding="utf-8")
        for command in (
            "Get-Content -LiteralPath AGENTS.md",
            "Get-Content -LiteralPath 'untracked notes.txt' -Raw",
            "get-content -literalpath AGENTS.md -raw",
            "cat -- AGENTS.md",
            f"cat -- '{self.root / 'untracked notes.txt'}'",
        ):
            self.assertEqual(self.shell(command), {})
        for command in (
            "Get-Content -Path *.md", "Get-Content -LiteralPath AGENTS.md | Invoke-Expression",
            "Get-Content -LiteralPath AGENTS.md > changed.md", "cat -- AGENTS.md; sh evil.sh",
            "cat -- .", "cat -- missing.txt", "cat -- ../outside.txt", "cat -- AGENTS.md:stream",
            "cat -- AGENTS.md --output=changed.md", "Get-Content -LiteralPath AGENTS.md -Wait",
        ):
            self.assert_denied(self.shell(command))

    def test_exact_read_commands_reject_linked_file_or_directory(self):
        self.block()
        (self.root / "notes.md").write_text("Ordinary file", encoding="utf-8")
        # Use the platform-link predicate directly so Windows CI doesn't need
        # Developer Mode or symlink creation privileges to test rejection.
        original = hooks._linked
        with mock.patch.object(hooks, "_linked", side_effect=lambda path: path.name == "notes.md" or original(path)):
            self.assert_denied(self.shell("cat -- notes.md"))
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "notes.md").write_text("Ordinary file", encoding="utf-8")
        with mock.patch.object(hooks, "_linked", side_effect=lambda path: path.name == "nested" or original(path)):
            self.assert_denied(self.shell("Get-Content -LiteralPath nested/notes.md"))

    def test_git_diagnostic_grammar_disables_executable_diff_helpers(self):
        self.block()
        for command in (
            "git --no-pager status --porcelain=v1 --untracked-files=all",
            "git --no-pager diff --no-ext-diff --no-textconv",
            "git --no-pager diff --no-ext-diff --no-textconv --cached -- notes.md",
            f"git --no-pager -C '{self.root}' diff --no-ext-diff --no-textconv -- notes.md",
        ):
            self.assertEqual(self.shell(command), {})
        for command in (
            "git diff", "git --no-pager diff", "git --no-pager -c diff.external=evil diff",
            "git --no-pager diff --no-ext-diff --no-textconv --output=draft.md",
            "git --no-pager diff --no-ext-diff --no-textconv -- ../elsewhere",
            "git --no-pager status --porcelain=v1 --untracked-files=all; git reset --hard",
            "git --no-pager push --force", "git --no-pager config --global core.hooksPath none",
        ):
            self.assert_denied(self.shell(command))

    def test_stop_does_not_infer_upload_paths_or_claim_completion(self):
        self.assertEqual(self.call("Stop"), {})
        self.runtime.checkpoint.assert_called_once_with(
            self.root, message="Seedbag conversation checkpoint", paths=None,
            incomplete=True, session="test-session")

    def test_blocked_stop_has_one_continuation_then_honest_warning(self):
        self.runtime.checkpoint.side_effect = core.Error("intended_file_paths_required")
        first = self.call("Stop", stop_hook_active=False)
        self.assertEqual(first["decision"], "block")
        self.assertIn("explicit intended paths", first["reason"])
        second = self.call("Stop", stop_hook_active=True)
        self.assertNotIn("decision", second)
        self.assertIn("Do not claim synchronization", second["systemMessage"])
        self.runtime.begin.assert_not_called()

    def test_stop_rejects_unverified_success_like_object(self):
        self.runtime.checkpoint.return_value = {"ok": True, "state": "publishing"}
        self.assertEqual(self.call("Stop")["decision"], "block")

    def test_git_deadline_bounds_network_call_and_resets_after_hook(self):
        with mock.patch.object(git.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
            with git.operation_deadline(1):
                git._git(self.root, "ls-remote", "origin")
                self.assertGreater(run.call_args.kwargs["timeout"], 0)
                self.assertLessEqual(run.call_args.kwargs["timeout"], 1)
            git._git(self.root, "status")
            self.assertEqual(run.call_args.kwargs["timeout"], 120)

    def test_expired_git_deadline_emits_deny_before_host_timeout(self):
        def expired(*args, **kwargs):
            with git.operation_deadline(-1):
                return git._git(self.root, "ls-remote", "origin")
        self.runtime.require_ready.side_effect = expired
        with mock.patch.object(git.subprocess, "run") as run:
            self.assert_denied(self.shell("python arbitrary.py"))
            run.assert_not_called()

    def test_nested_deadline_cannot_extend_outer_budget(self):
        with mock.patch.object(git.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
            with git.operation_deadline(1):
                with git.operation_deadline(999):
                    git._git(self.root, "ls-remote", "origin")
                    self.assertLessEqual(run.call_args.kwargs["timeout"], 1)

    def test_real_git_descendant_cannot_hold_deadline_open_through_pipes(self):
        started = self.root / "child-started"
        finished = self.root / "child-finished"
        child = self.root / "deadline-child.py"
        child.write_text(
            "from pathlib import Path\nimport time\n"
            f"Path({str(started)!r}).write_text('started')\n"
            "time.sleep(3)\n"
            f"Path({str(finished)!r}).write_text('finished')\n", encoding="utf-8")
        # The descendant may release its process a moment after the finish
        # marker. Its cwd must not hold the disposable directory open on Windows.
        alias = ("!cd " + shlex.quote(self.root.parent.as_posix()) + " && "
                 + shlex.quote(Path(sys.executable).as_posix()) + " " + shlex.quote(child.as_posix()))
        env = os.environ.copy()
        env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_COUNT": "0"})
        clock_start = time.monotonic()
        try:
            with self.assertRaises(core.Error):
                with git.operation_deadline(0.6):
                    git._git(self.root, "-c", "alias.seedbagdeadline=" + alias, "seedbagdeadline", env=env)
            elapsed = time.monotonic() - clock_start
            self.assertTrue(started.exists(), "The real descendant must start for this regression test")
            self.assertLess(elapsed, 2.0, "A descendant-held stream defeated the 0.6-second Git budget")
        finally:
            # This fixture's child finishes itself; don't leave a background
            # process alive or use broad process-name termination in a test.
            until = time.monotonic() + 5
            while started.exists() and not finished.exists() and time.monotonic() < until:
                time.sleep(0.05)
            if started.exists():
                self.assertTrue(finished.exists(), "Synthetic child did not complete its bounded lifetime")

    def test_git_tempfile_streams_preserve_binary_stdin_and_byte_results(self):
        payload = b"\x00\xff\nSeedbag binary fixture\r\n"
        expected = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\x00" + payload).hexdigest()
        result = git._git(self.root, "hash-object", "--stdin", input_bytes=payload)
        self.assertEqual(result.stdout, expected.encode() + b"\n")
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.returncode, 0)
        failed = git._git(self.root, "--seedbag-invalid-option", allow_failure=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIsInstance(failed.stderr, bytes)
        self.assertIn(b"unknown option", failed.stderr)


class HookInstallationTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(os.environ.get("SEEDBAG_TEST_WORK", Path.cwd() / "work")).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="seedbag-hook-install-new-", dir=workspace)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.env = os.environ.copy()
        updates = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_COUNT": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        removed = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
        self.env.update(updates)
        for name in removed:
            self.env.pop(name, None)
        environment = scoped_environment(updates, removed)
        environment.__enter__()
        self.addCleanup(environment.__exit__, None, None, None)
        templates = self.root / "templates"
        templates.mkdir()
        self.git("init", "--template=" + str(templates))
        (self.root / "seedbag.py").write_text("# synthetic launcher\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("/.codex/hooks.json\n", encoding="utf-8")
        self.directory = self.root / ".codex"
        self.directory.mkdir()
        self.target = self.directory / "hooks.json"

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], env=self.env,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return result

    def test_preparation_preserves_other_hooks_and_never_trusts(self):
        existing = {"description": "Owner configuration", "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "owner-hook"}]}]}}
        self.target.write_text(json.dumps(existing), encoding="utf-8")
        config = self.directory / "config.toml"
        config.write_text('model = "owner-model"\n', encoding="utf-8")
        before_config = config.read_bytes()
        result = hooks.install(self.root)
        document = json.loads(self.target.read_bytes())
        self.assertEqual(document["description"], existing["description"])
        self.assertEqual(document["hooks"]["PreToolUse"][0], existing["hooks"]["PreToolUse"][0])
        self.assertEqual(result["state"], "prepared_requires_host_trust")
        self.assertFalse(result["active_verified"])
        self.assertFalse(result["setup_complete"])
        self.assertFalse(result["protected_work_ready"])
        self.assertIn("host_dispatched_tool_gate_verified", result["pending_requirements"])
        self.assertFalse(result["trust_changed"])
        self.assertEqual(before_config, config.read_bytes())
        self.assertEqual(set(document["hooks"]), set(hooks.EVENTS))
        self.assertNotIn("SessionEnd", document["hooks"])

    def test_repeat_installation_is_byte_identical(self):
        hooks.install(self.root)
        before = self.target.read_bytes()
        result = hooks.install(self.root)
        self.assertFalse(result["changed"])
        self.assertEqual(before, self.target.read_bytes())

    def test_existing_hook_definitions_require_review_before_replacement(self):
        hooks.install(self.root)
        document = json.loads(self.target.read_bytes())
        document["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "old-device-python previous-checkout"
        self.target.write_text(json.dumps(document), encoding="utf-8")
        before = self.target.read_bytes()
        with self.assertRaisesRegex(core.Error, "Different Seedbag"):
            hooks.install(self.root)
        self.assertEqual(before, self.target.read_bytes())

    def test_inline_config_hooks_are_preserved_without_second_representation(self):
        config = self.directory / "config.toml"
        config.write_text('[hooks]\nSessionStart = []\n', encoding="utf-8")
        before = config.read_bytes()
        with self.assertRaisesRegex(core.Error, "inline hooks"):
            hooks.install(self.root)
        self.assertFalse(self.target.exists())
        self.assertEqual(before, config.read_bytes())

    def test_invalid_existing_json_is_not_overwritten(self):
        self.target.write_bytes(b"{invalid")
        with self.assertRaisesRegex(core.Error, "invalid"):
            hooks.install(self.root)
        self.assertEqual(self.target.read_bytes(), b"{invalid")

    def test_device_specific_commands_cannot_be_prepared_for_shared_file(self):
        (self.root / ".gitignore").write_text("", encoding="utf-8")
        with self.assertRaisesRegex(core.Error, "ignored and untracked"):
            hooks.install(self.root)
        (self.root / ".gitignore").write_text("/.codex/hooks.json\n", encoding="utf-8")
        self.target.write_text('{"hooks": {}}', encoding="utf-8")
        self.git("add", "--force", ".codex/hooks.json")
        before = self.target.read_bytes()
        with self.assertRaisesRegex(core.Error, "ignored and untracked"):
            hooks.install(self.root)
        self.assertEqual(before, self.target.read_bytes())

    def test_generated_platform_command_runs_from_subdirectory(self):
        # Exercise the actual generated shell command and JSON stdin contract,
        # without needing an account/model or modifying global host config.
        script = (
            "import json, pathlib, sys\n"
            "event = json.load(sys.stdin)\n"
            "assert sys.argv[1:] == ['--root', str(pathlib.Path(__file__).resolve().parent), 'hook']\n"
            "print(json.dumps({'hookSpecificOutput': {'hookEventName': event['hook_event_name'], 'permissionDecision': 'deny', 'permissionDecisionReason': 'fixture blocked'}}))\n"
        )
        (self.root / "seedbag.py").write_text(script, encoding="utf-8")
        hooks.install(self.root)
        handler = json.loads(self.target.read_bytes())["hooks"]["PreToolUse"][0]["hooks"][0]
        subdirectory = self.root / "nested"
        subdirectory.mkdir()
        command = (["powershell", "-NoProfile", "-NonInteractive", "-Command", handler["commandWindows"]]
                   if os.name == "nt" else ["sh", "-c", handler["command"]])
        result = subprocess.run(command, input=json.dumps({"hook_event_name": "PreToolUse"}).encode(),
                                cwd=subdirectory, env=self.env, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")


class HookRuntimeIntegrationTests(unittest.TestCase):
    def test_host_session_matches_implicit_cli_guard_and_released_stop(self):
        """Real ledger/Git/claim operations, no mocked synchronization results."""
        sys.path.insert(0, str(PACKAGE))
        import seedbag
        import seedbag_context as views
        import seedbag_sync as sync
        workspace = Path(os.environ.get("SEEDBAG_TEST_WORK", Path.cwd() / "work")).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="seedbag-hook-runtime-new-", dir=workspace) as directory:
            base = Path(directory).resolve()
            root = base / "project"
            remote = base / "remote.git"
            empty = base / "empty-templates"
            empty.mkdir()
            env = os.environ.copy()
            updates = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_COUNT": "0",
                       "CODEX_THREAD_ID": "test-host-session", "PYTHONDONTWRITEBYTECODE": "1"}
            removed = ("SEEDBAG_SESSION_ID", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
            env.update(updates)
            for key in removed:
                env.pop(key, None)
            with scoped_environment(updates, removed):
                def command(where, *args):
                    result = subprocess.run(["git", "-c", "init.templateDir=" + str(empty), "-C", str(where), *args],
                                            capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                command(base, "init", "--bare", "--initial-branch=main", str(remote))
                seedbag.plant(root, "Hook integration fixture", remote.as_posix(), use_git=False)
                command(root, "init", "--initial-branch=main")
                command(root, "config", "--local", "user.name", "Seedbag fixture")
                command(root, "config", "--local", "user.email", "fixture@example.invalid")
                command(root, "config", "--local", "commit.gpgsign", "false")
                command(root, "remote", "add", "origin", str(remote))
                sync.configure(root)
                sync.begin(root, setup=True)
                sync.checkpoint(root, "Initial fixture", paths=sync.status(root)["changed_paths"])
                event = {"hook_event_name": "SessionStart", "session_id": "test-host-session", "cwd": str(root)}
                begun = hooks.handle(root, event)
                self.assertIn("established", json.dumps(begun))
                before = core.load(root)
                core.apply(root, [{"op": "project.set", "purpose": "Saved after automatic session entry"}],
                           before["revision"], before["digest"])
                views.render(root)
                event.update(hook_event_name="PreToolUse", tool_name="apply_patch", tool_input={"command": "fixture patch"})
                self.assertIn("freshly verified", hooks.handle(root, event)["hookSpecificOutput"]["additionalContext"])
                event["hook_event_name"] = "Stop"
                self.assertEqual(hooks.handle(root, event)["decision"], "block")
                sync.checkpoint(root, "Save intended work", paths=sync.status(root)["changed_paths"])
                event["stop_hook_active"] = True
                self.assertEqual(hooks.handle(root, event), {})
                self.assertEqual(core.load(root)["state"]["project"]["purpose"], "Saved after automatic session entry")


if __name__ == "__main__":
    unittest.main()
