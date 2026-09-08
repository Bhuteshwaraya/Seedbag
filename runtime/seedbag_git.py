"""Ordinary Git publication and index checks for Seedbag projects.

No automatic merge, reset, force push, global configuration, or branch promotion.
The optional hook is a local convenience, not an adversarial security boundary.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shlex
import subprocess
import sys
import tempfile
import time

import seedbag_core as core
import seedbag_context as views

Error = core.Error
_OPERATION_DEADLINE = ContextVar("seedbag_git_operation_deadline", default=None)


@contextmanager
def operation_deadline(seconds):
    """Bound a sequence of Git calls so a host hook can emit its own failure.

    An inner operation cannot extend an outer deadline. This only changes this
    Python context, never user configuration or the child process environment.
    """
    proposed = time.monotonic() + seconds
    existing = _OPERATION_DEADLINE.get()
    token = _OPERATION_DEADLINE.set(min(existing, proposed) if existing is not None else proposed)
    try:
        yield
    finally:
        _OPERATION_DEADLINE.reset(token)


LEDGER = ".seedbag/ledger.json"
REQUIRED_FILES = (
    "README.md", "CONTINUE_HERE.md", "AGENTS.md", "FIRST_RUN.md", "SYNC.md",
    "seedbag_setup.py", "seedbag.py", "SEEDBAG_LICENSE.txt",
    ".seedbag/runtime/seedbag_core.py", ".seedbag/runtime/seedbag_context.py",
    ".seedbag/runtime/seedbag_git.py", ".seedbag/runtime/seedbag_sync.py",
    ".seedbag/runtime/seedbag_hooks.py", ".seedbag/runtime/seedbag_codex.py", ".seedbag/sync.json", LEDGER, "PROJECT.md", "STATE.md",
    ".gitignore", ".gitattributes",
)
_ENTRY_START = "<!-- seedbag:continue:start -->"
_ENTRY_END = "<!-- seedbag:continue:end -->"
_ENTRY_BLOCK = re.compile(
    r"(?m)^" + re.escape(_ENTRY_START) + r"\n```text\n([^\r\n]+)\n```\n"
    + re.escape(_ENTRY_END) + r"$"
)


def _git(root, *args, allow_failure=False, input_bytes=None, env=None):
    deadline = _OPERATION_DEADLINE.get()
    remaining = min(120, deadline - time.monotonic()) if deadline is not None else 120
    if remaining <= 0:
        raise Error("The synchronization time budget ended. Preserve files and inspect shared state before retrying.")
    try:
        # PIPE-based communicate() can wait beyond its timeout when a Git
        # descendant inherits a pipe. Regular temporary files have no EOF wait
        # on another process. This applies to stdin as well as both outputs.
        # A timed-out transport may still have an uncertain remote outcome; the
        # caller must inspect that state, never assume a cancellation receipt.
        with ExitStack() as stack:
            output = stack.enter_context(tempfile.TemporaryFile())
            errors = stack.enter_context(tempfile.TemporaryFile())
            incoming = subprocess.DEVNULL
            if input_bytes is not None:
                incoming = stack.enter_context(tempfile.TemporaryFile())
                incoming.write(input_bytes)
                incoming.seek(0)
            completed = subprocess.run(
                ["git", "-C", str(root), *args], stdin=incoming,
                stdout=output, stderr=errors, timeout=remaining, env=env,
            )
            # Read only the size observed after Git returned; an unrelated
            # lingering descendant cannot extend the read indefinitely.
            output_size = os.fstat(output.fileno()).st_size
            error_size = os.fstat(errors.fileno()).st_size
            output.seek(0)
            errors.seek(0)
            result = subprocess.CompletedProcess(completed.args, completed.returncode,
                                                 output.read(output_size), errors.read(error_size))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Error(f"Git could not finish. Local files are preserved: {exc}") from exc
    if result.returncode and not allow_failure:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise Error(f"Git {args[0]} failed. Local files are preserved. {detail}")
    return result


def _text(root, *args):
    return _git(root, *args).stdout.decode("utf-8", "strict").strip()


def _root(root):
    root = Path(root).resolve()
    actual = Path(_text(root, "rev-parse", "--show-toplevel")).resolve()
    if actual != root:
        raise Error("Use the project repository root; a parent repository is not the project.")
    return root


def _head(root):
    result = _git(root, "rev-parse", "--verify", "HEAD", allow_failure=True)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def _names(data):
    return [p.decode("utf-8", "strict") for p in data.split(b"\0") if p]


def _relative(name):
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise Error("Publication paths must be exact project-relative file paths.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in ("..", ".git") or ":" in p for p in path.parts):
        raise Error(f"Path is outside the allowed project files: {name}")
    if str(path) != name or name in (".", ""):
        raise Error(f"Use a normalized exact file path: {name}")
    return path


def _no_link(root, relative):
    cursor = root
    for component in _relative(relative).parts:
        cursor = cursor / component
        if cursor.is_symlink() or (cursor.exists() and getattr(cursor.lstat(), "st_file_attributes", 0) & 0x400):
            raise Error(f"Linked paths are not published by Seedbag: {relative}")
    return cursor


def _index(root):
    records = []
    for raw in _git(root, "ls-files", "--stage", "-z").stdout.split(b"\0"):
        if not raw:
            continue
        metadata, name = raw.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split()
        name = name.decode("utf-8", "strict")
        _relative(name)
        if stage != "0":
            raise Error("Resolve the existing Git merge conflict before publishing; all versions are preserved.")
        if mode not in ("100644", "100755"):
            raise Error(f"The staged snapshot contains a link or submodule: {name}")
        records.append((name, oid))
    return records


def _validate_views(root, snapshot):
    for name, expected in views.view_texts(snapshot).items():
        path = root / name
        if not path.is_file() or path.read_bytes() != expected.encode("utf-8"):
            raise Error(f"{name} does not match the ledger. Render generated views, then stage their exact versions.")


def validate_entry_files(root, snapshot):
    """Validate complete project files without importing or executing their code."""
    root = Path(root)
    missing = [name for name in REQUIRED_FILES if not _no_link(root, name).is_file()]
    if missing:
        raise Error("The project snapshot is missing required files: " + ", ".join(missing))
    prompts = {}
    for name in ("README.md", "CONTINUE_HERE.md"):
        try:
            contents = (root / name).read_bytes().decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise Error(f"{name} must be UTF-8 text.") from exc
        blocks = list(_ENTRY_BLOCK.finditer(contents))
        if contents.count(_ENTRY_START) != 1 or contents.count(_ENTRY_END) != 1 or len(blocks) != 1:
            raise Error(f"{name} must contain exactly one marked, copyable continuation prompt block.")
        paragraph = blocks[0][1]
        if not paragraph.strip() or paragraph != paragraph.strip():
            raise Error(f"{name} must contain one nonempty continuation paragraph without surrounding whitespace.")
        prompts[name] = paragraph
    paragraph = prompts["CONTINUE_HERE.md"]
    if prompts["README.md"] != paragraph:
        raise Error("README.md must contain the exact saved CONTINUE_HERE.md continuation prompt.")
    prefix = "Continue my project: "
    locator = paragraph.removeprefix(prefix)
    if not paragraph.startswith(prefix) or not locator.strip() or locator != locator.strip():
        raise Error("CONTINUE_HERE.md must contain the short request followed by its project locator.")
    repository = snapshot["ledger"]["repository"]
    if repository and locator != repository:
        raise Error("CONTINUE_HERE.md does not identify this project's saved repository locator.")
    if not repository and not (PurePosixPath(locator).is_absolute() or PureWindowsPath(locator).is_absolute()):
        raise Error("A local-only CONTINUE_HERE.md must identify an absolute folder location.")
    policy = core.read_json(root / ".seedbag/sync.json")
    expected_keys = {"schema", "policy", "repository", "remote", "branch", "claim_ref"}
    if (not isinstance(policy, dict) or set(policy) != expected_keys or policy["schema"] != 1
            or policy["repository"] != repository
            or policy["policy"] != ("strict" if repository else "local")
            or policy["claim_ref"] != "refs/heads/seedbag-sync-claims"
            or not isinstance(policy["remote"], str) or not policy["remote"] or policy["remote"].startswith("-")
            or not isinstance(policy["branch"], str) or not policy["branch"] or policy["branch"].startswith("-")):
        raise Error("The installed synchronization policy is missing, invalid, or does not match this project.")
    return {"ok": True, "continuation_prompt": paragraph}


def _readiness(root, snapshot, incomplete):
    warnings = core.readiness(snapshot, root=root)
    blocking = [problem for problem in warnings if not (
        incomplete and problem.startswith(("Unprocessed capture:", "Unresolved external effect:"))
    )]
    if blocking:
        raise Error("Checkpoint is not ready: " + "; ".join(blocking))
    return warnings


def _resolve_commit(root, ref):
    if not isinstance(ref, str) or not ref or ref.startswith("-") or "\0" in ref:
        raise Error("Supply an explicit existing commit or ref to audit.")
    result = _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}", allow_failure=True)
    if result.returncode:
        raise Error(f"Cannot resolve commit {ref!r}. Fetch the intended history explicitly before auditing it.")
    return result.stdout.decode("ascii").strip()


def _pending_parents(root):
    parents = []
    if head := _head(root):
        parents.append(head)
    merge_path = Path(_text(root, "rev-parse", "--git-path", "MERGE_HEAD"))
    if not merge_path.is_absolute():
        merge_path = root / merge_path
    if merge_path.exists():
        for ref in merge_path.read_text(encoding="ascii").splitlines():
            parents.append(_resolve_commit(root, ref.strip()))
    return list(dict.fromkeys(parents))


def _commit_records(root, commit):
    records = []
    for raw in _git(root, "ls-tree", "-r", "-z", "--full-tree", commit).stdout.split(b"\0"):
        if not raw:
            continue
        metadata, name = raw.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        name = name.decode("utf-8", "strict")
        _relative(name)
        if kind != "blob" or mode not in ("100644", "100755"):
            raise Error(f"The committed snapshot contains a link or submodule: {name}")
        records.append((name, oid))
    return records


def _audit_records(root, records, parents, incomplete):
    if LEDGER not in {name for name, _ in records}:
        raise Error("The snapshot must include canonical .seedbag/ledger.json.")
    with tempfile.TemporaryDirectory(prefix="seedbag-snapshot-") as temporary:
        staged = Path(temporary) / "snapshot"
        staged.mkdir()
        for name, oid in records:
            path = staged.joinpath(*PurePosixPath(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_git(root, "cat-file", "blob", oid).stdout)
        snapshot = core.validate(staged)
        validate_entry_files(staged, snapshot)
        checked = []
        for parent in dict.fromkeys(parents):
            old = _git(root, "show", f"{parent}:{LEDGER}", allow_failure=True)
            if old.returncode:
                listed = _names(_git(root, "ls-tree", "--name-only", "-z", parent, "--", LEDGER).stdout)
                if LEDGER in listed:
                    raise Error(f"The ledger at parent/base {parent} cannot be verified.")
                continue  # A parent before Seedbag planting has no ledger to extend.
            parent_file = Path(temporary) / "prior-ledger.json"
            parent_file.write_bytes(old.stdout)
            try:
                core.validate_parent(staged, core.read_json(parent_file))
            except Error as exc:
                raise Error(f"{exc}. The snapshot does not preserve parent/base {parent}. Keep both branches. Divergent event chains cannot both prefix one linear ledger: choose a lineage and replay reviewed changes there while preserving the other candidate, without claiming that both event histories were merged.") from exc
            previous_prompt = _git(root, "show", f"{parent}:CONTINUE_HERE.md", allow_failure=True)
            if previous_prompt.returncode:
                raise Error(f"The permanent continuation prompt at parent/base {parent} cannot be verified.")
            if previous_prompt.stdout != (staged / "CONTINUE_HERE.md").read_bytes():
                raise Error(f"CONTINUE_HERE.md changed from parent/base {parent}. Preserve the permanent prompt unchanged during ordinary project work.")
            checked.append(parent)
        _validate_views(staged, snapshot)
        warnings = _readiness(staged, snapshot, incomplete)
        return {"ok": True, "revision": snapshot["revision"], "digest": snapshot["digest"],
                "tracked_files": len(records), "checked_parent_ledgers": checked,
                "snapshot_only": bool(incomplete), "readiness_warnings": warnings}


def gate(root, incomplete=False):
    """Validate INDEX and preserve HEAD plus every pending merge parent's ledger."""
    root = _root(root)
    records = _index(root)
    if LEDGER not in {name for name, _ in records}:
        raise Error("Stage the canonical .seedbag/ledger.json before committing this project.")
    parents = _pending_parents(root)
    result = _audit_records(root, records, parents, incomplete)
    return {**result, "source": "staged_index", "parent_commits": parents}


