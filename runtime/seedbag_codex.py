"""Review-scoped Codex configuration through its supported app-server API.

This prepares future project-bound contexts. It starts no model turn and cannot
certify that a different, already running conversation intercepts its tools.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import seedbag_core as core
import seedbag_hooks as hooks

EVENTS = {
    "SessionStart": ("sessionStart", "session_start"),
    "UserPromptSubmit": ("userPromptSubmit", "user_prompt_submit"),
    "PreToolUse": ("preToolUse", "pre_tool_use"),
    "Stop": ("stop", "stop"),
}
MAX_OUTPUT = 8 * 1024 * 1024
MAX_LINE = 2 * 1024 * 1024


def _same_path(value, expected):
    return isinstance(value, str) and Path(value).is_absolute() and Path(value).resolve() == expected


class _Server:
    """A bounded, short-lived configuration client; stderr is never exposed."""

    def __init__(self, executable, root, timeout=40):
        self.end = time.monotonic() + timeout
        self.serial = 0
        self.pending = b""
        self.total = 0
        self.directory = tempfile.TemporaryDirectory(prefix="seedbag-codex-rpc-")
        self.output = None
        self.reader = None
        self.process = None
        try:
            path = Path(self.directory.name) / "responses.jsonl"
            self.output = path.open("wb", buffering=0)
            self.reader = path.open("rb", buffering=0)
            self.process = subprocess.Popen(
                [str(executable), "app-server"], cwd=root, stdin=subprocess.PIPE,
                stdout=self.output, stderr=subprocess.DEVNULL, bufsize=0,
            )
            self.request("initialize", {
                "clientInfo": {"name": "seedbag_project_configuration", "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
            self._send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _remaining(self):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise core.Error("Codex configuration probe timed out; activation remains unverified")
        return remaining

    def _send(self, document):
        encoded = (json.dumps(document, ensure_ascii=True) + "\n").encode("utf-8")
        if len(encoded) > 64 * 1024:
            raise core.Error("Codex configuration request exceeded the bounded protocol size")
        outcome = []
        completed = threading.Event()

        def write():
            try:
                remaining = memoryview(encoded)
                while remaining:
                    count = self.process.stdin.write(remaining)
                    if not count:
                        raise OSError("closed protocol input")
                    remaining = remaining[count:]
                self.process.stdin.flush()
            except (OSError, ValueError):
                outcome.append(False)
            finally:
                completed.set()

        threading.Thread(target=write, daemon=True).start()
        if not completed.wait(self._remaining()):
            raise core.Error("Codex configuration probe timed out; activation remains unverified")
        if outcome:
            raise core.Error("Codex configuration connection closed; activation remains unverified")

    def request(self, method, params):
        self.serial += 1
        identity = self.serial
        self._send({"id": identity, "method": method, "params": params})
        while True:
            self._remaining()
            chunk = self.reader.read(65536)
            if chunk:
                self.total += len(chunk)
                self.pending += chunk
                if self.total > MAX_OUTPUT:
                    raise core.Error("Codex configuration response exceeded the bounded protocol size")
                while b"\n" in self.pending:
                    line, self.pending = self.pending.split(b"\n", 1)
                    if len(line) > MAX_LINE:
                        raise core.Error("Codex configuration response exceeded the bounded protocol size")
                    try:
                        value = json.loads(line)
                    except (ValueError, UnicodeDecodeError) as exc:
                        raise core.Error("Codex returned an invalid configuration response") from exc
                    if not isinstance(value, dict):
                        raise core.Error("Codex returned an invalid configuration response")
                    if value.get("id") == identity:
                        if "error" in value or "result" not in value:
                            raise core.Error("Codex refused the configuration operation; inspect host permissions and retry the read-only probe")
                        return value["result"]
                if len(self.pending) > MAX_LINE:
                    raise core.Error("Codex configuration response exceeded the bounded protocol size")
            elif self.process.poll() is not None:
                raise core.Error("Codex configuration server exited; activation remains unverified")
            else:
                time.sleep(min(0.02, self._remaining()))

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    try:
                        self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
            if self.process.stdin is not None:
                self.process.stdin.close()
        for stream in (self.reader, self.output):
            if stream is not None:
                stream.close()
        # No pipe reader is waiting for inherited handles from server descendants.
        try:
            self.directory.cleanup()
        except OSError:
            pass


def _snapshot(root):
    selected = [root / "seedbag.py", root / ".codex" / "hooks.json"]
    config = root / ".codex" / "config.toml"
    if config.exists() or hooks._linked(config):
        selected.append(config)
    runtime = root / ".seedbag" / "runtime"
    if not runtime.is_dir() or hooks._linked(runtime.parent) or hooks._linked(runtime):
        raise core.Error("Codex configuration requires a planted project runtime")
    selected.extend(sorted(runtime.glob("seedbag_*.py")))
    if not selected[2:]:
        raise core.Error("Codex configuration requires a planted project runtime")
    result = {}
    for path in selected:
        if hooks._linked(path) or not path.is_file():
            raise core.Error("Refusing missing or linked project configuration/runtime files")
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _definitions(root):
    target = root / ".codex" / "hooks.json"
    if hooks._linked(target.parent) or hooks._linked(target):
        raise core.Error("Refusing linked project hook configuration")
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise core.Error("Prepare and review this project's hook definitions before configuring Codex") from exc
    if not isinstance(document, dict) or not isinstance(document.get("hooks"), dict):
        raise core.Error("Project hook configuration has an unsupported shape")
    result = {}
    for event in EVENTS:
        groups = document["hooks"].get(event)
        if not isinstance(groups, list):
            raise core.Error("Project hook configuration lacks the four generated Seedbag callbacks")
        expected = hooks._handler(root, Path(sys.executable).resolve(), event)
        found = []
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise core.Error("Project hook matcher has an unsupported shape")
            for handler_index, handler in enumerate(group["hooks"]):
                if not isinstance(handler, dict):
                    raise core.Error("Project hook handler has an unsupported shape")
                if str(handler.get("statusMessage", "")).startswith(hooks.STATUS_PREFIX):
                    if handler != expected or set(group) != {"hooks"}:
                        raise core.Error("Seedbag callback differs from this runtime's generated definition; review before changing trust")
                    found.append((group_index, handler_index, expected))
        if len(found) != 1:
            raise core.Error("Project hook configuration must contain exactly one generated Seedbag callback per event")
        result[event] = found[0]
    return result


def _configuration(server, root):
    result = server.request("config/read", {"includeLayers": True, "cwd": str(root)})
    if not isinstance(result, dict) or not isinstance(result.get("layers"), list):
        raise core.Error("Codex did not expose versioned user configuration; no settings were written")
    users = [layer for layer in result["layers"] if isinstance(layer, dict)
             and isinstance(layer.get("name"), dict) and layer["name"].get("type") == "user"
             and layer["name"].get("profile") is None]
    if len(users) != 1:
        raise core.Error("Codex did not identify one versioned user configuration; no settings were written")
    layer = users[0]
    path = layer["name"].get("file")
    version = layer.get("version")
    config = layer.get("config")
    if (not isinstance(path, str) or not Path(path).is_absolute()
            or not isinstance(version, str) or not version or not isinstance(config, dict)
            or layer.get("disabledReason") is not None):
        raise core.Error("Codex user configuration is unavailable or managed; no settings were written")
    projects = config.get("projects", {})
    if not isinstance(projects, dict):
        raise core.Error("Codex project trust configuration has an unsupported shape")
    matching = [(key, value) for key, value in projects.items() if _same_path(key, root)]
    if len(matching) > 1:
        raise core.Error("Codex has ambiguous trust entries for this folder; reconcile through the host")
    trust = matching[0][1] if matching else {}
    if not isinstance(trust, dict):
        raise core.Error("Codex project trust entry has an unsupported shape")
    # Preserve an existing spelling of the same physical path, including Windows case.
    project_key = matching[0][0] if matching else os.path.normcase(str(root))
    return {"path": path, "version": version, "project_key": project_key,
            "project_trusted": trust.get("trust_level") == "trusted"}


def _listed(server, root, expected, allow_missing=False):
    result = server.request("hooks/list", {"cwds": [str(root)]})
    if not isinstance(result, dict) or not isinstance(result.get("data"), list) or len(result["data"]) != 1:
        raise core.Error("Codex did not identify this project's callbacks")
    entry = result["data"][0]
    if (not isinstance(entry, dict) or not _same_path(entry.get("cwd"), root)
            or not isinstance(entry.get("hooks"), list)
            or entry.get("errors") != [] or entry.get("warnings") != []):
        raise core.Error("Codex reported a project callback discovery problem; inspect its host controls")
    selected = {}
    for item in entry["hooks"]:
        if not isinstance(item, dict):
            raise core.Error("Codex returned malformed callback metadata")
        if not str(item.get("statusMessage", "")).startswith(hooks.STATUS_PREFIX):
            continue
        event = next((name for name, wire in EVENTS.items() if item.get("eventName") == wire[0]), None)
        if event is None or event in selected:
            raise core.Error("Codex returned duplicate or unexpected Seedbag callbacks")
        group_index, handler_index, handler = expected[event]
        source = item.get("sourcePath")
        command = handler["commandWindows"] if os.name == "nt" else handler["command"]
        key = f"{source}:{EVENTS[event][1]}:{group_index}:{handler_index}"
        if (not _same_path(source, root / ".codex" / "hooks.json")
                or item.get("key") != key or item.get("source") != "project"
                or item.get("handlerType") != "command" or item.get("command") != command
                or item.get("statusMessage") != handler["statusMessage"]
                or item.get("async") is not False or item.get("matcher") is not None
                or item.get("timeoutSec") != handler["timeout"] or item.get("additionalContextLimit") is not None
                or item.get("pluginId") is not None or item.get("isManaged") is not False
                or item.get("enabled") is not True
                or item.get("trustStatus") not in {"trusted", "untrusted", "modified"}
                or not isinstance(item.get("currentHash"), str)
                or re.fullmatch(r"sha256:[a-f0-9]{64}", item["currentHash"]) is None):
            raise core.Error("Codex callback metadata differs from the reviewed project definitions; trust was not granted")
        selected[event] = {"key": item["key"], "hash": item["currentHash"], "trusted": item["trustStatus"] == "trusted"}
    if not selected and allow_missing:
        return {}
    if set(selected) != set(EVENTS):
        raise core.Error("Codex did not discover all four reviewed project callbacks")
    return selected


def _write(server, configuration, edits):
    result = server.request("config/batchWrite", {
        "edits": edits, "filePath": configuration["path"],
        "expectedVersion": configuration["version"], "reloadUserConfig": True,
    })
    if not isinstance(result, dict) or result.get("status") != "ok" or result.get("overriddenMetadata") is not None:
        raise core.Error("Codex did not verify the scoped configuration write; retry the read-only probe before further changes")


def configure(root, codex=None, trust_reviewed=False):
    """Inspect, or explicitly trust only reviewed local generated definitions.

    ``trust_reviewed`` confirms the assistant has inspected this runtime and its
    exact commands under the user's setup authorization; it is not an activation
    attestation. No caller-supplied global config path or model prompt is accepted.
    """
    root = Path(root).resolve()
    if type(trust_reviewed) is not bool:
        raise core.Error("trust_reviewed must be an explicit boolean")
    executable = codex or shutil.which("codex")
    if executable is None or not Path(executable).is_file():
        raise core.Error("A supported installed Codex executable is required for host configuration")
    expected = _definitions(root)
    baseline = _snapshot(root)
    writes = 0
    write_attempted = False
    try:
        with _Server(executable, root) as server:
            config = _configuration(server, root)
            selected = _listed(server, root, expected, allow_missing=not config["project_trusted"])
            if trust_reviewed and not config["project_trusted"]:
                if (root / ".codex" / "config.toml").exists():
                    raise core.Error("This untrusted project has additional Codex settings. Review and trust the full project configuration through the host before using exact-callback setup")
                if _snapshot(root) != baseline:
                    raise core.Error("Reviewed project files changed during host configuration")
                write_attempted = True
                _write(server, config, [{"keyPath": "projects." + json.dumps(config["project_key"], ensure_ascii=False) + ".trust_level",
                                        "value": "trusted", "mergeStrategy": "replace"}])
                writes += 1
                config = _configuration(server, root)
                if not config["project_trusted"]:
                    raise core.Error("Codex did not confirm this project's trust; setup remains incomplete")
                selected = _listed(server, root, expected)
            if trust_reviewed and selected and not all(item["trusted"] for item in selected.values()):
                if _snapshot(root) != baseline:
                    raise core.Error("Reviewed project files changed during host configuration")
                edits = [{"keyPath": "hooks.state." + json.dumps(item["key"], ensure_ascii=False) + ".trusted_hash",
                          "value": item["hash"], "mergeStrategy": "replace"}
                         for item in selected.values() if not item["trusted"]]
                write_attempted = True
                _write(server, config, edits)
                writes += 1
                config = _configuration(server, root)
                after = _listed(server, root, expected)
                if ({event: item["hash"] for event, item in after.items()}
                        != {event: item["hash"] for event, item in selected.items()}
                        or not config["project_trusted"] or not all(item["trusted"] for item in after.values())):
                    raise core.Error("Codex did not confirm the exact reviewed callback trust; setup remains incomplete")
                selected = after
            if _snapshot(root) != baseline:
                raise core.Error("Reviewed project files changed during host configuration")
            trusted = config["project_trusted"] and len(selected) == 4 and all(item["trusted"] for item in selected.values())
            return {
                "state": "configuration_trusted_requires_conversation_verification" if trusted else "configuration_requires_review",
                "project": str(root), "configuration_trusted": trusted,
                "project_trusted": config["project_trusted"], "callbacks_discovered": len(selected),
                "callbacks_trusted": sum(item["trusted"] for item in selected.values()),
                "configuration_writes": writes, "active_verified": False,
                "protected_work_ready": False, "setup_complete": False,
                "scope": "Configuration for future contexts opened in this project folder; no existing conversation was moved or verified.",
                "next_action": "Verify these callbacks in the actual project-bound conversation and observe host tool interception before product work.",
            }
    except core.Error as exc:
        if write_attempted:
            raise core.Error("Scoped Codex settings may already be saved; setup remains incomplete. Run the read-only probe before retrying. " + str(exc)) from exc
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise core.Error("Codex configuration could not be verified; settings may have been saved. Run the read-only probe before retrying") from exc
