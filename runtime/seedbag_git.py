"""Ordinary Git publication and index checks for Seedbag projects.

No automatic merge, reset, force push, global configuration, or branch promotion.
The optional hook is a local convenience, not an adversarial security boundary.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import tempfile

import seedbag_core as core
import seedbag_context as views

Error = core.Error
LEDGER = ".seedbag/ledger.json"


def _git(root, *args, allow_failure=False, input_bytes=None, env=None):
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], input=input_bytes,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, env=env,
        )
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


def _remote_refs(root):
    output = _text(root, "for-each-ref", "--format=%(refname)%00%(objectname)%00%(committerdate:iso-strict)%00%(subject)", "refs/remotes/")
    result = []
    for line in output.splitlines():
        ref, commit, date, subject = line.split("\0", 3)
        if not ref.endswith("/HEAD"):
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
    root = _root(root)
    if not isinstance(paths, list) or not paths or len(set(paths)) != len(paths):
        raise Error("Name the exact intended files once each; publication does not stage the whole directory.")
    for name in paths:
        path = _no_link(root, name)
        if path.is_dir():
            raise Error(f"Name individual files rather than a directory: {name}")
        if name.startswith(".seedbag-local/"):
            raise Error("Local locks and scratch state are not publication targets.")
        if name.startswith(".seedbag/") and name != LEDGER and not name.startswith(".seedbag/runtime/"):
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