def audit_commit(root, commit, base, incomplete=False):
    """Read-only audit of pinned committed blobs against a known base and parents.

    Does not inspect checkout/index, fetch, execute checks, or audit every
    intermediate historical snapshot. It verifies the selected snapshot only.
    """
    root = _root(root)
    subject = _resolve_commit(root, commit)
    baseline = _resolve_commit(root, base)
    if _git(root, "merge-base", "--is-ancestor", baseline, subject, allow_failure=True).returncode:
        raise Error("The selected commit does not descend from the known base. Preserve both refs and reconcile before claiming continuity.")
    # Read actual commit headers: rev-list can hide parents at a shallow-clone
    # boundary. Missing parent objects must cause an explicit audit refusal.
    header = _git(root, "cat-file", "commit", subject).stdout.split(b"\n\n", 1)[0]
    parents = [_resolve_commit(root, line[7:].decode("ascii")) for line in header.splitlines() if line.startswith(b"parent ")]
    result = _audit_records(root, _commit_records(root, subject), [baseline, *parents], incomplete)
    return {**result, "source": "committed_snapshot", "commit": subject, "base_commit": baseline,
            "parent_commits": parents,
            "boundary": "Selected committed snapshot, explicit base, and immediate parents only. No checks executed, refs changed, or automatic semantic merge performed."}


