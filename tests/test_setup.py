"""Deterministic setup preflight tests: no live authentication or networking."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("seedbag_setup", Path(__file__).resolve().parents[1] / "seedbag_setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
SECRET = "ghp_THIS_MUST_NEVER_APPEAR_IN_THE_REPORT"
REPOSITORY = "https://github.com/fixture-owner/fixture-repository.git"


class SetupTests(unittest.TestCase):
    def run_case(self, *, absent=(), token_code=0, api_code=0, api_error="", git_code=0, git_error="", network=True, api_body=None):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            stdout, stderr, code = "", "", 0
            if argv[1:] == ["--version"]:
                stdout = f"{argv[0]} version " + ("2.53.0.windows.3" if argv[0] == "git" else "2.97.0")
            elif argv[1:3] == ["auth", "token"]:
                self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
                self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
                code = token_code
            elif argv[1:3] == ["api", "user"]:
                self.assertEqual(argv[3:], ["--hostname", "github.com", "--jq", "{login: .login, id: .id}"])
                stdout = api_body if api_body is not None else json.dumps({"login": "Fixture-User", "id": 42})
                stderr, code = api_error, api_code
            elif argv[1] == "ls-remote":
                self.assertEqual(argv[2:], ["--", REPOSITORY, "HEAD"])
                stderr, code = git_error, git_code
            else:
                self.fail("Unexpected probe")
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["timeout"], 20)
            return subprocess.CompletedProcess(argv, code, stdout, stderr)

        with patch.object(setup.shutil, "which", side_effect=lambda name: None if name in absent else name), patch.object(setup.subprocess, "run", side_effect=fake_run):
            report = setup.preflight(network=network, repository=REPOSITORY if network else None)
        self.assertNotIn(SECRET, json.dumps(report))
        return report, calls

    def test_working_probes_still_require_assistant_judgment(self):
        report, calls = self.run_case()
        self.assertEqual(report["status"], "network_probes_passed")
        self.assertEqual(report["probes"]["github_api"]["account"], {"login": "Fixture-User", "id": 42})
        self.assertEqual(report["route_readiness"], "requires_assistant_judgment")
        self.assertIn("private_repository_push_permission", report["not_proven"])
        self.assertEqual(len(calls), 5)

    def action_ids(self, report):
        actions = report["recommended_actions"]
        self.assertTrue(all(set(action) == {"id", "message"} for action in actions))
        self.assertEqual(len(actions), len({action["id"] for action in actions}))
        for action in actions:
            self.assertEqual(action["message"], setup.ACTION_MESSAGES[action["id"]])
        return [action["id"] for action in actions]

    def test_success_recommends_reuse_and_remaining_private_verification_only(self):
        report, calls = self.run_case()
        self.assertEqual(self.action_ids(report), ["reuse_available_tools", "reuse_authenticated_connection",
                                                 "reuse_working_transport", "verify_private_publication"])
        self.assertEqual(len(calls), 5)

    def test_offline_actions_only_cover_observed_local_tools(self):
        for absent, expected in (((), ["reuse_available_tools"]), (("gh",), ["reuse_available_tools"]),
                                 (("git", "gh"), ["reuse_available_tools", "supply_missing_git"])):
            with self.subTest(absent=absent):
                report, calls = self.run_case(absent=absent, network=False)
                self.assertEqual(self.action_ids(report), expected)
                self.assertTrue(all(argv[1:] == ["--version"] for argv, _ in calls))
        with patch.object(setup.sys, "version_info", (3, 10, 14)):
            report, _ = self.run_case(network=False, absent=("git", "gh"))
        self.assertEqual(self.action_ids(report), ["supply_supported_python", "supply_missing_git"])

    def test_missing_git_and_gh_are_reports_not_crashes(self):
        for absent in (("git",), ("gh",), ("git", "gh")):
            with self.subTest(absent=absent):
                report, calls = self.run_case(absent=absent)
                self.assertEqual(report["status"], "probes_blocked" if "git" in absent else "probes_incomplete")
                self.assertEqual(report["assistant_connectors"], "unknown_not_inspected")
                for name in absent:
                    self.assertFalse(any(argv[0] == name for argv, _ in calls))

    def test_missing_gh_is_optional_for_local_probes(self):
        report, _ = self.run_case(absent=("gh",), network=False)
        self.assertEqual(report["status"], "local_probes_passed")
        self.assertEqual(report["probes"]["github_cli"]["status"], "missing")
        self.assertEqual(report["probes"]["github_api"]["status"], "not_inspected")
        self.assertEqual(report["assistant_connectors"], "unknown_not_inspected")
        self.assertEqual(report["route_readiness"], "requires_assistant_judgment")

    def test_unavailable_gh_leaves_successful_network_probe_incomplete(self):
        discovery = [("git", {"status": "available", "version": "2.53.0"}),
                     ("gh", {"status": "version_unrecognized", "version": None})]
        with patch.object(setup, "discover", side_effect=discovery), patch.object(setup, "run_probe", return_value=(subprocess.CompletedProcess([], 0, "", ""), None)) as run:
            report = setup.preflight(network=True, repository=REPOSITORY)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][1], "ls-remote")
        self.assertEqual(report["status"], "probes_incomplete")
        self.assertEqual(report["probes"]["github_api"]["status"], "cli_unavailable")
        self.assertEqual(report["probes"]["git_transport"]["status"], "read_succeeded")
        self.assertEqual(report["assistant_connectors"], "unknown_not_inspected")

    def test_missing_readable_auth_does_not_request_login(self):
        report, calls = self.run_case(token_code=1)
        self.assertEqual(report["probes"]["github_cli_auth"]["status"], "no_readable_cli_auth")
        self.assertEqual(report["probes"]["github_api"]["status"], "not_inspected_without_readable_cli_auth")
        self.assertFalse(any(argv[1:3] == ["api", "user"] for argv, _ in calls))

    def test_actual_http_401_is_bad_credentials(self):
        report, _ = self.run_case(api_code=1, api_error="gh: Bad credentials (HTTP 401) " + SECRET)
        self.assertEqual(report["probes"]["github_api"]["status"], "bad_credentials")

    def test_network_and_tls_failures_are_not_expired_auth(self):
        for message, category in (("connectex: forbidden socket " + SECRET, "network_access_blocked"),
                                  ("could not resolve host", "network_unavailable"),
                                  ("x509 certificate failure", "tls_failed"),
                                  ("unrecognized failure " + SECRET, "api_error_unknown")):
            with self.subTest(category=category):
                report, _ = self.run_case(api_code=1, api_error=message)
                self.assertEqual(report["probes"]["github_api"]["status"], category)

    def test_api_access_denial_and_rate_limits_are_not_credentials(self):
        for message, category in (("gh: Forbidden (HTTP 403) " + SECRET, "api_access_denied"),
                                  ("gh: Too many requests (HTTP 429)", "api_rate_limited"),
                                  ("gh: API rate limit exceeded (HTTP 403)", "api_rate_limited")):
            with self.subTest(category=category):
                report, _ = self.run_case(api_code=1, api_error=message)
                self.assertEqual(report["probes"]["github_api"]["status"], category)
                self.assertEqual(report["probes"]["github_cli_auth"]["status"], "credential_readable")

    def test_unreadable_ssh_key_outranks_publickey_failure(self):
        report, _ = self.run_case(git_code=128, git_error='Load key "private/path/' + SECRET + '": Permission denied\nPermission denied (publickey).')
        self.assertEqual(report["probes"]["git_transport"]["status"], "transport_access_blocked")
        self.assertEqual(report["probes"]["github_api"]["status"], "authenticated")

    def test_specific_transport_faults_preserve_credentials_and_never_emit_diagnostics(self):
        cases = (
            ('fatal: detected dubious ownership in repository at "' + SECRET + '"', "repository_ownership_untrusted", "verify_repository_ownership"),
            ("Host key verification failed. " + SECRET, "ssh_host_verification_failed", "verify_ssh_host"),
            ("WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! " + SECRET, "ssh_host_verification_failed", "verify_ssh_host"),
            ('Load key "' + SECRET + '": invalid format\nPermission denied (publickey).', "transport_key_invalid", "inspect_key_format"),
            ('Load key "' + SECRET + '": Permission denied\nPermission denied (publickey).', "transport_access_blocked", "verify_key_access"),
            ('error: cannot spawn git-credential-manager: No such file or directory ' + SECRET, "transport_helper_failed", "inspect_git_helper"),
            ('error: git-remote-https died of signal 11 ' + SECRET, "transport_helper_failed", "inspect_git_helper"),
            ('git-remote-https.exe access violation 0xC0000005 ' + SECRET, "transport_helper_failed", "inspect_git_helper"),
            ("fatal: unable to find remote helper for 'https' " + SECRET, "transport_helper_failed", "inspect_git_helper"),
        )
        for message, category, action in cases:
            with self.subTest(category=category, message=message):
                report, calls = self.run_case(git_code=128, git_error=message)
                self.assertEqual(report["probes"]["git_transport"]["status"], category)
                self.assertEqual(self.action_ids(report), ["reuse_available_tools", "reuse_authenticated_connection",
                                                          "preserve_credentials", action])
                self.assertEqual(len(calls), 5)
                self.assertNotIn(SECRET, json.dumps(report))

    def test_transport_categories_require_specific_evidence_and_service(self):
        for message in ("permission denied " + SECRET, "invalid format " + SECRET,
                        "cannot spawn unknown-tool " + SECRET, "helper output " + SECRET,
                        "git-remote-https reported an unknown failure " + SECRET):
            with self.subTest(message=message):
                self.assertEqual(setup.classify_error(message, "git"), "transport_error_unknown")
        self.assertEqual(setup.classify_error("Host key verification failed", "api"), "api_error_unknown")
        self.assertEqual(setup.classify_error("git-remote-https died of signal 11", "api"), "api_error_unknown")

    def test_specific_transport_categories_outrank_secondary_authentication_failures(self):
        for message, expected in (("Host key verification failed", "ssh_host_verification_failed"),
                                  ("fatal: detected dubious ownership in repository", "repository_ownership_untrusted"),
                                  ("git-remote-https died of signal 11", "transport_helper_failed")):
            self.assertEqual(setup.classify_error(message + "\nAuthentication failed\nPermission denied (publickey)", "git"), expected)

    def test_action_guidance_limits_repairs_and_avoids_protocol_switches(self):
        report, _ = self.run_case(git_code=128, git_error='Load key "' + SECRET + '": Permission denied')
        action = report["recommended_actions"][-1]
        self.assertEqual(action["id"], "verify_key_access")
        self.assertIn("intended user before", action["message"])
        self.assertIn("exact-file", action["message"])
        self.assertIn("approval route", action["message"])
        report, _ = self.run_case(git_code=128, git_error="connection timed out " + SECRET)
        action = report["recommended_actions"][-1]
        self.assertEqual(action["id"], "resolve_network_failure")
        self.assertIn("do not change the connection protocol automatically", action["message"])
        self.assertNotIn("SSH", action["message"])

    def test_api_failure_actions_distinguish_rejection_from_connection_faults(self):
        for message, expected in (("HTTP 401 Bad credentials", "renew_rejected_connection"),
                                  ("HTTP 403 Forbidden", "check_api_access"),
                                  ("HTTP 429 rate limit", "respect_api_rate_limit"),
                                  ("connectex forbidden socket", "resolve_network_access"),
                                  ("x509 certificate error", "verify_tls")):
            with self.subTest(expected=expected):
                report, calls = self.run_case(api_code=1, api_error=message + " " + SECRET)
                actions = self.action_ids(report)
                self.assertIn(expected, actions)
                self.assertEqual("renew_rejected_connection" in actions, expected == "renew_rejected_connection")
                self.assertEqual("preserve_credentials" in actions, expected != "renew_rejected_connection")
                self.assertEqual(len(calls), 5)

    def test_missing_cli_auth_recommends_inspection_without_automatic_login(self):
        for kwargs in ({"absent": ("gh",)}, {"token_code": 1}):
            report, calls = self.run_case(**kwargs)
            self.assertEqual(self.action_ids(report), ["reuse_available_tools", "inspect_existing_connection",
                                                     "reuse_working_transport", "verify_private_publication"])
            self.assertFalse(any(argv[1:3] == ["auth", "login"] or argv[1] == "config" for argv, _ in calls))

    def test_git_network_and_authentication_failures_differ(self):
        for message, status in (("ssh: connect to host ssh.github.com port 443: Permission denied", "network_access_blocked"),
                                ("Permission denied (publickey)", "transport_authentication_failed"),
                                ("unexpected failure " + SECRET, "transport_error_unknown")):
            with self.subTest(status=status):
                report, _ = self.run_case(git_code=128, git_error=message)
                self.assertEqual(report["probes"]["git_transport"]["status"], status)

    def test_offline_only_discovers_versions(self):
        report, calls = self.run_case(network=False)
        self.assertEqual(report["mode"], "offline")
        self.assertIsNone(report["repository"])
        self.assertTrue(all(argv[1:] == ["--version"] for argv, _ in calls))
        self.assertEqual(report["probes"]["github_api"]["status"], "not_inspected")

    def test_transport_environment_preserves_config(self):
        inherited = {"GIT_SSH_COMMAND": "shared-ssh-config", "GH_HOST": "other.example", "GIT_CONFIG_COUNT": "1",
                     "GIT_CONFIG_KEY_0": "url.git@github.com:.insteadOf", "GIT_CONFIG_VALUE_0": "https://github.com/"}
        with patch.dict(os.environ, inherited):
            before = os.environ.copy()
            _, calls = self.run_case()
            self.assertEqual(dict(os.environ), before)
        for _, kwargs in calls:
            self.assertTrue(all(kwargs["env"][key] == value for key, value in inherited.items()))
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(kwargs["env"]["GH_PROMPT_DISABLED"], "1")

    def test_invalid_identity_body_is_not_reprinted(self):
        for body in (SECRET, json.dumps({"login": SECRET, "id": 42}), json.dumps({"login": "Fixture", "id": True}), json.dumps({"login": "Fixture", "id": 42, "token": SECRET})):
            report, _ = self.run_case(api_body=body)
            self.assertEqual(report["probes"]["github_api"]["status"], "identity_response_invalid")

    def test_timeout_and_execution_errors_never_emit_exception(self):
        for exception, category in ((subprocess.TimeoutExpired([SECRET], 20, output=SECRET, stderr=SECRET), "timeout"),
                                    (FileNotFoundError(SECRET), "missing"), (PermissionError(SECRET), "executable_access_blocked"),
                                    (OSError(SECRET), "execution_error")):
            with patch.object(setup.subprocess, "run", side_effect=exception):
                result, error = setup.run_probe(["git", "--version"], {}, 20)
            self.assertIsNone(result)
            self.assertEqual(error, category)
            self.assertNotIn(SECRET, error)

    def test_old_python_is_reported_as_unsupported(self):
        with patch.object(setup.sys, "version_info", (3, 10, 14)):
            report, _ = self.run_case(network=False)
        self.assertEqual(report["probes"]["python"]["status"], "unsupported")
        self.assertEqual(report["status"], "probes_blocked")

    def test_unrecognized_tool_output_is_not_reprinted(self):
        with patch.object(setup.shutil, "which", return_value="git"), patch.object(setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, SECRET, SECRET)):
            _, report = setup.discover("git", {}, 20)
        self.assertEqual(report, {"status": "version_unrecognized", "version": None})

    def test_successful_read_does_not_fail_on_stderr_warning(self):
        report, _ = self.run_case(git_error="Load key unused-identity: Permission denied " + SECRET)
        self.assertEqual(report["probes"]["git_transport"]["status"], "read_succeeded")

    def test_invalid_timeout_is_rejected_before_probes(self):
        for value in ("0", "121", "-1", "1.5", SECRET):
            output = io.StringIO()
            with contextlib.redirect_stderr(output), self.assertRaises(SystemExit), patch.object(setup.subprocess, "run") as run:
                setup.main(["--timeout", value])
            run.assert_not_called()
            self.assertNotIn(SECRET, output.getvalue())

    def test_url_allowlist_rejects_credentials_and_arbitrary_targets(self):
        for url in ("http://github.com/a/b", "https://evil.example/a/b", "https://github.com.evil/a/b",
                    "https://user:" + SECRET + "@github.com/a/b", "https://github.com:443/a/b",
                    "https://github.com/a/b?token=" + SECRET, "https://github.com/a/b#fragment", "https://github.com/a/..",
                    "https://github.com/a/%2e%2e", "https://github.com/a/b/c", "https://github.com/a/b\\c", "https://github.com/a/b\n"):
            with self.subTest(url=url):
                output = io.StringIO()
                with contextlib.redirect_stderr(output), self.assertRaises(SystemExit), patch.object(setup.subprocess, "run") as run:
                    setup.main(["--network", "--repository", url])
                run.assert_not_called()
                self.assertNotIn(SECRET, output.getvalue())
        self.assertEqual(setup.repository_url(REPOSITORY), REPOSITORY)

    def test_network_requires_explicit_repository_before_any_probe(self):
        output = io.StringIO()
        with patch.object(setup.subprocess, "run") as run, patch.object(setup.shutil, "which") as which:
            with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as error:
                setup.main(["--network"])
            self.assertEqual(error.exception.code, 2)
            self.assertIn(setup.MISSING_REPOSITORY, output.getvalue())
            with self.assertRaisesRegex(setup.argparse.ArgumentTypeError, "explicit --repository"):
                setup.preflight(network=True)
            run.assert_not_called()
            which.assert_not_called()

    def test_cli_default_and_offline_exit_zero_with_single_json(self):
        for args in ([], ["--offline"]):
            output = io.StringIO()
            with patch.object(setup.shutil, "which", return_value=None), patch.object(setup.subprocess, "run") as run, contextlib.redirect_stdout(output):
                self.assertEqual(setup.main(args), 0)
            run.assert_not_called()
            self.assertEqual(len(output.getvalue().splitlines()), 1)
            self.assertEqual(json.loads(output.getvalue())["mode"], "offline")
            self.assertIsNone(json.loads(output.getvalue())["repository"])


if __name__ == "__main__":
    unittest.main()
