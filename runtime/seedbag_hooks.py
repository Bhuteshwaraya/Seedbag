"""Project-local Codex lifecycle adapter, not a filesystem security boundary.

Definitions are prepared locally and require the host's own review/trust flow.
The adapter never sets trust, starts a service, or guesses which files to upload.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
import tomllib

import seedbag_core as core
import seedbag_git as git


EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "Stop")
STATUS_PREFIX = "Seedbag synchronization: "
RECOVERY_COMMANDS = {
    "sync-begin", "sync-checkpoint", "sync-status", "sync-configure", "sync-recover",
    "status", "context", "inspect", "doctor", "gate", "render", "effect-resolve",
}
# These are exact host tool identities, not name fragments such as /read|list/.
# Unknown tools are denied while synchronization is blocked. Recovery through the
# installed CLI and a small Git diagnostic grammar remains available.
NON_WRITING_TOOLS = {
    "read_file", "list_dir", "list_directory", "view_image", "read_mcp_resource",
    "list_mcp_resources", "list_mcp_resource_templates", "request_permissions",
    "request_user_input", "request_user_input_async", "update_plan", "get_goal", "clock__curr_time",
    "mcp__codex_app__list_threads", "mcp__codex_app__read_thread",
    "mcp__codex_app__list_archived_threads", "mcp__codex_app__wait_threads",
}


def _sync():
    # Import lazily so preparing/reviewing the adapter doesn't start synchronization.
    import seedbag_sync
    return seedbag_sync


def _session(event):
    value = event.get("session_id")
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise core.Error("Codex did not provide a valid session identity; synchronization is unverified")
    return value


def _context(event_name, message):
    return {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": message}}


def _deny(message):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": message}}


def _brief(error):
    # Never echo tool inputs, raw subprocess stderr, remote URLs, or credentials.
    # Runtime errors are useful for diagnosis through the explicit sync command;
    # hook messages only expose the exception class and a bounded known state.
    value = str(error)
    known = (
        "intended_file_paths_required", "remote_unavailable", "claim_conflict",
        "diverged", "not_configured", "session_mismatch", "runtime_changed",
        "untrusted", "missing", "dirty", "remote_advanced",
    )
    return next((state for state in known if state in value), type(error).__name__)


def _blocked_message(error):
    return (
        "Seedbag has not established a current shared starting point (" + _brief(error) + "). "
        "Pause new project changes. Use this project's sync-status and recovery commands, "
        "inspect existing changes, then run sync-begin with explicit intended paths when needed. "
        "Handle synchronization for the person; ask only when access or project intent requires them. "
        "Use a direct native shell call for the permitted recovery command. If this host exposes it only "
        "through a blocked code wrapper, automatic recovery on that path is unverified; preserve a "
        "complete handoff and use a host-permitted direct recovery route. "
        "Do not disable the gate or move work to an uncovered tool to bypass it."
    )


def _tokens(command):
    """Recognize a deliberately small single-command shell grammar.

    This is not a general shell read-only classifier. Expansion, redirection,
    composition, scripts, functions, and escaped syntax are unsupported.
    """
    if not isinstance(command, str) or not command.strip() or any(c in command for c in "\n\r\x00`$%!^"):
        return None
    parser = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
    parser.whitespace_split = True
    parser.commenters = ""
    parser.escape = ""
    try:
        args = list(parser)
    except ValueError:
        return None
    if args[:1] == ["&"]:  # PowerShell's invocation operator, once at the start.
        args = args[1:]
    if not args or any(any(c in part for c in ";&|<>()") for part in args):
        return None
    return args


def _path(root, candidate, cwd):
    try:
        path = Path(candidate)
        return (path if path.is_absolute() else cwd / path).resolve()
    except (OSError, ValueError):
        return None


def _setup_arguments(args):
    """The installed setup helper performs capability/read-only auth probes."""
    seen = set()
    while args:
        flag = args.pop(0)
        if flag in seen:
            return False
        seen.add(flag)
        if flag in {"--offline", "--network", "--help", "-h"}:
            continue
        if flag not in {"--repository", "--timeout"} or not args:
            return False
        value = args.pop(0)
        if flag == "--timeout" and (not value.isdigit() or not 1 <= int(value) <= 120):
            return False
        if flag == "--repository" and not value.startswith("https://github.com/"):
            return False
    return not {"--offline", "--network"} <= seen and ("--network" not in seen or "--repository" in seen)


def _regular_read_path(root, candidate, cwd):
    """Read a named ordinary file, without globbing, links, or traversal."""
    try:
        source = Path(candidate)
        if ".." in source.parts:
            return False
        path = source if source.is_absolute() else cwd / source
        if not path.is_relative_to(root):
            return False
        parts = path.relative_to(root).parts
        if not parts or any(":" in part for part in parts):
            return False
        current = root
        for part in parts:
            current = current / part
            if _linked(current):
                return False
        return stat.S_ISREG(path.lstat().st_mode)
    except (OSError, ValueError):
        return False


def _recovery_shell(root, event):
    data = event.get("tool_input")
    if not isinstance(data, dict):
        return False
    args = _tokens(data.get("command", data.get("cmd")))
    if not args:
        return False
    cwd = _path(root, data.get("workdir", event.get("cwd", str(root))), root)
    if cwd is None or not cwd.is_relative_to(root):
        return False
    executable = args.pop(0)
    if executable in {"whoami", "whoami.exe"} and not args:
        return True
    if executable.lower() == "get-content":
        if len(args) not in (2, 3) or args[0].lower() != "-literalpath":
            return False
        return (len(args) == 2 or args[2].lower() == "-raw") and _regular_read_path(root, args[1], cwd)
    if executable == "cat":
        return len(args) == 2 and args[0] == "--" and _regular_read_path(root, args[1], cwd)
    # Literal executable names or the exact Python running the installed adapter.
    python_names = {"python", "python3", "python.exe", "python3.exe"}
    is_python = executable in python_names or _path(root, executable, cwd) == Path(sys.executable).resolve()
    if is_python:
        while args and args[0] in {"-B", "-I", "-S"}:
            args.pop(0)
        if not args:
            return False
        script = _path(root, args.pop(0), cwd)
        if script == root / "seedbag_setup.py":
            return _setup_arguments(args)
        if script != root / "seedbag.py":
            return False
        explicit_root = False
        seen = set()
        while args and args[0] in {"--root", "--session"}:
            flag = args.pop(0)
            if flag in seen or not args:
                return False
            seen.add(flag)
            value = args.pop(0)
            if flag == "--root":
                if _path(root, value, cwd) != root:
                    return False
                explicit_root = True
            elif value != event.get("session_id"):
                return False
        if not explicit_root and cwd != root:
            return False
        return bool(args and args[0] in RECOVERY_COMMANDS and not any(
            part == "--root" or part.startswith("--root=") for part in args[1:]))
    if executable not in {"git", "git.exe"}:
        return False
    # Exact diagnostic forms only. Disallow -c, aliases, pager, external diff,
    # textconv, --output, arbitrary revision expressions, and global mutations.
    if args[:1] != ["--no-pager"]:
        return False
    args = args[1:]
    if args[:1] == ["-C"]:
        if len(args) < 3 or _path(root, args[1], cwd) != root:
            return False
        args = args[2:]
    elif cwd != root:
        return False
    if args == ["status", "--porcelain=v1", "--untracked-files=all"]:
        return True
    if args[:3] != ["diff", "--no-ext-diff", "--no-textconv"]:
        return False
    rest = args[3:]
    if rest[:1] == ["--cached"]:
        rest = rest[1:]
    if not rest:
        return True
    if rest.pop(0) != "--":
        return False
    return all(not item.startswith("-") and _path(root, item, cwd) is not None
               and _path(root, item, cwd).is_relative_to(root) for item in rest)


def _recovery_tool(root, event):
    name = event.get("tool_name")
    if name in NON_WRITING_TOOLS:
        return True
    if name in {"Bash", "exec_command", "shell_command"}:
        return _recovery_shell(root, event)
    return False


def handle(root, event):
    # Leave time for controlled failure JSON before the host's 50-second limit.
    # Git timeouts are cumulative within this context, including nested calls.
    with git.operation_deadline(40):
        return _handle(root, event)


def _handle(root, event):
    """Return documented Codex hook JSON; do not put diagnostics on stdout."""
    root = Path(root).resolve()
    if not isinstance(event, dict):
        raise core.Error("Hook input must be a JSON object")
    name = event.get("hook_event_name")
    if name not in EVENTS:
        raise core.Error("Unsupported Seedbag hook event")
    try:
        session = _session(event)
        if name in {"SessionStart", "UserPromptSubmit"}:
            result = _sync().begin(root, session=session)
            if isinstance(result, dict) and result.get("state") == "local_only" and result.get("ready_to_edit") is True:
                return _context(name, "This project is configured for local work only; no shared synchronization is claimed.")
            if not isinstance(result, dict) or result.get("state") != "ready_to_edit":
                raise core.Error("Sync did not return a verified editing state")
            return _context(name, "Seedbag established the current shared starting point. "
                            "Read fresh project context before acting. Continue using this installed runtime; "
                            "checkpoint explicit intended files before finishing substantial work. "
                            "Synchronization is not approval for additional project work.")
        if name == "PreToolUse":
            if _recovery_tool(root, event):
                return {}
            result = _sync().require_ready(root, session=session, refresh=True)
            if isinstance(result, dict) and result.get("state") == "local_only" and result.get("ready_to_edit") is True:
                return {}
            if not isinstance(result, dict) or result.get("state") != "ready_to_edit":
                raise core.Error("Sync did not return a verified editing state")
            return {}
        # No file list is inferred from the transcript or arbitrary workspace
        # changes. The runtime can verify/release a clean checkpoint; a dirty
        # checkpoint requires the assistant to name the intended paths itself.
        local_status = _sync().status(root)
        if isinstance(local_status, dict) and local_status.get("state") == "local_only":
            return {}
        result = _sync().checkpoint(root, message="Seedbag conversation checkpoint", paths=None,
                                    incomplete=True, session=session)
        if not isinstance(result, dict) or result.get("state") != "shared_verified" or result.get("shared") is not True or result.get("released") is not True:
            raise core.Error("Checkpoint did not return success")
        return {}
    except Exception as error:
        # A failed adapter still emits the valid deny wire shape for covered
        # tools. Uncaught command-hook failures can otherwise fail open in hosts.
        if name == "PreToolUse":
            return _deny(_blocked_message(error))
        if name != "Stop":
            # Allow the prompt itself so diagnosis/recovery remains possible.
            return _context(name, _blocked_message(error))
        message = (
            "Seedbag could not verify a shared closeout (" + _brief(error) + "). "
            "Inspect pending state and run sync-checkpoint with explicit intended paths, "
            "using --incomplete if the work is unfinished. Do not stage unrelated files or secrets. "
            "If access, conflict, or uncertain publication prevents saving, preserve the files "
            "and tell the person clearly what remains only here. Do not claim synchronization."
        )
        if event.get("stop_hook_active") is True:
            # A failed network or unresolved decision must not cause an endless
            # model continuation loop. The editing gate remains closed.
            return {"systemMessage": message}
        return {"decision": "block", "reason": message}


def _quote_ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def _linked(path):
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except FileNotFoundError:
        return False


def _handler(root, python, event):
    argv = [str(python), "-B", str(root / "seedbag.py"), "--root", str(root), "hook"]
    # This configuration belongs to one device/checkout and is ignored by Git.
    command = " ".join(shlex.quote(part) for part in argv)
    windows = "& " + " ".join(_quote_ps(part) for part in argv)
    return {"type": "command", "command": command, "commandWindows": windows,
            "timeout": 50, "statusMessage": STATUS_PREFIX + event}


def install(root, python=None):
    """Prepare local definitions, preserving other hooks and all trust settings.

    The host must review these exact definitions. This function cannot verify
    runtime activation; it deliberately returns ``prepared_requires_host_trust``.
    """
    root = Path(root).resolve()
    interpreter = Path(python or sys.executable).resolve()
    if not interpreter.is_file() or not (root / "seedbag.py").is_file():
        raise core.Error("Preparing hooks requires the installed launcher and an existing Python executable")
    directory = root / ".codex"
    target = directory / "hooks.json"
    for path in (directory, target, directory / "config.toml"):
        if _linked(path):
            raise core.Error("Refusing a linked project hook configuration path")
    config = directory / "config.toml"
    if config.exists():
        try:
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise core.Error("Project config could not be parsed; existing files were preserved") from exc
        if "hooks" in parsed:
            raise core.Error("Project config already defines inline hooks; reconcile one representation before installation")
    check = subprocess.run(["git", "-C", str(root), "check-ignore", "--quiet", "--", ".codex/hooks.json"],
                           capture_output=True, timeout=10)
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", ".codex/hooks.json"],
                             capture_output=True, timeout=10)
    if check.returncode != 0 or tracked.returncode == 0:
        raise core.Error("Local .codex/hooks.json must be ignored and untracked before preparing device-specific commands")
    original = target.read_bytes() if target.exists() else None
    try:
        document = json.loads(original) if original is not None else {"hooks": {}}
    except (ValueError, UnicodeDecodeError) as exc:
        raise core.Error("Existing hooks.json is invalid; it was preserved") from exc
    if not isinstance(document, dict) or not isinstance(document.get("hooks", {}), dict):
        raise core.Error("Existing hooks.json has an unsupported shape; it was preserved")
    merged = copy.deepcopy(document)
    events = merged.setdefault("hooks", {})
    for event in EVENTS:
        groups = events.setdefault(event, [])
        if not isinstance(groups, list):
            raise core.Error("Existing hook event is not a list; it was preserved")
        desired = {"hooks": [_handler(root, interpreter, event)]}
        if desired in groups:
            continue
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise core.Error("Existing hook matcher has an unsupported shape; it was preserved")
            if any(isinstance(handler, dict) and str(handler.get("statusMessage", "")).startswith(STATUS_PREFIX)
                   for handler in group.get("hooks", [])):
                raise core.Error("Different Seedbag hook definitions already exist; review them before replacing anything")
        groups.append(desired)
    encoded = (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    changed = merged != document
    if changed or original is None:
        directory.mkdir(exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".seedbag-hooks-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as handle_file:
                handle_file.write(encoded)
                handle_file.flush()
                os.fsync(handle_file.fileno())
            if (target.read_bytes() if target.exists() else None) != original:
                raise core.Error("Hook configuration changed during preparation; original update was preserved")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {"state": "prepared_requires_host_trust", "path": str(target), "changed": changed,
            "active_verified": False, "trust_changed": False, "events": list(EVENTS),
            "next_action": "Review and trust the project and these hook definitions in the host. "
                           "Codex CLI exposes this through /hooks. Then verify actual lifecycle execution.",
            "coverage": "Supported Codex tool paths only; running terminal input and exempt tools are outside this guardrail."}