def connector_export(root, commit, output):
    """Prepare an initial committed snapshot for an assistant-operated connector.

    This is not publication or a remote receipt. A connector must independently
    verify the private target, its README-only bootstrap parent, exact uploaded
    objects, non-force ref update, and final readback before claiming sharing.
    Existing projects must retain their real history through ordinary Git.
    """
    root = _root(root)
    destination = Path(output).absolute()
    if destination.is_relative_to(root):
        _no_link(root, destination.relative_to(root).as_posix())
    if destination.is_symlink():
        raise Error("The export output cannot be a linked path.")
    destination = destination.resolve()
    local_scratch = root / ".seedbag-local"
    if destination.is_relative_to(root) and (destination == local_scratch or not destination.is_relative_to(local_scratch)):
        raise Error("Write the export outside the project or inside .seedbag-local; it must not become a project file.")
    if destination.exists():
        raise Error("The export output already exists. Keep it and choose a new output file.")
    if _text(root, "rev-parse", "--show-object-format") != "sha1":
        raise Error("The GitHub connector export requires a SHA-1 Git repository.")
    subject = _resolve_commit(root, commit)
    commit_bytes = _git(root, "cat-file", "commit", subject).stdout
    if hashlib.sha1(b"commit " + str(len(commit_bytes)).encode("ascii") + b"\0" + commit_bytes).hexdigest() != subject:
        raise Error("The selected commit object does not match its hash; do not export replacement objects.")
    headers = commit_bytes.split(b"\n\n", 1)[0].splitlines()
    if any(line.startswith(b"parent ") for line in headers):
        raise Error("Connector export supports only the first parentless project commit, not continuation or rewritten history.")
    audit = audit_commit(root, subject, subject)
    ledger = json.loads(_git(root, "show", f"{subject}:{LEDGER}").stdout)
    locator = ledger["repository"]
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})", locator)
    if not match or match[2] in (".", ".."):
        raise Error("Connector export needs the project's plain HTTPS GitHub repository locator: https://github.com/OWNER/REPOSITORY.")
    files = []
    for raw in _git(root, "ls-tree", "-r", "-z", "--full-tree", subject).stdout.split(b"\0"):
        if not raw:
            continue
        metadata, path_bytes = raw.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        name = path_bytes.decode("utf-8", "strict")
        _relative(name)
        if kind != "blob" or mode not in ("100644", "100755"):
            raise Error(f"Connector export contains a link or submodule: {name}")
        if name == ".seedbag-local" or name.startswith(".seedbag-local/"):
            raise Error("Connector export cannot include local scratch files or earlier export payloads.")
        data = _git(root, "cat-file", "blob", oid).stdout
        if hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest() != oid:
            raise Error(f"The committed blob does not match its hash: {name}")
        files.append({"path": name, "mode": mode, "type": "blob", "sha": oid,
                      "size": len(data), "encoding": "base64", "content": base64.b64encode(data).decode("ascii")})
    tree = next(line[5:].decode("ascii") for line in headers if line.startswith(b"tree "))
    boundary = (
        "Prepared local bytes only. No upload, account configuration, remote privacy check, ref change, or network verification occurred. "
        "Before initial publication, independently verify through the connector that the target is this private repository and its current default-branch "
        "tip is a parentless README-only bootstrap commit with no ledger. Use that verified tip as the sole parent of the new remote commit, "
        "upload these exact blobs and modes, verify the complete tree, update the ref without force, then read back the exact commit and tree. "
        "The local parentless commit is an export source, not the resulting shared commit. Preserve the resulting real remote history when continuing."
    )
    export = {"schema": "seedbag-initial-connector-export-1", "state": "prepared_not_shared", "shared": False,
              "repository": {"url": locator, "full_name": f"{match[1]}/{match[2]}", "privacy": "unverified"},
              "source": {"commit": subject, "tree": tree, "parent_commits": [],
                         "revision": audit["revision"], "digest": audit["digest"]},
              "files": files, "boundary": boundary}
    encoded = core.canonical(export) + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves any competing output that appeared after the
    # preflight; an export never overwrites project data or an earlier receipt.
    with destination.open("xb") as stream:
        stream.write(encoded)
    return {"state": "prepared_not_shared", "shared": False, "output": str(destination),
            "sha256": hashlib.sha256(encoded).hexdigest(), "files": len(files),
            "repository": locator, **export["source"], "boundary": boundary}


