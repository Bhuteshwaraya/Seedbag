"""Scoped host configuration, concurrency, and honest readiness regressions."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest import mock

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "runtime"))
import seedbag_codex as codex
import seedbag_core as core
import seedbag_hooks as hooks


class FakeServer:
    def __init__(self, root, trusted=True):
        self.root = root
        self.config_path = root.parent / "synthetic-user-config.toml"
        self.config = {"model": "preserve-model", "projects": {}, "hooks": {"state": {"unrelated": {"enabled": False}}}}
        if trusted:
            self.config["projects"][str(root)] = {"trust_level": "trusted", "unrelated": "keep"}
        self.version = 1
        self.requests = []
        self.writes = []
        self.change_listing = None
        self.change_config = None
        self.before_write = None
        self.write_error = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def request(self, method, params):
        self.requests.append((method, copy.deepcopy(params)))
        if method == "config/read":
            result = {"config": {}, "layers": [{
                "name": {"type": "user", "file": str(self.config_path), "profile": None},
                "version": f"v{self.version}", "config": copy.deepcopy(self.config),
            }]}
            if self.change_config:
                self.change_config(result)
            return result
        if method == "hooks/list":
            definitions = []
            if any(codex._same_path(path, self.root) and entry.get("trust_level") == "trusted"
                   for path, entry in self.config["projects"].items()):
                for index, (event, (wire, snake)) in enumerate(codex.EVENTS.items()):
                    handler = hooks._handler(self.root, Path(sys.executable).resolve(), event)
                    source = str(self.root / ".codex" / "hooks.json")
                    key = f"{source}:{snake}:0:0"
                    digest = f"sha256:{index + 1:064x}"
                    definitions.append({
                        "key": key, "eventName": wire, "handlerType": "command",
                        "command": handler["commandWindows"] if os.name == "nt" else handler["command"],
                        "async": False, "matcher": None, "timeoutSec": 50,
                        "statusMessage": handler["statusMessage"], "additionalContextLimit": None,
                        "sourcePath": source, "source": "project", "pluginId": None,
                        "displayOrder": index, "enabled": True, "isManaged": False,
                        "currentHash": digest,
                        "trustStatus": "trusted" if self.config["hooks"]["state"].get(key, {}).get("trusted_hash") == digest else "untrusted",
                    })
            result = {"data": [{"cwd": str(self.root), "hooks": definitions, "warnings": [], "errors": []}]}
            if self.change_listing:
                self.change_listing(result)
            return result
        if method != "config/batchWrite":
            raise AssertionError(method)
        if self.before_write:
            self.before_write()
        if self.write_error or params["expectedVersion"] != f"v{self.version}":
            raise core.Error("Synthetic concurrent configuration change")
        self.assert_scoped(params)
        self.writes.append(copy.deepcopy(params))
        for edit in params["edits"]:
            if edit["keyPath"].startswith("projects."):
                key = json.loads(edit["keyPath"][len("projects."):-len(".trust_level")])
                self.config["projects"].setdefault(key, {})["trust_level"] = edit["value"]
            else:
                key = json.loads(edit["keyPath"][len("hooks.state."):-len(".trusted_hash")])
                self.config["hooks"]["state"].setdefault(key, {})["trusted_hash"] = edit["value"]
        self.version += 1
        return {"status": "ok", "filePath": str(self.config_path), "version": f"v{self.version}", "overriddenMetadata": None}

    def assert_scoped(self, params):
        assert params["filePath"] == str(self.config_path)
        assert params["reloadUserConfig"] is True
        assert all(edit["mergeStrategy"] == "replace" for edit in params["edits"])
        assert all(edit["keyPath"].startswith(("projects.", "hooks.state.")) for edit in params["edits"])


class CodexConfigurationTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(os.environ.get("SEEDBAG_TEST_WORK", Path.cwd() / "work")).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="seedbag-codex-test-", dir=workspace)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "seedbag.py").write_text("# synthetic launcher\n", encoding="utf-8")
        runtime = self.root / ".seedbag" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "seedbag_hooks.py").write_text("# synthetic runtime\n", encoding="utf-8")
        (self.root / ".codex").mkdir()
        self.target = self.root / ".codex" / "hooks.json"
        self.document = {"hooks": {event: [{"hooks": [hooks._handler(self.root, Path(sys.executable).resolve(), event)]}]
                                   for event in codex.EVENTS}}
        self.save_hooks()
        self.server = FakeServer(self.root)
        self.factory = mock.patch.object(codex, "_Server", return_value=self.server).start()
        self.addCleanup(mock.patch.stopall)

    def save_hooks(self):
        self.target.write_text(json.dumps(self.document), encoding="utf-8")

    def configure(self, **kwargs):
        return codex.configure(self.root, codex=sys.executable, **kwargs)

    def test_default_probe_never_writes_or_claims_activation(self):
        result = self.configure()
        self.assertEqual(result["callbacks_discovered"], 4)
        self.assertEqual(self.server.writes, [])
        self.assertFalse(result["configuration_trusted"])
        for field in ("active_verified", "protected_work_ready", "setup_complete"):
            self.assertIs(result[field], False)
        self.assertTrue(self.server.closed)

    def test_untrusted_additional_project_settings_are_not_implicitly_approved(self):
        self.server.config["projects"] = {}
        config = self.root / ".codex" / "config.toml"
        original = b'[mcp_servers.extra]\ncommand = "review-this-separately"\n'
        config.write_bytes(original)
        with self.assertRaisesRegex(core.Error, "additional Codex settings"):
            self.configure(trust_reviewed=True)
        self.assertEqual(self.server.writes, [])
        self.assertEqual(config.read_bytes(), original)

    def test_already_trusted_additional_settings_are_preserved(self):
        config = self.root / ".codex" / "config.toml"
        original = b'model = "existing-selection"\n'
        config.write_bytes(original)
        result = self.configure(trust_reviewed=True)
        self.assertTrue(result["configuration_trusted"])
        self.assertEqual(config.read_bytes(), original)
        self.assertTrue(all(edit["keyPath"].startswith("hooks.state.")
                            for write in self.server.writes for edit in write["edits"]))

    def test_reviewed_trust_changes_only_four_exact_hashes_and_preserves_settings(self):
        result = self.configure(trust_reviewed=True)
        self.assertTrue(result["configuration_trusted"])
        self.assertFalse(result["active_verified"])
        self.assertFalse(result["setup_complete"])
        self.assertIn("future contexts", result["scope"])
        self.assertEqual(len(self.server.writes), 1)
        self.assertEqual(len(self.server.writes[0]["edits"]), 4)
        self.assertEqual(self.server.writes[0]["expectedVersion"], "v1")
        self.assertEqual(self.server.config["model"], "preserve-model")
        self.assertEqual(self.server.config["hooks"]["state"]["unrelated"], {"enabled": False})
        self.assertEqual(self.server.config["projects"][str(self.root)]["unrelated"], "keep")
        self.assertEqual(self.target.read_text(encoding="utf-8"), json.dumps(self.document))

    def test_new_project_trust_is_scoped_then_definitions_discovered_and_trusted(self):
        self.server.config["projects"] = {str(self.root.parent): {"trust_level": "untrusted"}}
        result = self.configure(trust_reviewed=True)
        self.assertTrue(result["configuration_trusted"])
        self.assertEqual(len(self.server.writes), 2)
        first, second = self.server.writes
        self.assertEqual(first["edits"], [{
            "keyPath": "projects." + json.dumps(os.path.normcase(str(self.root))) + ".trust_level",
            "value": "trusted", "mergeStrategy": "replace",
        }])
        self.assertEqual(second["expectedVersion"], "v2")
        self.assertEqual(self.server.config["projects"][str(self.root.parent)]["trust_level"], "untrusted")

    def test_untrusted_project_readonly_probe_does_not_change_project_trust(self):
        self.server.config["projects"] = {}
        result = self.configure()
        self.assertFalse(result["project_trusted"])
        self.assertEqual(result["callbacks_discovered"], 0)
        self.assertEqual(self.server.writes, [])

    def test_already_trusted_configuration_is_idempotent_but_not_live_proof(self):
        self.configure(trust_reviewed=True)
        self.server.writes.clear()
        result = self.configure(trust_reviewed=True)
        self.assertTrue(result["configuration_trusted"])
        self.assertFalse(result["protected_work_ready"])
        self.assertEqual(self.server.writes, [])

    def test_unrelated_callbacks_are_never_trusted(self):
        def extra(result):
            result["data"][0]["hooks"].append({"statusMessage": "Other owner's callback", "command": "other-command"})
        self.server.change_listing = extra
        self.configure(trust_reviewed=True)
        self.assertEqual(len(self.server.writes[0]["edits"]), 4)

    def test_modified_local_callback_or_matcher_is_rejected_before_server_start(self):
        for mutation in (lambda group: group["hooks"][0].update(command="arbitrary command"),
                         lambda group: group.update(matcher="apply_patch"),
                         lambda group: group["hooks"][0].update(timeout=90)):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.document)
                mutation(self.document["hooks"]["PreToolUse"][0])
                self.save_hooks()
                with self.assertRaises(core.Error):
                    self.configure(trust_reviewed=True)
                self.document = original
        self.factory.assert_not_called()
        self.assertEqual(self.server.writes, [])

    def test_adversarial_host_metadata_never_receives_trust(self):
        cases = {
            "sourcePath": str(self.root / "elsewhere.json"), "source": "user",
            "key": 'another-hook".enabled', "command": "arbitrary command",
            "async": True, "matcher": "apply_patch", "isManaged": True,
            "enabled": False, "timeoutSec": 99, "additionalContextLimit": 0,
            "currentHash": "not-a-hash", "handlerType": "prompt", "pluginId": "other-plugin",
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                self.server.change_listing = lambda result, k=key, v=value: result["data"][0]["hooks"][0].update({k: v})
                with self.assertRaises(core.Error):
                    self.configure(trust_reviewed=True)
                self.assertEqual(self.server.writes, [])

    def test_duplicate_missing_wrong_cwd_and_discovery_errors_are_rejected(self):
        for mutation in (
            lambda result: result["data"][0]["hooks"].append(copy.deepcopy(result["data"][0]["hooks"][0])),
            lambda result: result["data"][0]["hooks"].pop(),
            lambda result: result["data"][0].update(cwd=str(self.root.parent)),
            lambda result: result["data"][0].update(errors=[{"message": "private-value"}]),
            lambda result: result.update(data=[]),
        ):
            with self.subTest(mutation=mutation):
                self.server.change_listing = mutation
                with self.assertRaises(core.Error) as caught:
                    self.configure(trust_reviewed=True)
                self.assertNotIn("private-value", str(caught.exception))
                self.assertEqual(self.server.writes, [])

    def test_missing_or_disabled_versioned_user_layer_refuses_writes(self):
        for mutation in (
            lambda result: result.update(layers=[]),
            lambda result: result["layers"][0].pop("version"),
            lambda result: result["layers"][0].update(disabledReason="managed private setting"),
            lambda result: result["layers"][0]["name"].update(file="relative-config.toml"),
        ):
            with self.subTest(mutation=mutation):
                self.server.change_config = mutation
                with self.assertRaises(core.Error):
                    self.configure(trust_reviewed=True)
                self.assertEqual(self.server.writes, [])

    def test_concurrent_config_change_is_not_overwritten(self):
        def concurrent_change():
            self.server.version += 1
            self.server.config["model"] = "concurrent-owner-choice"
        self.server.before_write = concurrent_change
        with self.assertRaises(core.Error):
            self.configure(trust_reviewed=True)
        self.assertEqual(self.server.writes, [])
        self.assertEqual(self.server.config["model"], "concurrent-owner-choice")

    def test_changed_runtime_between_review_and_trust_is_rejected(self):
        def change(result):
            (self.root / "seedbag.py").write_text("# changed after review\n", encoding="utf-8")
        self.server.change_listing = change
        with self.assertRaisesRegex(core.Error, "files changed"):
            self.configure(trust_reviewed=True)
        self.assertEqual(self.server.writes, [])

    def test_changed_hash_during_readback_never_claims_ready(self):
        def change(result):
            if self.server.writes:
                result["data"][0]["hooks"][0]["currentHash"] = "sha256:" + "f" * 64
        self.server.change_listing = change
        with self.assertRaisesRegex(core.Error, "settings may already be saved"):
            self.configure(trust_reviewed=True)
        self.assertEqual(len(self.server.writes), 1)

    def test_partial_project_trust_reports_saved_state_without_blind_retry(self):
        self.server.config["projects"] = {}
        def change(result):
            if self.server.writes:
                result["data"][0]["hooks"][0]["enabled"] = False
        self.server.change_listing = change
        with self.assertRaisesRegex(core.Error, "settings may already be saved"):
            self.configure(trust_reviewed=True)
        self.assertEqual(len(self.server.writes), 1)

    def test_explicit_boolean_and_executable_required(self):
        for value in ("yes", 1, None):
            with self.assertRaises(core.Error):
                self.configure(trust_reviewed=value)
        with self.assertRaises(core.Error):
            codex.configure(self.root, codex=str(self.root / "missing-codex"))
        self.factory.assert_not_called()

    def test_linked_configuration_or_runtime_is_rejected(self):
        original = hooks._linked
        for target in (self.root / ".codex", self.root / ".seedbag", self.target,
                       self.root / ".seedbag" / "runtime" / "seedbag_hooks.py"):
            with self.subTest(target=target), mock.patch.object(hooks, "_linked", side_effect=lambda path: path == target or original(path)):
                with self.assertRaises(core.Error):
                    self.configure(trust_reviewed=True)
        self.factory.assert_not_called()


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(os.environ.get("SEEDBAG_TEST_WORK", Path.cwd() / "work")).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="seedbag-codex-protocol-", dir=workspace)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.script = self.root / "fake-server.py"
        self.real_popen = subprocess.Popen
        self.calls = []

    def server(self, response, timeout=2):
        self.script.write_text(
            "import json, sys, time\n"
            "for line in sys.stdin:\n"
            " request = json.loads(line)\n"
            " if 'id' not in request: continue\n"
            " if request['method'] == 'initialize':\n"
            "  print(json.dumps({'id':request['id'], 'result':{}}), flush=True)\n"
            " else:\n" + "\n".join("  " + line for line in response.splitlines()) + "\n",
            encoding="utf-8",
        )

        def launch(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return self.real_popen([sys.executable, "-u", str(self.script)], **kwargs)

        patch = mock.patch.object(codex.subprocess, "Popen", side_effect=launch)
        patch.start()
        self.addCleanup(patch.stop)
        return codex._Server(sys.executable, self.root, timeout=timeout)

    def test_short_lived_client_preserves_environment_and_binds_cwd(self):
        with self.server("print(json.dumps({'id':request['id'], 'result':{'ok':True}}), flush=True)") as server:
            self.assertEqual(server.request("config/read", {}), {"ok": True})
            process = server.process
        argv, options = self.calls[0]
        self.assertEqual(argv, [sys.executable, "app-server"])
        self.assertEqual(options["cwd"], self.root)
        self.assertNotIn("env", options)
        self.assertEqual(options["stderr"], subprocess.DEVNULL)
        self.assertIsNotNone(process.poll())

    def test_protocol_error_and_invalid_json_do_not_echo_private_text(self):
        for code in ("print(json.dumps({'id':request['id'], 'error':{'message':'private-token-value'}}), flush=True)",
                     "print('private-token-value', flush=True)"):
            with self.subTest(code=code), self.server(code) as server:
                with self.assertRaises(core.Error) as caught:
                    server.request("config/read", {})
                self.assertNotIn("private-token-value", str(caught.exception))

    def test_unresponsive_server_has_bounded_lifetime(self):
        start = time.monotonic()
        with self.server("time.sleep(5)", timeout=0.3) as server:
            with self.assertRaisesRegex(core.Error, "timed out"):
                server.request("config/read", {})
            process = server.process
        self.assertLess(time.monotonic() - start, 2)
        self.assertIsNotNone(process.poll())

    def test_oversized_unterminated_output_is_bounded(self):
        with self.server("print('x' * 4096, end='', flush=True)\ntime.sleep(1)") as server:
            with mock.patch.object(codex, "MAX_LINE", 1024), self.assertRaisesRegex(core.Error, "bounded protocol size"):
                server.request("config/read", {})


if __name__ == "__main__":
    unittest.main()