def _remote_refs(root):
    output = _text(root, "for-each-ref", "--format=%(refname)%00%(objectname)%00%(committerdate:iso-strict)%00%(subject)", "refs/remotes/")
    result = []
    for line in output.splitlines():
        ref, commit, date, subject = line.split("\0", 3)
        if not ref.endswith(("/HEAD", "/seedbag-sync-claims")):
            result.append({"ref": ref, "commit": commit, "recorded_commit_time": date, "subject": subject})
    return result


def status(root, fetch=False):
    """Distinguish local saves, commits, and cached/shared branch knowledge."""
    root = Path(root).resolve()
    probe = _git(root, "rev-parse", "--show-toplevel", allow_failure=True)
    if probe.returncode or Path(probe.stdout.decode("utf-8").strip()).resolve() != root:
        return {"git_state": "not_initialized", "local_state": "local_only", "commit_state": "unborn",
                "shared_state": "no_shared_reference", "reference_freshness": "no_project_git_repository",
                "branch": None, "commit": None, "upstream": None, "ahead": None, "behind": None,
                "candidate_refs": [], "candidate_count": 0, "candidate_overflow": False,
                "guidance": "Files remain local. This project has no Git repository; any parent repository was ignored. No network operation was performed."}
    remotes = _text(root, "remote").splitlines()
    if fetch:
        for remote in remotes:
            _git(root, "fetch", "--", remote)
    branch_result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allow_failure=True)
    branch = branch_result.stdout.decode().strip() if branch_result.returncode == 0 else None
    head = _head(root)
    upstream_result = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", allow_failure=True)
    upstream = upstream_result.stdout.decode().strip() if upstream_result.returncode == 0 else None
    if not upstream and branch and "origin" in remotes:
        candidate = f"refs/remotes/origin/{branch}"
        if _git(root, "show-ref", "--verify", "--quiet", candidate, allow_failure=True).returncode == 0:
            upstream = f"origin/{branch}"
    ahead = behind = None
    shared = "no_shared_reference"
    if head and upstream:
        ahead, behind = map(int, _text(root, "rev-list", "--left-right", "--count", f"HEAD...{upstream}").split())
        shared = "diverged" if ahead and behind else "ahead" if ahead else "behind" if behind else "matches_reference"
    staged = _names(_git(root, "diff", "--cached", "--name-only", "-z").stdout)
    unstaged = _names(_git(root, "diff", "--name-only", "-z").stdout)
    untracked = _names(_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout)
    refs = _remote_refs(root)
    primary_ref = f"refs/remotes/{upstream}" if upstream else None
    candidates = [entry for entry in refs if entry["ref"] != primary_ref]
    return {"git_state": "initialized", "branch": branch, "commit": head, "local_state": "dirty" if staged or unstaged or untracked else "clean",
            "commit_state": "committed" if head else "unborn", "staged": staged, "unstaged": unstaged,
            "untracked": untracked, "upstream": upstream, "ahead": ahead, "behind": behind,
            "shared_state": shared, "reference_freshness": "fetched_this_call" if fetch and remotes else "cached_not_rechecked",
            "candidate_refs": candidates[:100], "candidate_count": len(candidates), "candidate_overflow": len(candidates) > 100,
            "guidance": "Saved files are local; commits are local until pushed. Inspect relevant candidate state before resuming. No candidate is automatically selected or approved."}


def candidate_state(root, ref):
    """Read one explicitly selected discovered branch, without checkout/promotion."""
    root = _root(root)
    matches = [entry for entry in _remote_refs(root) if entry["ref"] == ref]
    if not matches:
        raise Error("Choose an exact remote branch from status metadata before inspecting candidate state.")
    commit = matches[0]["commit"]
    result = _git(root, "show", f"{commit}:STATE.md", allow_failure=True)
    if result.returncode:
        raise Error("That branch has no STATE.md. Inspect its committed changes before choosing it.")
    return {"ref": ref, "commit": commit, "state": result.stdout.decode("utf-8", "strict"),
            "boundary": "Candidate document only; reading it does not prove readiness or authorize promotion."}


def publish(root, message, paths, remote="origin", branch=None, incomplete=False):
    """Publish installed projects only through their bound synchronization gate."""
    root = _root(root)
    if core._installed(root):
        import seedbag_sync as sync
        policy = sync._policy(root)
        if policy["policy"] != "strict":
            raise Error("This project is local-only; it has no bound shared publication destination.")
        if remote != policy["remote"] or (branch is not None and branch != policy["branch"]):
            raise Error("Publication must use this project's bound remote and branch; another configured repository is not its destination.")
        return sync.checkpoint(root, message, paths, incomplete=incomplete)
    return _publish_uncoordinated(root, message, paths, remote, branch, incomplete)


def _publish_uncoordinated(root, message, paths, remote="origin", branch=None, incomplete=False):
    """Internal historical snapshot/transport primitive, not an installed API.

    Tests use this to model writers outside synchronization. Installed commands
    must call publish or seedbag_sync.checkpoint, which enforce the binding.
    """
    root = _root(root)
    if not isinstance(paths, list) or not paths or len(set(paths)) != len(paths):
        raise Error("Name the exact intended files once each; publication does not stage the whole directory.")
    for name in paths:
        path = _no_link(root, name)
        if path.is_dir():
            raise Error(f"Name individual files rather than a directory: {name}")
        if name.startswith(".seedbag-local/"):
            raise Error("Local locks and scratch state are not publication targets.")
        if name.startswith(".seedbag/") and name not in (LEDGER, ".seedbag/sync.json") and not name.startswith(".seedbag/runtime/"):
            raise Error(f"Local Seedbag working files are not publication targets: {name}")
    if not isinstance(message, str) or not message.strip():
        raise Error("Supply a short checkpoint message describing the saved change.")
    if not isinstance(remote, str) or not remote or remote.startswith("-") or remote not in _text(root, "remote").splitlines():
        raise Error("Choose an already configured Git remote; Seedbag does not configure credentials or destinations.")
    if branch is None:
        result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allow_failure=True)
        if result.returncode:
            raise Error("Choose a publication branch; this checkout has a detached HEAD.")
        branch = result.stdout.decode().strip()
    if not isinstance(branch, str) or branch.startswith("-") or _git(root, "check-ref-format", "--branch", branch, allow_failure=True).returncode:
        raise Error("Use a valid explicit Git branch name.")
    with core.project_lock(root):
        snapshot = core.validate(root)
        _validate_views(root, snapshot)
        warnings = _readiness(root, snapshot, incomplete)
        _index(root)  # Refuse pre-existing conflicts before changing the index.
        staged = set(_names(_git(root, "diff", "--cached", "--name-only", "-z").stdout))
        if staged - set(paths):
            raise Error("Other files are already staged. Reconcile the intended checkpoint first: " + ", ".join(sorted(staged - set(paths))))
        unstaged = set(_names(_git(root, "diff", "--name-only", "-z").stdout))
        if staged & unstaged:
            raise Error("The index holds a different version of an intended file. Reconcile it before publication: " + ", ".join(sorted(staged & unstaged)))
        _git(root, "add", "--", *paths)
        gate(root, incomplete=incomplete)
        if _git(root, "diff", "--cached", "--quiet", allow_failure=True).returncode == 1:
            commit_env = dict(os.environ)
            commit_env.pop("SEEDBAG_INCOMPLETE_CHECKPOINT", None)
            if incomplete:
                commit_env["SEEDBAG_INCOMPLETE_CHECKPOINT"] = "1"
            _git(root, "commit", "-m", message, env=commit_env)
        commit = _head(root)
        if commit is None:
            raise Error("There is no commit to publish. Save an intended project checkpoint first.")
        _git(root, "fetch", "--", remote)
        destination = f"refs/heads/{branch}"
        remote_tip = _git(root, "ls-remote", "--heads", remote, destination).stdout.decode().strip()
        remote_commit = None
        if remote_tip:
            remote_commit = remote_tip.split()[0]
            # Ensure an exact non-default destination ref is available locally.
            if _git(root, "cat-file", "-e", remote_commit, allow_failure=True).returncode:
                _git(root, "fetch", "--", remote, destination)
            if _git(root, "merge-base", "--is-ancestor", remote_commit, commit, allow_failure=True).returncode:
                raise Error("The shared branch is ahead or divergent. Your local commit and files are preserved; compare both branches and reconcile before another publish.")
        # A local commit may have been created without the optional hook.
        # Compare outgoing committed data with shared data, not just topology.
        audit_commit(root, commit, remote_commit or commit, incomplete=incomplete)
        _git(root, "push", "--", remote, f"{commit}:{destination}")
        verified = _git(root, "ls-remote", "--heads", remote, destination).stdout.decode().strip()
        if not verified or verified.split()[0] != commit:
            raise Error("Push returned, but the shared tip did not match on readback. Keep the local commit and inspect the remote before retrying.")
        return {"state": "shared_verified", "commit": commit, "remote": remote, "branch": branch,
                "verification": "exact remote tip readback", "revision": snapshot["revision"], "digest": snapshot["digest"],
                "snapshot_only": bool(incomplete), "readiness_warnings": warnings}


def install_hook(root):
    root = _root(root)
    custom = _git(root, "config", "--get", "core.hooksPath", allow_failure=True)
    if custom.returncode == 0:
        raise Error("A Git hooks path is already configured. Keep it and add the Seedbag gate to your existing workflow explicitly.")
    hook = Path(_text(root, "rev-parse", "--git-path", "hooks/pre-commit"))
    if not hook.is_absolute():
        hook = root / hook
    if hook.exists() or hook.is_symlink():
        raise Error("A pre-commit hook already exists. It was preserved; integrate the Seedbag gate explicitly.")
    installed_module = root / ".seedbag/runtime/seedbag_git.py"
    # Planting calls this function from the seed package after copying runtime.
    # Bind that hook to the project's own copy, never to the seed directory.
    module = installed_module if installed_module.is_file() else Path(__file__).resolve()
    command = " ".join(shlex.quote(Path(p).as_posix()) for p in (sys.executable, str(module)))
    content = f"#!/bin/sh\nexec {command} --gate {shlex.quote(root.as_posix())}\n"
    hook.parent.mkdir(parents=True, exist_ok=True)
    try:
        with hook.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    except FileExistsError as exc:
        raise Error("A pre-commit hook appeared during installation. It was not overwritten.") from exc
    hook.chmod(hook.stat().st_mode | 0o111)
    return {"installed": str(hook), "boundary": "Optional local check; users can bypass hooks. No global Git setting changed."}


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3 or sys.argv[1] != "--gate":
            raise Error("Usage: seedbag_git.py --gate PROJECT_ROOT")
        print(json.dumps(gate(Path(sys.argv[2]), incomplete=os.environ.get("SEEDBAG_INCOMPLETE_CHECKPOINT") == "1")))
    except (Error, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
